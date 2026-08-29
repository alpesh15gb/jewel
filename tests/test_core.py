import os, tempfile, uuid
from pathlib import Path

TEST_DIR = Path(tempfile.mkdtemp(prefix="jewellan-test-"))
os.environ["JEWELLAN_DB"] = str(TEST_DIR / "test.db")
os.environ["JEWELLAN_DATA_DIR"] = str(TEST_DIR)

from fastapi.testclient import TestClient
from jewel_server.main import app

TEST_ADMIN_PASSWORD = "JewelTest#1234"


def auth_headers(client):
    last = None
    for password in (TEST_ADMIN_PASSWORD, "Jewel@123"):
        r = client.post("/api/auth/login", json={"username": "admin", "password": password, "client_name": "pytest"})
        last = r
        if r.status_code != 200:
            continue
        data = r.json()
        headers = {"Authorization": f"Bearer {data['token']}"}
        if data["user"].get("must_change_password"):
            changed = client.post(
                "/api/auth/change-password",
                headers=headers,
                json={"old_password": password, "new_password": TEST_ADMIN_PASSWORD},
            )
            assert changed.status_code == 200, changed.text
        return headers
    assert last is not None and last.status_code == 200, last.text if last is not None else "login failed"


def test_health_login_inventory_sale_and_audit():
    with TestClient(app) as c:
        assert c.get("/api/health").json()["ok"] is True
        h = auth_headers(c)
        assert c.post("/api/rates", headers=h, json={"metal": "Gold", "purity": "916", "rate_per_gram": 6000}).status_code == 200
        item = {"name": "22K Ring", "category": "Ring", "metal": "Gold", "purity": "916", "gross_weight": 10.0, "stone_weight": 1.0, "net_weight": 9.0, "making_type": "per_gram", "making_value": 500, "stone_value": 1000, "cost_amount": 40000, "huid": "ABC123"}
        r = c.post("/api/items", headers=h, json=item); assert r.status_code == 200, r.text
        it = r.json(); assert it["net_weight"] == 9.0
        assert c.get(f"/api/items/barcode/{it['barcode']}", headers=h).status_code == 200
        q = c.post("/api/sales/quote", headers=h, json={"lines": [{"item_id": it["id"]}], "discount": 0, "old_gold": []}); assert q.status_code == 200, q.text
        quote = q.json(); assert quote["total"] > 0
        payload = {"client_request_id": str(uuid.uuid4()), "branch_id": 1, "counter_id": 1, "lines": [{"item_id": it["id"]}], "discount": 0, "old_gold": [], "payment_cash": quote["total"], "payment_card": 0, "payment_upi": 0, "payment_credit": 0}
        sale = c.post("/api/sales", headers=h, json=payload); assert sale.status_code == 200, sale.text
        sid = sale.json()["id"]
        retry = c.post("/api/sales", headers=h, json=payload); assert retry.status_code == 200; assert retry.json()["id"] == sid; assert retry.json()["idempotent"] is True
        assert c.get(f"/api/items/{it['id']}", headers=h).json()["item"]["status"] == "sold"
        pdf = c.get(f"/api/sales/{sid}/invoice.pdf", headers=h); assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
        cancel = c.post(f"/api/sales/{sid}/cancel", headers=h, json={"reason": "test"}); assert cancel.status_code == 200, cancel.text
        assert c.get(f"/api/items/{it['id']}", headers=h).json()["item"]["status"] == "in_stock"
        a = c.post("/api/stock-audits", headers=h, json={"branch_id": 1}); assert a.status_code == 200
        aid = a.json()["id"]
        assert c.post(f"/api/stock-audits/{aid}/scan", headers=h, json={"barcode": it["barcode"]}).status_code == 200
        close = c.post(f"/api/stock-audits/{aid}/close", headers=h, json={}); assert close.status_code == 200; assert close.json()["missing"] == []


def test_purchase_creates_tag_and_backup():
    with TestClient(app) as c:
        h = auth_headers(c)
        s = c.post("/api/suppliers", headers=h, json={"name": "Test Supplier", "phone": "123"}); assert s.status_code == 200
        p = c.post("/api/purchases", headers=h, json={"client_request_id": str(uuid.uuid4()), "supplier_id": s.json()["id"], "branch_id": 1, "paid": 1000, "items": [{"name": "Silver Chain", "category": "Chain", "metal": "Silver", "purity": "925", "gross_weight": 20, "stone_weight": 0, "net_weight": 20, "cost_amount": 1000}]}); assert p.status_code == 200, p.text
        rows = c.get("/api/items", headers=h, params={"q": "Silver Chain"}).json(); assert rows and rows[0]["status"] == "in_stock"
        b = c.post("/api/backups", headers=h, json={"label": "pytest"}); assert b.status_code == 200, b.text



def test_company_settings_are_generic_and_configurable():
    with TestClient(app) as c:
        h = auth_headers(c)
        before = c.get("/api/company", headers=h)
        assert before.status_code == 200, before.text
        company = before.json()
        assert company["settings"].get("business_name", "") != "Bijoria"
        assert (company.get("branch") or {}).get("name", "") != "Bijoria Main Showroom"

        saved = c.put("/api/company", headers=h, json={
            "business_name": "Test Jewellers",
            "branch_name": "Main Showroom",
            "business_state_code": "36",
            "business_state_name": "Telangana",
            "business_gstin": "",
            "business_address": "Test Address",
            "business_pincode": "500001",
            "business_phone": "0400000000",
            "business_email": "accounts@example.test",
            "counter_count": 3,
            "invoice_prefix": "INV",
            "tag_prefix": "TAG",
            "gst_default": "3",
            "business_timezone_offset_minutes": "330",
        })
        assert saved.status_code == 200, saved.text
        result = saved.json()
        assert result["configured"] is True
        assert result["settings"]["business_name"] == "Test Jewellers"
        assert result["settings"]["business_state_code"] == "36"
        assert result["branch"]["name"] == "Main Showroom"
        assert len(result["counters"]) == 3
