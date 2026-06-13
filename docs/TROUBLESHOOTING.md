# Troubleshooting

## Install / environment

### `micromamba` / conda env on network drive

If ComfyUI or this node pack lives on `\\server\share\...`, the runtime is
automatically placed in `%LOCALAPPDATA%\ComfyUI-MAMMA\runtime`. Keep the MAMMA
**repo clone** on a local drive too.

### detectron2 / pytorch_sdf compile fails

Install [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/)
with **Desktop development with C++**, then re-run:

```bat
python install_env.py --repo C:\dev\mamma --step compile --force
```

### Doctor reports missing weights

See [WEIGHTS.md](WEIGHTS.md). Gated files are the usual gap after a fresh install.

## Pipeline runs

### Cancel does not stop processing

MAMMA runs as a subprocess tree. Use a recent build of this node pack (includes a
watchdog that `taskkill`s the tree on ComfyUI interrupt). If orphans remain after
killing ComfyUI, end `python.exe` processes whose command line contains `inference`
or `run_ma_`.

### Preset change wiped my outputs

Switching `quick.yaml` ↔ `full.yaml` (or changing frame range) triggers a forced
recompute and deletes cached step outputs. Use `full.yaml` for production runs and
save the workflow after setting it.

### `ma_vis` fails with `PYOPENGL_PLATFORM=wgl`

Another ComfyUI node may export `PYOPENGL_PLATFORM=wgl`. This pack strips it
before spawning MAMMA. Re-apply Windows patches if you updated the MAMMA clone
from upstream without re-running `apply_windows_patches.py`.

### `ma_masks` crashes with exit `4294967295`

Usually a Windows DLL teardown issue after the step actually finished. Recent
patches use `TerminateProcess` and a `DONE` sentinel so completed work is not
reported as failure. Re-run `scripts\apply_windows_patches.bat`.

### Progress bar stuck at 0%

`ma_3d` and `ma_vis` use custom log formats; ensure you are on a recent node
pack build. Heartbeat lines print every ~10s in the ComfyUI console even when
the UI bar is coarse.

### Export node validation errors (`target_app`, `fps`)

If the workflow was saved before export widgets were added, delete
**MAMMA Export Mesh Sequence**, re-add it, and reconnect `ma_3d_dir`.

## Workflow setup

### Video import

Core ComfyUI **Load Video** only sees the `input/` folder. Use **MAMMA Load Video
(from Path)** for absolute paths, or **MAMMA Build Footage** with core Load Video
nodes.

### Calibration

MAMMA does not estimate camera parameters from video alone. Provide a calibration
YAML (see `mamma/configs/examples/calib/`). **MAMMA Calibration** validates it.

## Getting help

Include:

- ComfyUI console log (last ~100 lines with `[MAMMA]`)
- `output/logs/jobs/local/comfy/<step>/capture01.err` for the failing step
- Preset name (`full.yaml` vs `quick.yaml`) and frame range
- GPU model and whether the MAMMA repo is on a local or network path
