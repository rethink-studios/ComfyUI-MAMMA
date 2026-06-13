"""Self-contained MAMMA environment installer.

Bootstraps everything into the node pack's own directory — no system conda
required:

    ComfyUI-MAMMA\\.runtime\\
        micromamba.exe          downloaded official static binary
        mamba\\envs\\mamma\\      the environment itself
        shims\\conda.bat         translates MAMMA's internal `conda run`
        state.json              completed-step sentinels + resolved paths

Usable as a library (the MAMMA Install Environment node) or from a terminal:

    python install_env.py --repo C:\\path\\to\\mamma --step all
"""
from __future__ import annotations

import argparse
import glob as _glob
import json
import os
import platform
import subprocess
import sys
import time
import urllib.parse
import urllib.request

NODE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(NODE_DIR, ".runtime")
MICROMAMBA_URL = (
    "https://github.com/mamba-org/micromamba-releases/releases/latest/download/"
    "micromamba-win-64.exe"
)
ENV_NAME = "mamma"

STEPS = ["runtime", "env", "cuda", "pip", "compile", "shim", "weights", "doctor"]


def _is_network_path(path: str) -> bool:
    """True for UNC paths and drive letters mapped to network shares."""
    if path.startswith("\\\\"):
        return True
    drive = os.path.splitdrive(os.path.abspath(path))[0]
    if not drive:
        return False
    try:
        import ctypes

        return ctypes.windll.kernel32.GetDriveTypeW(drive + "\\") == 4  # DRIVE_REMOTE
    except Exception:
        return False


def default_runtime_dir() -> str:
    """Node-local .runtime, unless the node lives on a network drive —
    conda envs can't be created on UNC paths (libmamba weakly_canonical
    error, no hardlinks), so fall back to LOCALAPPDATA in that case."""
    if _is_network_path(NODE_DIR):
        return os.path.join(
            os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
            "ComfyUI-MAMMA", "runtime",
        )
    return STATE_DIR


# ---------------------------------------------------------------------------
# State — always in the node dir so the runner finds it regardless of where
# the heavy runtime landed.
# ---------------------------------------------------------------------------

def _state_path() -> str:
    return os.path.join(STATE_DIR, "state.json")


def load_state() -> dict:
    try:
        with open(_state_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(_state_path(), "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_print(text: str) -> None:
    """Print robustly regardless of console codepage (cp1252 vs utf-8)."""
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    sys.stdout.write(text.encode(enc, "replace").decode(enc, "replace") + "\n")
    sys.stdout.flush()


def _log(msg: str) -> None:
    _safe_print(f"[MAMMA-install] {msg}")


def _paths(runtime_dir: str) -> dict:
    root_prefix = os.path.join(runtime_dir, "mamba")
    return {
        "micromamba": os.path.join(runtime_dir, "micromamba.exe"),
        "root_prefix": root_prefix,
        "env_prefix": os.path.join(root_prefix, "envs", ENV_NAME),
        "shim_dir": os.path.join(runtime_dir, "shims"),
        "shim_bat": os.path.join(runtime_dir, "shims", "conda.bat"),
    }


def _mamba_env(runtime_dir: str, extra: dict | None = None) -> dict:
    env = os.environ.copy()
    env["MAMBA_ROOT_PREFIX"] = _paths(runtime_dir)["root_prefix"]
    env.pop("PYTHONPATH", None)  # don't leak ComfyUI's modules into the env
    if extra:
        env.update(extra)
    return env


def _stream(cmd: list[str] | str, cwd: str | None, env: dict, label: str = "MAMMA-install") -> int:
    _safe_print(f"[{label}] cmd={cmd if isinstance(cmd, str) else ' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd, cwd=cwd, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            _safe_print(f"[{label}] {line}")
    proc.wait()
    return proc.returncode


def find_vcvars64() -> str | None:
    """Locate vcvars64.bat (VS Build Tools / VS with C++ workload)."""
    cand = os.environ.get("VCVARS64", "")
    if cand and os.path.isfile(cand):
        return cand
    patterns = [
        r"C:\Program Files*\Microsoft Visual Studio\*\*\VC\Auxiliary\Build\vcvars64.bat",
        r"C:\Program Files (x86)\Microsoft Visual Studio\*\*\VC\Auxiliary\Build\vcvars64.bat",
    ]
    for pat in patterns:
        hits = sorted(_glob.glob(pat), reverse=True)
        if hits:
            return hits[0]
    return None


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

def step_runtime(runtime_dir: str, force: bool = False) -> None:
    """Download micromamba.exe."""
    p = _paths(runtime_dir)
    if os.path.isfile(p["micromamba"]) and not force:
        _log(f"micromamba already present: {p['micromamba']}")
        return
    os.makedirs(runtime_dir, exist_ok=True)
    _log(f"downloading micromamba from {MICROMAMBA_URL}")
    tmp = p["micromamba"] + ".part"
    urllib.request.urlretrieve(MICROMAMBA_URL, tmp)
    os.replace(tmp, p["micromamba"])
    size = os.path.getsize(p["micromamba"]) / 1e6
    if size < 1:
        raise RuntimeError("micromamba download looks truncated")
    _log(f"micromamba ready ({size:.1f} MB)")


_WIN_EXCLUDED_PKGS = ("wget",)  # no win-64 build; downloads are ported to Python here


def _win_env_yaml(runtime_dir: str, yaml_path: str) -> str:
    """Write a win-64 variant of the env spec with unix-only packages removed."""
    import re

    with open(yaml_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    pattern = re.compile(
        r"^\s*-\s*(" + "|".join(_WIN_EXCLUDED_PKGS) + r")\s*(=.*)?$"
    )
    kept = [ln for ln in lines if not pattern.match(ln)]
    os.makedirs(runtime_dir, exist_ok=True)
    out = os.path.join(runtime_dir, "mamma_conda_win.yaml")
    with open(out, "w", encoding="utf-8") as f:
        f.writelines(kept)
    return out


def step_env(runtime_dir: str, mamma_repo: str, force: bool = False) -> None:
    """Create the conda env from MAMMA's mamma_conda.yaml (+ git)."""
    p = _paths(runtime_dir)
    yaml_src = os.path.join(mamma_repo, "requirements", "mamma_conda.yaml")
    if not os.path.isfile(yaml_src):
        raise FileNotFoundError(f"env spec not found: {yaml_src}")
    yaml_path = _win_env_yaml(runtime_dir, yaml_src)
    if os.path.isdir(p["env_prefix"]) and not force:
        _log(f"env already exists: {p['env_prefix']}")
    else:
        cmd = [p["micromamba"], "create", "-y", "-n", ENV_NAME, "-f", yaml_path]
        if force:
            cmd.insert(2, "--rc-file=none")
        rc = _stream(cmd, mamma_repo, _mamba_env(runtime_dir))
        if rc != 0:
            raise RuntimeError(f"env creation failed (exit {rc})")
    # git is needed for the git+https pip installs; bundle it in the env so
    # machines without system git still work.
    rc = _stream(
        [p["micromamba"], "install", "-y", "-n", ENV_NAME, "-c", "conda-forge", "git"],
        mamma_repo, _mamba_env(runtime_dir),
    )
    if rc != 0:
        raise RuntimeError(f"git install into env failed (exit {rc})")
    _log("env ready")


def step_cuda(runtime_dir: str, force: bool = False) -> None:
    """Install the CUDA 12.4 toolkit into the env (for nvcc compiles)."""
    p = _paths(runtime_dir)
    nvcc = os.path.join(p["env_prefix"], "bin", "nvcc.exe")
    nvcc_alt = os.path.join(p["env_prefix"], "Library", "bin", "nvcc.exe")
    if (os.path.isfile(nvcc) or os.path.isfile(nvcc_alt)) and not force:
        _log("CUDA toolkit already in env")
        return
    rc = _stream(
        [p["micromamba"], "install", "-y", "-n", ENV_NAME,
         "-c", "nvidia/label/cuda-12.4.1", "cuda-toolkit"],
        None, _mamba_env(runtime_dir),
    )
    if rc != 0:
        raise RuntimeError(f"CUDA toolkit install failed (exit {rc})")
    _log("CUDA toolkit ready")


def step_pip(runtime_dir: str, mamma_repo: str) -> None:
    """Pip layer 1: requirements.txt (no compiles)."""
    p = _paths(runtime_dir)
    req = os.path.join(mamma_repo, "requirements", "requirements.txt")
    rc = _stream(
        [p["micromamba"], "run", "-n", ENV_NAME,
         "python", "-m", "pip", "install", "-r", req],
        mamma_repo, _mamba_env(runtime_dir),
    )
    if rc != 0:
        raise RuntimeError(f"pip layer 1 failed (exit {rc})")
    # Windows extras missing from MAMMA's requirements: decord (SAM2 reads
    # MP4s directly on full-range runs), pi-heif (ultralytics image opener),
    # usd-core (animated USD export).
    rc = _stream(
        [p["micromamba"], "run", "-n", ENV_NAME,
         "python", "-m", "pip", "install", "decord", "pi-heif", "usd-core"],
        mamma_repo, _mamba_env(runtime_dir),
    )
    if rc != 0:
        raise RuntimeError(f"pip layer 1 extras failed (exit {rc})")
    _log("pip layer 1 ready")


def _fix_msys_link(env_prefix: str) -> None:
    """The env's git package ships an MSYS link.exe (GNU coreutils) that
    shadows MSVC's linker during builds. Rename it out of the way."""
    msys_link = os.path.join(env_prefix, "Library", "usr", "bin", "link.exe")
    if os.path.isfile(msys_link):
        os.replace(msys_link, msys_link + ".bak")
        _log("renamed MSYS link.exe (was shadowing the MSVC linker)")


PYTORCH_SDF_ZIP = (
    "https://github.com/cuevhv/pytorch_sdf/archive/refs/heads/torch2.5-cu124.zip"
)


_DEBUG_BLOCK_TAGS = ("PRINT_TIMINGS", "DEBUG_PRINT", "BVH_PROFILING")


def _strip_debug_blocks(text: str) -> str:
    """Remove debug-only `#if(def) ... #endif` blocks. They appear inside
    AT_DISPATCH macro arguments, where MSVC's preprocessor forbids
    directives (GCC tolerates them)."""
    out: list[str] = []
    depth = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if depth == 0:
            if stripped.startswith("#if") and any(
                t in stripped for t in _DEBUG_BLOCK_TAGS
            ) and not stripped.startswith("#ifndef"):
                depth = 1
                continue
            out.append(line)
        else:
            if stripped.startswith("#if"):
                depth += 1
            elif stripped.startswith("#endif"):
                depth -= 1
            # block contents dropped
    return "".join(out)


def _prepare_pytorch_sdf(runtime_dir: str) -> str:
    """Download pytorch_sdf and apply MSVC compatibility patches.

    Upstream targets GCC; two fixes are needed for MSVC:
    * `__align__(N)` must come after the `struct` keyword, and
    * preprocessor directives cannot appear inside macro arguments.
    """
    import re
    import zipfile

    src_root = os.path.join(runtime_dir, "src")
    sdf_dir = os.path.join(src_root, "pytorch_sdf-torch2.5-cu124")
    marker = os.path.join(sdf_dir, ".win_patched")
    if os.path.isfile(marker):
        _log("pytorch_sdf already patched")
        return sdf_dir

    if not os.path.isdir(sdf_dir):
        os.makedirs(src_root, exist_ok=True)
        zip_path = os.path.join(src_root, "pytorch_sdf.zip")
        _log(f"downloading pytorch_sdf source from {PYTORCH_SDF_ZIP}")
        urllib.request.urlretrieve(PYTORCH_SDF_ZIP, zip_path)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(src_root)
        os.remove(zip_path)

    # GCC ignores `__align__(N)` placed between the template clause and the
    # `struct` keyword (no declarator), so the effective Linux layout is the
    # packed natural one. MSVC rejects the attribute (48 is not a power of
    # 2), so drop it entirely to match.
    align_before = re.compile(r"__align__\(\d+\)\s*\r?\n\s*struct")
    align_after = re.compile(r"struct\s+__align__\(\d+\)\s+")
    for sub in ("src", "include"):
        sub_dir = os.path.join(sdf_dir, sub)
        if not os.path.isdir(sub_dir):
            continue
        for name in os.listdir(sub_dir):
            path = os.path.join(sub_dir, name)
            if not os.path.isfile(path):
                continue
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
            new = align_before.sub("struct", text)
            new = align_after.sub("struct ", new)
            if name.endswith((".cu", ".cpp")):
                new = _strip_debug_blocks(new)
                # Windows `long` is 32-bit; libtorch only exports the
                # int64_t instantiation of data_ptr<T>.
                new = re.sub(r"\blong\b", "int64_t", new)
            if new != text:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(new)
                _log(f"patched {sub}/{name} for MSVC")
    with open(marker, "w", encoding="ascii") as f:
        f.write("patched for MSVC\n")
    return sdf_dir


def step_compile(runtime_dir: str, mamma_repo: str) -> None:
    """Pip layer 2: detectron2 + pytorch_sdf, compiled with MSVC + env nvcc."""
    p = _paths(runtime_dir)
    vcvars = find_vcvars64()
    if not vcvars:
        raise RuntimeError(
            "MSVC C++ build tools not found. Install 'Visual Studio Build Tools' "
            "with the 'Desktop development with C++' workload, e.g.:\n"
            "  winget install Microsoft.VisualStudio.2022.BuildTools\n"
            "then re-run this step."
        )
    env_prefix = p["env_prefix"]
    _fix_msys_link(env_prefix)
    sdf_dir = _prepare_pytorch_sdf(runtime_dir)

    extra = {
        "CUDA_HOME": env_prefix,
        "CUDA_PATH": env_prefix,
        "DISTUTILS_USE_SDK": "1",
        "MAMBA_ROOT_PREFIX": p["root_prefix"],
    }
    # detectron2 straight from git; pytorch_sdf from the patched local tree.
    # Raw command strings: list2cmdline mangles the nested quotes cmd needs.
    targets = [
        ("detectron2", '"git+https://github.com/facebookresearch/detectron2.git"'),
        ("pytorch_sdf (patched)", f'"{sdf_dir}"'),
    ]
    for label, target in targets:
        _log(f"building {label} ...")
        inner = (
            f'"{vcvars}" && '
            f'"{p["micromamba"]}" run -n {ENV_NAME} '
            f"python -m pip install --no-build-isolation {target}"
        )
        rc = _stream(f'cmd /s /c "{inner}"', mamma_repo, _mamba_env(runtime_dir, extra))
        if rc != 0:
            raise RuntimeError(
                f"compile of {label} failed (exit {rc}). Check MSVC/CUDA output above."
            )
    _log("compile layer ready")


def step_shim(runtime_dir: str) -> None:
    """Generate conda.bat + conda_shim.py translating `conda run` -> micromamba."""
    p = _paths(runtime_dir)
    os.makedirs(p["shim_dir"], exist_ok=True)
    shim_py = os.path.join(p["shim_dir"], "conda_shim.py")
    with open(shim_py, "w", encoding="utf-8") as f:
        f.write(
            '"""conda -> micromamba translation shim (generated)."""\n'
            "import os, subprocess, sys\n\n"
            f"MICROMAMBA = {p['micromamba']!r}\n"
            f"ROOT_PREFIX = {p['root_prefix']!r}\n\n"
            "args = [a for a in sys.argv[1:]\n"
            "        if a not in ('--no-capture-output', '--live-stream')]\n"
            "env = os.environ.copy()\n"
            "env['MAMBA_ROOT_PREFIX'] = ROOT_PREFIX\n"
            "sys.exit(subprocess.call([MICROMAMBA] + args, env=env))\n"
        )
    with open(p["shim_bat"], "w", encoding="ascii") as f:
        f.write(
            "@echo off\r\n"
            f'"{sys.executable}" "{shim_py}" %*\r\n'
        )
    # MAMMA's runner spawns `Popen(["conda", "run", ...])` per step; Windows
    # CreateProcess only resolves a bare name to a .exe, so the .bat shim is
    # invisible to it. pip-installing a console script gives the env a real
    # Scripts\conda.exe launcher that those child processes can find.
    pkg_dir = os.path.join(runtime_dir, "shim_pkg")
    os.makedirs(pkg_dir, exist_ok=True)
    with open(os.path.join(pkg_dir, "mamma_conda_shim.py"), "w", encoding="utf-8") as f:
        f.write(
            '"""conda -> micromamba shim, exposed as conda.exe (generated)."""\n'
            "import ctypes, os, subprocess, sys\n\n"
            f"MICROMAMBA = {p['micromamba']!r}\n"
            f"ROOT_PREFIX = {p['root_prefix']!r}\n\n\n"
            "def _escape_unc_cwd():\n"
            "    # cmd.exe (used inside `micromamba run`) rejects UNC working\n"
            "    # directories and silently falls back to C:\\Windows. Remap the\n"
            "    # UNC cwd to its mapped drive letter when one exists.\n"
            "    cwd = os.getcwd()\n"
            "    if not cwd.startswith('\\\\\\\\'):\n"
            "        return\n"
            "    mpr = ctypes.WinDLL('mpr')\n"
            "    for code in range(65, 91):\n"
            "        drive = chr(code) + ':'\n"
            "        buf = ctypes.create_unicode_buffer(1024)\n"
            "        n = ctypes.c_ulong(1024)\n"
            "        if mpr.WNetGetConnectionW(drive, buf, ctypes.byref(n)) == 0:\n"
            "            remote = buf.value.rstrip('\\\\')\n"
            "            if cwd.lower().startswith(remote.lower()):\n"
            "                os.chdir(drive + cwd[len(remote):])\n"
            "                return\n\n\n"
            "def main():\n"
            "    _escape_unc_cwd()\n"
            "    args = [a for a in sys.argv[1:]\n"
            "            if a not in ('--no-capture-output', '--live-stream')]\n"
            "    env = os.environ.copy()\n"
            "    env['MAMBA_ROOT_PREFIX'] = ROOT_PREFIX\n"
            "    # torch ships Intel OpenMP, conda packages pull LLVM OpenMP;\n"
            "    # loading both crashes (0xC0000005). Allow the duplicate.\n"
            "    env['KMP_DUPLICATE_LIB_OK'] = 'TRUE'\n"
            "    sys.exit(subprocess.call([MICROMAMBA] + args, env=env))\n"
        )
    with open(os.path.join(pkg_dir, "pyproject.toml"), "w", encoding="utf-8") as f:
        f.write(
            "[build-system]\n"
            'requires = ["setuptools"]\n'
            'build-backend = "setuptools.build_meta"\n\n'
            "[project]\n"
            'name = "mamma-conda-shim"\n'
            'version = "0.1.0"\n'
            'description = "conda -> micromamba shim for the MAMMA env"\n\n'
            "[project.scripts]\n"
            'conda = "mamma_conda_shim:main"\n\n'
            "[tool.setuptools]\n"
            'py-modules = ["mamma_conda_shim"]\n'
        )
    rc = _stream(
        [p["micromamba"], "run", "-n", ENV_NAME,
         "python", "-m", "pip", "install", "--no-deps", "--force-reinstall", "-q", pkg_dir],
        runtime_dir, _mamba_env(runtime_dir),
    )
    if rc != 0:
        raise RuntimeError(f"installing the conda.exe shim failed (exit {rc})")
    env_conda = os.path.join(p["env_prefix"], "Scripts", "conda.exe")
    if not os.path.isfile(env_conda):
        raise RuntimeError(f"conda.exe shim missing after install: {env_conda}")

    state = load_state()
    state["conda_cmd"] = p["shim_bat"]
    state["root_prefix"] = p["root_prefix"]
    state["micromamba"] = p["micromamba"]
    state["env_name"] = ENV_NAME
    state["runtime_dir"] = runtime_dir
    save_state(state)
    _log(f"shim ready: {p['shim_bat']} + {env_conda}")


# ---------------------------------------------------------------------------
# Weights (public + license-gated)
# ---------------------------------------------------------------------------

PUBLIC_WEIGHTS = [
    ("https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_large.pt",
     os.path.join("weights", "sam2", "sam2.1_hiera_large.pt")),
    ("https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo12x.pt",
     os.path.join("weights", "yolo", "yolo12x.pt")),
]


def _download_public(url: str, out_path: str) -> None:
    if os.path.isfile(out_path) and os.path.getsize(out_path) > 1024 * 1024:
        _log(f"[skip] {os.path.basename(out_path)} (already present)")
        return
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    _log(f"downloading {os.path.basename(out_path)} ...")
    tmp = out_path + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": "ComfyUI-MAMMA"})
    with urllib.request.urlopen(req) as resp, open(tmp, "wb") as f:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    os.replace(tmp, out_path)
    _log(f"[ok] {os.path.basename(out_path)} ({os.path.getsize(out_path) / 1e6:.1f} MB)")

def _download_gated(domain: str, sfile: str, out_path: str, username: str, password: str) -> None:
    if os.path.isfile(out_path) and os.path.getsize(out_path) > 1024:
        with open(out_path, "rb") as f:
            head = f.read(256)
        if b"<html" not in head.lower() and b"<!doctype" not in head.lower():
            _log(f"[skip] {os.path.basename(out_path)} (already present)")
            return
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    url = f"https://download.is.tue.mpg.de/download.php?domain={domain}&resume=1&sfile={sfile}"
    data = urllib.parse.urlencode({"username": username, "password": password}).encode()
    _log(f"downloading {sfile} ...")
    # The server authenticates the POST, sets a session cookie and 302s to
    # the same URL; the cookie must survive the redirect (wget semantics).
    import http.cookiejar
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )
    req = urllib.request.Request(url, data=data)
    tmp = out_path + ".part"
    with opener.open(req) as resp, open(tmp, "wb") as f:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    with open(tmp, "rb") as f:
        head = f.read(256)
    if b"<html" in head.lower() or b"<!doctype" in head.lower() or b"Error:" in head:
        os.remove(tmp)
        raise RuntimeError(
            f"{sfile}: server returned an error page — check the {domain} "
            "account credentials (register at https://{0}.is.tue.mpg.de/)".format(domain)
        )
    os.replace(tmp, out_path)
    _log(f"[ok] {os.path.basename(out_path)} ({os.path.getsize(out_path) / 1e6:.1f} MB)")


def _precache_hf_models(runtime_dir: str) -> None:
    """Pre-fetch HF checkpoints that MAMMA otherwise downloads at runtime
    (open_clip CLIP model used by ma_masks). Retried because HF rate-limits
    anonymous requests."""
    p = _paths(runtime_dir)
    code = (
        "from huggingface_hub import hf_hub_download;"
        "hf_hub_download('laion/CLIP-ViT-B-32-laion2B-s34B-b79K',"
        " 'open_clip_pytorch_model.bin');"
        "print('clip cached')"
    )
    for attempt in range(3):
        rc = _stream(
            [p["micromamba"], "run", "-n", ENV_NAME, "python", "-c", code],
            runtime_dir, _mamba_env(runtime_dir), label="hf-cache",
        )
        if rc == 0:
            return
        _log(f"HF pre-cache attempt {attempt + 1} failed (rc={rc}), retrying...")
        time.sleep(10)
    _log("WARNING: could not pre-cache CLIP weights; ma_masks will retry at runtime")


def step_weights(
    mamma_repo: str,
    mamma_user: str = "", mamma_pass: str = "",
    smplx_user: str = "", smplx_pass: str = "",
    runtime_dir: str = "",
) -> None:
    data_dir = os.path.join(mamma_repo, "data")
    # Public checkpoints (SAM2 segmentation, YOLO detection) need no account.
    for url, rel in PUBLIC_WEIGHTS:
        _download_public(url, os.path.join(data_dir, rel))
    if runtime_dir:
        _precache_hf_models(runtime_dir)
    did_any = False
    if mamma_user and mamma_pass:
        _download_gated(
            "mamma", "weights/mamma_mask_full_cvpr.ckpt",
            os.path.join(data_dir, "weights", "ma_2d", "mamma_mask_full_cvpr.ckpt"),
            mamma_user, mamma_pass,
        )
        _download_gated(
            "mamma", "mamma_assets/verts_512.pkl",
            os.path.join(data_dir, "body_models", "downsampled_verts", "verts_512.pkl"),
            mamma_user, mamma_pass,
        )
        did_any = True
    else:
        _log("MAMMA credentials empty — skipping landmark ckpt + verts "
             "(register at https://mamma.is.tue.mpg.de/)")
    if smplx_user and smplx_pass:
        zip_path = os.path.join(data_dir, "_smplx_locked_head_download.zip")
        dest = os.path.join(data_dir, "body_models", "smplx_locked_head")
        marker = os.path.join(dest, "models")
        if os.path.isdir(marker) or _glob.glob(os.path.join(dest, "**", "SMPLX_*.npz"), recursive=True):
            _log("[skip] smplx_locked_head (already extracted)")
        else:
            _download_gated("smplx", "smplx_lockedhead_20230207.zip", zip_path, smplx_user, smplx_pass)
            import zipfile
            os.makedirs(dest, exist_ok=True)
            with zipfile.ZipFile(zip_path) as z:
                z.extractall(dest)
            os.remove(zip_path)
            # smplx.create expects <dest>/smplx/SMPLX_*.npz, but the zip wraps
            # everything in a models_lockedhead/ directory; flatten it.
            wrapped = os.path.join(dest, "models_lockedhead", "smplx")
            target = os.path.join(dest, "smplx")
            if os.path.isdir(wrapped) and not os.path.isdir(target):
                import shutil as _shutil
                _shutil.move(wrapped, target)
            _log(f"extracted SMPL-X locked-head model -> {dest}")
        did_any = True
    else:
        _log("SMPL-X credentials empty — skipping body model "
             "(register at https://smpl-x.is.tue.mpg.de/)")
    if not did_any:
        _log("no gated credentials given; public weights downloaded if needed")


def step_doctor(runtime_dir: str, mamma_repo: str) -> int:
    p = _paths(runtime_dir)
    rc = _stream(
        [p["micromamba"], "run", "-n", ENV_NAME, "python", "-m", "inference", "doctor"],
        mamma_repo, _mamba_env(runtime_dir), label="MAMMA-doctor",
    )
    _log(f"doctor exit code: {rc}")
    return rc


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def step_patches(mamma_repo: str) -> None:
    """Copy bundled Windows fixes into the MAMMA clone (no-op on Linux)."""
    if platform.system() != "Windows":
        _log("patches: skipped (not Windows)")
        return
    script = os.path.join(NODE_DIR, "scripts", "apply_windows_patches.py")
    if not os.path.isfile(script):
        _log("patches: apply_windows_patches.py not found — skipped")
        return
    _log("applying Windows compatibility patches to MAMMA repo...")
    rc = subprocess.call([sys.executable, script, "--repo", mamma_repo])
    if rc != 0:
        raise RuntimeError(f"apply_windows_patches failed (exit {rc})")


def install(
    mamma_repo: str,
    step: str = "all",
    runtime_dir: str = "",
    force: bool = False,
    mamma_user: str = "", mamma_pass: str = "",
    smplx_user: str = "", smplx_pass: str = "",
) -> str:
    mamma_repo = os.path.normpath(mamma_repo)
    if not os.path.isdir(mamma_repo):
        raise FileNotFoundError(f"MAMMA repo not found: {mamma_repo}")
    step_patches(mamma_repo)
    state = load_state()
    if not runtime_dir:
        runtime_dir = state.get("runtime_dir") or default_runtime_dir()
    if _is_network_path(runtime_dir):
        raise RuntimeError(
            f"runtime dir {runtime_dir!r} is on a network drive — conda envs "
            "cannot live on network shares. Pick a local path (e.g. "
            f"{default_runtime_dir()!r})."
        )
    _log(f"runtime dir: {runtime_dir}")
    if state.get("runtime_dir") and state["runtime_dir"] != runtime_dir:
        _log("runtime dir changed — resetting step sentinels")
        state = {k: v for k, v in state.items() if not k.startswith("done_")}
    state["runtime_dir"] = runtime_dir
    save_state(state)
    todo = STEPS if step == "all" else [step]
    done: list[str] = []
    # Only pip/compile trust sentinels (slow to re-verify); the other steps
    # check their own artifacts and fast-skip internally.
    sentinel_steps = ("pip", "compile")
    for s in todo:
        key = f"done_{s}"
        if step == "all" and state.get(key) and not force and s in sentinel_steps:
            _log(f"[skip] {s} (completed previously)")
            done.append(s)
            continue
        _log(f"=== step: {s} ===")
        if s == "runtime":
            step_runtime(runtime_dir, force)
        elif s == "env":
            step_env(runtime_dir, mamma_repo, force)
        elif s == "cuda":
            step_cuda(runtime_dir, force)
        elif s == "pip":
            step_pip(runtime_dir, mamma_repo)
        elif s == "compile":
            step_compile(runtime_dir, mamma_repo)
        elif s == "shim":
            step_shim(runtime_dir)
        elif s == "weights":
            step_weights(mamma_repo, mamma_user, mamma_pass, smplx_user, smplx_pass,
                         runtime_dir=runtime_dir)
        elif s == "doctor":
            rc = step_doctor(runtime_dir, mamma_repo)
            if rc != 0:
                _log("doctor reported problems (often just missing gated weights)")
        else:
            raise ValueError(f"unknown step {s!r}; valid: {STEPS}")
        state = load_state()
        state[key] = True
        save_state(state)
        done.append(s)
    return f"completed steps: {', '.join(done)}\nruntime: {runtime_dir}"


def main() -> None:
    ap = argparse.ArgumentParser(description="Install the self-contained MAMMA env")
    ap.add_argument("--repo", required=True, help="path to the MAMMA repo clone")
    ap.add_argument("--step", default="all", choices=["all"] + STEPS)
    ap.add_argument("--runtime-dir", default="")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--mamma-user", default=os.environ.get("MAMMA_USERNAME", ""))
    ap.add_argument("--mamma-pass", default=os.environ.get("MAMMA_PASSWORD", ""))
    ap.add_argument("--smplx-user", default=os.environ.get("SMPLX_USERNAME", ""))
    ap.add_argument("--smplx-pass", default=os.environ.get("SMPLX_PASSWORD", ""))
    args = ap.parse_args()
    print(install(
        args.repo, args.step, args.runtime_dir, args.force,
        args.mamma_user, args.mamma_pass, args.smplx_user, args.smplx_pass,
    ))


if __name__ == "__main__":
    main()
