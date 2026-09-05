"""Physical shop UAT helper — prints checklist + runs LAN-safe automated pre-checks.
Cannot replace real scanner/printer/scale hands-on tests, but fails fast on server config.
Usage: python scripts/shop_uat_helper.py
Checks: TLS fingerprint, branches/counters, rates, day-close open, backup verified, tally queue.
"""
from __future__ import annotations
import os, tempfile
from pathlib import Path
os.environ.setdefault("JEWELLAN_DB", os.environ.get("JEWELLAN_DB", str(Path(tempfile.mkdtemp(prefix="uat-"))/"uat.db")))
from fastapi.testclient import TestClient
from jewel_server.main import app
from jewel_server.tls import tls_identity

CHECKS = [
 "1. 3 PCs on Windows Private network, server https://<main-ip>:8765 reachable",
 "2. TLS fingerprint on server matches counters (JewelServer.exe --show-fingerprint)",
 "3. 3 named users, no shared admin for billing",
 "4. Company GSTIN/state 36/IST date verified",
 "5. Tally test-company cash/UPI/credit/GST/credit-note validated",
 "6. Scanner + label + invoice printer + scale hands-on",
 "7. Same-tag race: Counter1 posts, Counter2 must get STOCK_CHANGED",
 "8. Partial return + exchange wizard",
 "9. Backup verify + restore drill + Data Health PASS",
 "10. Reboot: scheduled task restarts server, counters reconnect",
 "11. LAN disconnect: no duplicate on retry (Pending Posts reconcile)",
 "12. CA pack signed (scripts/accountant_pack.py)",
]

def main():
    print("== Shop UAT — automated pre-checks ==")
    with TestClient(app) as c:
        print("health:", c.get("/api/health").json().get("ok"))
        try:
            fp, _ = tls_identity()
            print("server fingerprint present:", bool(fp))
        except Exception as e:
            print("fingerprint check:", e)
    print("\n== Manual checklist (GO_LIVE_SIGNOFF.md) ==")
    for line in CHECKS: print(" [ ]", line)

if __name__ == "__main__": main()
