import datetime as dt
import os
import shutil
import sqlite3
import tempfile
import threading
import uuid
from pathlib import Path

import pytest

# Allows this file to run by itself while remaining compatible with test_core,
# which normally establishes the shared isolated test database first.
if "JEWELLAN_DB" not in os.environ:
    _TEST_DIR = Path(tempfile.mkdtemp(prefix="jewellan-hardening-test-"))
    os.environ["JEWELLAN_DB"] = str(_TEST_DIR / "test.db")
    os.environ["JEWELLAN_DATA_DIR"] = str(_TEST_DIR)

from fastapi import HTTPException
from fastapi.testclient import TestClient

from jewel_server.audit_chain import verify_audit_chain
from jewel_server.backup import create_backup, verify_backup
from jewel_server.canonical import canonical_integrity
from jewel_server.db import business_date, read_db, set_setting, write_db
from jewel_server.main import app
from jewel_server.precision import money, money_paise, weight, weight_mg
from jewel_server.services import post_sale

TEST_ADMIN_PASSWORD = "JewelTest#1234"


def login(client, username="admin", password="Jewel@123"):
    candidates = [password]
    if username == "admin" and TEST_ADMIN_PASSWORD not in candidates:
        candidates.insert(0, TEST_ADMIN_PASSWORD)
    last = None
    for candidate in candidates:
        r = client.post(
            "/api/auth/login",
            json={"username": username, "password": candidate, "client_name": "hardening-pytest"},
        )
        last = r
        if r.status_code != 200:
            continue
        payload = r.json()
        headers = {"Authorization": f"Bearer {payload['token']}"}
        user = payload["user"]
        if user.get("must_change_password"):
            new_password = TEST_ADMIN_PASSWORD if username == "admin" else candidate + "!Changed"
            changed = client.post(
                "/api/auth/change-password",
                headers=headers,
                json={"old_password": candidate, "new_password": new_password},
            )
            assert changed.status_code == 200, changed.text
            user["must_change_password"] = 0
        return headers, user
    assert last is not None and last.status_code == 200, last.text if last is not None else "login failed"


def add_rate(client, headers, metal="Gold", purity="916", rate=6000):
    r = client.post(
        "/api/rates",
        headers=headers,
        json={"metal": metal, "purity": purity, "rate_per_gram": rate},
    )
    assert r.status_code == 200, r.text


def unique_huid():
    # exactly six uppercase alphanumeric characters
    return uuid.uuid4().hex[:6].upper()


def make_item_payload(**overrides):
    data = {
        "name": "Hardening Ring",
        "category": "Ring",
        "metal": "Gold",
        "purity": "916",
        "gross_weight": 5.125,
        "stone_weight": 0.125,
        "making_type": "per_gram",
        "making_value": 500,
        "stone_value": 250,
        "cost_amount": 20000,
        "huid": unique_huid(),
        "branch_id": 1,
        "counter_id": 1,
    }
    data.update(overrides)
    return data


def test_decimal_rounding_is_half_up_and_deterministic():
    assert money("1.005") == 1.01
    assert money("2.675") == 2.68
    assert weight("1.2345") == 1.235
    assert weight("0.0005") == 0.001


def test_password_change_is_enforced_server_side_before_operational_access():
    with TestClient(app) as client:
        admin_headers, _ = login(client)
        suffix = uuid.uuid4().hex[:6]
        username = f"cash{suffix}"
        temporary = "Cashier#1234"
        made = client.post(
            "/api/users",
            headers=admin_headers,
            json={"username": username, "full_name": "Password Gate Cashier", "role": "cashier", "password": temporary},
        )
        assert made.status_code == 200, made.text

        raw = client.post("/api/auth/login", json={"username": username, "password": temporary, "client_name": "gate-test"})
        assert raw.status_code == 200, raw.text
        token_headers = {"Authorization": f"Bearer {raw.json()['token']}"}
        assert raw.json()["user"]["must_change_password"] == 1
        blocked = client.get("/api/dashboard", headers=token_headers)
        assert blocked.status_code == 428, blocked.text

        changed = client.post(
            "/api/auth/change-password",
            headers=token_headers,
            json={"old_password": temporary, "new_password": "Cashier#12345New"},
        )
        assert changed.status_code == 200, changed.text
        allowed = client.get("/api/dashboard", headers=token_headers)
        assert allowed.status_code == 200, allowed.text


def test_weight_auto_calculation_huid_format_and_duplicate_protection():
    with TestClient(app) as client:
        headers, _ = login(client)
        huid = unique_huid().lower()
        created = client.post("/api/items", headers=headers, json=make_item_payload(huid=huid))
        assert created.status_code == 200, created.text
        item = created.json()
        assert item["net_weight"] == 5.0
        assert item["huid"] == huid.upper()

        impossible = client.post(
            "/api/items",
            headers=headers,
            json=make_item_payload(gross_weight=1.0, stone_weight=1.1),
        )
        assert impossible.status_code == 400

        mismatch = client.post(
            "/api/items",
            headers=headers,
            json=make_item_payload(net_weight=4.0),
        )
        assert mismatch.status_code == 400
        assert "gross minus stone" in mismatch.text.lower()

        bad_huid = client.post("/api/items", headers=headers, json=make_item_payload(huid="123"))
        assert bad_huid.status_code == 400

        duplicate = client.post("/api/items", headers=headers, json=make_item_payload(huid=huid.upper()))
        assert duplicate.status_code == 409


def test_canonical_paise_and_milligram_storage_is_populated_and_guarded():
    with TestClient(app) as client:
        headers, _ = login(client)
        add_rate(client, headers, rate="6000.005")
        made = client.post(
            "/api/items",
            headers=headers,
            json=make_item_payload(gross_weight="5.125", stone_weight="0.125", stone_value="250.005", cost_amount="20000.005"),
        )
        assert made.status_code == 200, made.text
        item = made.json()

        with read_db() as conn:
            row = conn.execute("SELECT * FROM items WHERE id=?", (item["id"],)).fetchone()
            assert row["gross_mg"] == weight_mg(row["gross_weight"]) == 5125
            assert row["stone_mg"] == 125
            assert row["net_mg"] == 5000
            assert row["stone_value_paise"] == money_paise(row["stone_value"])
            assert row["cost_amount_paise"] == money_paise(row["cost_amount"])
            assert canonical_integrity(conn)["ok"] is True

        with pytest.raises(sqlite3.DatabaseError):
            with write_db() as conn:
                # Direct legacy-value mutation without its canonical mirror must be rejected.
                conn.execute("UPDATE items SET cost_amount=cost_amount+1 WHERE id=?", (item["id"],))

        quote = client.post(
            "/api/sales/quote",
            headers=headers,
            json={"lines": [{"item_id": item["id"], "item_version": item["version"]}], "old_gold": [], "branch_id": 1, "counter_id": 1},
        )
        assert quote.status_code == 200, quote.text
        sale = client.post(
            "/api/sales",
            headers=headers,
            json={
                "client_request_id": str(uuid.uuid4()),
                "branch_id": 1,
                "counter_id": 1,
                "lines": [{"item_id": item["id"], "item_version": item["version"]}],
                "old_gold": [],
                "payment_cash": quote.json()["total"],
                "payment_card": 0,
                "payment_upi": 0,
                "payment_credit": 0,
                "quote_id": quote.json()["quote_id"],
                "quote_hash": quote.json()["quote_hash"],
            },
        )
        assert sale.status_code == 200, sale.text
        with read_db() as conn:
            s = conn.execute("SELECT * FROM sales WHERE id=?", (sale.json()["id"],)).fetchone()
            assert s["total_paise"] == money_paise(s["total"])
            assert s["payment_cash_paise"] == s["total_paise"]
            line = conn.execute("SELECT * FROM sale_items WHERE sale_id=?", (s["id"],)).fetchone()
            assert line["line_total_paise"] == money_paise(line["line_total"])
            assert line["gross_mg"] == weight_mg(line["gross_weight"])
            assert canonical_integrity(conn)["ok"] is True


def test_business_timezone_drives_business_date():
    with write_db() as conn:
        set_setting(conn, "business_timezone_offset_minutes", "840")
    try:
        with read_db() as conn:
            got = business_date(conn)
        expected = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=840)).date().isoformat()
        assert got == expected
    finally:
        with write_db() as conn:
            set_setting(conn, "business_timezone_offset_minutes", "330")


def test_manager_net_weight_override_requires_reason_and_is_audited():
    with TestClient(app) as client:
        admin_headers, _ = login(client)
        suffix = uuid.uuid4().hex[:6]
        username = f"mgr{suffix}"
        password = "Manager#1234"
        r = client.post(
            "/api/users",
            headers=admin_headers,
            json={"username": username, "full_name": "Weight Manager", "role": "manager", "password": password},
        )
        assert r.status_code == 200, r.text
        manager_headers, _ = login(client, username, password)

        denied = client.post(
            "/api/items",
            headers=manager_headers,
            json=make_item_payload(net_weight=4.8, allow_net_weight_override=True),
        )
        assert denied.status_code == 400

        accepted = client.post(
            "/api/items",
            headers=manager_headers,
            json=make_item_payload(
                net_weight=4.8,
                allow_net_weight_override=True,
                net_weight_override_reason="documented loose-stone exception",
            ),
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["net_weight"] == 4.8
        assert accepted.json()["net_weight_override_reason"] == "documented loose-stone exception"

        with read_db() as conn:
            row = conn.execute(
                "SELECT details_json FROM audit_log WHERE entity='item' AND entity_id=? ORDER BY id DESC LIMIT 1",
                (str(accepted.json()["id"]),),
            ).fetchone()
            assert row and "documented loose-stone exception" in row["details_json"]


def test_audit_chain_is_valid_and_database_rejects_audit_mutation():
    with TestClient(app) as client:
        headers, _ = login(client)
        client.post("/api/items", headers=headers, json=make_item_payload())

    with read_db() as conn:
        chain = verify_audit_chain(conn)
        assert chain["ok"], chain
        audit_id = conn.execute("SELECT id FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()[0]

    with pytest.raises(sqlite3.DatabaseError):
        with write_db() as conn:
            conn.execute("UPDATE audit_log SET action='tampered' WHERE id=?", (audit_id,))
    with pytest.raises(sqlite3.DatabaseError):
        with write_db() as conn:
            conn.execute("DELETE FROM audit_log WHERE id=?", (audit_id,))


def test_posted_sale_lines_and_journals_are_immutable():
    with TestClient(app) as client:
        headers, _ = login(client)
        add_rate(client, headers)
        item = client.post("/api/items", headers=headers, json=make_item_payload()).json()
        quote = client.post(
            "/api/sales/quote",
            headers=headers,
            json={"lines": [{"item_id": item["id"], "item_version": item["version"]}], "old_gold": [], "branch_id": 1, "counter_id": 1},
        ).json()
        sale = client.post(
            "/api/sales",
            headers=headers,
            json={
                "client_request_id": str(uuid.uuid4()),
                "branch_id": 1,
                "counter_id": 1,
                "lines": [{"item_id": item["id"], "item_version": item["version"]}],
                "old_gold": [],
                "payment_cash": quote["total"],
                "payment_card": 0,
                "payment_upi": 0,
                "payment_credit": 0,
                "quote_id": quote["quote_id"],
                "quote_hash": quote["quote_hash"],
            },
        )
        assert sale.status_code == 200, sale.text
        sale_id = sale.json()["id"]

    with read_db() as conn:
        line_id = conn.execute("SELECT id FROM sale_items WHERE sale_id=?", (sale_id,)).fetchone()[0]
        journal_id = conn.execute(
            "SELECT id FROM journal_entries WHERE ref_type='sale' AND ref_id=?", (sale_id,)
        ).fetchone()[0]
        journal_line_id = conn.execute("SELECT id FROM journal_lines WHERE entry_id=? LIMIT 1", (journal_id,)).fetchone()[0]

    for sql, args in (
        ("UPDATE sale_items SET line_total=line_total+1 WHERE id=?", (line_id,)),
        ("DELETE FROM sale_items WHERE id=?", (line_id,)),
        ("UPDATE journal_entries SET memo='changed' WHERE id=?", (journal_id,)),
        ("UPDATE journal_lines SET debit=debit+1 WHERE id=?", (journal_line_id,)),
    ):
        with pytest.raises(sqlite3.DatabaseError):
            with write_db() as conn:
                conn.execute(sql, args)


def test_two_counter_sale_attempts_cannot_sell_same_tag_twice():
    with TestClient(app) as client:
        headers, user = login(client)
        add_rate(client, headers)
        item = client.post("/api/items", headers=headers, json=make_item_payload()).json()
        quote = client.post(
            "/api/sales/quote",
            headers=headers,
            json={"lines": [{"item_id": item["id"], "item_version": item["version"]}], "old_gold": [], "branch_id": 1, "counter_id": 1},
        ).json()

    barrier = threading.Barrier(2)
    results = []
    lock = threading.Lock()

    def worker(counter_name):
        payload = {
            "client_request_id": str(uuid.uuid4()),
            "branch_id": 1,
            "counter_id": 1,
            "lines": [{"item_id": item["id"], "item_version": item["version"]}],
            "old_gold": [],
            "payment_cash": quote["total"],
            "payment_card": 0,
            "payment_upi": 0,
            "payment_credit": 0,
            "quote_id": quote["quote_id"],
            "quote_hash": quote["quote_hash"],
            "notes": counter_name,
        }
        barrier.wait()
        try:
            with write_db() as conn:
                result = post_sale(conn, payload, user, "127.0.0.1")
            outcome = ("ok", result["id"])
        except HTTPException as exc:
            outcome = ("http", exc.status_code)
        except Exception as exc:  # captured so the assertion reports unexpected failures clearly
            outcome = ("error", type(exc).__name__, str(exc))
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=worker, args=(f"counter-{n}",)) for n in (1, 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert all(not thread.is_alive() for thread in threads)
    assert sum(1 for result in results if result[0] == "ok") == 1, results
    assert sum(1 for result in results if result[:2] == ("http", 409)) == 1, results
    with read_db() as conn:
        posted = conn.execute(
            "SELECT count(*) FROM sale_items si JOIN sales s ON s.id=si.sale_id WHERE si.item_id=? AND s.status='posted'",
            (item["id"],),
        ).fetchone()[0]
        assert posted == 1


def test_verified_backup_manifest_and_corruption_detection():
    backup = create_backup("hardening-test")
    verified = verify_backup(backup)
    assert verified["ok"], verified
    assert verified["checksum_verified"] is True
    assert verified["sha256"]
    assert backup.with_suffix(backup.suffix + ".manifest.json").exists()

    corrupted = backup.with_name(backup.stem + "-corrupt.db")
    shutil.copy2(backup, corrupted)
    with corrupted.open("r+b") as f:
        f.seek(0)
        f.write(b"NOTASQLITEDATABASE")
        f.flush()
    with pytest.raises(sqlite3.DatabaseError):
        verify_backup(corrupted)


def test_last_active_admin_cannot_be_demoted_or_disabled():
    with TestClient(app) as client:
        headers, user = login(client)
        demote = client.put(
            f"/api/users/{user['id']}", headers=headers, json={"full_name": "Administrator", "role": "manager"}
        )
        assert demote.status_code == 400
        disable = client.put(
            f"/api/users/{user['id']}", headers=headers, json={"full_name": "Administrator", "active": False}
        )
        assert disable.status_code == 400


def test_login_failures_are_throttled():
    with TestClient(app) as client:
        username = "missing-" + uuid.uuid4().hex[:10]
        for _ in range(5):
            r = client.post("/api/auth/login", json={"username": username, "password": "wrong-password"})
            assert r.status_code == 401, r.text
        locked = client.post("/api/auth/login", json={"username": username, "password": "wrong-password"})
        assert locked.status_code == 429, locked.text
        assert int(locked.headers["Retry-After"]) > 0


def test_integrity_report_and_day_close_are_clean_after_valid_transactions():
    with TestClient(app) as client:
        headers, _ = login(client)
        integrity = client.get("/api/integrity", headers=headers)
        assert integrity.status_code == 200, integrity.text
        body = integrity.json()
        assert body["sqlite_quick_check"] == ["ok"]
        assert body["foreign_key_violations"] == 0
        assert body["unbalanced_journals"] == 0
        assert body["audit_chain"]["ok"] is True
        assert body["canonical"]["ok"] is True
        assert body["canonical"]["mismatches"] == 0

        close = client.get("/api/reports/day-close", headers=headers)
        assert close.status_code == 200, close.text
        close_body = close.json()
        assert close_body["journal"]["balanced"] is True
        assert close_body["sales"]["payments_match_sales"] is True
