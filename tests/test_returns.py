from __future__ import annotations

import os
import sqlite3
import tempfile
import uuid
from pathlib import Path

import pytest

if "JEWELLAN_DB" not in os.environ:
    _TEST_DIR = Path(tempfile.mkdtemp(prefix="jewellan-returns-test-"))
    os.environ["JEWELLAN_DB"] = str(_TEST_DIR / "test.db")
    os.environ["JEWELLAN_DATA_DIR"] = str(_TEST_DIR)

from fastapi.testclient import TestClient

from jewel_server.db import read_db, write_db
from jewel_server.main import app
from jewel_server.precision import money_paise

TEST_ADMIN_PASSWORD = "JewelTest#1234"


def _login(client: TestClient) -> dict[str, str]:
    for password in (TEST_ADMIN_PASSWORD, "Jewel@123"):
        r=client.post("/api/auth/login",json={"username":"admin","password":password,"client_name":"returns-pytest"})
        if r.status_code!=200:
            continue
        data=r.json();headers={"Authorization":f"Bearer {data['token']}"}
        if data["user"].get("must_change_password"):
            changed=client.post("/api/auth/change-password",headers=headers,json={"old_password":password,"new_password":TEST_ADMIN_PASSWORD})
            assert changed.status_code==200,changed.text
        return headers
    raise AssertionError("admin login failed")


def _item(name: str) -> dict:
    return {
        "name":name,"category":"Ring","metal":"Gold","purity":"916",
        "gross_weight":"3.125","stone_weight":"0.125","making_type":"per_gram",
        "making_value":"450.00","stone_value":"125.00","cost_amount":"12000.00",
        "huid":uuid.uuid4().hex[:6].upper(),"branch_id":1,"counter_id":1,
    }


def _make_sale(client: TestClient, headers: dict[str,str], customer_id: int | None = None, count: int = 2):
    client.post("/api/rates",headers=headers,json={"metal":"Gold","purity":"916","rate_per_gram":"7000.00"})
    items=[]
    for n in range(count):
        r=client.post("/api/items",headers=headers,json=_item(f"Return Test Ring {uuid.uuid4().hex[:5]}-{n}"))
        assert r.status_code==200,r.text;items.append(r.json())
    lines=[{"item_id":x["id"],"item_version":x["version"]} for x in items]
    q=client.post("/api/sales/quote",headers=headers,json={"lines":lines,"discount":0,"old_gold":[],"branch_id":1,"counter_id":1})
    assert q.status_code==200,q.text
    payload={"client_request_id":str(uuid.uuid4()),"branch_id":1,"counter_id":1,"customer_id":customer_id,"lines":lines,"discount":0,"old_gold":[],"payment_cash":q.json()["total"],"payment_card":0,"payment_upi":0,"payment_credit":0,"quote_id":q.json()["quote_id"],"quote_hash":q.json()["quote_hash"]}
    sale=client.post("/api/sales",headers=headers,json=payload)
    assert sale.status_code==200,sale.text
    detail=client.get(f"/api/sales/{sale.json()['id']}",headers=headers)
    assert detail.status_code==200,detail.text
    return sale.json(),detail.json(),items


def test_partial_return_credit_note_exact_balance_pdf_and_reversal():
    with TestClient(app) as client:
        headers=_login(client)
        cust=client.post("/api/customers",headers=headers,json={"name":f"Return Customer {uuid.uuid4().hex[:6]}","phone":"9999999999"})
        assert cust.status_code==200,cust.text;customer_id=cust.json()["id"]
        sale,detail,items=_make_sale(client,headers,customer_id,2)
        line_ids=[x["id"] for x in detail["lines"]]

        quoted=client.post(f"/api/sales/{sale['id']}/return-quote",headers=headers,json={"sale_item_ids":[line_ids[0]]})
        assert quoted.status_code==200,quoted.text
        quote=quoted.json();assert quote["selected_count"]==1 and quote["total"]>0
        assert quote["cgst"]+quote["sgst"]==pytest.approx(quote["gst"],abs=0.001)
        assert quote["igst"]==0

        request_id=str(uuid.uuid4())
        ret=client.post(f"/api/sales/{sale['id']}/return",headers=headers,json={"client_request_id":request_id,"sale_item_ids":[line_ids[0]],"reason":"Customer exchange","refund_cash":0,"refund_card":0,"refund_upi":0,"refund_credit":quote["total"]})
        assert ret.status_code==200,ret.text
        payload=ret.json();rid=payload["return"]["id"]
        assert payload["return"]["total"]==quote["total"]
        assert payload["return"]["status"]=="posted"

        retry=client.post(f"/api/sales/{sale['id']}/return",headers=headers,json={"client_request_id":request_id,"sale_item_ids":[line_ids[0]],"reason":"Customer exchange","refund_cash":0,"refund_card":0,"refund_upi":0,"refund_credit":quote["total"]})
        assert retry.status_code==200 and retry.json()["idempotent"] is True
        duplicate=client.post(f"/api/sales/{sale['id']}/return",headers=headers,json={"client_request_id":str(uuid.uuid4()),"sale_item_ids":[line_ids[0]],"reason":"Duplicate return","refund_cash":0,"refund_card":0,"refund_upi":0,"refund_credit":quote["total"]})
        assert duplicate.status_code==409

        assert client.get(f"/api/items/{items[0]['id']}",headers=headers).json()["item"]["status"]=="in_stock"
        assert client.get(f"/api/items/{items[1]['id']}",headers=headers).json()["item"]["status"]=="sold"
        with read_db() as conn:
            customer=conn.execute("SELECT balance,balance_paise FROM customers WHERE id=?",(customer_id,)).fetchone()
            assert customer["balance_paise"]==-money_paise(quote["total"])
            assert money_paise(customer["balance"])==customer["balance_paise"]
            row=conn.execute("SELECT * FROM sale_returns WHERE id=?",(rid,)).fetchone()
            assert row["total_paise"]==money_paise(quote["total"])
            assert row["cgst_paise"]+row["sgst_paise"]+row["igst_paise"]==row["gst_paise"]
            assert conn.execute("SELECT count(*) FROM journal_entries WHERE ref_type='sale_return' AND ref_id=?",(rid,)).fetchone()[0]==1
            assert conn.execute("SELECT count(*) FROM tally_sync_queue WHERE entity_type='sale_return' AND entity_id=? AND operation='create'",(rid,)).fetchone()[0]==1

        pdf=client.get(f"/api/returns/{rid}/credit-note.pdf",headers=headers)
        assert pdf.status_code==200 and pdf.content.startswith(b"%PDF")
        day=client.get("/api/reports/day-close",headers=headers,params={"date":detail["sale"]["business_date"]})
        assert day.status_code==200,day.text
        d=day.json();assert d["returns"]["count"]>=1;assert d["returns"]["refunds_match_returns"] is True;assert d["net_sales"]["payments_match_net_sales"] is True
        health=client.get("/api/integrity",headers=headers);assert health.status_code==200,health.text;assert health.json()["ok"] is True,health.json().get("issues")

        cancelled=client.post(f"/api/returns/{rid}/cancel",headers=headers,json={"reason":"Manager reversed test return"})
        assert cancelled.status_code==200,cancelled.text
        assert client.get(f"/api/items/{items[0]['id']}",headers=headers).json()["item"]["status"]=="sold"
        with read_db() as conn:
            customer=conn.execute("SELECT balance_paise FROM customers WHERE id=?",(customer_id,)).fetchone()
            assert customer["balance_paise"]==0
            assert conn.execute("SELECT count(*) FROM sale_return_items WHERE return_id=? AND active=1",(rid,)).fetchone()[0]==0
            assert conn.execute("SELECT count(*) FROM journal_entries WHERE ref_type='sale_return_cancel' AND ref_id=?",(rid,)).fetchone()[0]==1
            assert conn.execute("SELECT count(*) FROM tally_sync_queue WHERE entity_type='sale_return' AND entity_id=? AND operation='cancel'",(rid,)).fetchone()[0]==1
        health=client.get("/api/integrity",headers=headers);assert health.status_code==200;assert health.json()["ok"] is True,health.json().get("issues")

        with pytest.raises(sqlite3.DatabaseError):
            with write_db() as conn:
                conn.execute("UPDATE sale_returns SET total_paise=total_paise+1 WHERE id=?",(rid,))


def test_customer_credit_sale_uses_exact_balance_and_cancel_reverses_it():
    with TestClient(app) as client:
        headers=_login(client)
        cust=client.post("/api/customers",headers=headers,json={"name":f"Credit Customer {uuid.uuid4().hex[:6]}"})
        assert cust.status_code==200;cid=cust.json()["id"]
        client.post("/api/rates",headers=headers,json={"metal":"Gold","purity":"916","rate_per_gram":"7000"})
        made=client.post("/api/items",headers=headers,json=_item(f"Credit Ring {uuid.uuid4().hex[:5]}"));assert made.status_code==200,made.text
        line={"item_id":made.json()["id"],"item_version":made.json()["version"]}
        q=client.post("/api/sales/quote",headers=headers,json={"lines":[line],"old_gold":[],"branch_id":1,"counter_id":1});assert q.status_code==200
        sale=client.post("/api/sales",headers=headers,json={"client_request_id":str(uuid.uuid4()),"branch_id":1,"counter_id":1,"customer_id":cid,"lines":[line],"old_gold":[],"payment_cash":0,"payment_card":0,"payment_upi":0,"payment_credit":q.json()["total"],"quote_id":q.json()["quote_id"],"quote_hash":q.json()["quote_hash"]});assert sale.status_code==200,sale.text
        with read_db() as conn:
            row=conn.execute("SELECT balance,balance_paise FROM customers WHERE id=?",(cid,)).fetchone();assert row["balance_paise"]==money_paise(q.json()["total"]);assert money_paise(row["balance"])==row["balance_paise"]
        cancel=client.post(f"/api/sales/{sale.json()['id']}/cancel",headers=headers,json={"reason":"Credit sale test reversal"});assert cancel.status_code==200,cancel.text
        with read_db() as conn:assert conn.execute("SELECT balance_paise FROM customers WHERE id=?",(cid,)).fetchone()[0]==0
