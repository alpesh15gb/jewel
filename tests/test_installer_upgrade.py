from pathlib import Path


def test_installer_stops_all_jewellan_processes_before_upgrade():
    text = Path("installer/JewelLAN.iss").read_text(encoding="utf-8")
    assert "JEWELLAN_UPGRADE_LOCK_HARDENING" in text
    assert '/End /TN "JewelLAN Server"' in text
    assert '/End /TN "JewelLAN Tally Bridge"' in text
    assert '/Delete /TN "JewelLAN Server" /F' in text
    assert '/Delete /TN "JewelLAN Tally Bridge" /F' in text
    assert '/IM JewelServer.exe' in text
    assert '/IM JewelTallyBridge.exe' in text
    assert '/IM JewelPOS.exe' in text
    assert "restartreplace" in text
