@echo off
REM ===========================================================================
REM  Personal Fitness Tracker - fetch a database backup from the Pi
REM
REM  Pulls a backup of the Pi's database to the PC so you can inspect it
REM  locally without touching the live database on the Pi.
REM
REM  This is read-only with respect to the Pi: nothing on the Pi is modified.
REM
REM  Usage:
REM    fetch-database.bat              list available backups
REM    fetch-database.bat <name>       download a specific backup
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

set "LOCAL_BACKUPS=%PROJECT_DIR%\backups"

REM ------------------------------- header ----------------------------------
echo ============================================================
echo   Personal Fitness Tracker  -  Fetch database from Pi
echo ============================================================
echo.
echo   Pi host    : %PI_USER%@%PI_HOST%
echo   Target dir : %LOCAL_BACKUPS%
echo.

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

if not "%~1"=="" goto :fetch

REM ----------------------- 1. list available backups ------------------------
echo Available backups on the Pi:
ssh %PI_USER%@%PI_HOST% "ls -1t '%PI_APP%/backups/' 2>/dev/null || echo '   (no backups folder yet)'"
echo.
echo To download one, run:
echo     fetch-database.bat ^<backup-name^>
echo.
pause
exit /b 0

REM ----------------------- 2. fetch a specific backup -----------------------
:fetch
set "BACKUP_NAME=%~1"
if "%BACKUP_NAME%"=="" (
    echo ERROR: No backup name given.
    goto :fail
)

if not exist "%LOCAL_BACKUPS%" mkdir "%LOCAL_BACKUPS%"

echo Downloading %BACKUP_NAME% ...
scp "%PI_USER%@%PI_HOST%:%PI_APP%/backups/%BACKUP_NAME%" "%LOCAL_BACKUPS%\%BACKUP_NAME%"
if errorlevel 1 (
    echo ERROR: Download failed. Check the backup name and try again.
    goto :fail
)
echo.
echo   Saved to: %LOCAL_BACKUPS%\%BACKUP_NAME%
echo.
echo   Inspect it with:
echo     py scripts\db_tool.py info
echo   (after copying it to data\fitness.db, or point the tool at it)
echo.

pause
exit /b 0

:fail
echo.
echo ============================================================
echo   Fetch FAILED - see the message above
echo ============================================================
echo.
pause
exit /b 1
