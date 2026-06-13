"""Export MAMMA ma_3d results to animated mesh sequences (OBJ/PLY).

ma_3d writes one ``verts_joints_body_id-NN.npz`` per person with
``pred_vertices`` of shape (F, V, 3) in metres. SMPL-X triangle topology is
constant, so faces are read once from the SMPL-X model npz shipped with the
MAMMA weights (key ``f``).
"""
from __future__ import annotations

import glob
import json
import os
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np

NODE_DIR = os.path.dirname(os.path.abspath(__file__))


def find_smplx_faces(search_dir: str) -> np.ndarray | None:
    """Locate a SMPLX_*.npz under search_dir and return its faces array."""
    root = os.path.normpath(os.path.expanduser(search_dir.strip()))
    patterns = ["**/SMPLX_NEUTRAL.npz", "**/SMPLX_*.npz", "**/smplx*.npz"]
    for pat in patterns:
        for path in sorted(glob.glob(os.path.join(root, pat), recursive=True)):
            try:
                with np.load(path, allow_pickle=True) as data:
                    if "f" in data.files:
                        return np.asarray(data["f"]).astype(np.int64)
            except Exception:
                continue
    return None


def load_person_motions(ma_3d_dir: str) -> list[tuple[int, np.ndarray]]:
    """Return [(body_id, vertices (F,V,3)), ...] sorted by body id."""
    root = os.path.normpath(os.path.expanduser(ma_3d_dir.strip()))
    paths = sorted(glob.glob(os.path.join(root, "verts_joints_body_id*.npz")))
    if not paths:
        raise FileNotFoundError(
            f"No verts_joints_body_id*.npz in {root}. "
            "Run the MAMMA pipeline first (ma_3d step must complete)."
        )
    out = []
    for path in paths:
        stem = Path(path).stem
        try:
            body_id = int(stem.split("body_id-")[-1])
        except ValueError:
            body_id = len(out)
        with np.load(path, allow_pickle=True) as data:
            verts = np.asarray(data["pred_vertices"], dtype=np.float32)
        if verts.ndim != 3 or verts.shape[-1] != 3:
            raise ValueError(f"{path}: pred_vertices must be (F, V, 3), got {verts.shape}")
        out.append((body_id, verts))
    out.sort(key=lambda t: t[0])
    return out


def write_obj(path: str, verts: np.ndarray, faces: np.ndarray | None) -> None:
    lines = [f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}" for v in verts]
    if faces is not None:
        lines += [f"f {a} {b} {c}" for a, b, c in (faces + 1)]
    with open(path, "w", encoding="ascii") as f:
        f.write("\n".join(lines) + "\n")


def write_ply(path: str, verts: np.ndarray, faces: np.ndarray | None) -> None:
    n_faces = 0 if faces is None else len(faces)
    header = (
        "ply\nformat binary_little_endian 1.0\n"
        f"element vertex {len(verts)}\n"
        "property float x\nproperty float y\nproperty float z\n"
        f"element face {n_faces}\n"
        "property list uchar int vertex_indices\n"
        "end_header\n"
    )
    with open(path, "wb") as f:
        f.write(header.encode("ascii"))
        f.write(verts.astype("<f4").tobytes())
        if faces is not None:
            buf = bytearray()
            for a, b, c in faces:
                buf += struct.pack("<Biii", 3, int(a), int(b), int(c))
            f.write(bytes(buf))


def _mamma_env_python() -> str:
    """Python.exe of the self-contained MAMMA env (used for USD export)."""
    state_path = os.path.join(NODE_DIR, ".runtime", "state.json")
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
        py = os.path.join(state["root_prefix"], "envs", state.get("env_name", "mamma"), "python.exe")
        if os.path.isfile(py):
            return py
    except (OSError, ValueError, KeyError):
        pass
    raise RuntimeError(
        "MAMMA env python not found — run the 'MAMMA Install Environment' node first."
    )


def _progress_bar(total: int):
    """ComfyUI progress bar if running inside ComfyUI, else None."""
    try:
        from comfy.utils import ProgressBar
        return ProgressBar(total)
    except Exception:
        return None


def export_usd(
    ma_3d_dir: str,
    export_dir: str,
    fps: float = 30.0,
    every_nth: int = 1,
    smplx_search_dir: str = "",
    target: str = "maya",
) -> tuple[str, str]:
    """Write one animated .usdc via the MAMMA env (installs usd-core on demand)."""
    py = _mamma_env_python()
    env = dict(os.environ, KMP_DUPLICATE_LIB_OK="TRUE")

    probe = subprocess.run([py, "-c", "import pxr"], capture_output=True, env=env)
    if probe.returncode != 0:
        print("[MAMMA-export] installing usd-core into the MAMMA env...")
        pip = subprocess.run(
            [py, "-m", "pip", "install", "--no-input", "usd-core"],
            capture_output=True, text=True, env=env,
        )
        if pip.returncode != 0:
            raise RuntimeError(f"pip install usd-core failed:\n{pip.stdout}\n{pip.stderr}")

    os.makedirs(export_dir, exist_ok=True)
    out_path = os.path.join(export_dir, "mamma_motion.usdc")
    cmd = [
        py, os.path.join(NODE_DIR, "usd_export.py"),
        "--ma_3d_dir", ma_3d_dir,
        "--out", out_path,
        "--fps", str(fps),
        "--every_nth", str(every_nth),
        "--smplx_dir", smplx_search_dir,
        "--target", target,
    ]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, env=env, cwd=NODE_DIR,
    )
    pbar = None
    tail: list[str] = []
    for line in proc.stdout:
        tail = (tail + [line])[-50:]
        if line.startswith("PROG "):
            try:
                done, total = int(line.split()[1]), int(line.split()[2])
            except (ValueError, IndexError):
                continue
            if pbar is None:
                pbar = _progress_bar(total)
            if pbar is not None:
                pbar.update_absolute(done, total)
        else:
            sys.stdout.write(line)
    rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"USD export failed (exit {rc}):\n{''.join(tail)}")

    report = f"Animated USD ({target} orientation/units) written to {out_path}"
    if not smplx_search_dir.strip() or find_smplx_faces(smplx_search_dir) is None:
        report += "\nWARNING: SMPL-X faces not found — exported point clouds only."
    return export_dir, report


def export_mesh_sequence(
    ma_3d_dir: str,
    export_dir: str = "",
    fmt: str = "obj",
    every_nth: int = 1,
    smplx_search_dir: str = "",
    fps: float = 30.0,
    target: str = "maya",
) -> tuple[str, str]:
    """Export per-person, per-frame meshes. Returns (export_dir, report)."""
    fmt = fmt.lower().strip()
    if fmt not in ("obj", "ply", "usd"):
        raise ValueError(f"format must be 'obj', 'ply' or 'usd', got {fmt!r}")
    every_nth = max(1, int(every_nth))

    if not export_dir.strip():
        export_dir = os.path.normpath(ma_3d_dir.strip()).rstrip("\\/") + "_meshes"
    export_dir = os.path.normpath(os.path.expanduser(export_dir.strip()))

    if fmt == "usd":
        return export_usd(
            ma_3d_dir=os.path.normpath(os.path.expanduser(ma_3d_dir.strip())),
            export_dir=export_dir,
            fps=fps,
            every_nth=every_nth,
            smplx_search_dir=smplx_search_dir,
            target=target,
        )

    persons = load_person_motions(ma_3d_dir)

    faces = None
    if smplx_search_dir.strip():
        faces = find_smplx_faces(smplx_search_dir)
    warnings = []
    if faces is None:
        warnings.append(
            "SMPL-X faces npz not found — exporting vertices only (point cloud). "
            "Point smplx_models_dir at the MAMMA body-model folder "
            "(e.g. <repo>/data/body_models)."
        )

    writer = write_obj if fmt == "obj" else write_ply
    expected = sum(len(range(0, v.shape[0], every_nth)) for _, v in persons)
    pbar = _progress_bar(expected)
    total = 0
    for body_id, verts in persons:
        person_dir = os.path.join(export_dir, f"person_{body_id:02d}")
        os.makedirs(person_dir, exist_ok=True)
        frame_indices = range(0, verts.shape[0], every_nth)
        for i in frame_indices:
            writer(os.path.join(person_dir, f"frame_{i:05d}.{fmt}"), verts[i], faces)
            total += 1
            if pbar is not None:
                pbar.update_absolute(total, expected)
        print(f"[MAMMA-export] person {body_id}: {len(list(frame_indices))} frames -> {person_dir}")

    report = (
        f"Exported {total} {fmt.upper()} meshes for {len(persons)} person(s) to {export_dir}"
        + ("" if faces is not None else "\nWARNING: " + warnings[0])
    )
    return export_dir, report
