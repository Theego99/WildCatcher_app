@echo off
setlocal
echo.
echo ========================================
echo   WildCatcher v2.0 Build
echo ========================================
echo.
where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo ERROR: Python not found. Activate your venv first.
    pause
    exit /b 1
)
where pyinstaller >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo PyInstaller not found. Installing...
    pip install pyinstaller
)
echo [1/4] Cleaning previous builds...
if exist "dist" rmdir /s /q "dist"
if exist "build" rmdir /s /q "build"
echo [2/4] Preparing installer data...
if not exist "installer_data" mkdir "installer_data"
echo [] > "installer_data\registry.json"
echo [3/4] Running PyInstaller...
echo.
pyinstaller wildcatcher.spec --noconfirm
if %ERRORLEVEL% neq 0 (
    echo.
    echo ERROR: PyInstaller build failed!
    pause
    exit /b 1
)
echo.
echo PyInstaller build complete.
echo.
if not exist "dist\WildCatcher\models" mkdir "dist\WildCatcher\models"
copy /y "installer_data\registry.json" "dist\WildCatcher\models\registry.json" >nul
if /i "%1"=="exe" (
    echo Skipping installer. Portable app ready at: dist\WildCatcher\
    pause
    exit /b 0
)
echo [4/4] Building Windows installer...
set "INNO="
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "INNO=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set "INNO=C:\Program Files\Inno Setup 6\ISCC.exe"
if "%INNO%"=="" (
    echo Inno Setup 6 not found. Install from: https://jrsoftware.org/isdl.php
    echo Portable app is ready at: dist\WildCatcher\
    pause
    exit /b 0
)
"%INNO%" installer.iss
if %ERRORLEVEL% neq 0 (
    echo ERROR: Installer build failed!
    pause
    exit /b 1
)
echo.
echo ========================================
echo   BUILD COMPLETE
echo ========================================
echo   Portable:  dist\WildCatcher\WildCatcher.exe
echo   Installer: installer_output\WildCatcher_v2.0_Setup.exe
echo ========================================
pause
