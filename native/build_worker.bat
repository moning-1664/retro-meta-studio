@echo off
REM Builds MediaCopyWorker.exe (a standalone native binary, no Python runtime).
REM build.bat calls this before the PyInstaller step - if no compiler is
REM found, this fails but the app still works via the in-process fallback
REM in media_copy_worker.py (this worker is an optional optimization/
REM mitigation, not a hard requirement).
cd /d "%~dp0"

REM Always start from a clean slate - if a previous successful build left a
REM MediaCopyWorker.exe here and this build's compile then fails, we must
REM NOT let build.bat silently bundle the stale (possibly out-of-date) exe.
REM Deleting it first means "exe present" always means "this build's source
REM actually compiled".
if exist MediaCopyWorker.exe del /q MediaCopyWorker.exe

where cl >nul 2>nul
if %ERRORLEVEL%==0 (
    echo [MSVC build]
    cl /O2 /nologo media_copy_worker.c /Fe:MediaCopyWorker.exe /link Shell32.lib
    if %ERRORLEVEL% NEQ 0 goto :fail
    goto :ok
)

where gcc >nul 2>nul
if %ERRORLEVEL%==0 (
    echo [MinGW gcc build]
    gcc -municode -O2 -o MediaCopyWorker.exe media_copy_worker.c -lshell32
    if %ERRORLEVEL% NEQ 0 goto :fail
    goto :ok
)

echo [SKIPPED] No cl.exe (Visual Studio) or gcc (MinGW/MSYS2) found - could not build MediaCopyWorker.exe.
echo           The app still works: media copy falls back to in-process copy.
exit /b 1

:ok
echo [DONE] native\MediaCopyWorker.exe
exit /b 0

:fail
echo [FAILED] Compile error - see log above (app still works via in-process fallback)
exit /b 1
