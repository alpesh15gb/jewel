from __future__ import annotations

from pathlib import Path

def write_if_changed(path: str, text: str) -> None:
    p = Path(path)
    old = p.read_text(encoding="utf-8")
    if old != text:
        p.write_text(text, encoding="utf-8")
        print("updated", path)
    else:
        print("unchanged", path)

def must_replace(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Could not find patch anchor: {label}")
    return text.replace(old, new, 1)

def patch_installer() -> None:
    path = "installer/JewelLAN.iss"
    text = Path(path).read_text(encoding="utf-8")
    if 'MyBridgeExe' not in text:
        text = text.replace('#define MyServerExe "JewelServer.exe"', '#define MyServerExe "JewelServer.exe"\n#define MyBridgeExe "JewelTallyBridge.exe"', 1)
    if 'Name: "fulltally"' not in text:
        text = text.replace('Name: "full"; Description: "Server + Counter (recommended for the main showroom PC)"', 'Name: "full"; Description: "Server + Counter (recommended for the main showroom PC)"\nName: "fulltally"; Description: "Server + Counter + Tally Bridge"', 1)
        text = text.replace('Name: "client"; Description: "Counter only (connect to an existing JewelLAN server)"', 'Name: "client"; Description: "Counter only (connect to an existing JewelLAN server)"\nName: "tally"; Description: "Tally Bridge only (install on the TallyPrime PC)"', 1)
    text = text.replace('Name: "server"; Description: "JewelLAN Server - central database and LAN service"; Types: full server', 'Name: "server"; Description: "JewelLAN Server - central database and LAN service"; Types: full fulltally server', 1)
    text = text.replace('Name: "client"; Description: "JewelLAN POS - billing / inventory counter application"; Types: full client', 'Name: "client"; Description: "JewelLAN POS - billing / inventory counter application"; Types: full fulltally client', 1)
    if 'Name: "tallybridge"' not in text:
        text = text.replace('Name: "client"; Description: "JewelLAN POS - billing / inventory counter application"; Types: full fulltally client', 'Name: "client"; Description: "JewelLAN POS - billing / inventory counter application"; Types: full fulltally client\nName: "tallybridge"; Description: "JewelLAN Tally Bridge - local TallyPrime connector"; Types: fulltally tally', 1)
    if '{#MyBridgeExe}' not in text.split('[Icons]')[0]:
        text = text.replace('Source: "..\\dist\\{#MyClientExe}"; DestDir: "{app}"; DestName: "{#MyClientExe}"; Flags: ignoreversion; Components: client', 'Source: "..\\dist\\{#MyClientExe}"; DestDir: "{app}"; DestName: "{#MyClientExe}"; Flags: ignoreversion; Components: client\nSource: "..\\dist\\{#MyBridgeExe}"; DestDir: "{commonappdata}\\JewelLAN\\bin"; DestName: "{#MyBridgeExe}"; Flags: ignoreversion; Components: tallybridge', 1)
    if 'JewelLAN Tally Bridge Token' not in text:
        text = text.replace('Name: "{autodesktop}\\JewelLAN POS"; Filename: "{app}\\{#MyClientExe}"; WorkingDir: "{app}"; Tasks: desktopicon; Components: client', 'Name: "{autodesktop}\\JewelLAN POS"; Filename: "{app}\\{#MyClientExe}"; WorkingDir: "{app}"; Tasks: desktopicon; Components: client\nName: "{autoprograms}\\JewelLAN Tally Bridge Token"; Filename: "{commonappdata}\\JewelLAN\\bin\\{#MyBridgeExe}"; Parameters: "--show-token"; WorkingDir: "{commonappdata}\\JewelLAN\\bin"; Components: tallybridge', 1)
    if 'JewelLAN Tally Bridge TCP' not in text:
        insert = '''\n; Tally Bridge is exposed only to the Private LAN; TallyPrime itself remains localhost-only.\nFilename: "{sys}\\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""JewelLAN Tally Bridge TCP"""; Flags: runhidden; Components: tallybridge\nFilename: "{sys}\\schtasks.exe"; Parameters: "/Delete /TN ""JewelLAN Tally Bridge"" /F"; Flags: runhidden; Components: tallybridge\nFilename: "{sys}\\netsh.exe"; Parameters: "advfirewall firewall add rule name=""JewelLAN Tally Bridge TCP"" dir=in action=allow protocol=TCP localport=8767 profile=private enable=yes"; Flags: runhidden; Components: tallybridge\nFilename: "{sys}\\schtasks.exe"; Parameters: "/Create /TN ""JewelLAN Tally Bridge"" /SC ONSTART /RU SYSTEM /RL HIGHEST /TR ""{commonappdata}\\JewelLAN\\bin\\{#MyBridgeExe} --host 0.0.0.0 --port 8767 --tally-url http://127.0.0.1:9000"" /F"; Flags: runhidden; Components: tallybridge\nFilename: "{sys}\\schtasks.exe"; Parameters: "/Run /TN ""JewelLAN Tally Bridge"""; Flags: runhidden; Components: tallybridge\n'''
        text = text.replace('; Counter users can launch immediately after setup.', insert + '\n; Counter users can launch immediately after setup.', 1)
        text = text.replace('Filename: "{sys}\\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""JewelLAN Discovery UDP"""; Flags: runhidden\n', 'Filename: "{sys}\\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""JewelLAN Discovery UDP"""; Flags: runhidden\nFilename: "{sys}\\schtasks.exe"; Parameters: "/End /TN ""JewelLAN Tally Bridge"""; Flags: runhidden\nFilename: "{sys}\\schtasks.exe"; Parameters: "/Delete /TN ""JewelLAN Tally Bridge"" /F"; Flags: runhidden\nFilename: "{sys}\\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""JewelLAN Tally Bridge TCP"""; Flags: runhidden\n', 1)
        text = text.replace('    Sleep(750);\n  end;\nend;', '    Sleep(750);\n  end;\n  if WizardIsComponentSelected(\'tallybridge\') then\n  begin\n    Exec(ExpandConstant(\'{sys}\\schtasks.exe\'), \'/End /TN "JewelLAN Tally Bridge"\', \'\', SW_HIDE, ewWaitUntilTerminated, ResultCode);\n    Sleep(500);\n  end;\nend;', 1)
    write_if_changed(path, text)

if __name__ == "__main__":
    patch_installer()
