; Installeur Inno Setup pour ALFRED
; Compilé par scripts/build.py ou par le workflow release.yml :
;   ISCC.exe /DAppVersion=0.1.0 installer\alfred.iss

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#define AppName "Alfred"
#define AppPublisher "Dorian Dubosc"
#define AppURL "https://github.com/Captain-VII/alfred"
#define AppExe "Alfred.exe"

[Setup]
AppId={{7E1D2A6B-0C3F-4A5E-9B8D-ALFRED000001}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=Output
OutputBaseFilename=Alfred-Setup-{#AppVersion}
SetupIconFile=..\assets\icons\alfred.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.22000
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "autostart"; Description: "Lancer Alfred au démarrage de Windows"; GroupDescription: "Démarrage :"

[Files]
Source: "..\dist\Alfred\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Désinstaller {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Démarrage automatique : même clé que celle gérée par les réglages d'Alfred
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Alfred"; ValueData: """{app}\{#AppExe}"" --minimized"; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#AppExe}"; Description: "Lancer {#AppName}"; Flags: nowait postinstall skipifsilent
; Installation silencieuse (mise à jour auto) : relance Alfred sans interaction
Filename: "{app}\{#AppExe}"; Parameters: "--minimized"; Flags: nowait skipifnotsilent

[UninstallDelete]
Type: filesandordirs; Name: "{userappdata}\Alfred\cache"
Type: filesandordirs; Name: "{userappdata}\Alfred\logs"

[Code]
// Ferme Alfred avant l'installation (mise à jour) pour libérer les fichiers.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Exec('taskkill.exe', '/IM {#AppExe} /F', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := '';
end;
