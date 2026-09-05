@echo off
setlocal
cd /d "%~dp0"
title Tinix Social Hub

where py >nul 2>nul
if errorlevel 1 (
  where python >nul 2>nul
  if errorlevel 1 (
    echo [LOI] Khong tim thay Python 3.11 tro len.
    echo Tai Python tai https://www.python.org/downloads/ va chon "Add Python to PATH".
    pause
    exit /b 1
  )
  set "PYTHON_CMD=python"
) else (
  set "PYTHON_CMD=py -3"
)

%PYTHON_CMD% -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>nul
if errorlevel 1 (
  echo [LOI] Tinix Social Hub can Python 3.11 tro len.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [Tinix] Dang tao moi truong Python rieng...
  %PYTHON_CMD% -m venv .venv
  if errorlevel 1 goto :error
)

set "VENV_PY=.venv\Scripts\python.exe"
"%VENV_PY%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>nul
if errorlevel 1 (
  echo [LOI] Moi truong .venv hien tai dung Python qua cu.
  echo Hay doi ten thu muc .venv cu va chay lai Run.bat.
  pause
  exit /b 1
)

set "REQ_HASH="
set "INSTALLED_HASH="
for /f %%H in ('powershell -NoProfile -Command "(Get-FileHash -Algorithm SHA256 -LiteralPath 'requirements.txt').Hash"') do set "REQ_HASH=%%H"
if exist ".venv\.requirements.sha256" set /p INSTALLED_HASH=<".venv\.requirements.sha256"

if /I not "%REQ_HASH%"=="%INSTALLED_HASH%" (
  echo [Tinix] Dang cap nhat dependency...
  "%VENV_PY%" -m pip install --disable-pip-version-check -r requirements.txt
  if errorlevel 1 goto :error
  >".venv\.requirements.sha256" echo %REQ_HASH%
)

"%VENV_PY%" -c "import fastapi,uvicorn,httpx,multipart,psutil,playwright,PIL" >nul 2>nul
if errorlevel 1 goto :error

if not exist ".env" copy /y ".env.example" ".env" >nul

set "CHROME_FOUND="
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "CHROME_FOUND=1"
if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "CHROME_FOUND=1"
if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set "CHROME_FOUND=1"
if not defined CHROME_FOUND (
  echo [CANH BAO] Chua tim thay Google Chrome o vi tri mac dinh.
  echo Ban van co the dung WebUI; hay cai Chrome hoac dat TINIX_CHROME_PATH trong .env.
)

echo [Tinix] Dang kiem tra va dong phien lam viec cu (neu co)...
"%VENV_PY%" -m app.cleanup

echo [Tinix] WebUI local se tu dong mo sau khi backend san sang.
echo [Tinix] Nhan Ctrl+C de dung an toan.
"%VENV_PY%" -m app
if errorlevel 1 goto :error
exit /b 0

:error
echo.
echo [LOI] Tinix Social Hub khong the khoi dong. Xem logs\tinix.log neu co.
pause
exit /b 1
