from __future__ import annotations
import os, tempfile, uuid
from pathlib import Path
if "JEWELLAN_DB" not in os.environ:
    _TD = Path(tempfile.mkdtemp(prefix="jewellan-offline-parity-"))
    os.environ["JEWELLAN_DB"] = str(_TD / "test.db")
    os.environ["JEWELLAN_DATA_DIR"] = str(_TD)
from fastapi.testclient import TestClient
from jewel_server.main import app

PW = "JewelTest#1234"

def _h(c):
    for p in (PW, "Jewel@123"):
        r = c.post("/api/auth/login", json={"username":"admin","password":p,"client_name":"parity"})
        if r.status_code != 200: continue
        d = r.json(); h = {"Authorization": f"Bearer {d['token']}"}
        if d["user"].get("must_change_password"):
            assert c.post("/api/auth/change-password", headers=h, json={"old_password":p,"new_password":PW}).status_code == 200
        return h
    raise AssertionError("login failed")

def _item(c,h,name="Parity Ring"):
    c.post("/api/rates", headers=h, json={"metal":"Gold","purity":"916","rate_per_gram":7000})
    r = c.post("/api/items", headers=h, json={"name":name+" "+uuid.uuid4().hex[:5],"category":"Ring","metal":"Gold","purity":"916","gross_weight":5,"stone_weight":0,"making_type":"per_gram","making_value":100,"cost_amount":10000,"huid":uuid.uuid4().hex[:6].upper(),"branch_id":1})
    assert r.status_code == 200, r.text
    return r.json()

def test_estimation_does_not_move_stock():
    with TestClient(app) as c:
        h=_h(c); it=_item(c,h)
        e=c.post("/api/estimations", headers=h, json={"branch_id":1,"lines":[{"item_id":it["id"],"item_version":it["version"]}],"discount":0})
        assert e.status_code==200, e.text
        eid=e.json()["id"]
        assert c.get(f"/api/items/{it['id']}", headers=h).json()["item"]["status"]=="in_stock"
        assert c.get(f"/api/estimations/{eid}/estimation.pdf", headers=h).status_code==200
        assert c.post(f"/api/estimations/{eid}/cancel", headers=h).status_code==200

def test_loyalty_earn_and_redeem_offline():
    with TestClient(app) as c:
        h=_h(c)
        cu=c.post("/api/customers", headers=h, json={"name":"Loyal "+uuid.uuid4().hex[:5]}).json()
        it=_item(c,h)
        q=c.post("/api/sales/quote", headers=h, json={"lines":[{"item_id":it["id"],"item_version":it["version"]}],"branch_id":1}).json()
        s=c.post("/api/sales", headers=h, json={"client_request_id":str(uuid.uuid4()),"branch_id":1,"lines":[{"item_id":it["id"],"item_version":it["version"]}],"discount":0,"payment_cash":q["total"],"payment_card":0,"payment_upi":0,"payment_credit":0,"quote_hash":q["quote_hash"],"customer_id":cu["id"]})
        assert s.status_code==200, s.text
        # earned floor(total/1000)
        cust=c.get("/api/customers", headers=h).json()
        row=[x for x in cust if x["id"]==cu["id"]][0]
        assert int(float(row.get("loyalty_points") or 0)) >= int(q["total"]//1000)
        # redeem more than balance fails
        it2=_item(c,h)
        q2=c.post("/api/sales/quote", headers=h, json={"lines":[{"item_id":it2["id"],"item_version":it2["version"]}],"branch_id":1}).json()
        bad=c.post("/api/sales", headers=h, json={"client_request_id":str(uuid.uuid4()),"branch_id":1,"lines":[{"item_id":it2["id"],"item_version":it2["version"]}],"discount":0,"loyalty_redeem_points":999999,"payment_cash":q2["total"],"payment_card":0,"payment_upi":0,"payment_credit":0,"quote_hash":q2["quote_hash"],"customer_id":cu["id"]})
        assert bad.status_code in (400,409), bad.text

def test_chit_and_gold_loan_offline_ledgers():
    with TestClient(app) as c:
        h=_h(c)
        cu=c.post("/api/customers", headers=h, json={"name":"Chit "+uuid.uuid4().hex[:5]}).json()
        sch=c.post("/api/chit-schemes", headers=h, json={"name":"G11 "+uuid.uuid4().hex[:4],"monthly_amount":5000}).json()
        mem=c.post("/api/chit-members", headers=h, json={"scheme_id":sch["id"] if isinstance(sch,dict) and "id" in sch else sch.get("id",1),"customer_id":cu["id"],"start_date":"2026-09-04"})
        # scheme endpoint returns id+code
        assert mem.status_code==200, mem.text
        mid=mem.json()["id"]
        assert c.post(f"/api/chit-members/{mid}/pay", headers=h, json={"amount":5000}).status_code==200
        loan=c.post("/api/gold-loans", headers=h, json={"customer_id":cu["id"],"gross_weight":10,"net_weight":9,"loan_amount":50000})
        assert loan.status_code==200, loan.text
        lid=loan.json()["id"]
        assert c.post(f"/api/gold-loans/{lid}/pay", headers=h, json={"amount":1000,"kind":"interest"}).status_code==200
        assert c.post(f"/api/gold-loans/{lid}/pay", headers=h, json={"amount":50000,"kind":"closure"}).status_code==200

def test_offline_reports_present():
    with TestClient(app) as c:
        h=_h(c)
        assert c.get("/api/reports/profit-loss", headers=h).status_code==200
        assert c.get("/api/reports/balance-sheet", headers=h).status_code==200
        assert c.get("/api/reports/metal-wise", headers=h).status_code==200
        assert c.get("/api/reports/gstr", headers=h).status_code==200

def test_customer_crm_validation():
    with TestClient(app) as c:
        h=_h(c)
        bad=c.post("/api/customers", headers=h, json={"name":""})
        assert bad.status_code==400
        ok=c.post("/api/customers", headers=h, json={"name":"CRM "+uuid.uuid4().hex[:5],"birthday":"1990-01-01","anniversary":"2020-02-02"})
        assert ok.status_code==200, ok.text
        cid=ok.json()["id"]
        bad2=c.put(f"/api/customers/{cid}", headers=h, json={"birthday":"not-a-date"})
        assert bad2.status_code==400
