@echo off
setlocal
cd /d "%~dp0"

REM Run from source without building an exe (for development/debugging).
REM For a distributable executable, use build.bat instead.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
    pause
    exit /b 1
)

if not exist venv (
    echo Virtual environment not found, creating one...
    python -m venv venv
    call venv\Scripts\activate.bat
    python -m pip install --upgrade pip >nul
    pip install -r requirements.txt
) else (
    call venv\Scripts\activate.bat
)

python main.py
if errorlevel 1 (
    echo.
    echo [ERROR] The program exited with an error. Check the log above.
    pause
)
