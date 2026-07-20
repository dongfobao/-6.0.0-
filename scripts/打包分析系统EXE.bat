@echo off
setlocal
cd /d "%~dp0.."

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 scripts\package_dashboard_release.py
) else (
  python scripts\package_dashboard_release.py
)

if errorlevel 1 (
  echo.
  echo Package failed.
  exit /b 1
)

echo.
echo Package completed.
