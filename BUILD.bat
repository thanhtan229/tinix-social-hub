@echo off
setlocal EnableExtensions EnableDelayedExpansion
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
set "NEED_DEPS=0"

if not exist "%VENV_PY%" (
  echo [Tinix] Dang khoi tao moi truong .venv...
  %PYTHON_CMD% -m venv .venv
  if errorlevel 1 exit /b 1
  set "NEED_DEPS=1"
)

if "!NEED_DEPS!"=="0" (
  "%VENV_PY%" -c "from hashlib import sha256; from pathlib import Path; import sys; marker=Path('.venv/.tinix-requirements.sha256'); digest=sha256(Path('requirements.txt').read_bytes()).hexdigest(); sys.exit(0 if marker.is_file() and marker.read_text(encoding='ascii').strip()==digest else 1)" >nul 2>nul
  if errorlevel 1 set "NEED_DEPS=1"
)
if "!NEED_DEPS!"=="0" (
  "%VENV_PY%" -c "import cryptography, fastapi, httpx, multipart, PIL, playwright, psutil, tzdata, uvicorn" >nul 2>nul
  if errorlevel 1 set "NEED_DEPS=1"
)
if "!NEED_DEPS!"=="1" (
  echo [Tinix] Dang dong bo dependencies...
  "%VENV_PY%" -m pip install --disable-pip-version-check -r requirements.txt
  if errorlevel 1 exit /b 1
  "%VENV_PY%" -c "from hashlib import sha256; from pathlib import Path; marker=Path('.venv/.tinix-requirements.sha256'); marker.write_text(sha256(Path('requirements.txt').read_bytes()).hexdigest() + '\n', encoding='ascii')"
  if errorlevel 1 exit /b 1
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
