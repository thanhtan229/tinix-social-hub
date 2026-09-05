@echo off
setlocal
cd /d "%~dp0"
title Stop Tinix Social Hub

set "VENV_PY=.venv\Scripts\python.exe"

echo [Tinix] Dang dong may chu Tinix Social Hub va cac tien trinh lien quan...
if exist "%VENV_PY%" (
  "%VENV_PY%" -m app.cleanup
  "%VENV_PY%" -c "import psutil, os; [p.kill() for p in psutil.process_iter(['name', 'cmdline']) if p.info['name'] in ('python.exe', 'pythonw.exe') and any('app' in str(arg) for arg in (p.info['cmdline'] or [])) and p.pid != os.getpid()]" >nul 2>nul
)
echo [Tinix] Da dung may chu ngam thanh cong.
ping 127.0.0.1 -n 3 >nul
exit /b 0
