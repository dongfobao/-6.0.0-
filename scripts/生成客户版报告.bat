@echo off
setlocal
cd /d "%~dp0.."

where py >nul 2>nul
if %errorlevel%==0 (
  set "PYTHON_CMD=py -3"
) else (
  set "PYTHON_CMD=python"
)

%PYTHON_CMD% app\customer_delivery_entry.py

if errorlevel 1 (
  echo.
  echo 客户版报告生成失败。
  pause
)
