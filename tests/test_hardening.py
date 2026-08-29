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
from jewel_server.db import read_db, write_db
from jewel_server.main import app
from jewel_server.precision import money, weight
from jewel_server.services import create_item, post_sale


def login(client, username="admin", password="Jewel@123"):
    r = client.post(
        "/api/auth/login",
        json={"username": username, "password": password, "client_name": "hardening-pytest"},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()["user"]


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
            "/api/sales/quote", headers=headers, json={"lines": [{"item_id": item["id"]}], "old_gold": []}
        ).json()
        sale = client.post(
            "/api/sales",
            headers=headers,
            json={
                "client_request_id": str(uuid.uuid4()),
                "branch_id": 1,
                "counter_id": 1,
                "lines": [{"item_id": item["id"]}],
                "old_gold": [],
                "payment_cash": quote["total"],
                "payment_card": 0,
                "payment_upi": 0,
                "payment_credit": 0,
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
            "/api/sales/quote", headers=headers, json={"lines": [{"item_id": item["id"]}], "old_gold": []}
        ).json()

    barrier = threading.Barrier(2)
    results = []
    lock = threading.Lock()

    def worker(counter_name):
        payload = {
            "client_request_id": str(uuid.uuid4()),
            "branch_id": 1,
            "counter_id": 1,
            "lines": [{"item_id": item["id"]}],
            "old_gold": [],
            "payment_cash": quote["total"],
            "payment_card": 0,
            "payment_upi": 0,
            "payment_credit": 0,
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

        close = client.get("/api/reports/day-close", headers=headers)
        assert close.status_code == 200, close.text
        close_body = close.json()
        assert close_body["journal"]["balanced"] is True
        assert close_body["sales"]["payments_match_sales"] is True
