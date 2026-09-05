from __future__ import annotations
import os, tempfile, uuid
from pathlib import Path
if "JEWELLAN_DB" not in os.environ:
    _TD = Path(tempfile.mkdtemp(prefix="jewellan-guards-"))
    os.environ["JEWELLAN_DB"] = str(_TD / "test.db")
    os.environ["JEWELLAN_DATA_DIR"] = str(_TD)
from fastapi.testclient import TestClient
from jewel_server.main import app

PW = "JewelTest#1234"

def _h(c):
    for p in (PW, "Jewel@123"):
        r = c.post("/api/auth/login", json={"username":"admin","password":p,"client_name":"guards"})
        if r.status_code != 200: continue
        d = r.json(); h = {"Authorization": f"Bearer {d['token']}"}
        if d["user"].get("must_change_password"):
            assert c.post("/api/auth/change-password", headers=h, json={"old_password":p,"new_password":PW}).status_code == 200
        return h
    raise AssertionError("login failed")

def _item(c,h):
    c.post("/api/rates", headers=h, json={"metal":"Gold","purity":"916","rate_per_gram":10000})
    r = c.post("/api/items", headers=h, json={"name":"G","category":"Ring","metal":"Gold","purity":"916","gross_weight":5,"stone_weight":0,"branch_id":1})
    assert r.status_code == 200, r.text
    return r.json()

def test_discount_cap_400():
    with TestClient(app) as c:
        h=_h(c); it=_item(c,h)
        q=c.post("/api/sales/quote", headers=h, json={"lines":[{"item_id":it["id"],"item_version":it["version"]}],"discount":99999999,"branch_id":1})
        assert q.status_code==400, q.text
        assert q.json()["error"]["code"]=="DISCOUNT_EXCEEDS_SUBTOTAL"

def test_old_gold_tolerance_and_override():
    with TestClient(app) as c:
        h=_h(c); it=_item(c,h)
        q=c.post("/api/sales/quote", headers=h, json={"lines":[{"item_id":it["id"],"item_version":it["version"]}],"branch_id":1}).json()
        og={"metal":"Gold","purity":"916","gross_weight":10,"deduction_percent":0,"rate":10000,"value":999999}
        bad=c.post("/api/sales", headers=h, json={"client_request_id":str(uuid.uuid4()),"branch_id":1,"lines":[{"item_id":it["id"],"item_version":it["version"]}],"discount":0,"old_gold":[og],"payment_cash":q["total"],"payment_card":0,"payment_upi":0,"payment_credit":0,"quote_hash":q["quote_hash"]})
        assert bad.status_code==400 and bad.json()["error"]["code"]=="OLD_GOLD_VALUE_MISMATCH", bad.text
        # manager override with reason passes validation (may still fail quote match if totals differ — must re-quote without old gold value change? override keeps same value so quote differs; use fresh quote that includes old gold)
        q2=c.post("/api/sales/quote", headers=h, json={"lines":[{"item_id":it["id"],"item_version":it["version"]}],"branch_id":1,"old_gold":[]}).json()
        # small old gold within total: 2g @10000 = 20000, total ~51500 → payable ~31500
        og_ok=dict(og, gross_weight=2, value=20000)
        q3=c.post("/api/sales/quote", headers=h, json={"lines":[{"item_id":it["id"],"item_version":it["version"]}],"branch_id":1,"old_gold":[og_ok]}).json()
        ok=c.post("/api/sales", headers=h, json={"client_request_id":str(uuid.uuid4()),"branch_id":1,"lines":[{"item_id":it["id"],"item_version":it["version"]}],"discount":0,"old_gold":[og_ok],"allow_old_gold_override":True,"old_gold_override_reason":"tested","payment_cash":q3["payable"],"payment_card":0,"payment_upi":0,"payment_credit":0,"quote_hash":q3["quote_hash"]})
        # value 20000 vs expected 20000 → within tolerance, posts fine
        assert ok.status_code==200, ok.text

def test_idempotency_ignores_quote_and_order():
    with TestClient(app) as c:
        h=_h(c)
        a=_item(c,h); b=_item(c,h)
        q=c.post("/api/sales/quote", headers=h, json={"lines":[{"item_id":a["id"],"item_version":a["version"]},{"item_id":b["id"],"item_version":b["version"]}],"branch_id":1}).json()
        rid=str(uuid.uuid4())
        body={"client_request_id":rid,"branch_id":1,"lines":[{"item_id":a["id"],"item_version":a["version"]},{"item_id":b["id"],"item_version":b["version"]}],"discount":0,"payment_cash":q["total"],"payment_card":0,"payment_upi":0,"payment_credit":0,"quote_hash":q["quote_hash"]}
        s1=c.post("/api/sales", headers=h, json=body)
        assert s1.status_code==200, s1.text
        # retry same logical sale, reversed line order + different quote hash field + refs → still idempotent
        # (no fresh quote: items are sold now, so use a fake hash — fingerprint excludes quotes)
        body2=dict(body, lines=list(reversed(body["lines"])), quote_hash="Q-fakehash1234567890", payment_references={"cash":"x"})
        s2=c.post("/api/sales", headers=h, json=body2)
        assert s2.status_code==200 and s2.json().get("idempotent") is True, s2.text
        # different discount → conflict
        body3=dict(body, discount=5, quote_hash="Q-fake2")
        s3=c.post("/api/sales", headers=h, json=body3)
        assert s3.status_code==409 and s3.json()["error"]["code"]=="IDEMPOTENCY_CONFLICT", s3.text
