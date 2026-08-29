#define MyAppName "JewelLAN"
#define MyAppVersion "1.2.0-rc1"
#define MyFileVersion "1.2.0.0"
#define MyPublisher "JewelLAN"
#define MyClientExe "JewelPOS.exe"
#define MyServerExe "JewelServer.exe"
#define MyBridgeExe "JewelTallyBridge.exe"

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
VersionInfoVersion={#MyFileVersion}
VersionInfoCompany={#MyPublisher}
VersionInfoDescription=Offline jewellery ERP/POS for Windows LAN
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyFileVersion}

[Types]
Name: "full"; Description: "Server + Counter (recommended for the main showroom PC)"
Name: "fulltally"; Description: "Server + Counter + Tally Bridge"
Name: "server"; Description: "Server only (database and LAN host)"
Name: "client"; Description: "Counter only (connect to an existing JewelLAN server)"
Name: "tally"; Description: "Tally Bridge only (install on the TallyPrime PC)"
Name: "custom"; Description: "Custom"; Flags: iscustom

[Components]
Name: "server"; Description: "JewelLAN Server - central database and LAN service"; Types: full fulltally server
Name: "client"; Description: "JewelLAN POS - billing / inventory counter application"; Types: full fulltally client
Name: "tallybridge"; Description: "JewelLAN Tally Bridge - local TallyPrime connector"; Types: fulltally tally

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Components: client

[Dirs]
Name: "{commonappdata}\JewelLAN"; Components: server
Name: "{commonappdata}\JewelLAN\bin"; Components: server
Name: "{commonappdata}\JewelLAN\backups"; Components: server

[Files]
Source: "..\dist\{#MyServerExe}"; DestDir: "{commonappdata}\JewelLAN\bin"; DestName: "{#MyServerExe}"; Flags: ignoreversion restartreplace; Components: server
Source: "..\dist\{#MyClientExe}"; DestDir: "{app}"; DestName: "{#MyClientExe}"; Flags: ignoreversion restartreplace; Components: client
Source: "..\dist\{#MyBridgeExe}"; DestDir: "{commonappdata}\JewelLAN\bin"; DestName: "{#MyBridgeExe}"; Flags: ignoreversion restartreplace; Components: tallybridge
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion; Components: client
Source: "..\docs\OPERATIONS.md"; DestDir: "{app}\docs"; Flags: ignoreversion; Components: client

[Icons]
Name: "{autoprograms}\JewelLAN POS"; Filename: "{app}\{#MyClientExe}"; WorkingDir: "{app}"; Components: client
Name: "{autodesktop}\JewelLAN POS"; Filename: "{app}\{#MyClientExe}"; WorkingDir: "{app}"; Tasks: desktopicon; Components: client
Name: "{autoprograms}\JewelLAN Tally Bridge Token"; Filename: "{commonappdata}\JewelLAN\bin\{#MyBridgeExe}"; Parameters: "--show-token"; WorkingDir: "{commonappdata}\JewelLAN\bin"; Components: tallybridge

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

; Tally Bridge is exposed only to the Private LAN; TallyPrime itself remains localhost-only.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""JewelLAN Tally Bridge TCP"""; Flags: runhidden; Components: tallybridge
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN ""JewelLAN Tally Bridge"" /F"; Flags: runhidden; Components: tallybridge
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""JewelLAN Tally Bridge TCP"" dir=in action=allow protocol=TCP localport=8767 profile=private enable=yes"; Flags: runhidden; Components: tallybridge
Filename: "{sys}\schtasks.exe"; Parameters: "/Create /TN ""JewelLAN Tally Bridge"" /SC ONSTART /RU SYSTEM /RL HIGHEST /TR ""{commonappdata}\JewelLAN\bin\{#MyBridgeExe} --host 0.0.0.0 --port 8767 --tally-url http://127.0.0.1:9000"" /F"; Flags: runhidden; Components: tallybridge
Filename: "{sys}\schtasks.exe"; Parameters: "/Run /TN ""JewelLAN Tally Bridge"""; Flags: runhidden; Components: tallybridge

; Counter users can launch immediately after setup.
Filename: "{app}\{#MyClientExe}"; Description: "Launch JewelLAN POS"; Flags: nowait postinstall skipifsilent; Components: client

[UninstallRun]
; Stop/remove tasks and processes before deleting binaries. Database/backups are intentionally preserved.
Filename: "{sys}\schtasks.exe"; Parameters: "/End /TN ""JewelLAN Server"""; Flags: runhidden
Filename: "{sys}\schtasks.exe"; Parameters: "/End /TN ""JewelLAN Tally Bridge"""; Flags: runhidden
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN ""JewelLAN Server"" /F"; Flags: runhidden
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN ""JewelLAN Tally Bridge"" /F"; Flags: runhidden
Filename: "{sys}\taskkill.exe"; Parameters: "/F /T /IM JewelServer.exe"; Flags: runhidden
Filename: "{sys}\taskkill.exe"; Parameters: "/F /T /IM JewelTallyBridge.exe"; Flags: runhidden
Filename: "{sys}\taskkill.exe"; Parameters: "/F /T /IM JewelPOS.exe"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""JewelLAN Server TCP"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""JewelLAN Discovery UDP"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""JewelLAN Tally Bridge TCP"""; Flags: runhidden

[Code]
procedure StopJewelLANForUpgrade;
var
  ResultCode: Integer;
begin
  { JEWELLAN_UPGRADE_LOCK_HARDENING }
  { End and remove scheduled tasks before Inno tries to replace the EXEs. }
  Exec(ExpandConstant('{sys}\schtasks.exe'), '/End /TN "JewelLAN Server"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{sys}\schtasks.exe'), '/End /TN "JewelLAN Tally Bridge"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{sys}\schtasks.exe'), '/Delete /TN "JewelLAN Server" /F', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{sys}\schtasks.exe'), '/Delete /TN "JewelLAN Tally Bridge" /F', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

  { A task can report ended while its child process still owns the executable. }
  { Force-close every JewelLAN binary and wait synchronously for taskkill. }
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM JewelServer.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM JewelTallyBridge.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM JewelPOS.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

  { Give Windows/AV a short window to release final image handles. }
  Sleep(1200);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  NeedsRestart := False;
  StopJewelLANForUpgrade;
end;
