@echo off
setlocal
set "PROJECT_ROOT=%~dp0.."
pushd "%PROJECT_ROOT%"

echo == PHOTONForge Darktable Installer ==
echo.

REM --- Check Docker Desktop ---
docker info >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker Desktop is not running.
    echo         Start Docker Desktop and run this script again.
    pause
    exit /b 1
)
echo [OK] Docker Desktop is running.

REM --- Check Ubuntu WSL ---
wsl -d Ubuntu -- echo "" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Ubuntu WSL not found. Installing now...
    wsl --install -d Ubuntu
    echo.
    echo Ubuntu WSL installed. Restart your computer then run this script again.
    pause
    exit /b 0
)
echo [OK] Ubuntu WSL is available.

REM --- Build Docker image ---
echo.
echo Building Darktable Docker image (this takes a few minutes)...
docker compose -f deploy/docker-compose.darktable.yml build
if errorlevel 1 (
    echo [ERROR] Build failed. Check the output above for details.
    pause
    exit /b 1
)
echo [OK] Image built successfully.

REM --- Convert project path to WSL format ---
for /f "delims=" %%i in ('wsl wslpath "%PROJECT_ROOT:\=/%"') do set "WSL_PATH=%%i"

echo.
echo == Installation complete! ==
echo.
echo To run Darktable, open Ubuntu WSL and run:
echo   cd %WSL_PATH%
echo   docker compose -f deploy/docker-compose.darktable.yml up
echo.
pause
popd
