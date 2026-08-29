#define MyAppName "JewelLAN"
#define MyAppVersion "1.0.0"
#define MyPublisher "JewelLAN"
#define MyClientExe "JewelPOS.exe"
#define MyServerExe "JewelServer.exe"

[Setup]
AppId={{B8D67BE2-EEA9-4F25-9B25-4D04CC14745F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyPublisher}
DefaultDirName={autopf}\JewelLAN
DefaultGroupName=JewelLAN
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist\installer
OutputBaseFilename=JewelLAN-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes
UsePreviousSetupType=yes
UsePreviousTasks=yes
UninstallDisplayName=JewelLAN
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyPublisher}
VersionInfoDescription=Offline jewellery ERP/POS for Windows LAN
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}

[Types]
Name: "full"; Description: "Server + Counter (recommended for the main showroom PC)"
Name: "server"; Description: "Server only (database and LAN host)"
Name: "client"; Description: "Counter only (connect to an existing JewelLAN server)"
Name: "custom"; Description: "Custom"; Flags: iscustom

[Components]
Name: "server"; Description: "JewelLAN Server - central database and LAN service"; Types: full server
Name: "client"; Description: "JewelLAN POS - billing / inventory counter application"; Types: full client

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Components: client

[Dirs]
Name: "{commonappdata}\JewelLAN"; Components: server
Name: "{commonappdata}\JewelLAN\bin"; Components: server
Name: "{commonappdata}\JewelLAN\backups"; Components: server

[Files]
Source: "..\dist\{#MyServerExe}"; DestDir: "{commonappdata}\JewelLAN\bin"; DestName: "{#MyServerExe}"; Flags: ignoreversion; Components: server
Source: "..\dist\{#MyClientExe}"; DestDir: "{app}"; DestName: "{#MyClientExe}"; Flags: ignoreversion; Components: client
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion; Components: client
Source: "..\docs\OPERATIONS.md"; DestDir: "{app}\docs"; Flags: ignoreversion; Components: client

[Icons]
Name: "{autoprograms}\JewelLAN POS"; Filename: "{app}\{#MyClientExe}"; WorkingDir: "{app}"; Components: client
Name: "{autodesktop}\JewelLAN POS"; Filename: "{app}\{#MyClientExe}"; WorkingDir: "{app}"; Tasks: desktopicon; Components: client

[Run]
; Remove stale rules/tasks first so upgrades are deterministic.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""JewelLAN Server TCP"""; Flags: runhidden; Components: server
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""JewelLAN Discovery UDP"""; Flags: runhidden; Components: server
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN ""JewelLAN Server"" /F"; Flags: runhidden; Components: server

; LAN access is deliberately limited to Windows Private networks.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""JewelLAN Server TCP"" dir=in action=allow protocol=TCP localport=8765 profile=private enable=yes"; Flags: runhidden; Components: server
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""JewelLAN Discovery UDP"" dir=in action=allow protocol=UDP localport=8766 profile=private enable=yes"; Flags: runhidden; Components: server

; Run the server as SYSTEM at boot. Application data remains under ProgramData.
Filename: "{sys}\schtasks.exe"; Parameters: "/Create /TN ""JewelLAN Server"" /SC ONSTART /RU SYSTEM /RL HIGHEST /TR ""{commonappdata}\JewelLAN\bin\{#MyServerExe} --host 0.0.0.0 --port 8765"" /F"; Flags: runhidden; Components: server
Filename: "{sys}\schtasks.exe"; Parameters: "/Run /TN ""JewelLAN Server"""; Flags: runhidden; Components: server

; Counter users can launch immediately after setup.
Filename: "{app}\{#MyClientExe}"; Description: "Launch JewelLAN POS"; Flags: nowait postinstall skipifsilent; Components: client

[UninstallRun]
; Stop/remove the service task and LAN firewall rules. Database/backups are intentionally preserved.
Filename: "{sys}\schtasks.exe"; Parameters: "/End /TN ""JewelLAN Server"""; Flags: runhidden
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN ""JewelLAN Server"" /F"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""JewelLAN Server TCP"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""JewelLAN Discovery UDP"""; Flags: runhidden

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Result := '';
  NeedsRestart := False;

  { Stop an existing server before replacing its executable during upgrades. }
  if WizardIsComponentSelected('server') then
  begin
    Exec(ExpandConstant('{sys}\schtasks.exe'),
      '/End /TN "JewelLAN Server"', '', SW_HIDE,
      ewWaitUntilTerminated, ResultCode);
    Sleep(750);
  end;
end;
