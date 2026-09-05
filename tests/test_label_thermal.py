from jewel_server.label_printer import bulk_tspl, bulk_zpl, tspl_label, zpl_label

ITEM = {"tag_no":"TAG-0000001","barcode":"TAG-0000001","metal":"Gold","purity":"916","gross_weight":4.0,"net_weight":3.765,"huid":"ABC123"}
SET = {"business_name":"Madan Jewellers","label_width_mm":"60","label_height_mm":"30"}

def test_zpl_has_xa_xz_barcode_qr():
    z = zpl_label(ITEM, SET)
    assert z.startswith("^XA") and z.strip().endswith("^XZ")
    assert "^BCN" in z and "TAG-0000001" in z and "HUID ABC123" in z
    assert "^BQN" in z  # tall stock gets QR

def test_zpl_short_label_skips_qr():
    z = zpl_label(ITEM, {"business_name":"X","label_width_mm":"60","label_height_mm":"25"})
    assert "^BCN" in z and "^BQN" not in z

def test_tspl_has_size_barcode_qr():
    t = tspl_label(ITEM, SET)
    assert "SIZE 60 mm,30 mm" in t and 'BARCODE' in t and '"128"' in t
    assert "QRCODE" in t and "PRINT 1" in t

def test_bulk_counts():
    items = [dict(ITEM, tag_no=f"TAG-{i:07d}", barcode=f"TAG-{i:07d}") for i in range(3)]
    assert bulk_zpl(items, SET).count("^XA") == 3
    assert bulk_tspl(items, SET).count("PRINT 1") == 3

def test_thermal_endpoints():
    import os, tempfile
    from pathlib import Path
    if "JEWELLAN_DB" not in os.environ:
        td = Path(tempfile.mkdtemp(prefix="lbl-")); os.environ["JEWELLAN_DB"] = str(td/"t.db"); os.environ["JEWELLAN_DATA_DIR"] = str(td)
    from fastapi.testclient import TestClient
    from jewel_server.main import app
    with TestClient(app) as c:
        for p in ("JewelTest#1234","Jewel@123"):
            r = c.post("/api/auth/login", json={"username":"admin","password":p,"client_name":"lbl"})
            if r.status_code != 200: continue
            h = {"Authorization": f"Bearer {r.json()['token']}"}
            if r.json()["user"].get("must_change_password"):
                c.post("/api/auth/change-password", headers=h, json={"old_password":p,"new_password":"JewelTest#1234"})
                r = c.post("/api/auth/login", json={"username":"admin","password":"JewelTest#1234","client_name":"lbl"})
                h = {"Authorization": f"Bearer {r.json()['token']}"}
            it = c.post("/api/items", headers=h, json={"name":"Lbl","category":"Ring","metal":"Gold","purity":"916","gross_weight":2,"stone_weight":0,"branch_id":1}).json()
            assert c.get(f"/api/items/{it['id']}/label.zpl", headers=h).status_code == 200
            assert c.get(f"/api/items/{it['id']}/label.tspl", headers=h).status_code == 200
            b = c.post("/api/items/labels.zpl", headers=h, json={"item_ids":[it["id"]]})
            assert b.status_code == 200 and "^XA" in b.text
            return
        raise AssertionError("login failed")
