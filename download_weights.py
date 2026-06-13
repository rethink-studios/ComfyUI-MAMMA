"""Download the license-gated MAMMA model weights.

Both downloads require free registration (separate accounts):
  * MAMMA   -> https://mamma.is.tue.mpg.de/
  * SMPL-X  -> https://smpl-x.is.tue.mpg.de/

Credentials are taken from CLI args, then environment variables
(MAMMA_USERNAME / MAMMA_PASSWORD / SMPLX_USERNAME / SMPLX_PASSWORD),
then an interactive prompt. They are only sent to download.is.tue.mpg.de
and are never stored.

Usage:
  python download_weights.py --repo C:\\path\\to\\mamma
  python download_weights.py --repo C:\\path\\to\\mamma --mamma-user you@mail.com ...
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from install_env import load_state, step_weights  # noqa: E402


def _resolve(value: str, env_key: str, prompt: str, secret: bool = False) -> str:
    if value:
        return value
    if os.environ.get(env_key):
        return os.environ[env_key]
    if not sys.stdin.isatty():
        return ""
    ask = getpass.getpass if secret else input
    return ask(prompt).strip()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", required=True, help="path to the MAMMA repo clone")
    ap.add_argument("--mamma-user", default="")
    ap.add_argument("--mamma-pass", default="")
    ap.add_argument("--smplx-user", default="")
    ap.add_argument("--smplx-pass", default="")
    ap.add_argument("--skip-mamma", action="store_true")
    ap.add_argument("--skip-smplx", action="store_true")
    args = ap.parse_args()

    if not os.path.isdir(args.repo):
        sys.exit(f"MAMMA repo not found: {args.repo}")

    mamma_user = mamma_pass = smplx_user = smplx_pass = ""
    if not args.skip_mamma:
        print("MAMMA account (register at https://mamma.is.tue.mpg.de/)")
        mamma_user = _resolve(args.mamma_user, "MAMMA_USERNAME", "  email: ")
        mamma_pass = _resolve(args.mamma_pass, "MAMMA_PASSWORD", "  password: ", secret=True)
    if not args.skip_smplx:
        print("SMPL-X account (register at https://smpl-x.is.tue.mpg.de/)")
        smplx_user = _resolve(args.smplx_user, "SMPLX_USERNAME", "  email: ")
        smplx_pass = _resolve(args.smplx_pass, "SMPLX_PASSWORD", "  password: ", secret=True)

    if not (mamma_user and mamma_pass) and not (smplx_user and smplx_pass):
        print("No credentials supplied; downloading public weights only.")

    runtime_dir = load_state().get("runtime_dir", "")
    step_weights(args.repo, mamma_user, mamma_pass, smplx_user, smplx_pass,
                 runtime_dir=runtime_dir)
    print("done.")


if __name__ == "__main__":
    main()
