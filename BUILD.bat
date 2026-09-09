@echo off
setlocal
cd /d "%~dp0"
title Build Tinix Social Hub

echo [Tinix] Dang dung ung dung truoc khi rebuild...
call "%~dp0STOP.bat"

where py >nul 2>nul
if errorlevel 1 (
  set "PYTHON_CMD=python"
) else (
  set "PYTHON_CMD=py -3"
)

set "VENV_PY=.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
  echo [Tinix] Dang khoi tao moi truong .venv...
  %PYTHON_CMD% -m venv .venv
  "%VENV_PY%" -m pip install --disable-pip-version-check -r requirements.txt
)

echo [Tinix] Dang thuc hien Build, cap nhat version va Desktop shortcut...
"%VENV_PY%" build.py %*
if errorlevel 1 (
  echo.
  echo [LOI] Qua trinh build that bai!
  pause
  exit /b 1
)
echo.
echo [Tinix] Build thanh cong hoan toan!
ping 127.0.0.1 -n 3 >nul
exit /b 0
