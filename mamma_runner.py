from __future__ import annotations

import collections
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

_PIPELINE_STEPS = ("ma_cap", "ma_masks", "ma_2d", "ma_3d", "ma_vis")
# Rough share of total wall-clock per step (ma_masks dominates real runs).
_STEP_WEIGHTS = {"ma_cap": 0.05, "ma_masks": 0.50, "ma_2d": 0.20, "ma_3d": 0.15, "ma_vis": 0.10}
_STATUS_RE = re.compile(r"status:\s+(\w+)\[.*?\]\s+->\s+(\w+)")
_TQDM_RE = re.compile(r"(\d+)%\|[^|]*\|\s*(\d+)/(\d+)")
_CAMERA_RE = re.compile(r"\[(\d+)/(\d+)\]\s+Processing")
# ma_3d optimizer output: "RUN:  second_run" stage markers + "Iter. 12 of 100".
_MA3D_STAGES = ("first_run", "second_run", "third_run", "fourth_run")
_MA3D_RUN_RE = re.compile(r"RUN:\s+(\w+)")
_MA3D_ITER_RE = re.compile(r"Iter\.\s+(\d+)\s+of\s+(\d+)")
# Explicit progress lines emitted by patched MAMMA scripts (ma_vis overlay).
_PROG_RE = re.compile(r"MAMMA_PROG\s+(\d+)/(\d+)")


def _norm(path: str) -> str:
    return os.path.normpath(os.path.expanduser(path.strip()))


# ---------------------------------------------------------------------------
# Conda discovery — ComfyUI Desktop's process usually does not have conda on
# PATH, and MAMMA's own runner shells out to `conda run` per step, so the
# child process needs conda resolvable too. The node-local micromamba shim
# (created by the MAMMA Install Environment node) takes priority.
# ---------------------------------------------------------------------------

NODE_DIR = os.path.dirname(os.path.abspath(__file__))
RUNTIME_DIR = os.path.join(NODE_DIR, ".runtime")


def _runtime_state() -> dict:
    try:
        import json

        with open(os.path.join(RUNTIME_DIR, "state.json"), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def find_conda() -> str:
    shim = _runtime_state().get("conda_cmd", "")
    if shim and os.path.isfile(shim):
        return shim
    exe = os.environ.get("CONDA_EXE", "")
    if exe and os.path.isfile(exe):
        return exe
    which = shutil.which("conda")
    if which:
        return which
    home = os.path.expanduser("~")
    roots = [
        os.path.join(home, name)
        for name in ("miniconda3", "anaconda3", "miniforge3", "mambaforge")
    ] + [r"C:\ProgramData\miniconda3", r"C:\ProgramData\anaconda3", r"C:\miniconda3", r"C:\anaconda3"]
    for root in roots:
        for cand in (
            os.path.join(root, "Scripts", "conda.exe"),
            os.path.join(root, "condabin", "conda.bat"),
        ):
            if os.path.isfile(cand):
                return cand
    raise FileNotFoundError(
        "conda not found. Install Miniconda/Anaconda, or set the CONDA_EXE "
        "environment variable to the full path of conda.exe before launching "
        "ComfyUI Desktop."
    )


def _env_with_conda(conda_exe: str) -> dict:
    env = os.environ.copy()
    # Intel + LLVM OpenMP both end up loaded in the mamma env and crash
    # with 0xC0000005 on Windows; allowing the duplicate avoids it.
    env["KMP_DUPLICATE_LIB_OK"] = "TRUE"
    # sklearn TSNE still segfaults under the dual-OpenMP setup; it only
    # produces a diagnostic plot, so skip it (see segmentation/core/pipeline.py).
    env["MAMMA_DISABLE_TSNE"] = "1"
    # Other ComfyUI node packs may export PYOPENGL_PLATFORM (e.g. wgl), which
    # pyrender's OffscreenRenderer rejects on Windows. Don't pass it through.
    if os.name == "nt":
        env.pop("PYOPENGL_PLATFORM", None)
    state = _runtime_state()
    if state.get("conda_cmd") == conda_exe:
        # Node-local micromamba runtime: expose the shim dir as `conda` for
        # MAMMA's internal per-step `conda run` calls.
        env["MAMBA_ROOT_PREFIX"] = state.get("root_prefix", "")
        env["PATH"] = os.pathsep.join(
            [os.path.dirname(conda_exe), env.get("PATH", "")]
        )
        return env
    d = os.path.dirname(conda_exe)
    if d:
        root = os.path.dirname(d)
        extra = [
            p
            for p in (
                d,
                os.path.join(root, "condabin"),
                os.path.join(root, "Scripts"),
                os.path.join(root, "Library", "bin"),
            )
            if os.path.isdir(p)
        ]
        env["PATH"] = os.pathsep.join(extra + [env.get("PATH", "")])
        env.setdefault("CONDA_EXE", conda_exe)
    return env


def _comfy_progress_bar(total: int = 100):
    try:
        from comfy.utils import ProgressBar
        return ProgressBar(total)
    except Exception:
        return None


class _PipelineProgress:
    """Live progress for the MAMMA pipeline.

    MAMMA's runner redirects each step's stdout/stderr into per-step log
    files (<jobs>/<step>/<seq>.out|.err), so the parent process only sees
    coarse "Running/Done" transitions. To get real movement we tail the
    active step's log files in a background thread: tqdm counters live in
    .err, camera markers ("[2/4] Processing camera") in .out.

    Progress model: each step owns a weighted slice of 0-100%; within the
    running step the latest tqdm fraction (scaled by camera slot for
    ma_masks) fills the slice. The bar is clamped monotonic.
    """

    HEARTBEAT_S = 10.0
    POLL_S = 1.5

    def __init__(self, log_roots: list[str] | None = None, seq: str = "") -> None:
        self._pbar = _comfy_progress_bar(1000)
        self._log_roots = [r for r in (log_roots or []) if r]
        self._seq = seq
        self._lock = threading.Lock()
        self._step: Optional[str] = None
        self._inner = 0.0
        self._cam = (0, 0)
        self._ma3d_stage = 0
        self._done: set[str] = set()
        self._best = 0.0
        self._offsets: dict[str, int] = {}
        self._stop = threading.Event()
        self._last_beat = 0.0
        self._thread: Optional[threading.Thread] = None
        if self._log_roots and self._seq:
            self._thread = threading.Thread(target=self._tail_loop, daemon=True)
            self._thread.start()

    # --- overall percent ---------------------------------------------------

    def _overall(self) -> float:
        pct = sum(_STEP_WEIGHTS[s] for s in self._done)
        if self._step and self._step not in self._done:
            pct += _STEP_WEIGHTS.get(self._step, 0.0) * min(1.0, self._inner)
        return min(1.0, pct)

    def _emit(self) -> None:
        pct = self._overall()
        if pct < self._best:
            return
        self._best = pct
        if self._pbar is not None:
            try:
                self._pbar.update_absolute(int(pct * 1000), 1000)
            except Exception:
                # ComfyUI raises InterruptProcessingException inside the bar
                # hook when the user cancels; don't let it kill this thread.
                self._pbar = None

    # --- fed from the parent process's own stdout --------------------------

    def feed(self, line: str) -> None:
        m = _STATUS_RE.search(line)
        if not m:
            return
        step, state = m.group(1), m.group(2)
        if step not in _PIPELINE_STEPS:
            return
        with self._lock:
            if state == "Running":
                self._step = step
                self._inner = 0.0
                self._cam = (0, 0)
                self._ma3d_stage = 0
                self._offsets = {}
            elif state == "Done":
                self._done.add(step)
                if self._step == step:
                    self._step = None
            self._emit()

    # --- background tail of the active step's log files --------------------

    def _read_new(self, path: str) -> str:
        try:
            size = os.path.getsize(path)
        except OSError:
            return ""
        start = self._offsets.get(path, 0)
        if size <= start:
            return ""
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(start)
                chunk = f.read()
            self._offsets[path] = start + len(chunk.encode("utf-8", "replace"))
        except OSError:
            return ""
        return chunk

    def _tail_once(self) -> None:
        with self._lock:
            step = self._step
        if not step:
            return
        out_new = err_new = ""
        for root in self._log_roots:
            base = os.path.join(root, step, self._seq)
            out_new += self._read_new(base + ".out")
            err_new += self._read_new(base + ".err")

        cam = None
        for m in _CAMERA_RE.finditer(out_new + err_new):
            cam = (int(m.group(1)), int(m.group(2)))
        frac = None
        for m in _TQDM_RE.finditer(err_new.replace("\r", "\n")):
            cur, total = int(m.group(2)), int(m.group(3))
            if total > 0:
                frac = cur / total
        for m in _PROG_RE.finditer(err_new):
            cur, total = int(m.group(1)), int(m.group(2))
            if total > 0:
                frac = cur / total

        # ma_3d logs no tqdm; track its 4 optimizer stages + iteration lines.
        ma3d_stage = None
        ma3d_frac = None
        if step == "ma_3d":
            for m in _MA3D_RUN_RE.finditer(out_new):
                name = m.group(1)
                if name in _MA3D_STAGES:
                    ma3d_stage = _MA3D_STAGES.index(name)
            for m in _MA3D_ITER_RE.finditer(out_new):
                cur, total = int(m.group(1)), int(m.group(2))
                if total > 0:
                    ma3d_frac = cur / total

        with self._lock:
            if self._step != step:
                return
            if cam:
                self._cam = cam
            c, n = self._cam
            if step == "ma_3d":
                if ma3d_stage is not None:
                    self._ma3d_stage = ma3d_stage
                if ma3d_frac is not None:
                    n_stages = len(_MA3D_STAGES)
                    self._inner = max(
                        self._inner,
                        (self._ma3d_stage + min(1.0, ma3d_frac)) / n_stages,
                    )
            elif frac is not None:
                if step in ("ma_masks", "ma_vis") and n > 0:
                    self._inner = (max(c, 1) - 1) / n + frac / n
                else:
                    self._inner = frac
            elif cam and n > 0:
                self._inner = (c - 1) / n
            self._emit()
            now = time.monotonic()
            if now - self._last_beat >= self.HEARTBEAT_S:
                self._last_beat = now
                cam_txt = f" camera {c}/{n}," if n > 0 else ""
                step_pct = int(self._inner * 100)
                overall = max(self._best, self._overall())
                print(f"[MAMMA] progress: {step}{cam_txt} {step_pct}% of step "
                      f"(overall {int(overall * 100)}%)")

    def _tail_loop(self) -> None:
        while not self._stop.wait(self.POLL_S):
            try:
                self._tail_once()
            except Exception:
                pass

    def close(self, success: bool) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        if success and self._pbar is not None:
            try:
                self._pbar.update_absolute(1000, 1000)
            except Exception:
                pass


def _processing_interrupted() -> bool:
    try:
        import comfy.model_management as mm
        return mm.processing_interrupted()
    except Exception:
        return False


def _kill_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       capture_output=True)
    else:
        try:
            os.killpg(os.getpgid(pid), 9)
        except OSError:
            pass


def _run_streaming(
    cmd: list[str], cwd: str, env: dict, label: str,
    log_roots: list[str] | None = None, seq: str = "",
) -> tuple[int, str]:
    """Run cmd, streaming output to the ComfyUI console; return (rc, tail).

    Raises InterruptProcessingException if the user cancels the prompt; the
    whole child process tree is killed first (ComfyUI's interrupt mechanism
    only raises inside this Python process and would otherwise leave the
    pipeline running headless).
    """
    print(f"[{label}] cwd={cwd}")
    print(f"[{label}] cmd={' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    cancelled = threading.Event()

    def _watch() -> None:
        while proc.poll() is None:
            if _processing_interrupted():
                cancelled.set()
                print(f"[{label}] cancel requested -- killing process tree (pid {proc.pid})")
                _kill_tree(proc.pid)
                return
            time.sleep(1.0)

    watchdog = threading.Thread(target=_watch, daemon=True)
    watchdog.start()

    tail: collections.deque[str] = collections.deque(maxlen=120)
    progress = _PipelineProgress(log_roots=log_roots, seq=seq)
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                tail.append(line)
                print(f"[{label}] {line}")
                progress.feed(line)
        proc.wait()
    finally:
        progress.close(success=(proc.returncode == 0 and not cancelled.is_set()))

    if cancelled.is_set():
        print(f"[{label}] pipeline cancelled by user")
        try:
            from comfy.model_management import InterruptProcessingException
        except Exception:
            raise RuntimeError(f"{label} cancelled by user")
        raise InterruptProcessingException()
    return proc.returncode, "\n".join(tail)


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

def list_presets(mamma_repo: str) -> list[str]:
    presets_dir = Path(_norm(mamma_repo)) / "configs" / "examples" / "presets"
    if not presets_dir.is_dir():
        return ["quick.yaml", "full.yaml"]
    names = sorted(p.name for p in presets_dir.glob("*.yaml"))
    return names or ["quick.yaml", "full.yaml"]


def resolve_preset_path(mamma_repo: str, preset: str) -> str:
    preset = preset.strip()
    if os.path.isabs(preset) and os.path.isfile(preset):
        return preset
    candidate = Path(_norm(mamma_repo)) / "configs" / "examples" / "presets" / preset
    if candidate.is_file():
        return str(candidate)
    if os.path.isfile(preset):
        return _norm(preset)
    raise FileNotFoundError(f"Preset not found: {preset!r}")


def _patched_preset(
    preset_path: str, start_frame: Optional[int], end_frame: Optional[int]
) -> str:
    """Copy the preset with global.start_frame/end_frame overridden.

    Presets natively carry the frame range (quick.yaml ships 60-90), so a
    plain YAML edit is all the override needs — no MAMMA imports in the
    ComfyUI process.
    """
    if start_frame is None and end_frame is None:
        return preset_path
    import yaml

    with open(preset_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    g = cfg.setdefault("global", {})
    if start_frame is not None:
        g["start_frame"] = int(start_frame)
    if end_frame is not None:
        g["end_frame"] = int(end_frame)
    fd, path = tempfile.mkstemp(prefix="mamma_preset_", suffix=".yaml")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)
    return path


# ---------------------------------------------------------------------------
# Output layout
# ---------------------------------------------------------------------------

def resolve_output_paths(
    out_dir: str, out_tag: str, footage: str, seq_name: str
) -> dict[str, str]:
    dataset_name = os.path.basename(_norm(footage).rstrip("\\/")) or "dataset"
    out = Path(_norm(out_dir))
    vis_root = out / "ma_vis" / out_tag / dataset_name / seq_name
    return {
        "vis_dir": str(vis_root),
        "preview_video": str(vis_root / "preview.mp4"),
        "overlay_dir": str(vis_root / "overlay"),
        "ma_3d_dir": str(out / "ma_3d" / out_tag / dataset_name / seq_name),
    }


# ---------------------------------------------------------------------------
# Pipeline entry points
# ---------------------------------------------------------------------------

def run_pipeline(
    *,
    mamma_repo: str,
    preset: str,
    footage: str,
    seq_name: str,
    calib: str,
    out_tag: str = "comfy",
    out_dir: str = "",
    conda_env: str = "mamma",
    start_frame: int = -1,
    end_frame: int = -1,
    force: bool = False,
) -> dict[str, str]:
    repo = _norm(mamma_repo)
    if not os.path.isdir(repo):
        raise FileNotFoundError(f"MAMMA repo not found: {repo}")
    preset_path = resolve_preset_path(repo, preset)
    footage_path = _norm(footage)
    calib_path = _norm(calib)
    seq = seq_name.strip()
    if not os.path.isdir(footage_path):
        raise FileNotFoundError(f"Footage directory not found: {footage_path}")
    if not os.path.isfile(calib_path):
        raise FileNotFoundError(f"Calibration file not found: {calib_path}")
    if not os.path.isdir(os.path.join(footage_path, seq)):
        raise FileNotFoundError(
            f"Sequence directory not found: {os.path.join(footage_path, seq)}"
        )

    if not out_dir.strip():
        out_dir = os.path.join(repo, "output")
    out_dir = _norm(out_dir)
    os.makedirs(out_dir, exist_ok=True)

    start = start_frame if start_frame >= 0 else None
    end = end_frame if end_frame >= 0 else None
    cfg_path = _patched_preset(preset_path, start, end)

    tag = out_tag.strip() or "comfy"

    # MAMMA skips steps whose DONE marker exists, and several steps also keep
    # internal skip-if-exists caches (ma_cap gt npz, ma_masks masks.npy /
    # feature bank) that --force does NOT invalidate. When the preset/frame
    # range changes (or force is requested) the per-sequence output dirs must
    # be deleted, otherwise stale frame ranges get silently reused.
    import json

    fingerprint = {"preset": os.path.basename(preset_path), "start": start, "end": end}
    marker = os.path.join(out_dir, f".comfy_run_{tag}_{seq}.json")
    try:
        with open(marker, "r", encoding="utf-8") as f:
            prev = json.load(f)
    except (OSError, ValueError):
        prev = None
    if prev != fingerprint and prev is not None and not force:
        print(f"[MAMMA] preset/frame range changed ({prev} -> {fingerprint}); forcing recompute")
        force = True
    if force:
        dataset_name = os.path.basename(footage_path.rstrip("\\/")) or "dataset"
        for step in ("ma_cap", "ma_masks", "ma_2d", "ma_3d", "ma_vis"):
            step_dir = os.path.join(out_dir, step, tag, dataset_name, seq)
            if os.path.isdir(step_dir):
                print(f"[MAMMA] clearing stale outputs: {step_dir}")
                shutil.rmtree(step_dir, ignore_errors=True)
    with open(marker, "w", encoding="utf-8") as f:
        json.dump(fingerprint, f)
    conda_exe = find_conda()
    cmd = [
        conda_exe, "run", "-n", conda_env, "--no-capture-output", "--live-stream",
        "python", "-m", "inference", "run",
        "--cfg", cfg_path,
        "--footage", footage_path,
        "--seq_name", seq,
        "--calib", calib_path,
        "--out-tag", tag,
        "--out-dir", out_dir,
        "-v",
    ]
    if force:
        cmd.append("--force")

    # Step logs land at <jobs_log_dir>/<user>/<tag>/<step>/<seq>.out|.err.
    # jobs_log_dir is preset-relative ("output/logs/jobs", resolved from the
    # repo cwd) and user defaults to "local" on Windows; cover both roots.
    log_roots = [
        os.path.join(out_dir, "logs", "jobs", "local", tag),
        os.path.join(repo, "output", "logs", "jobs", "local", tag),
    ]
    rc, tail = _run_streaming(
        cmd, repo, _env_with_conda(conda_exe), "MAMMA",
        log_roots=list(dict.fromkeys(log_roots)), seq=seq,
    )
    if rc != 0:
        raise RuntimeError(f"MAMMA pipeline failed (exit {rc}). Last output:\n{tail[-4000:]}")

    paths = resolve_output_paths(out_dir, tag, footage_path, seq)
    status = "done"
    if not os.path.isfile(paths["preview_video"]):
        status = f"done (no preview at {paths['preview_video']})"
    paths["status"] = status
    return paths


def run_doctor(mamma_repo: str, conda_env: str = "mamma") -> str:
    repo = _norm(mamma_repo)
    if not os.path.isdir(repo):
        raise FileNotFoundError(f"MAMMA repo not found: {repo}")
    conda_exe = find_conda()
    cmd = [
        conda_exe, "run", "-n", conda_env, "--no-capture-output",
        "python", "-m", "inference", "doctor",
    ]
    rc, tail = _run_streaming(cmd, repo, _env_with_conda(conda_exe), "MAMMA-doctor")
    if rc != 0:
        raise RuntimeError(tail.strip() or f"doctor failed with exit {rc}")
    return tail.strip()
