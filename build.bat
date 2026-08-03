@echo off
setlocal
where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo ERROR: Python not found. Activate your venv first.
    pause
    exit /b 1
)
rem Single source of truth is wc_version.py -- read it instead of hardcoding
rem the version string here, which would otherwise drift silently (a future
rem release could sign/report the wrong installer filename).
for /f "delims=" %%v in ('python -c "import wc_version; print(wc_version.APP_VERSION)"') do set WC_VERSION=%%v
if "%WC_VERSION%"=="" (
    echo ERROR: Could not read APP_VERSION from wc_version.py
    pause
    exit /b 1
)
echo.
echo ========================================
echo   WildCatcher v%WC_VERSION% Build
echo ========================================
echo.
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
echo [3.5/4] Signing app executable (no-op if no cert configured)...
powershell -NoProfile -ExecutionPolicy Bypass -File "sign_windows.ps1" "dist\WildCatcher\WildCatcher.exe"
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
echo Signing installer (no-op if no cert configured)...
powershell -NoProfile -ExecutionPolicy Bypass -File "sign_windows.ps1" "installer_output\WildCatcher_v%WC_VERSION%_Setup.exe"
echo.
echo ========================================
echo   BUILD COMPLETE
echo ========================================
echo   Portable:  dist\WildCatcher\WildCatcher.exe
echo   Installer: installer_output\WildCatcher_v%WC_VERSION%_Setup.exe
echo ========================================
pause
