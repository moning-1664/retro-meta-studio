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
REM  [중요] 예전에는 여기서 dist\ 를 통째로 지웠다. 두 가지가 잘못됐다.
REM
REM   1. dist\db 에는 registry.db 와 archive.db 가 있다. **사용자 자산이다.**
REM      빌드할 때마다 등록한 Collection과 모아 둔 Archive가 통째로 사라졌다.
REM   2. 앱이 실행 중이면 rmdir 이 조용히 실패했다. errorlevel 을 보지 않았으므로
REM      스크립트는 그대로 진행했고, PyInstaller 도 잠긴 exe 를 덮어쓰지 못해
REM      실패했다. 그런데 화면에는 "Build complete"가 뜨는 경로가 있어서,
REM      **옛 exe 가 그대로 남은 채 새로 빌드했다고 믿게 되었다.**
REM      실제로 이것 때문에 고친 코드가 아니라 옛 코드를 테스트한 일이 있었다.
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
echo [6/6] Building with PyInstaller (this may take a few minutes)...
pyinstaller --noconfirm --onefile --windowed --name RetroMetaStudio --add-data "gui_web;gui_web" %WORKER_DATA% main.py

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed. Check the log above.
    pause
    exit /b 1
)

REM PyInstaller 가 0 을 돌려주고도 exe 를 남기지 못하는 경우가 있다(잠김 등).
REM "성공했다는 말"이 아니라 "실제로 파일이 있는가"로 판정한다.
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
