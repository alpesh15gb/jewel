import sqlite3

import pytest
from fastapi import HTTPException

from jewel_server import rate_management as rm


def rate_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE metal_rates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        metal TEXT NOT NULL,
        purity TEXT NOT NULL,
        rate_per_gram REAL NOT NULL,
        effective_at TEXT NOT NULL,
        created_by INTEGER,
        rate_paise_per_gram INTEGER
        )"""
    )
    conn.execute("CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL,updated_at TEXT NOT NULL)")
    conn.execute("INSERT INTO settings VALUES('business_timezone_offset_minutes','330','2026-08-30T00:00:00+00:00')")
    return conn


def add_rate(conn, metal, purity, rate, effective_at):
    conn.execute(
        "INSERT INTO metal_rates(metal,purity,rate_per_gram,effective_at,created_by,rate_paise_per_gram) VALUES(?,?,?,?,1,?)",
        (metal, purity, rate, effective_at, round(rate * 100)),
    )


def test_newer_base_rate_beats_stale_exact_purity_rate():
    conn = rate_db()
    add_rate(conn, "Gold", "916", 6000, "2026-08-29T04:00:00+00:00")
    add_rate(conn, "Gold", "999", 7000, "2026-08-30T04:00:00+00:00")

    row = rm.resolve_rate_row(conn, "Gold", "916")

    assert row is not None
    assert row["derived"] is True
    assert row["source_purity"] == "999"
    assert row["rate_per_gram"] == pytest.approx(6418.42)
    assert rm.latest_rate(conn, "Gold", "916") == pytest.approx(6418.42)


def test_same_batch_exact_purity_rate_wins():
    conn = rate_db()
    stamp = "2026-08-30T04:00:00+00:00"
    add_rate(conn, "Gold", "999", 7000, stamp)
    add_rate(conn, "Gold", "916", 6500, stamp)

    row = rm.resolve_rate_row(conn, "Gold", "916")

    assert row is not None
    assert row["derived"] is False
    assert row["source_purity"] == "916"
    assert row["rate_per_gram"] == pytest.approx(6500)


def test_daily_confirmation_is_per_metal_not_global(monkeypatch):
    conn = rate_db()
    monkeypatch.setattr(rm, "business_date", lambda _conn: "2026-08-30")
    add_rate(conn, "Gold", "999", 7000, "2026-08-30T04:00:00+00:00")
    add_rate(conn, "Silver", "999", 90, "2026-08-29T04:00:00+00:00")

    stale = rm.current_rate_snapshot(conn)
    assert stale["updated_today"] is False
    assert stale["stale_metals"] == ["Silver"]
    assert stale["metal_dates"]["Gold"] == "2026-08-30"
    assert stale["metal_dates"]["Silver"] == "2026-08-29"

    add_rate(conn, "Silver", "999", 92, "2026-08-30T04:05:00+00:00")
    current = rm.current_rate_snapshot(conn)
    assert current["updated_today"] is True
    assert current["stale_metals"] == []


def test_ibja_parser_uses_latest_date_and_pm_session_and_converts_indian_units():
    payload = [
        {"RateDate": "29/08/2026", "RateTime": "6PM", "Purity": "999", "GoldRate": "150000", "SilverRate": "230000"},
        {"RateDate": "30/08/2026", "RateTime": "12AM", "Purity": "999", "GoldRate": "158000", "SilverRate": "240000"},
        {"RateDate": "30/08/2026", "RateTime": "6PM", "Purity": "999", "GoldRate": "159578", "SilverRate": "243892"},
        {"RateDate": "30/08/2026", "RateTime": "6PM", "Purity": "916", "GoldRate": "146173", "SilverRate": "243892"},
    ]

    result = rm.parse_ibja_response(payload)
    rows = {(x["metal"], x["purity"]): x["rate_per_gram"] for x in result["rates"]}

    assert result["provider"] == "ibja"
    assert result["provider_date"] == "2026-08-30"
    assert result["session"] == "PM"
    assert rows[("Gold", "999")] == pytest.approx(15957.80)
    assert rows[("Gold", "916")] == pytest.approx(14617.30)
    assert rows[("Silver", "999")] == pytest.approx(243.89)


def test_ibja_invalid_payload_is_rejected():
    with pytest.raises(ValueError, match="(?i)token|rejected"):
        rm.parse_ibja_response([{"status": "invalid", "message": "Access Token Is Blank"}])


def test_rate_management_installs_router_pricing_dashboard_and_guard_once():
    import jewel_server.main as main_module
    from jewel_server import services

    rm.install_rate_management(main_module)
    rm.install_rate_management(main_module)

    paths = [getattr(route, "path", None) for route in main_module.app.routes]
    assert paths.count("/api/rate-management/current") == 1
    assert paths.count("/api/rate-management/apply") == 1
    assert services.latest_rate is rm.latest_rate
    assert main_module.latest_rate is rm.latest_rate
    assert main_module.APP_VERSION == "1.2.0-rc6"

    with pytest.raises(HTTPException) as exc:
        main_module.add_rate({"metal": "Gold", "purity": "999", "rate_per_gram": 7000}, {"role": "accounts"})
    assert exc.value.status_code == 403
