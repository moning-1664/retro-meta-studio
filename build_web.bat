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
echo [5/6] Cleaning previous build output...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist RetroMetadataManagerWeb.spec del /q RetroMetadataManagerWeb.spec
echo.

REM --- 6. Build with PyInstaller (bundle gui_web/ and the native worker as data) ---
echo [6/6] Building with PyInstaller (this may take a few minutes)...
pyinstaller --noconfirm --onefile --windowed --name RetroMetadataManagerWeb --add-data "gui_web;gui_web" %WORKER_DATA% main_gui.py

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed. Check the log above.
    pause
    exit /b 1
)

echo.
echo ===============================================
echo  Build complete!
echo  Executable: dist\RetroMetadataManagerWeb.exe
echo.
echo  Note: On first run, config.json and a backup\ folder
echo        will be created automatically next to the exe.
echo ===============================================
echo.
pause
