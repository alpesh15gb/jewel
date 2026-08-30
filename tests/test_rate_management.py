import os
import tempfile
from pathlib import Path

TEST_DIR = Path(tempfile.mkdtemp(prefix="jewellan-rates-test-"))
os.environ["JEWELLAN_DB"] = str(TEST_DIR / "rates.db")
os.environ["JEWELLAN_DATA_DIR"] = str(TEST_DIR)

from fastapi.testclient import TestClient
from jewel_server.main import app
from jewel_server.rate_management import install, parse_ibja_response

install(app)

TEST_ADMIN_PASSWORD = "JewelRates#1234"


def auth_headers(client):
    for password in (TEST_ADMIN_PASSWORD, "Jewel@123"):
        login = client.post("/api/auth/login", json={"username": "admin", "password": password, "client_name": "rate-tests"})
        if login.status_code != 200:
            continue
        data = login.json()
        headers = {"Authorization": f"Bearer {data['token']}"}
        if data["user"].get("must_change_password"):
            changed = client.post(
                "/api/auth/change-password",
                headers=headers,
                json={"old_password": password, "new_password": TEST_ADMIN_PASSWORD},
            )
            assert changed.status_code == 200, changed.text
        return headers
    raise AssertionError("Could not authenticate test administrator")


def test_ibja_parser_converts_source_units_to_rate_per_gram():
    parsed = parse_ibja_response(
        [
            {"RateDate": "30/08/2026", "RateTime": "6PM", "Purity": "999", "GoldRate": "159580", "SilverRate": "243892"},
            {"RateDate": "30/08/2026", "RateTime": "6PM", "Purity": "916", "GoldRate": "146173", "SilverRate": "243892"},
        ]
    )
    by_key = {(x["metal"], x["purity"]): x["rate_per_gram"] for x in parsed["rates"]}
    assert by_key[("Gold", "999")] == 15958.00
    assert by_key[("Gold", "916")] == 14617.30
    assert by_key[("Silver", "999")] == 243.89
    assert parsed["session"] == "6PM"


def test_rate_change_appends_history_and_changes_current_rate():
    with TestClient(app) as client:
        headers = auth_headers(client)
        first = client.post(
            "/api/rate-board/batch",
            headers=headers,
            json={"rates": [{"metal": "Gold", "purity": "916", "rate_per_gram": 14550}], "note": "opening"},
        )
        assert first.status_code == 200, first.text
        second = client.post(
            "/api/rate-board/batch",
            headers=headers,
            json={"rates": [{"metal": "Gold", "purity": "916", "rate_per_gram": 14625}], "note": "market moved"},
        )
        assert second.status_code == 200, second.text
        board = client.get("/api/rate-board", headers=headers)
        assert board.status_code == 200, board.text
        data = board.json()
        current = [x for x in data["current"] if x["metal"] == "Gold" and x["purity"] == "916"]
        history = [x for x in data["history"] if x["metal"] == "Gold" and x["purity"] == "916"]
        assert len(current) == 1
        assert current[0]["rate_per_gram"] == 14625
        assert len(history) >= 2
        assert history[0]["rate_per_gram"] == 14625
        assert history[1]["rate_per_gram"] == 14550


def test_reference_sync_does_not_change_shop_rate_until_explicit_apply(monkeypatch):
    import jewel_server.rate_management as rates

    with TestClient(app) as client:
        headers = auth_headers(client)
        client.post(
            "/api/rate-board/batch",
            headers=headers,
            json={"rates": [{"metal": "Gold", "purity": "999", "rate_per_gram": 15000}]},
        )
        saved = client.put(
            "/api/rate-board/provider",
            headers=headers,
            json={"provider": "ibja", "environment": "production", "access_token": "test-token"},
        )
        assert saved.status_code == 200, saved.text

        monkeypatch.setattr(
            rates,
            "_fetch_ibja",
            lambda token, environment, date_value: {
                "provider": "IBJA",
                "environment": environment,
                "rate_date": "30/08/2026",
                "session": "6PM",
                "fetched_at": "2026-08-30T12:30:00+00:00",
                "requested_business_date": date_value,
                "rates": [
                    {"metal": "Gold", "purity": "999", "rate_per_gram": 15958.00},
                    {"metal": "Gold", "purity": "916", "rate_per_gram": 14617.30},
                    {"metal": "Silver", "purity": "999", "rate_per_gram": 243.89},
                ],
            },
        )
        synced = client.post("/api/rate-board/sync", headers=headers, json={})
        assert synced.status_code == 200, synced.text
        assert synced.json()["applied"] is False
        board_before = client.get("/api/rate-board", headers=headers).json()
        current_999 = next(x for x in board_before["current"] if x["metal"] == "Gold" and x["purity"] == "999")
        assert current_999["rate_per_gram"] == 15000

        applied = client.post(
            "/api/rate-board/apply-reference",
            headers=headers,
            json={"gold_premium_per_gram": 2, "silver_premium_per_gram": 1, "round_to": 1},
        )
        assert applied.status_code == 200, applied.text
        board_after = client.get("/api/rate-board", headers=headers).json()
        gold_999 = next(x for x in board_after["current"] if x["metal"] == "Gold" and x["purity"] == "999")
        silver_999 = next(x for x in board_after["current"] if x["metal"] == "Silver" and x["purity"] == "999")
        assert gold_999["rate_per_gram"] == 15960
        assert silver_999["rate_per_gram"] == 245
