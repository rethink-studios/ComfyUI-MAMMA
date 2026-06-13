# ComfyUI-MAMMA

ComfyUI custom nodes for [MAMMA](https://github.com/cuevhv/mamma) — markerless
multi-camera motion capture (SMPL-X body fitting from synchronized video).

**Export directly to VFX pipelines** — animated **USD** (`.usdc`) with per-frame
body meshes, preset orientation and units for **Maya**, **Houdini**, **Blender**,
and **Unreal Engine**. One file, time-sampled geometry, ready to reference in a
shot or stage without a manual retarget pass.

Runs MAMMA in a **self-contained Python environment** (micromamba + CUDA 12.4 +
PyTorch 2.5) managed by this node pack. Your ComfyUI install is not modified.

**Windows only** (NVIDIA GPU). Linux support is not tested with this installer.

---

> ### Required after install: gated weights
>
> **`install_env.bat` alone is not enough.** You must register (free) at
> [MAMMA](https://mamma.is.tue.mpg.de/) and [SMPL-X](https://smpl-x.is.tue.mpg.de/),
> then run `scripts\download_gated_weights.bat`.
>
> **Full walkthrough (screenshots-level detail): [GATED_WEIGHTS.md](GATED_WEIGHTS.md)**  
> Also linked from the repo **Issues** tab → *Download gated weights*.

---

## Quick start

1. Clone this repo into `ComfyUI/custom_nodes/ComfyUI-MAMMA`:
   `git clone https://github.com/rethink-studios/ComfyUI-MAMMA.git`
2. Clone [MAMMA](https://github.com/cuevhv/mamma) somewhere local (not a network share)
3. Run `scripts\install_env.bat` (patches MAMMA + builds env, ~20–40 min)
4. **Gated weights (required)** — [GATED_WEIGHTS.md](GATED_WEIGHTS.md) → `scripts\download_gated_weights.bat`
5. Run `scripts\doctor.bat` — should report PASS
6. Open `example_workflows/MAMMA Render.json`, set **mamma_repo** on each node, queue

## Requirements

| Requirement | Notes |
|-------------|-------|
| Windows 10/11 | NVIDIA GPU with CUDA |
| [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) | "Desktop development with C++" workload (one-time, for detectron2 compile) |
| MAMMA repo clone | `git clone https://github.com/cuevhv/mamma.git` |
| Disk space | ~15–20 GB (env + weights + outputs) |
| Two free accounts | **Required** — [GATED_WEIGHTS.md](GATED_WEIGHTS.md) (MAMMA + SMPL-X) |

## Installation

### 1. Clone both repositories

```text
ComfyUI/
  custom_nodes/
    ComfyUI-MAMMA/     ← git clone https://github.com/rethink-studios/ComfyUI-MAMMA.git
C:\dev\mamma\         ← git clone https://github.com/cuevhv/mamma.git
```

Optional: copy `scripts\set_mamma_repo.bat.example` to `set_mamma_repo.bat` and set
`MAMMA_REPO` / `MAMMA_FOOTAGE` so batch scripts and node defaults are pre-filled.

### 2. Install environment

**Option A — batch script (recommended)**

```bat
scripts\install_env.bat
```

Applies Windows patches to your MAMMA clone, then runs the full installer.

**Option B — ComfyUI node**

Add **MAMMA Install Environment**, set `mamma_repo`, queue once.

**Option C — Python**

```bat
python scripts\apply_windows_patches.py --repo C:\dev\mamma
python install_env.py --repo C:\dev\mamma --step all
```

The runtime lives in `ComfyUI-MAMMA\.runtime\` when the node folder is on a local
drive. If the node folder is on a network share (`\\server\...`), the runtime is
created under `%LOCALAPPDATA%\ComfyUI-MAMMA\runtime` instead.

### 3. Download weights

Public weights (SAM2, YOLO, CLIP) — no account:

```bat
scripts\download_public_weights.bat
```

Gated weights (landmark checkpoint, SMPL-X) — requires registration:

```bat
scripts\download_gated_weights.bat
```

Full details: [docs/WEIGHTS.md](docs/WEIGHTS.md)

### 4. Verify

```bat
scripts\doctor.bat
```

Or queue **MAMMA Doctor (Preflight)** in ComfyUI.

## Nodes

| Node | Purpose |
|------|---------|
| MAMMA Load Video (from Path) | Load MP4/MOV from any absolute path |
| MAMMA Install Environment | One-time env setup + weight downloads |
| MAMMA Doctor (Preflight) | Health check |
| MAMMA Build Footage (from Videos) | Arrange videos into MAMMA's multi-camera layout |
| MAMMA Calibration | Validate / write camera calibration YAML |
| MAMMA Run Motion Capture | Full pipeline: masks → 2D → 3D → visualization |
| MAMMA Export Mesh Sequence | **USD** (animated `.usdc`) or per-frame OBJ/PLY — DCC presets for Maya, Houdini, Blender, Unreal |
| MAMMA Load Preview Video | Load rendered preview |
| MAMMA Load Overlay Video / List Overlay Videos | Per-camera overlay renders |

Example workflow: `example_workflows/MAMMA Render.json`

After loading the workflow, set **mamma_repo** on **MAMMA Run** and paths on the
video loader nodes. Use **`full.yaml`** for all frames; **`quick.yaml`** is a
30-frame demo only.

## VFX & DCC export (USD)

The **MAMMA Export Mesh Sequence** node turns `ma_3d` results into production-ready
geometry. **USD is the default** — the industry-standard scene format for VFX and
real-time pipelines (Pixar USD, Solaris, Maya USD, Houdini LOPs, Blender, Unreal).

Connect **ma_3d_dir** from **MAMMA Run** to **MAMMA Export Mesh Sequence**.

### Why USD

- **One animated file** — `mamma_motion.usdc` holds every tracked person with
  time-sampled vertex positions (no folder of thousands of OBJs)
- **Stage-native** — reference the cache on a USD stage alongside cameras, sets,
  and lighting; swap versions without re-importing
- **Pipeline-friendly** — same format used across film, TV, and games; ideal for
  comp, layout, and previz handoff

### DCC presets (`target_app`)

Each preset bakes the **axis orientation** and **units** the destination app
expects so you don't double-convert on import:

| Preset | App | Up axis | Units |
|--------|-----|---------|-------|
| `maya` | Autodesk Maya | Y-up | centimetres |
| `houdini` | SideFX Houdini | Y-up | metres |
| `blender` | Blender | Z-up | metres |
| `unreal` | Unreal Engine | Z-up | centimetres |
| `raw` | Custom / scripting | Z-up (MAMMA native) | metres |

Typical workflow: run capture → export with `format: usd` and `target_app: maya`
(or `houdini`, etc.) → reference `mamma_motion.usdc` in your shot.

### Export options

- **format**: `usd` (default) — single animated USD cache; `obj` / `ply` — per-frame
  sequences for tools that don't read USD
- **fps**: playback rate baked into USD time samples (match source footage)
- **every_nth**: subsample frames (1 = every frame)

Output example: `mamma_motion.usdc` with one `UsdGeomMesh` per person, vertex
animation on the stage timeline.

## Calibration

MAMMA does **not** auto-calibrate. Supply camera intrinsics/extrinsics in a YAML
file (see `mamma/configs/examples/calib/`). Use **MAMMA Calibration** to validate
and write the file your run will use.

## Troubleshooting

See [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

## Before pushing to GitHub

- `.runtime/` is local-only (~15 GB micromamba env) — never commit it
- Copy `scripts\set_mamma_repo.bat.example` → `set_mamma_repo.bat` for local paths (gitignored)
- Do not save workflows with password fields filled — see [SECURITY.md](SECURITY.md)
- Run `scripts\verify_clean.bat` before `git push`

## License

MIT — see [LICENSE](LICENSE). MAMMA, SMPL-X, and downloaded model weights are
subject to their own licenses.

## Credits

- [MAMMA](https://github.com/cuevhv/mamma) — Max Planck Institute for Intelligent Systems
- ComfyUI integration by [rethink-studios](https://github.com/rethink-studios)
