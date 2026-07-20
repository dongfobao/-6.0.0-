@echo off
setlocal
cd /d "%~dp0"

set "MONITOR_EXE=release\YLDQ6.0远程监控系统\YLDQ6.0远程监控系统.exe"
if exist "%MONITOR_EXE%" (
  start "" "%MONITOR_EXE%"
  exit /b 0
)

call "%~dp0启动源码调试.bat"
