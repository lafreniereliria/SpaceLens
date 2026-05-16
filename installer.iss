; ============================================================
;  SpaceLens / 建筑空间绩效评价平台  — Inno Setup script
;  Bundles the entire dist\SpaceLens\ folder into a single
;  self-extracting installer that works on a clean Windows PC.
;
;  Build prerequisites (handled by GitHub Actions):
;    - PyInstaller has already produced dist\SpaceLens\
;    - Inno Setup 6 is installed  (iscc.exe is on PATH)
; ============================================================

#define AppName      "建筑空间绩效评价平台"
#define AppNameEn    "SpaceLens"
#define AppVersion   "1.0.0"
#define AppPublisher "SpaceLens"
#define AppExeName   "SpaceLens.exe"
#define SourceDir    "dist\SpaceLens"

[Setup]
AppId={{A3F2C1E0-7B8D-4F9A-B3C2-1D0E5F6A7890}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppNameEn}
DefaultGroupName={#AppName}
OutputDir=installer_output
OutputBaseFilename=SpaceLens_Setup_{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
; Allow installing without admin rights (no UAC prompt needed for per-user installs)
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; Windows 8 / Server 2012 minimum
MinVersion=6.2
; 64-bit only
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
UninstallDisplayIcon={app}\{#AppExeName}
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
; Copy all PyInstaller output files recursively
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
; Optionally launch after install
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
