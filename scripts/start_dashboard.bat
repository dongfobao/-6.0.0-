@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0.."

set "PYTHON_EXE="
set "PYTHON_ARGS="
set "BUNDLED_PY=C:\Users\MyPC\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if exist "%BUNDLED_PY%" (
  set "PYTHON_EXE=%BUNDLED_PY%"
) else (
  where py >nul 2>nul
  if !errorlevel!==0 (
    set "PYTHON_EXE=py"
    set "PYTHON_ARGS=-3"
  ) else (
    where python >nul 2>nul
    if !errorlevel!==0 set "PYTHON_EXE=python"
  )
)

if not defined PYTHON_EXE (
  echo Python was not found. Install Python 3 or run the packaged EXE under release.
  pause
  exit /b 1
)

set "APP_URL=http://127.0.0.1:8765"
set "API_URL=http://127.0.0.1:8765/api/analysis"
set "PROJECT_DIR=%cd%"

rem Stop old YLDQ/source processes from this project.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$project=(Resolve-Path '%PROJECT_DIR%').Path.TrimEnd('\'); Get-CimInstance Win32_Process | Where-Object { $exe=[string]$_.ExecutablePath; $cmd=[string]$_.CommandLine; (($exe -and $exe.StartsWith($project,[StringComparison]::OrdinalIgnoreCase)) -or ($cmd -and $cmd.IndexOf($project,[StringComparison]::OrdinalIgnoreCase) -ge 0) -or ($cmd -and $cmd -like '*dashboard_server.py*') -or ($exe -and $exe -like '*YLDQ*.exe')) } | Sort-Object ProcessId -Descending | ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Sleep -Seconds 1" >nul

rem Refuse to start only when port 8765 is still held by an unrelated process.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$conn=Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if (-not $conn) { exit 1 }; $proc=Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $conn.OwningProcess); if (-not $proc) { exit 1 }; $project=(Resolve-Path '%PROJECT_DIR%').Path.TrimEnd('\'); $exe=[string]$proc.ExecutablePath; $cmd=[string]$proc.CommandLine; if ((($exe -and $exe.StartsWith($project,[StringComparison]::OrdinalIgnoreCase)) -or ($cmd -and $cmd.IndexOf($project,[StringComparison]::OrdinalIgnoreCase) -ge 0) -or ($cmd -and $cmd -like '*dashboard_server.py*'))) { exit 0 } else { exit 3 }"
if %errorlevel%==0 (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$conn=Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if ($conn) { Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue }"
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Sleep -Seconds 1" >nul
)
if %errorlevel%==3 goto port_conflict

start "YLDQ Analytics Source Service" /min "%PYTHON_EXE%" %PYTHON_ARGS% app\dashboard_server.py

set "READY="
for /l %%i in (1,1,20) do (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r=Invoke-WebRequest -Uri '!API_URL!' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }"
  if not errorlevel 1 (
    set "READY=1"
    goto open_browser
  )
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Sleep -Seconds 1" >nul
)

:open_browser
if defined READY (
  start "" "%APP_URL%"
  exit /b 0
)

echo Source startup failed. Check Python and app\dashboard_server.py.
pause
exit /b 1

:port_conflict
echo Port 8765 is occupied by another program. Close it and retry.
pause
exit /b 1
