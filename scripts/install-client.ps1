# Creates a desktop shortcut. JewelPOS.exe can also be run directly from any folder.
$ErrorActionPreference = "Stop"
$Source = Join-Path $PSScriptRoot "..\JewelPOS.exe"
if (!(Test-Path $Source)) { $Source = Join-Path (Get-Location) "JewelPOS.exe" }
if (!(Test-Path $Source)) { throw "JewelPOS.exe was not found." }
$Dir = "$env:LOCALAPPDATA\JewelLAN"
New-Item -ItemType Directory -Force -Path $Dir | Out-Null
Copy-Item $Source "$Dir\JewelPOS.exe" -Force
$ws = New-Object -ComObject WScript.Shell
$shortcut = $ws.CreateShortcut("$env:USERPROFILE\Desktop\JewelLAN POS.lnk")
$shortcut.TargetPath = "$Dir\JewelPOS.exe"
$shortcut.WorkingDirectory = $Dir
$shortcut.Save()
Write-Host "JewelLAN POS installed for this Windows user." -ForegroundColor Green
