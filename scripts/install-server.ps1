# Run as Administrator from the folder containing JewelServer.exe.
$ErrorActionPreference = "Stop"
$Source = Join-Path $PSScriptRoot "..\JewelServer.exe"
if (!(Test-Path $Source)) { $Source = Join-Path (Get-Location) "JewelServer.exe" }
if (!(Test-Path $Source)) { throw "JewelServer.exe was not found." }
$Bin = "$env:ProgramData\JewelLAN\bin"
New-Item -ItemType Directory -Force -Path $Bin | Out-Null
Copy-Item $Source "$Bin\JewelServer.exe" -Force

# Firewall: LAN clients use TCP 8765; discovery uses UDP 8766.
Get-NetFirewallRule -DisplayName "JewelLAN Server TCP" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
Get-NetFirewallRule -DisplayName "JewelLAN Discovery UDP" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName "JewelLAN Server TCP" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765 -Profile Private | Out-Null
New-NetFirewallRule -DisplayName "JewelLAN Discovery UDP" -Direction Inbound -Action Allow -Protocol UDP -LocalPort 8766 -Profile Private | Out-Null

# Start at boot under SYSTEM. Database/backups stay in C:\ProgramData\JewelLAN.
schtasks /Delete /TN "JewelLAN Server" /F 2>$null | Out-Null
schtasks /Create /TN "JewelLAN Server" /SC ONSTART /RU SYSTEM /RL HIGHEST /TR "`"$Bin\JewelServer.exe`" --host 0.0.0.0 --port 8765" /F | Out-Null
schtasks /Run /TN "JewelLAN Server" | Out-Null
Start-Sleep -Seconds 2

Write-Host "JewelLAN server installed and started." -ForegroundColor Green
Write-Host "Database: $env:ProgramData\JewelLAN\jewellan.db"
Write-Host "Backups:  $env:ProgramData\JewelLAN\backups"
Write-Host "LAN addresses:"
Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.PrefixOrigin -ne 'WellKnown' } | ForEach-Object { Write-Host "  http://$($_.IPAddress):8765" }
Write-Host "First login: admin / Jewel@123 - change it immediately."
