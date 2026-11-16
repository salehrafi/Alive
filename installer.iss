; ALIVE installer (Inno Setup 6).  Build with:  build_installer.ps1
; Per-user install: no administrator rights needed.

#define MyAppName "ALIVE"
#define MyAppVersion "1.0.0"
#define MyAppExe "ALIVE.exe"

[Setup]
AppId={{6F1B0C52-3E0A-4C8E-9B7A-A11CE5A1F001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=ALIVE
AppComments=Bluetooth speaker keep-alive
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExe}
SetupIconFile=assets\alive.ico
OutputDir=dist
OutputBaseFilename=ALIVE-Setup-{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#MyAppVersion}
VersionInfoProductName={#MyAppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked
Name: "startup"; Description: "Start ALIVE in the notification area when I sign in to Windows"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
; The whole PyInstaller folder build must come along: the exe needs _internal\.
Source: "dist\ALIVE\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; IconFilename: "{app}\{#MyAppExe}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Parameters: "--tray"; Tasks: startup

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Stop ALIVE (and its playback) before its files are removed.
Filename: "{sys}\taskkill.exe"; Parameters: "/IM {#MyAppExe} /F"; Flags: runhidden; RunOnceId: "StopALIVE"

[UninstallDelete]
; Created at runtime by ALIVE (silent WAV, not user data).
Type: filesandordirs; Name: "{localappdata}\ALIVE"
