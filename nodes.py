from __future__ import annotations

import os

from .mamma_runner import list_presets, run_doctor, run_pipeline
from .mesh_export import export_mesh_sequence
from .video_utils import list_overlay_videos, load_video_frames

# Set MAMMA_REPO / MAMMA_FOOTAGE env vars to pre-fill node widgets, or configure
# paths on each node after install.
MAMMA_REPO = os.environ.get("MAMMA_REPO", "").strip()
FOOTAGE_ROOT = os.environ.get("MAMMA_FOOTAGE", "").strip()


def _example_calib(repo: str = "") -> str:
    if repo:
        return os.path.join(repo, "configs", "examples", "calib", "iphones_outdoors.yaml")
    return "configs/examples/calib/iphones_outdoors.yaml"


def _body_models_dir(repo: str = "") -> str:
    if repo:
        return os.path.join(repo, "data", "body_models")
    return "data/body_models"


EXAMPLE_CALIB = _example_calib(MAMMA_REPO)


class MAMMALoadVideoPath:
    """Load a video (MP4/MOV/...) from any file path as a ComfyUI VIDEO.

    The core "Load Video" node only lists files inside ComfyUI's input
    folder; this node accepts an absolute path (network drives included).
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video_path": ("STRING", {"default": "", "multiline": False,
                                           "tooltip": "Full path to MP4/MOV, e.g. C:\\footage\\camA.mp4"}),
            }
        }

    RETURN_TYPES = ("VIDEO",)
    RETURN_NAMES = ("video",)
    FUNCTION = "load"
    CATEGORY = "MAMMA"

    @classmethod
    def IS_CHANGED(cls, video_path):
        path = os.path.normpath(os.path.expanduser(video_path.strip().strip('"')))
        try:
            return f"{path}:{os.path.getmtime(path)}:{os.path.getsize(path)}"
        except OSError:
            return path

    def load(self, video_path):
        path = os.path.normpath(os.path.expanduser(video_path.strip().strip('"')))
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Video not found: {path}")
        try:
            from comfy_api.input_impl import VideoFromFile
        except ImportError:
            from comfy_api.input_impl.video_types import VideoFromFile
        return (VideoFromFile(path),)


class MAMMAFootageBuilder:
    """Arrange ComfyUI VIDEO inputs into MAMMA's footage layout.

    Connect core "Load Video" nodes (one per camera). Files are written as
    <footage_root>/<seq_name>/videos/<CAM>.mp4 — the layout MAMMA's runner
    auto-detects.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "footage_root": ("STRING", {"default": FOOTAGE_ROOT, "multiline": False}),
                "seq_name": ("STRING", {"default": "capture01", "multiline": False}),
                "camera_names": ("STRING", {"default": "A001,B001,C001,D001", "multiline": False}),
                "video_1": ("VIDEO",),
            },
            "optional": {
                "video_2": ("VIDEO",),
                "video_3": ("VIDEO",),
                "video_4": ("VIDEO",),
                "video_5": ("VIDEO",),
                "video_6": ("VIDEO",),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("footage", "seq_name", "info")
    FUNCTION = "build"
    CATEGORY = "MAMMA"

    def build(self, footage_root, seq_name, camera_names, video_1,
              video_2=None, video_3=None, video_4=None, video_5=None, video_6=None):
        videos = [v for v in (video_1, video_2, video_3, video_4, video_5, video_6) if v is not None]
        names = [n.strip() for n in camera_names.split(",") if n.strip()]
        if len(names) < len(videos):
            raise ValueError(
                f"{len(videos)} videos connected but only {len(names)} camera names given: {names}"
            )
        if len(videos) < 2:
            print("[MAMMA] WARNING: MAMMA is a multi-view method; 1 camera will not reconstruct well. 3+ recommended.")

        seq = seq_name.strip()
        videos_dir = os.path.join(os.path.normpath(footage_root.strip()), seq, "videos")
        os.makedirs(videos_dir, exist_ok=True)

        written = []
        for name, vid in zip(names, videos):
            target = os.path.join(videos_dir, f"{name}.mp4")
            vid.save_to(target)
            written.append(f"{name}.mp4 ({os.path.getsize(target) / 1e6:.1f} MB)")
            print(f"[MAMMA] wrote {target}")

        info = f"{len(written)} camera(s) -> {videos_dir}\n" + "\n".join(written)
        return (os.path.normpath(footage_root.strip()), seq, info)


class MAMMACalibration:
    """Validate or author a MAMMA calibration YAML.

    MAMMA does not auto-calibrate: you must supply per-camera intrinsics and
    extrinsics (see mamma/docs/YOUR-DATA.md). Either point calib_file at an
    existing .yaml/.xcp/.json, or paste YAML into yaml_text to write a new
    file at save_path.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "calib_file": ("STRING", {"default": EXAMPLE_CALIB, "multiline": False}),
                "yaml_text": ("STRING", {"default": "", "multiline": True}),
                "save_path": ("STRING", {
                    "default": os.path.join(FOOTAGE_ROOT, "calibration.yaml"),
                    "multiline": False,
                }),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("calib", "report")
    FUNCTION = "resolve"
    CATEGORY = "MAMMA"

    _REQUIRED_KEYS = ("intrinsics", "resolution", "translation", "rotation_quaternion")

    def resolve(self, calib_file, yaml_text, save_path):
        import yaml

        if yaml_text.strip():
            data = yaml.safe_load(yaml_text)
            self._validate(data, "<yaml_text>")
            path = os.path.normpath(os.path.expanduser(save_path.strip()))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(yaml_text)
        else:
            path = os.path.normpath(os.path.expanduser(calib_file.strip()))
            if not os.path.isfile(path):
                raise FileNotFoundError(f"Calibration file not found: {path}")
            if path.lower().endswith((".yaml", ".yml")):
                with open(path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                self._validate(data, path)
            else:
                data = None  # .xcp / OpenCV .json validated by MAMMA itself

        if isinstance(data, dict):
            cams = data["cameras"]
            lines = [
                f"{name}: {c.get('resolution', '?')} px, "
                f"f=({c['intrinsics'][0]:.0f},{c['intrinsics'][1]:.0f})"
                for name, c in cams.items()
            ]
            report = f"{len(cams)} camera(s) in {path}\n" + "\n".join(lines)
        else:
            report = f"Using {path} (format validated by MAMMA at run time)"
        return (path, report)

    def _validate(self, data, source):
        if not isinstance(data, dict) or not isinstance(data.get("cameras"), dict) or not data["cameras"]:
            raise ValueError(
                f"{source}: calibration YAML must contain a non-empty 'cameras:' mapping. "
                "See mamma/configs/examples/calib/iphones_outdoors.yaml for the format."
            )
        for name, cam in data["cameras"].items():
            missing = [k for k in self._REQUIRED_KEYS if k not in cam]
            if missing:
                raise ValueError(f"{source}: camera {name!r} missing keys: {missing}")


class MAMMARun:
    @classmethod
    def INPUT_TYPES(cls):
        presets = list_presets(MAMMA_REPO)
        return {
            "required": {
                "mamma_repo": ("STRING", {"default": MAMMA_REPO, "multiline": False}),
                "preset": (presets, {"default": "full.yaml" if "full.yaml" in presets else presets[0],
                                      "tooltip": "full.yaml = all frames; quick.yaml = 30-frame demo (60-90)"}),
                "footage": ("STRING", {"default": "", "multiline": False}),
                "seq_name": ("STRING", {"default": "", "multiline": False}),
                "calib": ("STRING", {"default": EXAMPLE_CALIB, "multiline": False}),
                "out_tag": ("STRING", {"default": "comfy", "multiline": False}),
                "out_dir": ("STRING", {"default": "", "multiline": False}),
                "conda_env": ("STRING", {"default": "mamma", "multiline": False}),
                "start_frame": ("INT", {"default": -1, "min": -1, "max": 100000,
                                         "tooltip": "-1 = preset default (full.yaml processes every frame)"}),
                "end_frame": ("INT", {"default": -1, "min": -1, "max": 100000,
                                       "tooltip": "-1 = preset default"}),
                "force": ("BOOLEAN", {"default": False}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("vis_dir", "preview_video", "overlay_dir", "ma_3d_dir", "status")
    FUNCTION = "run"
    CATEGORY = "MAMMA"
    OUTPUT_NODE = True

    def run(self, mamma_repo, preset, footage, seq_name, calib, out_tag, out_dir,
            conda_env, start_frame, end_frame, force):
        paths = run_pipeline(
            mamma_repo=mamma_repo,
            preset=preset,
            footage=footage,
            seq_name=seq_name,
            calib=calib,
            out_tag=out_tag,
            out_dir=out_dir,
            conda_env=conda_env,
            start_frame=start_frame,
            end_frame=end_frame,
            force=force,
        )
        return (
            paths["vis_dir"],
            paths["preview_video"],
            paths["overlay_dir"],
            paths["ma_3d_dir"],
            paths["status"],
        )


class MAMMAExportMeshes:
    """Export ma_3d SMPL-X results as animated geometry.

    'usd' writes a single mamma_motion.usdc with per-frame vertex animation
    (imports as animated meshes in Blender/Houdini/Maya/Unreal).
    'obj'/'ply' write one file per frame per person.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "ma_3d_dir": ("STRING", {"default": "", "multiline": False}),
                "export_dir": ("STRING", {"default": "", "multiline": False,
                                           "tooltip": "Empty = <ma_3d_dir>_meshes"}),
                "format": (["usd", "obj", "ply"], {"default": "usd",
                            "tooltip": "usd = one animated file; obj/ply = per-frame sequence"}),
                "target_app": (["maya", "houdini", "blender", "unreal", "raw"], {
                    "default": "maya",
                    "tooltip": "Bakes the orientation/units the app expects: "
                               "Maya = Y-up cm, Houdini = Y-up m, Blender = Z-up m, "
                               "Unreal = Z-up cm, raw = MAMMA native (Z-up m)"}),
                "fps": ("FLOAT", {"default": 30.0, "min": 1.0, "max": 240.0, "step": 1.0,
                                   "tooltip": "Playback rate baked into the USD (match source footage)"}),
                "every_nth": ("INT", {"default": 1, "min": 1, "max": 100}),
                "smplx_models_dir": ("STRING", {
                    "default": _body_models_dir(MAMMA_REPO),
                    "multiline": False,
                    "tooltip": "Folder containing SMPLX_*.npz (for triangle faces)",
                }),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("export_dir", "report")
    FUNCTION = "export"
    CATEGORY = "MAMMA"
    OUTPUT_NODE = True

    def export(self, ma_3d_dir, export_dir, format, target_app, fps, every_nth, smplx_models_dir):
        out_dir, report = export_mesh_sequence(
            ma_3d_dir=ma_3d_dir,
            export_dir=export_dir,
            fmt=format,
            every_nth=every_nth,
            smplx_search_dir=smplx_models_dir,
            fps=fps,
            target=target_app,
        )
        print(f"[MAMMA-export] {report}")
        return (out_dir, report)


class MAMMAInstallEnv:
    """One-click installer for the self-contained MAMMA environment.

    Everything lands inside the node pack's .runtime folder: micromamba,
    the conda env (~15-25 GB), and a conda shim. Weights need free accounts
    at mamma.is.tue.mpg.de and smpl-x.is.tue.mpg.de — leave credentials
    empty to skip that step and rerun it later.
    """

    @classmethod
    def INPUT_TYPES(cls):
        from .install_env import STEPS
        return {
            "required": {
                "mamma_repo": ("STRING", {"default": MAMMA_REPO, "multiline": False}),
                "step": (["all"] + STEPS, {"default": "all"}),
                "force": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                "mamma_username": ("STRING", {
                    "default": "", "multiline": False,
                    "tooltip": "Optional — prefer scripts\\download_gated_weights.bat. Do not save workflows with passwords.",
                }),
                "mamma_password": ("STRING", {
                    "default": "", "multiline": False,
                    "tooltip": "Not stored on disk. Clear before saving workflow JSON.",
                }),
                "smplx_username": ("STRING", {
                    "default": "", "multiline": False,
                    "tooltip": "Separate SMPL-X account — see docs/WEIGHTS.md",
                }),
                "smplx_password": ("STRING", {
                    "default": "", "multiline": False,
                    "tooltip": "Not stored on disk. Clear before saving workflow JSON.",
                }),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("report",)
    FUNCTION = "install"
    CATEGORY = "MAMMA"
    OUTPUT_NODE = True

    def install(self, mamma_repo, step, force,
                mamma_username="", mamma_password="",
                smplx_username="", smplx_password=""):
        from .install_env import install
        report = install(
            mamma_repo=mamma_repo,
            step=step,
            force=force,
            mamma_user=mamma_username,
            mamma_pass=mamma_password,
            smplx_user=smplx_username,
            smplx_pass=smplx_password,
        )
        print(f"[MAMMA-install] {report}")
        return (report,)


class MAMMADoctor:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mamma_repo": ("STRING", {"default": MAMMA_REPO, "multiline": False}),
                "conda_env": ("STRING", {"default": "mamma", "multiline": False}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("report",)
    FUNCTION = "check"
    CATEGORY = "MAMMA"
    OUTPUT_NODE = True

    def check(self, mamma_repo, conda_env):
        return (run_doctor(mamma_repo, conda_env),)


class MAMMALoadPreview:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "preview_video": ("STRING", {"default": "", "multiline": False}),
                "max_frames": ("INT", {"default": 0, "min": 0, "max": 100000}),
                "skip_first": ("INT", {"default": 0, "min": 0, "max": 100000}),
                "select_every_nth": ("INT", {"default": 1, "min": 1, "max": 100}),
            }
        }

    RETURN_TYPES = ("IMAGE", "FLOAT", "INT")
    RETURN_NAMES = ("images", "fps", "frame_count")
    FUNCTION = "load"
    CATEGORY = "MAMMA"

    def load(self, preview_video, max_frames, skip_first, select_every_nth):
        images, fps = load_video_frames(
            preview_video,
            max_frames=max_frames,
            skip_first=skip_first,
            select_every_nth=select_every_nth,
        )
        return (images, fps, int(images.shape[0]))


class MAMMALoadOverlay:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "overlay_dir": ("STRING", {"default": "", "multiline": False}),
                "camera_index": ("INT", {"default": 0, "min": 0, "max": 64}),
                "max_frames": ("INT", {"default": 0, "min": 0, "max": 100000}),
            }
        }

    RETURN_TYPES = ("IMAGE", "STRING", "FLOAT", "INT")
    RETURN_NAMES = ("images", "video_path", "fps", "frame_count")
    FUNCTION = "load"
    CATEGORY = "MAMMA"

    def load(self, overlay_dir, camera_index, max_frames):
        videos = list_overlay_videos(overlay_dir)
        if not videos:
            raise FileNotFoundError(f"No overlay videos found in {overlay_dir}")
        if camera_index >= len(videos):
            raise IndexError(f"camera_index {camera_index} out of range ({len(videos)} videos)")
        video_path = videos[camera_index]
        images, fps = load_video_frames(video_path, max_frames=max_frames)
        return (images, video_path, fps, int(images.shape[0]))


class MAMMAOverlayList:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "overlay_dir": ("STRING", {"default": "", "multiline": False}),
            }
        }

    RETURN_TYPES = ("STRING", "INT")
    RETURN_NAMES = ("video_list", "count")
    FUNCTION = "list_videos"
    CATEGORY = "MAMMA"

    def list_videos(self, overlay_dir):
        videos = list_overlay_videos(overlay_dir)
        return ("\n".join(videos), len(videos))


NODE_CLASS_MAPPINGS = {
    "MAMMALoadVideoPath": MAMMALoadVideoPath,
    "MAMMAFootageBuilder": MAMMAFootageBuilder,
    "MAMMACalibration": MAMMACalibration,
    "MAMMARun": MAMMARun,
    "MAMMAExportMeshes": MAMMAExportMeshes,
    "MAMMAInstallEnv": MAMMAInstallEnv,
    "MAMMADoctor": MAMMADoctor,
    "MAMMALoadPreview": MAMMALoadPreview,
    "MAMMALoadOverlay": MAMMALoadOverlay,
    "MAMMAOverlayList": MAMMAOverlayList,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MAMMALoadVideoPath": "MAMMA Load Video (from Path)",
    "MAMMAFootageBuilder": "MAMMA Build Footage (from Videos)",
    "MAMMACalibration": "MAMMA Calibration",
    "MAMMARun": "MAMMA Run Motion Capture",
    "MAMMAExportMeshes": "MAMMA Export Mesh Sequence",
    "MAMMAInstallEnv": "MAMMA Install Environment",
    "MAMMADoctor": "MAMMA Doctor (Preflight)",
    "MAMMALoadPreview": "MAMMA Load Preview Video",
    "MAMMALoadOverlay": "MAMMA Load Overlay Video",
    "MAMMAOverlayList": "MAMMA List Overlay Videos",
}
