@echo off
setlocal
cd /d "%~dp0.."

echo.
echo ============================================================
echo  GATED WEIGHTS - REQUIRED AFTER install_env.bat
echo ============================================================
echo.
echo  Install downloads public weights only (SAM2, YOLO, CLIP).
echo  MAMMA will NOT run until you also download gated files.
echo.
echo  Full guide: GATED_WEIGHTS.md in this repo
echo  https://github.com/rethink-studios/ComfyUI-MAMMA/blob/main/GATED_WEIGHTS.md
echo.
echo ------------------------------------------------------------
echo  STEP 1 - Register (free, ~5 min each, SEPARATE accounts)
echo ------------------------------------------------------------
echo    MAMMA:  https://mamma.is.tue.mpg.de/
echo            - sign up, confirm email, ACCEPT LICENSE while logged in
echo.
echo    SMPL-X: https://smpl-x.is.tue.mpg.de/
echo            - different login from MAMMA, ACCEPT LICENSE
echo.
echo ------------------------------------------------------------
echo  STEP 2 - This script (prompts for both accounts)
echo ------------------------------------------------------------
echo    Downloads:
echo      mamma_mask_full_cvpr.ckpt
echo      verts_512.pkl
echo      smplx_lockedhead zip -^> SMPLX_*.npz
echo.
echo    Credentials: sent only to download.is.tue.mpg.de, not stored.
echo.
echo ------------------------------------------------------------
echo  STEP 3 - Verify
echo ------------------------------------------------------------
echo    scripts\doctor.bat   (should PASS)
echo.
echo ============================================================
echo.

if "%MAMMA_REPO%"=="" (
  set /p MAMMA_REPO=MAMMA repo path (e.g. C:\dev\mamma): 
)
if not exist "%MAMMA_REPO%" (
  echo ERROR: path not found: %MAMMA_REPO%
  echo.
  pause
  exit /b 1
)

python download_weights.py --repo "%MAMMA_REPO%"
set RC=%ERRORLEVEL%
echo.
if %RC%==0 (
  echo Next: scripts\doctor.bat
) else (
  echo Download failed. See GATED_WEIGHTS.md -^> Troubleshooting
)
echo.
pause
exit /b %RC%
