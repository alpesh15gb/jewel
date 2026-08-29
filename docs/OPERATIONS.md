# Operations runbook

## Server PC

Use a Windows 10/11 Pro or Windows Server machine with a UPS. Give it a static DHCP reservation on the router/switch.

Run `JewelLAN-Setup.exe` and choose **Server + Counter** for the main showroom PC, or **Server only** for a dedicated host. The installer requests Administrator permission through the normal Windows UAC prompt; no PowerShell commands are required.

Setup opens TCP `8765` and UDP `8766` on **Private** networks only, installs `JewelServer.exe` under `C:\ProgramData\JewelLAN\bin`, registers the `JewelLAN Server` startup task under SYSTEM, and starts it immediately.

The database lives at `C:\ProgramData\JewelLAN\jewellan.db`; backups live under `C:\ProgramData\JewelLAN\backups`.

Do not share the database file over SMB. Do not expose port 8765 to the public internet.

## Counter PC

Run the same `JewelLAN-Setup.exe` and choose **Counter only**. Setup creates the Start Menu and desktop shortcut.

At the login screen click **Discover**. If Windows or network policy blocks UDP discovery, enter the server address such as `http://192.168.1.20:8765`.

Initial login is `admin / Jewel@123`. Change it immediately, create named users, and use cashier/inventory/accounts roles for daily work.

## Recommended daily routine

1. Enter metal rates at opening.
2. Verify automatic backup list.
3. Operate sales/purchases/repairs normally.
4. Run a stock audit at closing by scanning all tags at each counter/vault.
5. Keep at least one backup copy on a second physical disk or NAS on the same private network.

## Upgrade

Run a newer `JewelLAN-Setup.exe` over the existing installation and choose the same machine role. Setup stops the existing server task before replacing the binary, recreates the Private-LAN firewall rules, and starts the server again. Database and backups are not replaced.

## Uninstall

Use **Settings -> Apps -> Installed apps -> JewelLAN -> Uninstall**. The uninstaller removes application binaries, the startup task and JewelLAN firewall rules. It deliberately leaves `C:\ProgramData\JewelLAN\jewellan.db` and `C:\ProgramData\JewelLAN\backups` intact to prevent accidental business-data loss.

## Recovery

For a manual database restore, stop the `JewelLAN Server` scheduled task, then from an elevated Command Prompt or PowerShell window run:

```text
C:\ProgramData\JewelLAN\bin\JewelServer.exe --restore C:\ProgramData\JewelLAN\backups\jewellan-YYYYMMDD-HHMMSS-manual.db
```

Start the scheduled task again. The restore command validates the backup and creates a pre-restore safety backup before replacement.

## Production signing

Testing builds are currently unsigned and may trigger Windows SmartScreen. Before distributing to staff or customers, Authenticode-sign `JewelLAN-Setup.exe`, `JewelPOS.exe` and `JewelServer.exe` with the organisation's code-signing certificate.
