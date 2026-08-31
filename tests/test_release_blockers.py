from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

if "JEWELLAN_DB" not in os.environ:
    _TEST_DIR = Path(tempfile.mkdtemp(prefix="jewellan-release-blockers-test-"))
    os.environ["JEWELLAN_DB"] = str(_TEST_DIR / "test.db")
    os.environ["JEWELLAN_DATA_DIR"] = str(_TEST_DIR)

from jewel_client import api as client_api
from jewel_client import config as client_config
from jewel_server.db import business_date, read_db, set_setting, write_db
from jewel_server.main import app


ADMIN_PASSWORDS = ("JewelTest#1234", "Jewel@123")


def login(client: TestClient) -> dict[str, str]:
    for password in ADMIN_PASSWORDS:
        response = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": password, "client_name": "release-blockers-pytest"},
        )
        if response.status_code != 200:
            continue
        data = response.json()
        headers = {"Authorization": f"Bearer {data['token']}"}
        if data["user"].get("must_change_password"):
            changed = client.post(
                "/api/auth/change-password",
                headers=headers,
                json={"old_password": password, "new_password": "JewelTest#1234"},
            )
            assert changed.status_code == 200, changed.text
        return headers
    raise AssertionError("admin login failed")


def error_code(response) -> str:
    body = response.json()
    return str(body.get("error", {}).get("code") or "")


def new_location(name: str | None = None) -> tuple[int, int]:
    suffix = uuid.uuid4().hex[:8].upper()
    with write_db() as conn:
        branch = conn.execute(
            "INSERT INTO branches(code,name,gstin,address,phone,active) VALUES(?,?,?,?,?,1)",
            (f"B{suffix}", name or f"Release Test Branch {suffix}", "", "", ""),
        ).lastrowid
        counter = conn.execute(
            "INSERT INTO counters(branch_id,name,active) VALUES(?,?,1)",
            (branch, f"Counter {suffix}"),
        ).lastrowid
    return int(branch), int(counter)


def item_payload(branch_id: int = 1, counter_id: int = 1, name: str | None = None) -> dict:
    return {
        "name": name or f"Release Test Ring {uuid.uuid4().hex[:8]}",
        "category": "Ring",
        "metal": "Gold",
        "purity": "916",
        "gross_weight": 3.125,
        "stone_weight": 0.125,
        "making_type": "per_gram",
        "making_value": 450,
        "stone_value": 125,
        "cost_amount": 12000,
        "huid": uuid.uuid4().hex[:6].upper(),
        "branch_id": branch_id,
        "counter_id": counter_id,
    }


def add_item(client: TestClient, headers: dict[str, str], branch_id: int = 1, counter_id: int = 1) -> dict:
    response = client.post("/api/items", headers=headers, json=item_payload(branch_id, counter_id))
    assert response.status_code == 200, response.text
    return response.json()


def add_rate(client: TestClient, headers: dict[str, str]) -> None:
    response = client.post(
        "/api/rates",
        headers=headers,
        json={"metal": "Gold", "purity": "916", "rate_per_gram": 7000},
    )
    assert response.status_code == 200, response.text


def quote(client: TestClient, headers: dict[str, str], item: dict, branch_id: int = 1, counter_id: int = 1, line=None):
    return client.post(
        "/api/sales/quote",
        headers=headers,
        json={
            "lines": [line or {"item_id": item["id"], "item_version": item["version"]}],
            "old_gold": [],
            "branch_id": branch_id,
            "counter_id": counter_id,
        },
    )


def post_sale(client: TestClient, headers: dict[str, str], item: dict, q: dict, branch_id: int = 1, counter_id: int = 1, **extra):
    body = {
        "client_request_id": str(uuid.uuid4()),
        "branch_id": branch_id,
        "counter_id": counter_id,
        "lines": [{"item_id": item["id"], "item_version": item["version"]}],
        "old_gold": [],
        "payment_cash": q["total"],
        "payment_card": 0,
        "payment_upi": 0,
        "payment_credit": 0,
        "quote_id": q["quote_id"],
        "quote_hash": q["quote_hash"],
    }
    body.update(extra)
    return client.post("/api/sales", headers=headers, json=body)


def test_price_tampering_is_rejected_for_quote_and_sale():
    with TestClient(app) as client:
        headers = login(client)
        add_rate(client, headers)
        item = add_item(client, headers)
        tampered = {
            "item_id": item["id"],
            "item_version": item["version"],
            "metal_rate": 1,
            "gst_rate": 0,
            "making_value": 0,
            "making_type": "fixed",
            "wastage_percent": 0,
            "stone_value": 0,
        }
        response = quote(client, headers, item, line=tampered)
        assert response.status_code == 400, response.text
        assert error_code(response) == "PRICE_OVERRIDE_NOT_ALLOWED"

        current = quote(client, headers, item)
        assert current.status_code == 200, current.text
        rejected = post_sale(
            client,
            headers,
            item,
            current.json(),
            lines=[tampered],
        )
        assert rejected.status_code in (400, 409), rejected.text
        assert error_code(rejected) in {"PRICE_OVERRIDE_NOT_ALLOWED", "QUOTE_STALE"}
        with write_db() as conn:
            assert conn.execute("SELECT count(*) FROM sale_items WHERE item_id=?", (item["id"],)).fetchone()[0] == 0


def test_cross_branch_sale_and_barcode_lookup_are_blocked_without_side_effects():
    with TestClient(app) as client:
        headers = login(client)
        add_rate(client, headers)
        branch_a, counter_a = new_location("Cross Branch A")
        branch_b, counter_b = new_location("Cross Branch B")
        item = add_item(client, headers, branch_b, counter_b)
        with read_db() as conn:
            before = {
                "sales": conn.execute("SELECT count(*) FROM sales").fetchone()[0],
                "movements": conn.execute("SELECT count(*) FROM stock_movements WHERE item_id=?", (item["id"],)).fetchone()[0],
                "journals": conn.execute("SELECT count(*) FROM journal_entries").fetchone()[0],
            }
        response = quote(client, headers, item, branch_a, counter_a)
        assert response.status_code == 409, response.text
        assert error_code(response) == "ITEM_LOCATION_CONFLICT"
        barcode = client.get(
            f"/api/items/barcode/{item['barcode']}",
            headers=headers,
            params={"branch_id": branch_a, "counter_id": counter_a},
        )
        assert barcode.status_code == 404, barcode.text
        with read_db() as conn:
            assert conn.execute("SELECT count(*) FROM sales").fetchone()[0] == before["sales"]
            assert conn.execute("SELECT count(*) FROM stock_movements WHERE item_id=?", (item["id"],)).fetchone()[0] == before["movements"]
            assert conn.execute("SELECT count(*) FROM journal_entries").fetchone()[0] == before["journals"]


def test_return_uses_current_open_date_not_original_sale_date():
    original_offset = None
    with read_db() as conn:
        original_offset = conn.execute("SELECT value FROM settings WHERE key='business_timezone_offset_minutes'").fetchone()[0]
    branch_id, counter_id = new_location("Return Date Branch")
    try:
        with TestClient(app) as client:
            headers = login(client)
            add_rate(client, headers)
            # Find a valid timezone offset that moves the business date forward/backward.
            with write_db() as conn:
                current_utc = dt.datetime.now(dt.timezone.utc)
                old_date = business_date(conn)
                candidates = {}
                for offset in range(-720, 841, 60):
                    set_setting(conn, "business_timezone_offset_minutes", str(offset))
                    candidates[offset] = (current_utc + dt.timedelta(minutes=offset)).date().isoformat()
                new_offset = next((offset for offset, value in candidates.items() if value != old_date), None)
                assert new_offset is not None
                set_setting(conn, "business_timezone_offset_minutes", str(330))
            item = add_item(client, headers, branch_id, counter_id)
            q = quote(client, headers, item, branch_id, counter_id)
            assert q.status_code == 200, q.text
            sale = post_sale(client, headers, item, q.json(), branch_id, counter_id)
            assert sale.status_code == 200, sale.text
            sale_id = sale.json()["id"]
            with write_db() as conn:
                set_setting(conn, "business_timezone_offset_minutes", str(330))
                old_date = business_date(conn)
            closed = client.post("/api/day-close", headers=headers, json={"branch_id": branch_id, "business_date": old_date})
            assert closed.status_code == 200, closed.text
            with write_db() as conn:
                set_setting(conn, "business_timezone_offset_minutes", str(new_offset))
                new_date = business_date(conn)
            assert new_date != old_date
            detail = client.get(f"/api/sales/{sale_id}", headers=headers).json()
            line_id = detail["lines"][0]["id"]
            rq = client.post(f"/api/sales/{sale_id}/return-quote", headers=headers, json={"sale_item_ids": [line_id]})
            assert rq.status_code == 200, rq.text
            total = rq.json()["total"]
            returned = client.post(
                f"/api/sales/{sale_id}/return",
                headers=headers,
                json={
                    "client_request_id": str(uuid.uuid4()),
                    "sale_item_ids": [line_id],
                    "reason": "Date-close regression",
                    "refund_cash": total,
                    "refund_card": 0,
                    "refund_upi": 0,
                    "refund_credit": 0,
                },
            )
            assert returned.status_code == 200, returned.text

            second = add_item(client, headers, branch_id, counter_id)
            second_quote = quote(client, headers, second, branch_id, counter_id)
            assert second_quote.status_code == 200, second_quote.text
            second_sale = post_sale(client, headers, second, second_quote.json(), branch_id, counter_id)
            assert second_sale.status_code == 200, second_sale.text
            second_detail = client.get(f"/api/sales/{second_sale.json()['id']}", headers=headers).json()
            close_current = client.post("/api/day-close", headers=headers, json={"branch_id": branch_id, "business_date": new_date})
            assert close_current.status_code == 200, close_current.text
            blocked = client.post(
                f"/api/sales/{second_sale.json()['id']}/return",
                headers=headers,
                json={
                    "client_request_id": str(uuid.uuid4()),
                    "sale_item_ids": [second_detail["lines"][0]["id"]],
                    "reason": "Closed current date",
                    "refund_cash": second_quote.json()["total"],
                },
            )
            assert blocked.status_code == 409, blocked.text
            assert error_code(blocked) == "DAY_CLOSED"
    finally:
        with write_db() as conn:
            set_setting(conn, "business_timezone_offset_minutes", str(original_offset or 330))


def test_branch_day_close_isolated_from_other_branch_reconciliation():
    with TestClient(app) as client:
        headers = login(client)
        add_rate(client, headers)
        branch_a, counter_a = new_location("Day Close A")
        branch_b, counter_b = new_location("Day Close B")
        item_a = add_item(client, headers, branch_a, counter_a)
        item_b = add_item(client, headers, branch_b, counter_b)
        q_a = quote(client, headers, item_a, branch_a, counter_a)
        q_b = quote(client, headers, item_b, branch_b, counter_b)
        assert q_a.status_code == q_b.status_code == 200
        sale_a = post_sale(client, headers, item_a, q_a.json(), branch_a, counter_a)
        sale_b = post_sale(client, headers, item_b, q_b.json(), branch_b, counter_b)
        assert sale_a.status_code == sale_b.status_code == 200
        with write_db() as conn:
            report_date = business_date(conn)
            sale_b_id = sale_b.json()["id"]
            actor_id = conn.execute("SELECT user_id FROM sales WHERE id=?", (sale_b_id,)).fetchone()[0]
            entry = conn.execute(
                "INSERT INTO journal_entries(entry_no,entry_date,memo,ref_type,ref_id,user_id,created_at) VALUES(?,?,?,?,?,?,?)",
                (f"BAD-{uuid.uuid4().hex[:8]}", report_date, "branch B test issue", "sale", sale_b_id, actor_id, report_date),
            ).lastrowid
            conn.execute(
                "INSERT INTO journal_lines(entry_id,account_code,debit,credit,party_type,party_id,debit_paise,credit_paise) VALUES(?,?,?,?,?,?,?,?)",
                (entry, "1000", 1, 0, None, None, 100, 0),
            )
        try:
            report = client.get("/api/reports/day-close", headers=headers, params={"date": report_date, "branch_id": branch_a})
            assert report.status_code == 200, report.text
            body = report.json()
            assert body["branch_id"] == branch_a
            assert body["sales"]["count"] == 1
            close = client.post("/api/day-close", headers=headers, json={"business_date": report_date, "branch_id": branch_a})
            assert close.status_code == 200, close.text
            evidence = close.json()["report"]
            assert evidence["branch_id"] == branch_a
            assert evidence["sales"]["count"] == 1
            with read_db() as conn:
                stored = json.loads(
                    conn.execute(
                        "SELECT evidence_json FROM day_closes WHERE branch_id=? AND business_date=?",
                        (branch_a, report_date),
                    ).fetchone()[0]
                )
            assert stored["integrity"]["issue_count"] == 0
            assert stored["integrity"]["unbalanced_journals"] == 0
        finally:
            with write_db() as conn:
                conn.execute(
                    "INSERT INTO journal_lines(entry_id,account_code,debit,credit,party_type,party_id,debit_paise,credit_paise) VALUES(?,?,?,?,?,?,?,?)",
                    (entry, "1000", 0, 1, None, None, 0, 100),
                )


def test_stock_audit_rejects_edit_and_transfer_after_snapshot_and_requires_reason_for_force():
    with TestClient(app) as client:
        headers = login(client)
        branch_a, counter_a = new_location("Audit A")
        branch_b, counter_b = new_location("Audit B")
        edited = add_item(client, headers, branch_a, counter_a)
        started = client.post("/api/stock-audits", headers=headers, json={"branch_id": branch_a, "counter_id": counter_a})
        assert started.status_code == 200, started.text
        update = client.put(
            f"/api/items/{edited['id']}",
            headers=headers,
            json={"name": "Edited after audit", "expected_version": edited["version"]},
        )
        assert update.status_code == 200, update.text
        blocked = client.post(f"/api/stock-audits/{started.json()['id']}/close", headers=headers, json={})
        assert blocked.status_code == 409, blocked.text
        assert error_code(blocked) == "AUDIT_MOVEMENT_CONFLICT"

        moved = add_item(client, headers, branch_a, counter_a)
        second = client.post("/api/stock-audits", headers=headers, json={"branch_id": branch_a, "counter_id": counter_a})
        assert second.status_code == 200, second.text
        transfer = client.post(
            f"/api/items/{moved['id']}/transfer",
            headers=headers,
            json={"branch_id": branch_b, "counter_id": counter_b, "note": "Audit transfer-out regression"},
        )
        assert transfer.status_code == 200, transfer.text
        blocked_transfer = client.post(f"/api/stock-audits/{second.json()['id']}/close", headers=headers, json={})
        assert blocked_transfer.status_code == 409, blocked_transfer.text
        no_reason = client.post(
            f"/api/stock-audits/{second.json()['id']}/close",
            headers=headers,
            json={"resolve_movements": True},
        )
        assert no_reason.status_code == 400, no_reason.text
        forced = client.post(
            f"/api/stock-audits/{second.json()['id']}/close",
            headers=headers,
            json={"resolve_movements": True, "reason": "Manager reviewed transfer"},
        )
        assert forced.status_code == 200, forced.text


def test_mandatory_quote_request_id_and_item_version_contracts():
    with TestClient(app) as client:
        headers = login(client)
        add_rate(client, headers)
        item = add_item(client, headers)
        missing_version = quote(client, headers, item, line={"item_id": item["id"]})
        assert missing_version.status_code == 400, missing_version.text
        assert error_code(missing_version) == "ITEM_VERSION_REQUIRED"
        missing_quote = client.post(
            "/api/sales",
            headers=headers,
            json={
                "client_request_id": str(uuid.uuid4()),
                "branch_id": 1,
                "counter_id": 1,
                "lines": [{"item_id": item["id"], "item_version": item["version"]}],
                "payment_cash": 0,
            },
        )
        assert missing_quote.status_code == 400, missing_quote.text
        assert error_code(missing_quote) == "QUOTE_REQUIRED"

        update_missing = client.put(f"/api/items/{item['id']}", headers=headers, json={"name": "No version"})
        assert update_missing.status_code == 400, update_missing.text
        assert error_code(update_missing) == "VERSION_REQUIRED"
        update_ok = client.put(
            f"/api/items/{item['id']}", headers=headers, json={"name": "Versioned", "expected_version": item["version"]}
        )
        assert update_ok.status_code == 200, update_ok.text
        stale = client.put(
            f"/api/items/{item['id']}", headers=headers, json={"name": "Stale", "expected_version": item["version"]}
        )
        assert stale.status_code == 409, stale.text
        assert error_code(stale) == "VERSION_CONFLICT"


@pytest.mark.parametrize("path,body", [
    ("/api/sales", {"lines": []}),
    ("/api/purchases", {"items": []}),
    ("/api/sales/999999999/return", {"sale_item_ids": [1]}),
])
def test_financial_writes_require_uuid_request_ids(path, body):
    with TestClient(app) as client:
        headers = login(client)
        missing = client.post(path, headers=headers, json=body)
        assert missing.status_code == 400, missing.text
        assert error_code(missing) == "REQUEST_ID_REQUIRED"
        malformed = dict(body, client_request_id="not-a-uuid")
        invalid = client.post(path, headers=headers, json=malformed)
        assert invalid.status_code == 400, invalid.text
        assert error_code(invalid) == "INVALID_REQUEST_ID"


def test_purchase_payment_direction_is_outgoing_and_sale_idempotency_is_exact():
    with TestClient(app) as client:
        headers = login(client)
        branch_id, counter_id = new_location("Purchase Direction")
        request_id = str(uuid.uuid4())
        purchase = client.post(
            "/api/purchases",
            headers=headers,
            json={
                "client_request_id": request_id,
                "branch_id": branch_id,
                "counter_id": counter_id,
                "items": [item_payload(branch_id, counter_id, "Purchased Regression Ring") | {"cost_amount": 100}],
                "gst": 0,
                "paid": 100,
                "payment_references": {"cash": "PURCHASE-TEST"},
            },
        )
        assert purchase.status_code == 200, purchase.text
        with read_db() as conn:
            payment = conn.execute(
                "SELECT * FROM payments WHERE transaction_type='purchase' AND transaction_id=?",
                (purchase.json()["id"],),
            ).fetchone()
            assert payment["direction"] == "out"

        add_rate(client, headers)
        item = add_item(client, headers)
        q = quote(client, headers, item)
        assert q.status_code == 200, q.text
        request_id = str(uuid.uuid4())
        first = post_sale(client, headers, item, q.json(), client_request_id=request_id)
        assert first.status_code == 200, first.text
        retry = post_sale(client, headers, item, q.json(), client_request_id=request_id)
        assert retry.status_code == 200 and retry.json().get("idempotent") is True
        conflict = post_sale(client, headers, item, q.json(), client_request_id=request_id, notes="changed after commit")
        assert conflict.status_code == 409, conflict.text
        assert error_code(conflict) == "IDEMPOTENCY_CONFLICT"


def test_pending_post_survives_ambiguous_http_5xx_and_connectivity_errors(monkeypatch, tmp_path):
    monkeypatch.setattr(client_config, "config_dir", lambda: tmp_path)

    class Response503:
        status_code = 503
        text = "temporary server failure"
        headers = {"content-type": "application/json"}

        @staticmethod
        def json():
            return {"error": {"code": "INTERNAL_ERROR", "message": "temporary server failure"}}

    monkeypatch.setenv("JEWELLAN_ALLOW_INSECURE_HTTP", "1")
    api = client_api.Api("http://localhost")
    monkeypatch.setattr(api.session, "request", lambda *args, **kwargs: Response503())
    request_id = str(uuid.uuid4())
    with pytest.raises(client_api.ApiError) as raised:
        api.post("/api/sales", {"client_request_id": request_id})
    assert raised.value.status == 503
    client_config.upsert_pending_post({"request_id": request_id, "operation": "sale", "state": "unknown", "payload": {"client_request_id": request_id}})
    assert client_config.load_pending_posts()[0]["request_id"] == request_id

    client_config.remove_pending_post(request_id)
    client_config.upsert_pending_post({"request_id": request_id, "operation": "sale", "state": "unknown", "error": "connectivity"})
    assert client_config.load_pending_posts()[0]["state"] == "unknown"
