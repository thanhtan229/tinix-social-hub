@echo off
setlocal
cd /d "%~dp0"
title Stop Tinix Social Hub

set "VENV_PY=.venv\Scripts\python.exe"

echo [Tinix] Dang dong may chu Tinix Social Hub va cac tien trinh lien quan...
if exist "%VENV_PY%" (
  "%VENV_PY%" -m app.cleanup
)
echo [Tinix] Da dung may chu ngam thanh cong.
ping 127.0.0.1 -n 3 >nul
exit /b 0
