# Gated weights — start here

**`install_env.bat` is not enough.** The installer downloads public weights (SAM2, YOLO,
CLIP) automatically, but MAMMA **cannot run** until you also download **license-gated**
files. That requires **two free registrations** on MPI sites, then one download script.

> **Short version:** register at [mamma.is.tue.mpg.de](https://mamma.is.tue.mpg.de/) and
> [smpl-x.is.tue.mpg.de](https://smpl-x.is.tue.mpg.de/) (separate accounts) → run
> `scripts\download_gated_weights.bat` → run `scripts\doctor.bat` until PASS.

---

## What you are downloading

| File | Why you need it | Account |
|------|-----------------|---------|
| `data/weights/ma_2d/mamma_mask_full_cvpr.ckpt` | 2D landmarks / masks stage | **MAMMA** |
| `data/body_models/downsampled_verts/verts_512.pkl` | Faster SMPL-X fitting | **MAMMA** |
| `data/body_models/smplx_locked_head/smplx/SMPLX_*.npz` | Body mesh model | **SMPL-X** |

Public weights (no account) are already handled by install:

- `data/weights/sam2/sam2.1_hiera_large.pt`
- `data/weights/yolo/yolo12x.pt`
- Hugging Face CLIP cache (during install or first run)

If gated files are missing, **MAMMA Run** will fail in `ma_2d` or `ma_3d` with missing-file
errors. `scripts\doctor.bat` will also report problems.

---

## Before you start

- [ ] MAMMA repo cloned locally, e.g. `C:\dev\mamma` (not a network share)
- [ ] `scripts\install_env.bat` finished successfully (or ComfyUI **MAMMA Install Environment** node)
- [ ] ~2 GB free under `<mamma_repo>\data\` for gated downloads
- [ ] A browser to register; use a real email (activation links are sent)

Optional: set `MAMMA_REPO` so scripts stop asking:

```bat
copy scripts\set_mamma_repo.bat.example scripts\set_mamma_repo.bat
notepad scripts\set_mamma_repo.bat
call scripts\set_mamma_repo.bat
```

---

## Step 1 — Register a MAMMA account (~5 min)

This account downloads the **landmark checkpoint** and **vertex pickle**.

1. Open **https://mamma.is.tue.mpg.de/**
2. Click **Register** / **Sign up**
3. Fill in email, name, affiliation (research / studio is fine)
4. Confirm your email if prompted
5. Log in
6. Read and **accept the license agreement** on the site  
   (downloads are blocked until you accept)

Keep the **email and password** handy — you will type them into the download script.

**Do not** use these credentials for SMPL-X; that is a different site.

---

## Step 2 — Register a SMPL-X account (~5 min)

This account downloads the **SMPL-X body model** (locked-head variant MAMMA uses).

1. Open **https://smpl-x.is.tue.mpg.de/**
2. Register with a **new** account (can be the same email address, but it is a
   **separate login** from MAMMA)
3. Confirm email / log in
4. Accept the **SMPL-X license**

You need **both** accounts. One registration does not cover the other.

---

## Step 3 — Run the gated downloader

Open **Command Prompt** (not PowerShell required, either works):

```bat
cd ComfyUI\custom_nodes\ComfyUI-MAMMA
scripts\download_gated_weights.bat
```

If `MAMMA_REPO` is not set, paste your MAMMA clone path when prompted, e.g.
`C:\dev\mamma`.

### What the script asks

```
MAMMA account (register at https://mamma.is.tue.mpg.de/)
  email: you@studio.com
  password: ********

SMPL-X account (register at https://smpl-x.is.tue.mpg.de/)
  email: you@studio.com
  password: ********
```

- Passwords are hidden while typing (normal)
- Credentials go **only** to `download.is.tue.mpg.de` over HTTPS
- Nothing is saved to disk or written into workflow JSON

### What you should see

```
downloading weights/mamma_mask_full_cvpr.ckpt ...
[ok] mamma_mask_full_cvpr.ckpt (...)
downloading mamma_assets/verts_512.pkl ...
[ok] verts_512.pkl (...)
downloading smplx_lockedhead_20230207.zip ...
[ok] smplx_lockedhead_20230207.zip (...)
extracted SMPL-X locked-head model -> ...\data\body_models\smplx_locked_head
done.
```

Re-running the script is safe — existing files are skipped.

---

## Step 4 — Verify (required)

```bat
scripts\doctor.bat
```

Target: **exit code 0** / doctor reports PASS.

Manual check — these paths should exist:

```text
<mamma_repo>\data\weights\ma_2d\mamma_mask_full_cvpr.ckpt
<mamma_repo>\data\body_models\downsampled_verts\verts_512.pkl
<mamma_repo>\data\body_models\smplx_locked_head\smplx\SMPLX_NEUTRAL.npz
```

Then open ComfyUI, load `example_workflows/MAMMA Render.json`, set **mamma_repo** on
each node, and queue.

---

## Other ways to download

### Environment variables (no interactive prompt)

```bat
set MAMMA_USERNAME=you@studio.com
set MAMMA_PASSWORD=your_mamma_password
set SMPLX_USERNAME=you@studio.com
set SMPLX_PASSWORD=your_smplx_password

python download_weights.py --repo C:\dev\mamma
```

Unset variables when done on shared machines.

### ComfyUI node

**MAMMA Install Environment** → optional username/password fields → `step = weights` or
`all`.

**Do not save the workflow** with passwords filled. Prefer the batch script instead.

### Download only one side

```bat
python download_weights.py --repo C:\dev\mamma --skip-smplx
python download_weights.py --repo C:\dev\mamma --skip-mamma
```

---

## Troubleshooting

### `server returned an error page — check credentials`

- Wrong password, or account not activated
- License not accepted on the website (log in in a browser and accept)
- Using MAMMA password for SMPL-X prompt (or vice versa)

Delete any tiny broken file at the target path and re-run.

### `MAMMA credentials empty — skipping...`

You pressed Enter without typing credentials, or ran from a non-interactive terminal.
Use env vars or run `download_gated_weights.bat` from cmd.

### Doctor still fails after download

1. Confirm paths in Step 4 above
2. `SMPLX_NEUTRAL.npz` must be under `...\smplx_locked_head\smplx\`, not still inside
   the zip
3. Re-run `scripts\download_gated_weights.bat`

### Install node only downloaded public weights

Expected if password fields were left blank. Run Step 3 — install does not guess your
MPI credentials.

### Legal / redistribution

- Do **not** commit or upload these files to GitHub
- Each user must register and download themselves
- See [docs/WEIGHTS.md](docs/WEIGHTS.md) for the full weight inventory

---

## Links

| Resource | URL |
|----------|-----|
| MAMMA registration | https://mamma.is.tue.mpg.de/ |
| SMPL-X registration | https://smpl-x.is.tue.mpg.de/ |
| Full weight table | [docs/WEIGHTS.md](docs/WEIGHTS.md) |
| General troubleshooting | [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) |
