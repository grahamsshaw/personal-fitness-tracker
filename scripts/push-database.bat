@echo off
REM ===========================================================================
REM  Personal Fitness Tracker - push the PC database to the Pi
REM
REM  This is the GUARDED database sync. It is deliberately separate from
REM  deploy-to-pi.bat so that a routine code deploy can never touch the
REM  database.
REM
REM  What it does:
REM    1. Backs up the Pi's current database FIRST (so the push is reversible)
REM    2. Copies the PC's data/fitness.db to the Pi
REM
REM  Because the PC database is a disposable scratch copy and the Pi database
REM  is the source of truth, this script always makes a safety backup on the
REM  Pi before overwriting anything.
REM
REM  Usage:
REM    push-database.bat
REM ===========================================================================

setlocal enabledelayedexpansion

REM ----------------------------- configuration -----------------------------
set "PI_HOST=192.168.0.97"
set "PI_USER=grahamsshaw"
set "PI_APP=/opt/stacks/python/scripts/fitness-tracker"

REM Local project folder. This script lives in scripts/, so the project root
REM is one level up from the batch file's own folder.
set "PROJECT_DIR=%~dp0.."
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

REM ------------------------------- header ----------------------------------
echo ============================================================
echo   Personal Fitness Tracker  -  Push database to Pi
echo ============================================================
echo.
echo   Pi host    : %PI_USER%@%PI_HOST%
echo   Target dir : %PI_APP%
echo   From       : %PROJECT_DIR%
echo.
echo   The Pi database will be backed up before anything is overwritten.
echo.

REM ----------------------------- 0. preflight ------------------------------
where ssh >nul 2>&1
if errorlevel 1 (
    echo ERROR: ssh not found. Install the Windows OpenSSH client.
    goto :fail
)
where scp >nul 2>&1
if errorlevel 1 (
    echo ERROR: scp not found. Install the Windows OpenSSH client.
    goto :fail
)

if not exist "%PROJECT_DIR%\data\fitness.db" (
    echo ERROR: No database found at %PROJECT_DIR%\data\fitness.db
    echo        Run an import on the PC first.
    goto :fail
)

REM ------------------- 1. back up the Pi database first -------------------
echo [1/2] Backing up the Pi database...
ssh %PI_USER%@%PI_HOST% "mkdir -p '%PI_APP%/backups' && cp '%PI_APP%/data/fitness.db' '%PI_APP%/backups/fitness-%DATE:~0,4%%DATE:~5,2%%DATE:~8,2%-%TIME:~0,2%%TIME:~3,2%%TIME:~6,2%.db' 2>/dev/null; echo '   backup done'"
if errorlevel 1 (
    echo ERROR: Could not back up the Pi database. Aborting - nothing was changed.
    goto :fail
)
echo.

REM ---------------------- 2. push the PC database -------------------------
echo [2/2] Copying the PC database to the Pi...
scp "%PROJECT_DIR%\data\fitness.db" "%PI_USER%@%PI_HOST%:%PI_APP%/data/fitness.db"
if errorlevel 1 (
    echo ERROR: File transfer failed.
    echo        The Pi database backup from step 1 is still in place.
    goto :fail
)
echo       done.
echo.

REM ------------------------------- report ----------------------------------
echo ============================================================
echo   Database pushed
echo ============================================================
echo.
echo   The Pi database is now the PC database.
echo   To restore the previous Pi database:
echo     ssh %PI_USER%@%PI_HOST% "docker exec fitness-web python /app/scripts/db_tool.py restore ^<backup-name^>"
echo.
echo   Backups live in: %PI_APP%/backups/
echo.

pause
exit /b 0

:fail
echo.
echo ============================================================
echo   Push FAILED - see the message above
echo ============================================================
echo.
pause
exit /b 1
