; ============================================================
; WildCatcher v2.0 — Inno Setup Installer Script
; ============================================================
; Prerequisites:
;   1. Run PyInstaller first:  pyinstaller wildcatcher.spec
;   2. Install Inno Setup:     https://jrsoftware.org/isdl.php
;   3. Open this file in Inno Setup Compiler and click Build
;      OR run from command line:
;      "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
; ============================================================

#define MyAppName "WildCatcher"
#define MyAppVersion "2.1.3"
#define MyAppPublisher "WildCatcher"
#define MyAppExeName "WildCatcher.exe"
; Path to the PyInstaller output folder
#define MyAppSourceDir "dist\WildCatcher"

[Setup]
AppId={{A3F7D2E1-8B4C-4F5A-9D6E-1C2B3A4F5E6D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=WildCatcher_v{#MyAppVersion}_Setup
SetupIconFile=assets\app_icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
; Single self-contained Setup.exe (no .bin slices) for simple client delivery
DiskSpanning=no
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
; Estimated size in KB (adjust based on actual build)
ExtraDiskSpaceRequired=0
PrivilegesRequired=lowest

[Languages]
Name: "english";    MessagesFile: "compiler:Default.isl"
Name: "japanese";   MessagesFile: "compiler:Languages\Japanese.isl"
Name: "spanish";    MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Bundle everything from the PyInstaller dist folder
Source: "{#MyAppSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; Create an empty models folder with clean registry for new installations
Source: "installer_data\registry.json"; DestDir: "{app}\models"; Flags: ignoreversion onlyifdoesntexist

[Icons]
Name: "{group}\{#MyAppName}";         Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}";    Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Clean up runtime files on uninstall
Type: files;      Name: "{app}\app.log"
Type: files;      Name: "{app}\license.wcl"
Type: filesandordirs; Name: "{app}\models"
Type: filesandordirs; Name: "{app}\__pycache__"
