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

python install_env.py --repo "%MAMMA_REPO%" --step doctor
exit /b %ERRORLEVEL%
