@echo off
REM ===========================================================================
REM  Personal Fitness Tracker - deploy to Raspberry Pi
REM
REM  What it does:
REM    1. Checks SSH access to the Pi and creates the target folder
REM    2. Confirms .env exists on the Pi (holds your credentials)
REM    3. Copies ONLY the app code + Docker files (tar streamed over SSH:
REM       no __pycache__, no data folder, no secrets)
REM    4. Works out whether the Pi uses "docker compose" or "docker-compose"
REM    5. Rebuilds and restarts the "fitness-web" container, then shows status
REM
REM  Usage:
REM    deploy-to-pi.bat              normal deploy (reuses Docker layer cache)
REM    deploy-to-pi.bat --no-cache   force a full rebuild (slow on a Pi)
REM
REM  NOTE: the app lives in its OWN sub-folder so the rail_app Dockerfile,
REM        docker-compose.yml, requirements.txt and README.md in the parent
REM        folder are never overwritten.
REM ===========================================================================

setlocal enabledelayedexpansion

REM ----------------------------- configuration -----------------------------
set "PI_HOST=192.168.0.97"
set "PI_USER=grahamsshaw"
set "PI_PARENT=/opt/stacks/python/scripts"
set "PI_APP=%PI_PARENT%/fitness-tracker"

REM Local project folder (strip the trailing backslash from %~dp0)
set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

REM Optional --no-cache flag
set "BUILD_FLAG="
if /i "%~1"=="--no-cache" set "BUILD_FLAG=--no-cache"

REM ------------------------------- header ----------------------------------
echo ============================================================
echo   Personal Fitness Tracker  -  Deploy to Raspberry Pi
echo ============================================================
echo.
echo   Pi host    : %PI_USER%@%PI_HOST%
echo   Target dir : %PI_APP%
echo   From       : %PROJECT_DIR%
echo.

REM ----------------------------- 0. preflight ------------------------------
where ssh >nul 2>&1
if errorlevel 1 (
    echo ERROR: ssh not found. Install the Windows OpenSSH client.
    goto :fail
)
where tar >nul 2>&1
if errorlevel 1 (
    echo ERROR: tar not found. It ships with Windows 10/11 - update Windows.
    goto :fail
)

REM --------------------- 1. connect + create target dir --------------------
echo [1/5] Connecting to the Pi and preparing the target folder...
ssh %PI_USER%@%PI_HOST% "mkdir -p '%PI_APP%/data' && echo '   remote folder ready'"
if errorlevel 1 (
    echo ERROR: SSH failed. You will be asked for the Pi password.
    goto :fail
)
echo.

REM ------------------------- 2. check .env exists --------------------------
echo [2/5] Checking for an existing .env on the Pi (holds your credentials)...
ssh %PI_USER%@%PI_HOST% "test -f '%PI_APP%/.env' && echo '   .env found' || echo '   No .env yet - one will be created from .env.example in the next step'"
echo.

REM ------------------------- 3. copy app code ------------------------------
REM Streaming a tar over SSH keeps the transfer clean:
REM   * no __pycache__ / .pyc junk ends up in the Docker build
REM   * no accidental nested "fitness_app/fitness_app" folders on redeploy
REM   * data/, .env, debug/, log/ etc. are never sent
REM
REM The trailing "test -f" makes the remote command fail if the extraction did
REM not actually produce the app, so a broken transfer cannot pass unnoticed.
echo [3/5] Copying application code and Docker files...
echo       (code only - the database is never transferred)
tar -cf - -C "%PROJECT_DIR%" --exclude "*__pycache__*" --exclude "*.pyc" --exclude "*.db" --exclude "data" --exclude "backups" fitness_app scripts requirements.txt Dockerfile docker-compose.yml .dockerignore .env.example README.md | ssh %PI_USER%@%PI_HOST% "tar -xf - -C '%PI_APP%' && test -f '%PI_APP%/fitness_app/__init__.py'"
if errorlevel 1 (
    echo ERROR: File transfer failed - nothing was deployed.
    goto :fail
)
echo       done.
echo.

REM --------------------- 3b. bootstrap .env if missing ---------------------
REM docker compose refuses to start when env_file is missing, so seed a fresh
REM .env from .env.example on the very first deploy. It is never overwritten
REM afterwards, so your credentials stay safe.
REM
REM NOTE: written as "test ... ||" rather than "[ ! -f ... ]" because delayed
REM expansion is enabled in this script and would eat the "!" character.
ssh %PI_USER%@%PI_HOST% "test -f '%PI_APP%/.env' && echo '   existing .env kept' || ( cp '%PI_APP%/.env.example' '%PI_APP%/.env' && echo '   created .env from .env.example - EDIT IT and add your credentials' )"
echo.

REM -------------------- 4. detect docker compose command --------------------
echo [4/5] Detecting Docker Compose on the Pi...
set "DC="
ssh %PI_USER%@%PI_HOST% "docker compose version" >nul 2>&1
if not errorlevel 1 (
    set "DC=docker compose"
) else (
    ssh %PI_USER%@%PI_HOST% "docker-compose version" >nul 2>&1
    if not errorlevel 1 (
        set "DC=docker-compose"
    )
)
if "!DC!"=="" (
    echo ERROR: Neither "docker compose" nor "docker-compose" found on the Pi.
    goto :fail
)
echo       using: !DC!
echo.

REM --------------------- 5. rebuild + restart container ---------------------
echo [5/5] Rebuilding and restarting the fitness-web container...
set "REBUILD_CMD=cd '%PI_APP%' && !DC! -p fitness down && !DC! -p fitness build"
if not "!BUILD_FLAG!"=="" set "REBUILD_CMD=!REBUILD_CMD! !BUILD_FLAG!"
set "REBUILD_CMD=!REBUILD_CMD! && !DC! -p fitness up -d"
ssh %PI_USER%@%PI_HOST% "!REBUILD_CMD!"
if errorlevel 1 (
    echo ERROR: Docker build/restart failed. Check the output above.
    goto :fail
)
echo.

REM ------------------------------- report -----------------------------------
echo ============================================================
echo   Deploy finished
echo ============================================================
echo.
ssh %PI_USER%@%PI_HOST% "docker ps --filter name=fitness-web --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"
echo.
echo   App URL : http://%PI_HOST%:5000
echo   (change it by setting FITNESS_HOST_PORT in the .env on the Pi)
echo.
echo   View logs : ssh %PI_USER%@%PI_HOST% "docker logs -f fitness-web"
echo   Stop app  : ssh %PI_USER%@%PI_HOST%   then: cd %PI_APP% ; !DC! -p fitness down
echo   Start app : ssh %PI_USER%@%PI_HOST%   then: cd %PI_APP% ; !DC! -p fitness up -d
echo.
pause
exit /b 0

:fail
echo.
echo ============================================================
echo   Deploy FAILED - see the message above
echo ============================================================
echo.
pause
exit /b 1
