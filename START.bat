@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Tinix Social Hub Launcher

where py >nul 2>nul
if errorlevel 1 (
  where python >nul 2>nul
  if errorlevel 1 (
    echo [LOI] Khong tim thay Python 3.11 tro len.
    pause
    exit /b 1
  )
  set "PYTHON_CMD=python"
) else (
  set "PYTHON_CMD=py -3"
)

set "VENV_PY=.venv\Scripts\python.exe"
set "VENV_PYW=.venv\Scripts\pythonw.exe"
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
  "%VENV_PY%" -c "import boto3, cryptography, fastapi, httpx, multipart, PIL, playwright, psutil, tzdata, uvicorn" >nul 2>nul
  if errorlevel 1 set "NEED_DEPS=1"
)
if "!NEED_DEPS!"=="1" (
  echo [Tinix] Dang dong bo dependencies...
  "%VENV_PY%" -m pip install --disable-pip-version-check -r requirements.txt
  if errorlevel 1 exit /b 1
  "%VENV_PY%" -c "from hashlib import sha256; from pathlib import Path; marker=Path('.venv/.tinix-requirements.sha256'); marker.write_text(sha256(Path('requirements.txt').read_bytes()).hexdigest() + '\n', encoding='ascii')"
  if errorlevel 1 exit /b 1
)

if not exist ".env" copy /y ".env.example" ".env" >nul

REM Tim port tu file .env (mac dinh 8000)
set "TINIX_PORT=8000"
if exist ".env" (
  for /f "usebackq tokens=1,2 delims==" %%A in (".env") do (
    set "KEY=%%A"
    set "VAL=%%B"
    if "!KEY!"=="TINIX_PORT" set "TINIX_PORT=!VAL!"
  )
)

REM Kiem tra icon va desktop shortcut
if not exist "app\static\favicon.ico" (
  "%VENV_PY%" build.py --no-bump --no-tests
)

REM Kiem tra server ngam da chay chua va dung phien ban khong
"%VENV_PY%" -c "import urllib.request, json, sys; from app import __version__; exec('try:\n r = urllib.request.urlopen(\"http://127.0.0.1:%TINIX_PORT%/api/health\", timeout=1)\n d = json.loads(r.read().decode())\n sys.exit(0 if d.get(\"version\") == __version__ else 1)\nexcept Exception:\n sys.exit(1)')" >nul 2>nul
if errorlevel 1 (
  call :start_background_server
  if errorlevel 1 exit /b 1
)

REM Tim Google Chrome hoac Microsoft Edge de mo che do App Mode doc lap
set "BROWSER_APP_EXE="
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "BROWSER_APP_EXE=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not defined BROWSER_APP_EXE if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "BROWSER_APP_EXE=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not defined BROWSER_APP_EXE if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set "BROWSER_APP_EXE=%LocalAppData%\Google\Chrome\Application\chrome.exe"

REM Neu khong co Chrome thi tim Edge
if not defined BROWSER_APP_EXE if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" set "BROWSER_APP_EXE=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if not defined BROWSER_APP_EXE if exist "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" set "BROWSER_APP_EXE=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"

echo [Tinix] Dang mo ung dung che do App Mode doc lap...
set "APP_DATA_DIR=%~dp0data\app_browser_profile"
if not exist "%APP_DATA_DIR%" mkdir "%APP_DATA_DIR%" 2>nul

if defined BROWSER_APP_EXE (
  start "" "%BROWSER_APP_EXE%" --app="http://127.0.0.1:%TINIX_PORT%" --user-data-dir="%APP_DATA_DIR%" --no-first-run --no-default-browser-check
) else (
  start "" "http://127.0.0.1:%TINIX_PORT%"
)

exit /b 0

:start_background_server
echo [Tinix] Dang don dep phien lam viec cu...
"%VENV_PY%" -m app.cleanup

echo [Tinix] Dang khoi dong may chu ngam (port %TINIX_PORT%)...
set "TINIX_OPEN_BROWSER=false"
start "" "%VENV_PYW%" -m app

REM Cho server san sang toi da 30 giay
for /l %%i in (1,1,30) do (
  "%VENV_PY%" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:%TINIX_PORT%/api/health', timeout=1)" >nul 2>nul
  if not errorlevel 1 (
    echo [Tinix] May chu ngam da san sang.
    exit /b 0
  )
  ping 127.0.0.1 -n 2 >nul
)

echo [LOI] May chu ngam khong phan hoi sau 30s. Kiem tra logs\tinix.log.
pause
exit /b 1
