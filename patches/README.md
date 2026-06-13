# Windows compatibility patches for upstream MAMMA

These files override parts of a standard `cuevhv/mamma` clone so the pipeline
runs on Windows with an NVIDIA GPU.

Applied automatically by:

- `scripts\apply_windows_patches.bat`
- `scripts\install_env.bat`
- `install_env.py` (start of install, Windows only)

## Patched files

| Path | Fix |
|------|-----|
| `segmentation/process_sequence.py` | DONE sentinel, clean process exit |
| `segmentation/run_ma_masks.py` | Avoid DLL teardown crash on exit |
| `segmentation/core/pipeline.py` | Skip t-SNE on Windows |
| `landmarks/run_ma_2d.py` | Clean process exit |
| `landmarks/utils/video_utils.py` | Bundled ffmpeg via imageio_ffmpeg |
| `optimization/run_ma_3d.py` | EGL guard, subprocess detection analysis, clean exit |
| `optimization/utils/utils_camera.py` | No EGL on Windows |
| `optimization/scene_debug/renderer.py` | No EGL on Windows |
| `optimization/utils/video_tools.py` | Bundled ffmpeg |
| `visualization/run_ma_vis.py` | Clean process exit |
| `visualization/overlay.py` | WGL/OpenGL fix, live progress lines |

Original files are backed up as `*.orig` on first apply.

After `git pull` in your MAMMA clone, re-run:

```bat
scripts\apply_windows_patches.bat
```
