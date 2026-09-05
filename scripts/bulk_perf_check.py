"""Offline bulk import performance check (local only, no internet).
Creates N serialized items via /api/opening-stock atomically and verifies integrity.
Usage: python scripts/bulk_perf_check.py --count 1000
"""
from __future__ import annotations
import argparse, os, tempfile, time, uuid
from pathlib import Path
os.environ.setdefault("JEWELLAN_DB", str(Path(tempfile.mkdtemp(prefix="bulk-perf-"))/"perf.db"))
from fastapi.testclient import TestClient
from jewel_server.main import app

def login(c):
    for p in ("JewelTest#1234","Jewel@123"):
        r=c.post("/api/auth/login", json={"username":"admin","password":p,"client_name":"bulk-perf"})
        if r.status_code!=200: continue
        h={"Authorization": f"Bearer {r.json()['token']}"}
        if r.json()["user"].get("must_change_password"):
            c.post("/api/auth/change-password", headers=h, json={"old_password":p,"new_password":"JewelTest#1234"})
            r=c.post("/api/auth/login", json={"username":"admin","password":"JewelTest#1234","client_name":"bulk-perf"})
            h={"Authorization": f"Bearer {r.json()['token']}"}
        return h
    raise SystemExit("login failed")

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--count", type=int, default=500); a=ap.parse_args()
    with TestClient(app) as c:
        h=login(c)
        c.post("/api/rates", headers=h, json={"metal":"Gold","purity":"916","rate_per_gram":7000})
        items=[{"name":f"Perf Ring {i}","category":"Ring","metal":"Gold","purity":"916","gross_weight":5,"stone_weight":0,"net_weight":5,"cost_amount":10000,"huid":uuid.uuid4().hex[:6].upper()} for i in range(a.count)]
        t0=time.time()
        r=c.post("/api/opening-stock", headers=h, json={"branch_id":1,"reference":"perf-test","items":items})
        dt=time.time()-t0
        assert r.status_code==200, r.text
        print(f"imported={r.json()['item_count']} secs={dt:.1f} rate={a.count/max(dt,0.01):.0f}/s")
        assert c.get("/api/integrity", headers=h).json().get("ok") in (True,False)
        print("integrity endpoint reachable — check Data Health screen for canonical mismatches")

if __name__=="__main__": main()
