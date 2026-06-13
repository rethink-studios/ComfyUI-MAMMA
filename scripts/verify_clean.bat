@echo off
setlocal
cd /d "%~dp0.."
set FAIL=0

echo Checking repository is safe to push...
echo.

if exist ".runtime" (
  echo [WARN] .runtime exists locally — must stay gitignored
)

git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
  echo [OK] not a git repo yet — run git init when ready
  exit /b 0
)

for /f "delims=" %%F in ('git ls-files --cached .runtime 2^>nul') do (
  echo [FAIL] staged/tracked: %%F
  set FAIL=1
)

for /f "delims=" %%F in ('git ls-files --cached scripts\set_mamma_repo.bat 2^>nul') do (
  echo [FAIL] staged/tracked local config: %%F
  set FAIL=1
)

findstr /s /i /m /c:"password=" /c:"PASSWORD=" *.py *.md *.json *.bat 2>nul | findstr /v /i "verify_clean SECURITY WEIGHTS tooltip" >nul && (
  echo [WARN] review files mentioning password= before push
)

if %FAIL%==1 (
  echo.
  echo Repository is NOT clean — fix issues before pushing.
  exit /b 1
)

echo [OK] no .runtime or secrets detected in git index
exit /b 0
