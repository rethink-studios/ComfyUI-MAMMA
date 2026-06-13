@echo off
setlocal
if "%MAMMA_REPO%"=="" (
  set /p MAMMA_REPO=MAMMA repo path: 
)
python "%~dp0apply_windows_patches.py" --repo "%MAMMA_REPO%"
exit /b %ERRORLEVEL%
