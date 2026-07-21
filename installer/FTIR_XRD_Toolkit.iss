; Inno Setup script for the FTIR & XRD Analysis Toolkit.
;
; Wraps the standalone PyInstaller build (dist\FTIR_XRD_Toolkit\, an onedir
; build -- FTIR_XRD_Toolkit.exe plus every bundled dependency as loose files
; in that folder; no Python or anything else needs to be installed on the
; target PC) into a normal Windows installer: Start Menu shortcut, optional
; Desktop shortcut, Add/Remove Programs entry, and a proper uninstaller.
;
; Build with (from this "installer" folder, or point ISCC at this file
; directly -- see build_installer.ps1 in the project root for the
; one-command version):
;     "C:\Users\<you>\AppData\Local\Programs\Inno Setup 6\ISCC.exe" FTIR_XRD_Toolkit.iss
;
; Requires dist\FTIR_XRD_Toolkit\ to already exist -- run
; `pyinstaller app.spec` from the project root first (or run
; build_installer.ps1, which does both steps).

#define MyAppName "FTIR & XRD Analysis Toolkit"
#define MyAppVersion "2.0.0"
#define MyAppPublisher "Ezzeldien Yousef"
#define MyAppURL "mailto:ezzyousef@aucegypt.edu"
#define MyAppExeName "FTIR_XRD_Toolkit.exe"
#define MyAppCopyright "Copyright (C) 2026 Ezzeldien Yousef"

[Setup]
; Fixed AppId (a GUID) so future versions upgrade in place instead of
; installing side by side -- generated once for this app, keep it stable.
AppId={{5284ED2C-749B-4C5D-A408-9E184725E68F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppCopyright={#MyAppCopyright}
DefaultDirName={autopf}\FTIR_XRD_Toolkit
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=output
OutputBaseFilename=FTIR_XRD_ToolkitSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=..\assets\icon.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The whole onedir build folder (FTIR_XRD_Toolkit.exe + every bundled DLL/
; data file it needs at runtime, including the reference databases),
; recursively -- NOT just the exe.
Source: "..\dist\FTIR_XRD_Toolkit\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\assets\icon.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\COPYRIGHT.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; IconFilename is set explicitly (not just relying on the exe's own
; embedded icon) so the Start Menu and Desktop shortcuts show the icon
; reliably even if Windows' shortcut-icon cache is stale.
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\icon.ico"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
