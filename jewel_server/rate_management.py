from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation
from typing import Any

import requests
from fastapi import APIRouter, Body, Depends, HTTPException

from .db import audit, business_date, get_settings, read_db, set_setting, utcnow, write_db
from .precision import money, money_paise
from .security import require


APP_VERSION = "1.2.0-rc6"
TROY_OUNCE_GRAMS = Decimal("31.1034768")
RATE_PROVIDERS = {"manual", "ibja", "goldapi"}
WRITE_ROLES = {"admin", "manager"}
STANDARD_RATE_TARGETS = (
    ("Gold", "999"),
    ("Gold", "995"),
    ("Gold", "916"),
    ("Gold", "750"),
    ("Gold", "585"),
    ("Silver", "999"),
    ("Silver", "925"),
    ("Platinum", "999"),
    ("Platinum", "950"),
)

router = APIRouter(prefix="/api/rate-management", tags=["metal-rates"])


def _d(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _purity_fraction(value: Any) -> Decimal:
    raw = str(value or "").upper().strip().replace("K", "")
    known = {
        "999": Decimal("0.999"), "995": Decimal("0.995"), "990": Decimal("0.990"),
        "958": Decimal("0.958"), "950": Decimal("0.950"), "925": Decimal("0.925"),
        "916": Decimal("0.916"), "875": Decimal("0.875"), "833": Decimal("0.833"),
        "750": Decimal("0.750"), "585": Decimal("0.585"), "417": Decimal("0.417"),
        "375": Decimal("0.375"), "24": Decimal("0.999"), "23": Decimal("0.958"),
        "22": Decimal("0.916"), "21": Decimal("0.875"), "20": Decimal("0.833"),
        "18": Decimal("0.750"), "14": Decimal("0.585"), "10": Decimal("0.417"),
        "9": Decimal("0.375"),
    }
    if raw in known:
        return known[raw]
    try:
        val = Decimal(raw)
    except InvalidOperation:
        return Decimal("1")
    if val > 24:
        val /= Decimal("1000")
    else:
        val /= Decimal("24")
    return min(max(val, Decimal("0.001")), Decimal("1"))


def _normal_metal(value: Any) -> str:
    raw = str(value or "").strip().lower()
    names = {"gold": "Gold", "silver": "Silver", "platinum": "Platinum"}
    return names.get(raw, str(value or "Gold").strip().title() or "Gold")


def _normal_purity(value: Any) -> str:
    raw = str(value or "999").upper().strip().replace("K", "")
    karat = {"24": "999", "23": "958", "22": "916", "21": "875", "20": "833", "18": "750", "14": "585", "10": "417", "9": "375"}
    return karat.get(raw, raw or "999")


def _ensure_write_role(user: dict[str, Any]) -> None:
    if user.get("role") not in WRITE_ROLES:
        raise HTTPException(403, "Only an administrator or manager can change shop metal rates")


def _business_date_for_timestamp(value: str, offset_minutes: int) -> str:
    try:
        parsed = dt.datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        local = parsed.astimezone(dt.timezone.utc) + dt.timedelta(minutes=offset_minutes)
        return local.date().isoformat()
    except Exception:
        return str(value or "")[:10]


def resolve_rate_row(conn, metal: str, purity: str) -> dict[str, Any] | None:
    """Resolve the active shop rate without letting stale exact-purity rows win.

    A jeweller may update only the day's base 999 rate. Older 916/750 rows must not
    silently override that newer market move. If an exact-purity rate was set at the
    newest effective timestamp it wins; otherwise the newest metal batch is used,
    preferring 999 as the derivation base.
    """
    metal = _normal_metal(metal)
    purity = _normal_purity(purity)
    exact = conn.execute(
        "SELECT * FROM metal_rates WHERE lower(metal)=lower(?) AND lower(purity)=lower(?) "
        "ORDER BY effective_at DESC,id DESC LIMIT 1",
        (metal, purity),
    ).fetchone()
    newest = conn.execute(
        "SELECT effective_at FROM metal_rates WHERE lower(metal)=lower(?) ORDER BY effective_at DESC,id DESC LIMIT 1",
        (metal,),
    ).fetchone()
    if not newest:
        return None
    newest_at = str(newest["effective_at"])
    if exact and str(exact["effective_at"]) == newest_at:
        row = dict(exact)
        row.update({"requested_purity": purity, "source_purity": str(exact["purity"]), "derived": False})
        return row

    candidates = conn.execute(
        "SELECT * FROM metal_rates WHERE lower(metal)=lower(?) AND effective_at=? ORDER BY id DESC",
        (metal, newest_at),
    ).fetchall()
    if not candidates:
        return None
    source = next((r for r in candidates if _normal_purity(r["purity"]) == "999"), None)
    if source is None:
        source = max(candidates, key=lambda r: _purity_fraction(r["purity"]))
    source_fraction = max(_purity_fraction(source["purity"]), Decimal("0.001"))
    target_fraction = _purity_fraction(purity)
    resolved = money(_d(source["rate_per_gram"]) * target_fraction / source_fraction)
    row = dict(source)
    row["rate_per_gram"] = resolved
    row["rate_paise_per_gram"] = money_paise(resolved)
    row.update({"requested_purity": purity, "source_purity": str(source["purity"]), "derived": _normal_purity(source["purity"]) != purity})
    return row


def latest_rate(conn, metal: str, purity: str) -> float:
    row = resolve_rate_row(conn, metal, purity)
    if not row:
        raise HTTPException(409, f"No metal rate configured for {_normal_metal(metal)} {_normal_purity(purity)}")
    return money(row["rate_per_gram"])


def current_rate_snapshot(conn) -> dict[str, Any]:
    settings = get_settings(conn)
    try:
        offset = int(str(settings.get("business_timezone_offset_minutes", "330")))
    except ValueError:
        offset = 330
    today = business_date(conn)
    db_pairs = {
        (_normal_metal(r["metal"]), _normal_purity(r["purity"]))
        for r in conn.execute("SELECT DISTINCT metal,purity FROM metal_rates").fetchall()
    }
    active_metals = sorted({metal for metal, _purity in db_pairs})
    pairs = list(dict.fromkeys((*STANDARD_RATE_TARGETS, *sorted(db_pairs))))
    rates = []
    metal_dates: dict[str, str] = {}
    for metal in active_metals:
        newest = conn.execute(
            "SELECT effective_at FROM metal_rates WHERE lower(metal)=lower(?) ORDER BY effective_at DESC,id DESC LIMIT 1",
            (metal,),
        ).fetchone()
        if newest:
            metal_dates[metal] = _business_date_for_timestamp(str(newest["effective_at"]), offset)
    for metal, purity in pairs:
        row = resolve_rate_row(conn, metal, purity)
        if not row:
            continue
        row_date = _business_date_for_timestamp(str(row.get("effective_at") or ""), offset)
        rates.append({
            "metal": metal,
            "purity": purity,
            "rate_per_gram": money(row["rate_per_gram"]),
            "effective_at": row.get("effective_at"),
            "business_date": row_date,
            "source_purity": row.get("source_purity"),
            "derived": bool(row.get("derived")),
            "source_rate_id": row.get("id"),
        })
    stale_metals = [metal for metal in active_metals if metal_dates.get(metal) != today]
    dates = list(metal_dates.values())
    return {
        "business_date": today,
        "last_rate_business_date": min(dates) if dates else None,
        "updated_today": bool(active_metals) and not stale_metals,
        "active_metals": active_metals,
        "metal_dates": metal_dates,
        "stale_metals": stale_metals,
        "rates": rates,
    }


def _parse_ibja_date(value: str) -> dt.date | None:
    try:
        return dt.datetime.strptime(str(value), "%d/%m/%Y").date()
    except Exception:
        return None


def _session_rank(value: Any) -> int:
    text = str(value or "").strip().upper()
    if "PM" in text or text.startswith("6") or text.startswith("18"):
        return 2
    return 1


def parse_ibja_response(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, list) or not payload:
        raise ValueError("IBJA returned no rate records")
    first = payload[0]
    if isinstance(first, dict) and str(first.get("status", "")).lower() in {"invalid", "error"}:
        raise ValueError(str(first.get("message") or "IBJA rejected the request"))
    records = [r for r in payload if isinstance(r, dict) and _parse_ibja_date(str(r.get("RateDate") or ""))]
    if not records:
        message = str(first.get("message") or "No IBJA rate was available") if isinstance(first, dict) else "No IBJA rate was available"
        raise ValueError(message)
    latest_date = max(_parse_ibja_date(str(r.get("RateDate"))) for r in records)
    dated = [r for r in records if _parse_ibja_date(str(r.get("RateDate"))) == latest_date]
    latest_session = max(_session_rank(r.get("RateTime")) for r in dated)
    selected = [r for r in dated if _session_rank(r.get("RateTime")) == latest_session]
    rates: list[dict[str, Any]] = []
    silver_seen = False
    for record in selected:
        purity = _normal_purity(record.get("Purity"))
        gold = _d(record.get("GoldRate"))
        if gold > 0:
            rates.append({"metal": "Gold", "purity": purity, "rate_per_gram": money(gold / Decimal("10"))})
        silver = _d(record.get("SilverRate"))
        if silver > 0 and not silver_seen:
            rates.append({"metal": "Silver", "purity": "999", "rate_per_gram": money(silver / Decimal("1000"))})
            silver_seen = True
    if not rates:
        raise ValueError("IBJA response did not contain usable Gold/Silver rates")
    return {
        "provider": "ibja",
        "provider_date": latest_date.isoformat(),
        "session": "PM" if latest_session == 2 else "AM",
        "rates": rates,
        "note": "IBJA benchmark reference; source values exclude GST and making charges.",
    }


def _fetch_ibja(token: str, today: dt.date) -> dict[str, Any]:
    start = today - dt.timedelta(days=7)
    try:
        response = requests.get(
            "https://ibjarates.com/API/GoldRates/",
            params={
                "ACCESS_TOKEN": token,
                "START_DATE": start.strftime("%d/%m/%Y"),
                "END_DATE": today.strftime("%d/%m/%Y"),
            },
            timeout=8,
        )
        response.raise_for_status()
        return parse_ibja_response(response.json())
    except requests.RequestException as exc:
        raise ValueError(f"Could not reach the IBJA Rates API: {exc}") from exc
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"IBJA returned an unreadable response: {exc}") from exc


def _fetch_goldapi(token: str) -> dict[str, Any]:
    headers = {"x-access-token": token, "Content-Type": "application/json"}
    values: dict[str, dict[str, Any]] = {}
    try:
        for symbol in ("XAU", "XAG"):
            response = requests.get(f"https://www.goldapi.io/api/price/{symbol}/INR", headers=headers, timeout=8)
            response.raise_for_status()
            values[symbol] = response.json()
    except requests.RequestException as exc:
        raise ValueError(f"Could not reach GoldAPI: {exc}") from exc
    rates = []
    for symbol, metal in (("XAU", "Gold"), ("XAG", "Silver")):
        data = values.get(symbol) or {}
        per_ounce = _d(data.get("price"))
        if per_ounce <= 0:
            raise ValueError(f"GoldAPI did not return a usable {symbol}/INR price")
        pure_per_gram = per_ounce / TROY_OUNCE_GRAMS
        rates.append({"metal": metal, "purity": "999", "rate_per_gram": money(pure_per_gram * Decimal("0.999"))})
    observed = values.get("XAU", {}).get("datetime") or values.get("XAU", {}).get("timestamp")
    return {
        "provider": "goldapi",
        "provider_date": str(observed or ""),
        "session": "live",
        "rates": rates,
        "note": "International XAU/XAG INR spot reference. Review and approve before using as shop rates.",
    }


def fetch_reference_rates(provider: str, settings: dict[str, str], today: dt.date) -> dict[str, Any]:
    provider = str(provider or settings.get("rate_provider") or "manual").strip().lower()
    if provider == "ibja":
        token = str(settings.get("rate_ibja_access_token") or "").strip()
        if not token:
            raise ValueError("IBJA API token is not configured. Add the official IBJA subscription token in Rate Provider Settings.")
        return _fetch_ibja(token, today)
    if provider == "goldapi":
        token = str(settings.get("rate_goldapi_access_token") or "").strip()
        if not token:
            raise ValueError("GoldAPI token is not configured. Add it in Rate Provider Settings.")
        return _fetch_goldapi(token)
    raise ValueError("Choose IBJA or GoldAPI for reference-rate sync. Manual shop rates never require internet.")


@router.get("/current")
def rate_current(user=Depends(require("rates"))):
    with read_db() as conn:
        return current_rate_snapshot(conn)


@router.get("/settings")
def rate_settings(user=Depends(require("rates"))):
    with read_db() as conn:
        settings = get_settings(conn)
    provider = str(settings.get("rate_provider") or "manual").lower()
    if provider not in RATE_PROVIDERS:
        provider = "manual"
    return {
        "provider": provider,
        "ibja_token_configured": bool(str(settings.get("rate_ibja_access_token") or "").strip()),
        "goldapi_token_configured": bool(str(settings.get("rate_goldapi_access_token") or "").strip()),
        "principle": "External feeds are reference-only until an authorised operator applies them to shop rates.",
    }


@router.put("/settings")
def rate_settings_save(payload: dict = Body(...), user=Depends(require("rates"))):
    if user.get("role") not in {"admin", "manager"}:
        raise HTTPException(403, "Administrator or manager permission is required to change rate-provider settings")
    provider = str(payload.get("provider") or "manual").strip().lower()
    if provider not in RATE_PROVIDERS:
        raise HTTPException(400, "Provider must be manual, ibja, or goldapi")
    with write_db() as conn:
        set_setting(conn, "rate_provider", provider)
        if "ibja_access_token" in payload and str(payload.get("ibja_access_token") or "").strip():
            set_setting(conn, "rate_ibja_access_token", str(payload["ibja_access_token"]).strip())
        if payload.get("clear_ibja_access_token"):
            set_setting(conn, "rate_ibja_access_token", "")
        if "goldapi_access_token" in payload and str(payload.get("goldapi_access_token") or "").strip():
            set_setting(conn, "rate_goldapi_access_token", str(payload["goldapi_access_token"]).strip())
        if payload.get("clear_goldapi_access_token"):
            set_setting(conn, "rate_goldapi_access_token", "")
        audit(conn, user["id"], "update", "rate_provider_settings", None, {"provider": provider})
    return {"ok": True, "provider": provider}


@router.post("/sync-preview")
def rate_sync_preview(payload: dict = Body(default={}), user=Depends(require("rates"))):
    if user.get("role") not in {"admin", "manager"}:
        raise HTTPException(403, "Administrator or manager permission is required to sync reference rates")
    provider = str(payload.get("provider") or "").strip().lower()
    with read_db() as conn:
        settings = get_settings(conn)
        today = dt.date.fromisoformat(business_date(conn))
    try:
        result = fetch_reference_rates(provider, settings, today)
    except ValueError as exc:
        raise HTTPException(502, str(exc)) from exc
    result["billing_changed"] = False
    result["instruction"] = "Review the reference values, then click Apply reference to make them the active shop rates."
    return result


@router.post("/apply")
def rate_apply(payload: dict = Body(...), user=Depends(require("rates"))):
    _ensure_write_role(user)
    rows = payload.get("rates") or []
    if not isinstance(rows, list) or not rows:
        raise HTTPException(400, "At least one metal rate is required")
    source = str(payload.get("source") or "manual").strip().lower()
    note = str(payload.get("note") or "").strip()[:500]
    effective_at = utcnow()
    clean = []
    seen = set()
    for raw in rows:
        metal = _normal_metal(raw.get("metal"))
        purity = _normal_purity(raw.get("purity"))
        pair = (metal.lower(), purity.lower())
        if pair in seen:
            raise HTTPException(400, f"Duplicate rate in the same update: {metal} {purity}")
        seen.add(pair)
        rate = money(raw.get("rate_per_gram"))
        if rate <= 0 or rate > 10_000_000:
            raise HTTPException(400, f"Invalid rate for {metal} {purity}")
        clean.append({"metal": metal, "purity": purity, "rate_per_gram": rate})
    ids = []
    with write_db() as conn:
        for row in clean:
            cur = conn.execute(
                "INSERT INTO metal_rates(metal,purity,rate_per_gram,effective_at,created_by,rate_paise_per_gram) VALUES(?,?,?,?,?,?)",
                (row["metal"], row["purity"], row["rate_per_gram"], effective_at, user["id"], money_paise(row["rate_per_gram"])),
            )
            ids.append(cur.lastrowid)
        audit(conn, user["id"], "apply", "metal_rate_batch", effective_at, {"source": source, "note": note, "rates": clean, "ids": ids})
        snapshot = current_rate_snapshot(conn)
    return {"ok": True, "effective_at": effective_at, "ids": ids, "source": source, "current": snapshot}


def _dashboard_with_resolved_rates(main_module):
    original = main_module.dashboard

    def dashboard(u):
        data = original(u)
        with read_db() as conn:
            snapshot = current_rate_snapshot(conn)
        data["rates"] = [
            {
                "metal": row["metal"],
                "purity": row["purity"],
                "rate_per_gram": row["rate_per_gram"],
                "effective_at": row["effective_at"],
                "derived": row["derived"],
                "source_purity": row["source_purity"],
            }
            for row in snapshot["rates"]
        ]
        data["rate_status"] = {
            "updated_today": snapshot["updated_today"],
            "stale_metals": snapshot["stale_metals"],
            "metal_dates": snapshot["metal_dates"],
        }
        return data

    main_module.dashboard = dashboard
    for route in main_module.app.routes:
        if getattr(route, "path", None) == "/api/dashboard" and "GET" in getattr(route, "methods", set()):
            route.endpoint = dashboard
            route.dependant.call = dashboard
            break


def _guard_legacy_rate_post(main_module):
    original = main_module.add_rate

    def guarded(p, u):
        _ensure_write_role(u)
        return original(p, u)

    main_module.add_rate = guarded
    for route in main_module.app.routes:
        if getattr(route, "path", None) == "/api/rates" and "POST" in getattr(route, "methods", set()):
            route.endpoint = guarded
            route.dependant.call = guarded
            break


def install_rate_management(main_module) -> None:
    """Install RC6 rate workflow while retaining compatible /api/rates history."""
    app = main_module.app
    if getattr(app.state, "rate_management_installed", False):
        return
    app.include_router(router)

    from . import services

    services.latest_rate = latest_rate
    main_module.latest_rate = latest_rate
    _dashboard_with_resolved_rates(main_module)
    _guard_legacy_rate_post(main_module)
    main_module.APP_VERSION = APP_VERSION
    app.version = APP_VERSION
    app.state.rate_management_installed = True
