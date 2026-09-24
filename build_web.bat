@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ===============================================
echo  Retro Metadata Manager (Web GUI) - Build Script
echo ===============================================
echo.

REM --- 1. Check Python ---
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
    echo         Install Python 3.11+ from https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [1/6] Python found:
python --version
echo.

REM --- 2. Create virtual environment if missing ---
if not exist venv (
    echo [2/6] Creating virtual environment...
    python -m venv venv
) else (
    echo [2/6] Using existing virtual environment
)
call venv\Scripts\activate.bat
echo.

REM --- 3. Install dependencies (includes pywebview) ---
echo [3/6] Installing dependencies (requests, Pillow, matplotlib, pywebview, pyinstaller)...
python -m pip install --upgrade pip >nul
pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install requirements.txt
    pause
    exit /b 1
)
pip install pyinstaller
if errorlevel 1 (
    echo [ERROR] Failed to install pyinstaller
    pause
    exit /b 1
)
echo.

REM --- 4. Build native media copy worker (AhnLab M1875 mitigation - optional) ---
echo [4/6] Building native media copy worker...
call native\build_worker.bat
cd /d "%~dp0"
if exist native\MediaCopyWorker.exe (
    echo       MediaCopyWorker.exe built - will bundle it.
    set "WORKER_DATA=--add-data native/MediaCopyWorker.exe;native"
) else (
    echo       [WARN] MediaCopyWorker.exe not built - app will use in-process
    echo       fallback for media copy ^(AhnLab M1875 risk on large exports^).
    set "WORKER_DATA="
)
echo.

REM --- 5. Clean previous build ---
REM
REM  Do not remove the entire dist directory. Two failures occurred before:
REM
REM   1. dist\db contains user registry.db and archive.db files.
REM      Removing dist would delete collections and the Archive database.
REM   2. When the app is running, removal can fail due to a locked exe.
REM      The old script continued and could report success with the old exe.
REM      This previously caused testing of outdated code.
echo [5/6] Cleaning previous build output...

tasklist /FI "IMAGENAME eq RetroMetaStudio.exe" 2>nul | find /I "RetroMetaStudio.exe" >nul
if not errorlevel 1 (
    echo [ERROR] RetroMetaStudio.exe is still running.
    echo         Close the app first - otherwise the old exe cannot be replaced
    echo         and you would end up testing the previous build.
    pause
    exit /b 1
)

if exist build rmdir /s /q build

REM dist\db, dist\clipboard, dist\logs are USER DATA. Only the exe is rebuilt.
if exist dist\RetroMetaStudio.exe del /q dist\RetroMetaStudio.exe
if exist dist\RetroMetaStudio.exe (
    echo [ERROR] Could not delete dist\RetroMetaStudio.exe - it is locked.
    echo         Close the app ^(and any Explorer preview^) and run this again.
    pause
    exit /b 1
)

if exist RetroMetaStudio.spec del /q RetroMetaStudio.spec
echo.

REM --- 6. Build with PyInstaller (bundle gui_web/ and the native worker as data) ---
REM
REM  Explicitly bundle comtypes and its submodules for MTP support.
REM  The PyInstaller contrib hook normally discovers these modules, but may
REM  be unavailable in offline or mismatched environments. Without them the
REM  packaged app can incorrectly ask users to install comtypes at runtime.
echo [6/6] Building with PyInstaller (this may take a few minutes)...
pyinstaller --noconfirm --onefile --windowed --name RetroMetaStudio --icon "app.ico" --add-data "gui_web;gui_web" --add-data "adapters/esde_templates;adapters/esde_templates" %WORKER_DATA% ^
    --hidden-import comtypes ^
    --hidden-import comtypes.client ^
    --hidden-import comtypes.gen ^
    --hidden-import comtypes.persist ^
    --hidden-import comtypes.typeinfo ^
    --hidden-import comtypes.automation ^
    --hidden-import comtypes.stream ^
    --hidden-import ctypes.wintypes ^
    main.py

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed. Check the log above.
    pause
    exit /b 1
)

REM Verify comtypes in the executable before reporting build success.
REM Use PyInstaller's archive_viewer to inspect the embedded PYZ modules.
echo [6/6] Verifying comtypes was bundled...
python -m PyInstaller.utils.cliutils.archive_viewer -r --brief dist\RetroMetaStudio.exe 2>nul | findstr /C:"comtypes.client" >nul
if errorlevel 1 (
    echo.
    echo [ERROR] comtypes.client was not bundled into the exe - MTP will fail
    echo         with "pip install comtypes" even though it is installed here.
    echo         Check that requirements.txt installed cleanly in [3/6] above.
    pause
    exit /b 1
)

REM Confirm that PyInstaller left an exe, including when a file was locked.
if not exist dist\RetroMetaStudio.exe (
    echo.
    echo [ERROR] Build reported success but dist\RetroMetaStudio.exe does not exist.
    pause
    exit /b 1
)

echo.
echo ===============================================
echo  Build complete!
echo  Executable: dist\RetroMetaStudio.exe
for %%F in (dist\RetroMetaStudio.exe) do echo  Built at:   %%~tF
echo.
echo  Note: On first run, config.json and a backup\ folder
echo        will be created automatically next to the exe.
echo ===============================================
echo.
pause
