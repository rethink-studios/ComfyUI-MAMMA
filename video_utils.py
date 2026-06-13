from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import torch


def load_video_frames(
    video_path: str,
    max_frames: int = 0,
    skip_first: int = 0,
    select_every_nth: int = 1,
) -> tuple[torch.Tensor, float]:
    path = os.path.normpath(os.path.expanduser(video_path.strip()))
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Video not found: {path}")

    try:
        import cv2
    except ImportError as exc:
        raise ImportError("opencv-python is required to load MAMMA preview videos") from exc

    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {path}")

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    frames: list[np.ndarray] = []
    index = 0
    loaded = 0

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if index < skip_first:
            index += 1
            continue
        if select_every_nth > 1 and ((index - skip_first) % select_every_nth) != 0:
            index += 1
            continue
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        frames.append(frame.astype(np.float32) / 255.0)
        loaded += 1
        index += 1
        if max_frames > 0 and loaded >= max_frames:
            break

    cap.release()
    if not frames:
        return torch.zeros((1, 64, 64, 3), dtype=torch.float32), fps
    return torch.from_numpy(np.stack(frames)), fps


def list_overlay_videos(overlay_dir: str) -> list[str]:
    root = Path(os.path.normpath(os.path.expanduser(overlay_dir.strip())))
    if not root.is_dir():
        return []
    return sorted(str(p) for p in root.glob("*.mp4") if p.name.lower() != "preview.mp4")
