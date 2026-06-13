# Security

## Credentials

- Gated weight downloads use your MAMMA / SMPL-X account via `download.is.tue.mpg.de`
- Credentials are **not written to disk** by `download_weights.py` or `install_env.py`
- Prefer `scripts\download_gated_weights.bat` or environment variables over filling
  password fields on the **MAMMA Install Environment** node
- **Do not save ComfyUI workflows** that contain username/password widget values

## Environment variables (optional)

```bat
set MAMMA_USERNAME=you@example.com
set MAMMA_PASSWORD=...
set SMPLX_USERNAME=you@example.com
set SMPLX_PASSWORD=...
```

Unset them after use on shared machines.

## Repository hygiene

Never commit:

- `.runtime/` (micromamba env, ~15+ GB)
- `scripts/set_mamma_repo.bat` (local paths)
- `.env` files

Run `scripts\verify_clean.bat` before `git push`.
