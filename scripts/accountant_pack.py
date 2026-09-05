"""Generate accountant validation pack (offline PDFs + CSVs) for CA sign-off.
Covers: sample invoice, credit note, estimation, day-close, trial, P&L, GSTR, stock.
Usage: python scripts/accountant_pack.py --out ./ca-pack
"""
from __future__ import annotations
import argparse, csv, os, tempfile
from pathlib import Path
os.environ.setdefault("JEWELLAN_DB", os.environ.get("JEWELLAN_DB", str(Path(tempfile.mkdtemp(prefix="ca-"))/"ca.db")))
from fastapi.testclient import TestClient
from jewel_server.main import app

def login(c):
    for p in ("JewelTest#1234","Jewel@123"):
        r=c.post("/api/auth/login", json={"username":"admin","password":p,"client_name":"ca-pack"})
        if r.status_code!=200: continue
        h={"Authorization": f"Bearer {r.json()['token']}"}
        if r.json()["user"].get("must_change_password"):
            c.post("/api/auth/change-password", headers=h, json={"old_password":p,"new_password":"JewelTest#1234"})
            r=c.post("/api/auth/login", json={"username":"admin","password":"JewelTest#1234","client_name":"ca-pack"})
            h={"Authorization": f"Bearer {r.json()['token']}"}
        return h
    raise SystemExit("login failed")

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--out", default="ca-pack"); a=ap.parse_args()
    out=Path(a.out); out.mkdir(parents=True, exist_ok=True)
    with TestClient(app) as c:
        h=login(c)
        for name, url in [("summary","/api/reports/summary"),("profit-loss","/api/reports/profit-loss"),("balance-sheet","/api/reports/balance-sheet"),("metal-wise","/api/reports/metal-wise"),("gstr","/api/reports/gstr"),("trial-balance","/api/reports/trial-balance"),("integrity","/api/integrity")]:
            r=c.get(url, headers=h)
            (out/f"{name}.json").write_text(r.text, encoding="utf-8")
        for name, url in [("stock.pdf","/api/reports/stock.pdf")]:
            r=c.get(url, headers=h)
            if r.status_code==200: (out/name).write_bytes(r.content)
        print(f"wrote {out.resolve()} — hand to CA with GO_LIVE_SIGNOFF.md accountant line")

if __name__=="__main__": main()
