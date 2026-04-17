@echo off
REM Build script for creating Windows executable
REM Usage: build_app.bat

REM Change to project root directory
cd /d "%~dp0\.."

REM Detect and activate virtual environment if present
set VENV_ACTIVATED=0
if exist ".venv\Scripts\activate.bat" (
    echo Activating virtual environment...
    call .venv\Scripts\activate.bat
    set VENV_ACTIVATED=1
) else if exist "venv\Scripts\activate.bat" (
    echo Activating virtual environment...
    call venv\Scripts\activate.bat
    set VENV_ACTIVATED=1
) else (
    echo No virtual environment found, using system Python
)
echo.

echo ======================================
echo OneLogin Migration Tool - App Builder
echo ======================================
echo.

echo Platform: Windows
echo.

REM Check if PyInstaller is installed
python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo PyInstaller not found. Installing...
    pip install pyinstaller
    if errorlevel 1 (
        echo ERROR: Failed to install PyInstaller
        pause
        exit /b 1
    )
)

REM Install dependencies from monorepo packages
echo Installing dependencies...
echo   1/4 Installing layered credentials package...
pip install -q -e packages\layered_credentials
if errorlevel 1 (
    echo ERROR: Failed to install layered_credentials package
    pause
    exit /b 1
)
echo   2/4 Installing core package...
pip install -q -e packages\core
if errorlevel 1 (
    echo ERROR: Failed to install core package
    pause
    exit /b 1
)
echo   3/4 Installing CLI package...
pip install -q -e packages\cli
if errorlevel 1 (
    echo ERROR: Failed to install CLI package
    pause
    exit /b 1
)
echo   4/4 Installing GUI package (with dev dependencies)...
pip install -q -e packages\gui[dev]
if errorlevel 1 (
    echo ERROR: Failed to install GUI package
    pause
    exit /b 1
)

REM Clean previous builds
echo Cleaning previous builds...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

REM Build the application
echo Building application...
python -m PyInstaller onelogin-migration-tool.spec
if errorlevel 1 (
    echo ERROR: Build failed
    pause
    exit /b 1
)

echo.
echo ======================================
echo Build complete!
echo ======================================
echo.
echo Windows executable created:
echo   dist\OneLogin Migration Tool.exe
echo.
echo To create an installer, use Inno Setup:
echo   1. Download Inno Setup from https://jrsoftware.org/isinfo.php
echo   2. Create an installer script (.iss file)
echo   3. Point it to dist\OneLogin Migration Tool.exe
echo.
pause
