@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0.."

set "PYTHON_EXE="
set "PYTHON_ARGS="
where py >nul 2>nul
if %errorlevel%==0 (
  set "PYTHON_EXE=py"
  set "PYTHON_ARGS=-3"
) else (
  set "PYTHON_EXE=python"
)

set "APP_URL=http://127.0.0.1:8765"
set "API_URL=http://127.0.0.1:8765/api/analysis"
set "PROJECT_DIR=%~dp0"

rem 1) Stop old project-related processes so every launch starts clean.
powershell -NoProfile -Command "& { $project = (Resolve-Path '%PROJECT_DIR%').Path.TrimEnd('\'); $targets = Get-CimInstance Win32_Process | Where-Object { $exe = [string]$_.ExecutablePath; $cmd = [string]$_.CommandLine; (($exe -and $exe.StartsWith($project, [System.StringComparison]::OrdinalIgnoreCase)) -or ($cmd -and $cmd.IndexOf($project, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) -or ($cmd -and $cmd -like '*dashboard_server.py*') -or ($exe -and ($exe -like '*YLDQ*.exe'))) }; $targets | Sort-Object ProcessId -Descending | ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} } }"
timeout /t 2 /nobreak >nul

rem 2) Abort only when port 8765 is still held by an unrelated process after cleanup.
powershell -NoProfile -Command "& { $conn = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if (-not $conn) { exit 1 }; $proc = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $conn.OwningProcess); if (-not $proc) { exit 1 }; $project = (Resolve-Path '%PROJECT_DIR%').Path.TrimEnd('\'); $exe = [string]$proc.ExecutablePath; $cmd = [string]$proc.CommandLine; if ((($exe -and $exe.StartsWith($project, [System.StringComparison]::OrdinalIgnoreCase)) -or ($cmd -and $cmd.IndexOf($project, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) -or ($cmd -and $cmd -like '*dashboard_server.py*'))) { exit 0 } else { exit 3 } }"
if %errorlevel%==0 (
  powershell -NoProfile -Command "& { $conn = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if ($conn) { try { Stop-Process -Id $conn.OwningProcess -Force -ErrorAction Stop } catch { exit 1 } } }"
  timeout /t 1 /nobreak >nul
)
if %errorlevel%==3 goto port_conflict

rem 3) Start current source service in its own process.
start "YLDQ Analytics Service" /min %PYTHON_EXE% %PYTHON_ARGS% app\dashboard_server.py

set "READY="
for /l %%i in (1,1,20) do (
  powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri '!API_URL!' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }"
  if not errorlevel 1 (
    set "READY=1"
    goto open_browser
  )
  timeout /t 1 /nobreak >nul
)

:open_browser
if defined READY (
  start "" "%APP_URL%"
  powershell -NoProfile -Command "Start-Process '%APP_URL%'" >nul 2>nul
  exit /b 0
)

echo.
echo Start failed. Check Python 3 and port 8765.
echo If the service is already running, open: %APP_URL%
pause
exit /b 1

:port_conflict
echo.
echo Port 8765 is occupied by a non-project process.
echo Close that process first, then run this BAT again.
pause
exit /b 1
