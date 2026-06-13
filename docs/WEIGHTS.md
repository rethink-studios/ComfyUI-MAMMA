# Model weights

> **New here?** Use the step-by-step guide: **[GATED_WEIGHTS.md](../GATED_WEIGHTS.md)**  
> (registration, download script, verification, troubleshooting)

MAMMA needs several checkpoint files under `<mamma_repo>/data/`. Some are
downloaded automatically; two require **free registration** on separate sites.

## Weight inventory

| File | Size (approx) | Account required | Download |
|------|---------------|------------------|----------|
| `weights/sam2/sam2.1_hiera_large.pt` | ~900 MB | No | automatic |
| `weights/yolo/yolo12x.pt` | ~120 MB | No | automatic |
| CLIP ViT-B-32 (Hugging Face cache) | ~600 MB | No | automatic |
| `weights/ma_2d/mamma_mask_full_cvpr.ckpt` | gated | **MAMMA** | credentials |
| `body_models/downsampled_verts/verts_512.pkl` | gated | **MAMMA** | credentials |
| `body_models/smplx_locked_head/smplx/` | gated | **SMPL-X** | credentials |

## Public weights (no registration)

```bat
scripts\download_public_weights.bat
```

Or as part of `install_env.py --step weights` with no credentials supplied.

## Gated weights (registration required)

You need **two separate accounts**:

### 1. MAMMA account

1. Go to https://mamma.is.tue.mpg.de/
2. Register (free, academic/research license)
3. Log in and accept the license terms
4. Note your email and password

Downloads:
- `mamma_mask_full_cvpr.ckpt` (2D landmark network)
- `verts_512.pkl` (downsampled SMPL-X vertices)

### 2. SMPL-X account

1. Go to https://smpl-x.is.tue.mpg.de/
2. Register (**different** account from MAMMA)
3. Log in and accept the SMPL-X license
4. Note your email and password

Downloads:
- `smplx_lockedhead_20230207.zip` → extracted to
  `data/body_models/smplx_locked_head/smplx/SMPLX_*.npz`

### Run the downloader

```bat
scripts\download_gated_weights.bat
```

The script prompts for each account. Credentials are sent **only** to
`download.is.tue.mpg.de` and are **not stored** on disk.

### Alternative: environment variables

```bat
set MAMMA_USERNAME=you@example.com
set MAMMA_PASSWORD=your_mamma_password
set SMPLX_USERNAME=you@example.com
set SMPLX_PASSWORD=your_smplx_password
python download_weights.py --repo C:\dev\mamma
```

### Alternative: CLI flags

```bat
python download_weights.py --repo C:\dev\mamma ^
  --mamma-user you@example.com --mamma-pass ... ^
  --smplx-user you@example.com --smplx-pass ...
```

### Alternative: ComfyUI Install node

Fill the username/password fields on **MAMMA Install Environment** and run with
`step = weights` or `step = all`.

## Verify downloads

```bat
scripts\doctor.bat
```

Or check these paths exist:

```text
<mamma_repo>/data/weights/sam2/sam2.1_hiera_large.pt
<mamma_repo>/data/weights/yolo/yolo12x.pt
<mamma_repo>/data/weights/ma_2d/mamma_mask_full_cvpr.ckpt
<mamma_repo>/data/body_models/downsampled_verts/verts_512.pkl
<mamma_repo>/data/body_models/smplx_locked_head/smplx/SMPLX_NEUTRAL.npz
```

## Example footage

From the MAMMA repo:

```bash
cd mamma
bash data/download_example.sh
```

Point the workflow's video loader nodes at the downloaded `videos/A001.mp4` etc.

## License reminders

- MAMMA weights: subject to the [MAMMA license](https://mamma.is.tue.mpg.de/)
- SMPL-X: subject to the [SMPL-X license](https://smpl-x.is.tue.mpg.de/)
- Do not redistribute downloaded files; users must register and download themselves
