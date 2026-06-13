"""Write MAMMA ma_3d results as a single animated USD file.

Runs inside the MAMMA conda env (needs usd-core + numpy). One UsdGeomMesh
per person with time-sampled points. MAMMA's data is Z-up metres; the
--target preset bakes the rotation/scale the destination app expects and
stamps matching stage metadata so importers don't double-convert.

Emits "PROG <done> <total>" lines on stdout for progress reporting.
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mesh_export import find_smplx_faces, load_person_motions  # noqa: E402

# Source data: Z-up, metres. rotate_x converts to Y-up where needed.
TARGETS = {
    "maya":    {"rotate_x": -90.0, "scale": 100.0, "up": "y", "mpu": 0.01},  # Y-up, cm
    "houdini": {"rotate_x": -90.0, "scale": 1.0,   "up": "y", "mpu": 1.0},   # Y-up, m
    "blender": {"rotate_x": 0.0,   "scale": 1.0,   "up": "z", "mpu": 1.0},   # Z-up, m
    "unreal":  {"rotate_x": 0.0,   "scale": 100.0, "up": "z", "mpu": 0.01},  # Z-up, cm
    "raw":     {"rotate_x": 0.0,   "scale": 1.0,   "up": "z", "mpu": 1.0},   # native
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ma_3d_dir", required=True)
    ap.add_argument("--out", required=True, help="Output .usd/.usdc/.usda path")
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--every_nth", type=int, default=1)
    ap.add_argument("--smplx_dir", default="")
    ap.add_argument("--target", choices=sorted(TARGETS), default="maya")
    args = ap.parse_args()

    from pxr import Gf, Usd, UsdGeom, Vt

    persons = load_person_motions(args.ma_3d_dir)
    faces = find_smplx_faces(args.smplx_dir) if args.smplx_dir.strip() else None
    stride = max(1, args.every_nth)
    t_cfg = TARGETS[args.target]

    out_path = os.path.normpath(args.out)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    if os.path.exists(out_path):
        os.remove(out_path)

    stage = Usd.Stage.CreateNew(out_path)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y if t_cfg["up"] == "y" else UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, t_cfg["mpu"])
    fps = args.fps / stride
    stage.SetTimeCodesPerSecond(fps)
    stage.SetFramesPerSecond(fps)

    root = UsdGeom.Xform.Define(stage, "/MAMMA")
    stage.SetDefaultPrim(root.GetPrim())
    if t_cfg["rotate_x"]:
        root.AddRotateXOp().Set(t_cfg["rotate_x"])
    if t_cfg["scale"] != 1.0:
        s = float(t_cfg["scale"])
        root.AddScaleOp().Set(Gf.Vec3f(s, s, s))

    if faces is not None:
        counts = Vt.IntArray([3] * len(faces))
        indices = Vt.IntArray(faces.astype(np.int32).flatten().tolist())

    total = sum(len(verts[::stride]) for _, verts in persons)
    done = 0
    max_frames = 0
    for body_id, verts in persons:
        verts = verts[::stride]
        max_frames = max(max_frames, len(verts))
        mesh = UsdGeom.Mesh.Define(stage, f"/MAMMA/person_{body_id:02d}")
        mesh.CreateSubdivisionSchemeAttr(UsdGeom.Tokens.none)
        if faces is not None:
            mesh.CreateFaceVertexCountsAttr(counts)
            mesh.CreateFaceVertexIndicesAttr(indices)
        pts_attr = mesh.CreatePointsAttr()
        ext_attr = mesh.CreateExtentAttr()
        for i, frame in enumerate(verts):
            frame = np.ascontiguousarray(frame, dtype=np.float32)
            t = Usd.TimeCode(i)
            pts_attr.Set(Vt.Vec3fArray.FromNumpy(frame), t)
            lo = [float(x) for x in frame.min(axis=0)]
            hi = [float(x) for x in frame.max(axis=0)]
            ext_attr.Set(Vt.Vec3fArray([Gf.Vec3f(*lo), Gf.Vec3f(*hi)]), t)
            done += 1
            if done % 10 == 0 or done == total:
                print(f"PROG {done} {total}", flush=True)
        print(f"[MAMMA-usd] person {body_id}: {len(verts)} frames", flush=True)

    stage.SetStartTimeCode(0)
    stage.SetEndTimeCode(max(0, max_frames - 1))
    stage.GetRootLayer().Save()
    print(
        f"[MAMMA-usd] wrote {out_path} ({len(persons)} person(s), {max_frames} frames "
        f"@ {fps:g} fps, target={args.target})",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    rc = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(rc)
