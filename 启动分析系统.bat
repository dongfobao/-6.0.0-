@echo off
setlocal
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$release=Join-Path (Get-Location) 'release'; $exe=Get-ChildItem -LiteralPath $release -Recurse -Filter 'YLDQ*.exe' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1; if ($exe) { Start-Process -FilePath $exe.FullName; exit 0 } else { exit 2 }"
if %errorlevel%==0 exit /b 0

echo Packaged EXE was not found under release.
echo Please package the analysis system first, or run start source debug.
pause
exit /b 1
