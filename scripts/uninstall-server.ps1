# Stops startup and firewall rules. It deliberately DOES NOT delete the database or backups.
schtasks /End /TN "JewelLAN Server" 2>$null | Out-Null
schtasks /Delete /TN "JewelLAN Server" /F 2>$null | Out-Null
Get-NetFirewallRule -DisplayName "JewelLAN Server TCP" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
Get-NetFirewallRule -DisplayName "JewelLAN Discovery UDP" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
Write-Host "JewelLAN server startup removed. Data in $env:ProgramData\JewelLAN was preserved."
