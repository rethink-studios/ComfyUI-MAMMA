"""Apply bundled Windows compatibility patches to a MAMMA repo clone.

Upstream MAMMA targets Linux clusters. These patches fix OpenGL, ffmpeg,
OpenMP teardown crashes, and progress logging on Windows.

Usage:
  python scripts/apply_windows_patches.py --repo C:\\path\\to\\mamma
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys

NODE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATCH_ROOT = os.path.join(NODE_DIR, "patches", "mamma")


def apply(repo: str, dry_run: bool = False) -> list[str]:
    repo = os.path.normpath(os.path.expanduser(repo))
    if not os.path.isdir(repo):
        raise FileNotFoundError(f"MAMMA repo not found: {repo}")
    if not os.path.isdir(PATCH_ROOT):
        raise FileNotFoundError(f"patch bundle missing: {PATCH_ROOT}")

    applied: list[str] = []
    for root, _dirs, files in os.walk(PATCH_ROOT):
        for name in files:
            rel = os.path.relpath(os.path.join(root, name), PATCH_ROOT)
            src = os.path.join(root, name)
            dst = os.path.join(repo, rel)
            if dry_run:
                print(f"would patch: {rel}")
            else:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                if os.path.isfile(dst):
                    bak = dst + ".orig"
                    if not os.path.isfile(bak):
                        shutil.copy2(dst, bak)
                shutil.copy2(src, dst)
                print(f"patched: {rel}")
            applied.append(rel)
    return applied


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", required=True, help="path to MAMMA repo clone")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    files = apply(args.repo, dry_run=args.dry_run)
    if not files:
        print("no patch files found", file=sys.stderr)
        sys.exit(1)
    print(f"done ({len(files)} files)")


if __name__ == "__main__":
    main()
