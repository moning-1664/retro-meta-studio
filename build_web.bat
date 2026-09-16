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
REM
REM  comtypes(storage/mtp_wpd.py, MTP 연결)는 --hidden-import로 직접 못 박는다.
REM  PyInstaller는 comtypes.client가 필요로 하는 서브모듈(comtypes.persist,
REM  comtypes.gen 등)을 pyinstaller-hooks-contrib 훅에 기대어 자동으로 찾는데,
REM  이 훅은 별도 pip 설치 항목이라 이 스크립트가 명시적으로 깔지 않는다 -
REM  pyinstaller가 그것을 의존성으로 끌어오지 못하는 환경(오프라인 pip 캐시,
REM  버전 불일치 등)에서는 훅이 조용히 안 걸리고, comtypes 자체는 설치돼 있어도
REM  실행 시 "pip install comtypes"라는 엉뚱한 안내가 뜬다(실제로 이렇게 겪었다) -
REM  빠진 것은 comtypes가 아니라 comtypes.client가 딛고 선 서브모듈이기 때문이다.
REM  훅이 하는 일과 정확히 같은 목록을 여기서도 직접 적어 그 훅에 기대지 않는다.
echo [6/6] Building with PyInstaller (this may take a few minutes)...
pyinstaller --noconfirm --onefile --windowed --name RetroMetaStudio --icon "app.ico" --add-data "gui_web;gui_web" %WORKER_DATA% ^
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

REM comtypes가 실제로 exe 안에 들어갔는지 그 자리에서 확인한다. 빠졌으면
REM "Build complete"라고 말한 뒤에야 기기에서 뒤늦게 알게 된다 - 그러면 밤에
REM 실기 테스트를 하다가 원인도 모른 채 시간을 버린다. PyInstaller가 공개
REM 제공하는 archive_viewer로 PYZ 안(pure-python 모듈이 압축되는 곳)까지
REM 재귀적으로 들여다본다 - 내부 바이너리 포맷을 직접 읽는 것보다 버전이
REM 바뀌어도 깨지지 않는다.
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
