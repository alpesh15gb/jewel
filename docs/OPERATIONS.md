# Operations runbook

## Server PC

Use a Windows 10/11 Pro or Windows Server machine with a UPS. Give it a static DHCP reservation on the router/switch. Extract the Windows build artifact and run PowerShell as Administrator:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install-server.ps1
```

The installer opens TCP 8765 and UDP 8766 on **Private** networks only, copies `JewelServer.exe` under `C:\ProgramData\JewelLAN\bin`, and registers a startup task. The database lives at `C:\ProgramData\JewelLAN\jewellan.db`; backups live under `C:\ProgramData\JewelLAN\backups`.

Do not share the database file over SMB. Do not expose port 8765 to the public internet.

## Counter PC

Run `JewelPOS.exe` or `install-client.ps1`. At the login screen click **Discover**. If Windows blocks UDP discovery, enter the server address such as `http://192.168.1.20:8765`.

Initial login is `admin / Jewel@123`. Change it immediately, create named users, and use cashier/inventory roles for daily work.

## Recommended daily routine

1. Enter metal rates at opening.
2. Verify automatic backup list.
3. Operate sales/purchases/repairs normally.
4. Run a stock audit at closing by scanning all tags at each counter/vault.
5. Keep at least one backup copy on a second physical disk or NAS on the same private network.

## Recovery

Stop the JewelLAN scheduled task, then from an elevated console:

```powershell
C:\ProgramData\JewelLAN\bin\JewelServer.exe --restore C:\ProgramData\JewelLAN\backups\jewellan-YYYYMMDD-HHMMSS-manual.db
```

Start the scheduled task again. The restore command validates the backup and creates a pre-restore safety backup before replacement.
