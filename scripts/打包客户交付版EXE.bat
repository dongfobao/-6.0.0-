@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

where py >nul 2>nul
if %errorlevel%==0 (
  set "PYTHON_CMD=py -3"
) else (
  set "PYTHON_CMD=python"
)

%PYTHON_CMD% -m PyInstaller --noconfirm packaging\customer_delivery.spec
if errorlevel 1 (
  echo.
  echo EXE 打包失败。
  pause
  exit /b 1
)

set "RELEASE_DIR=%cd%\release\YLDQ数据分析系统"
if exist "%RELEASE_DIR%" rmdir /s /q "%RELEASE_DIR%"
mkdir "%RELEASE_DIR%"

xcopy /e /i /y ".\dist\YLDQ数据分析系统\*" "%RELEASE_DIR%\" >nul
if not exist "%RELEASE_DIR%\实时数据" mkdir "%RELEASE_DIR%\实时数据"
if not exist "%RELEASE_DIR%\实时数据\data_0" mkdir "%RELEASE_DIR%\实时数据\data_0"
if not exist "%RELEASE_DIR%\实时数据\breath_data" mkdir "%RELEASE_DIR%\实时数据\breath_data"
if not exist "%RELEASE_DIR%\实时数据\run" mkdir "%RELEASE_DIR%\实时数据\run"

copy /y ".\docs\客户交付版使用说明.txt" "%RELEASE_DIR%\使用说明.txt" >nul

echo.
echo 打包完成：
echo %RELEASE_DIR%
pause
