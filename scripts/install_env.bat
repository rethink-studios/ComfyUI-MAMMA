@echo off
setlocal
cd /d "%~dp0.."

if "%MAMMA_REPO%"=="" (
  set /p MAMMA_REPO=MAMMA repo path (clone of cuevhv/mamma): 
)
if not exist "%MAMMA_REPO%\requirements\mamma_conda.yaml" (
  echo ERROR: not a MAMMA repo: %MAMMA_REPO%
  exit /b 1
)

echo Applying Windows patches...
python "%~dp0apply_windows_patches.py" --repo "%MAMMA_REPO%"
if errorlevel 1 exit /b 1

echo.
echo Installing environment (20-40 min first run)...
python install_env.py --repo "%MAMMA_REPO%" --step all
exit /b %ERRORLEVEL%
