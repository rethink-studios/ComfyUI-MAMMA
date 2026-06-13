@echo off
setlocal
cd /d "%~dp0.."

if "%MAMMA_REPO%"=="" (
  set /p MAMMA_REPO=MAMMA repo path: 
)
if not exist "%MAMMA_REPO%" (
  echo ERROR: path not found: %MAMMA_REPO%
  exit /b 1
)

echo.
echo You need TWO free accounts (separate registrations):
echo   MAMMA  - https://mamma.is.tue.mpg.de/
echo   SMPL-X - https://smpl-x.is.tue.mpg.de/
echo.
echo Credentials are sent only to download.is.tue.mpg.de and are not stored.
echo.

python download_weights.py --repo "%MAMMA_REPO%"
exit /b %ERRORLEVEL%
