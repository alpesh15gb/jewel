from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import requests
from fastapi import APIRouter, Body, Depends, HTTPException, Query

from .db import app_data_dir, audit, business_date, read_db, rowsdict, utcnow, write_db
from .precision import money, money_paise
from .security import current_user, require

router = APIRouter(prefix="/api/rate-board", tags=["rate-board"])

IBJA_PROD_URL = "https://ibjarates.com/API/GoldRates/"
IBJA_UAT_URL = "https://uat.ibjarates.com/API/GoldRates/"
PROVIDER_FILE = "rate-provider-secret.json"
REFERENCE_FILE = "rate-reference-last.json"


def _provider_path() -> Path:
    return app_data_dir() / PROVIDER_FILE


def _reference_path() -> Path:
    return app_data_dir() / REFERENCE_FILE


def _restrict_secret(path: Path) -> None:
    if os.name != "nt":
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return
    try:
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", "*S-1-5-18:F", "*S-1-5-32-544:F"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
    except Exception as exc:
        raise RuntimeError(f"Could not secure JewelLAN rate-provider secret ACL: {exc}") from exc


def _read_json(path: Path, default: dict | None = None) -> dict:
    if not path.exists():
        return dict(default or {})
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else dict(default or {})
    except Exception:
        return dict(default or {})


def _write_json(path: Path, value: dict, secret: bool = False) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    if secret:
        _restrict_secret(tmp)
    os.replace(tmp, path)
    if secret:
        _restrict_secret(path)


def _normal_metal(value: Any) -> str:
    raw = str(value or "").strip().title()
    aliases = {"Au": "Gold", "Ag": "Silver", "Pt": "Platinum"}
    raw = aliases.get(raw, raw)
    if raw not in {"Gold", "Silver", "Platinum"}:
        raise ValueError("Metal must be Gold, Silver or Platinum")
    return raw


def _normal_purity(value: Any) -> str:
    raw = str(value or "").upper().strip().replace("K", "")
    karat = {"24": "999", "23": "958", "22": "916", "21": "875", "20": "833", "18": "750", "14": "585", "10": "417", "9": "375"}
    raw = karat.get(raw, raw)
    if not raw.isdigit() or not (1 <= int(raw) <= 999):
        raise ValueError("Purity must be a fineness such as 999, 916, 750 or 585")
    return raw


def _rate(value: Any) -> float:
    try:
        out = money(value)
    except Exception as exc:
        raise ValueError("Rate must be numeric") from exc
    if out <= 0:
        raise ValueError("Rate must be positive")
    if out > 10_000_000:
        raise ValueError("Rate per gram is outside the accepted range")
    return out


def _current_rows(conn) -> list[dict]:
    rows = conn.execute(
        """
        SELECT r.*
          FROM metal_rates r
          JOIN (
                SELECT metal,purity,MAX(id) AS id
                  FROM metal_rates
                 GROUP BY lower(metal),lower(purity)
               ) x ON x.id=r.id
         ORDER BY CASE lower(r.metal) WHEN 'gold' THEN 1 WHEN 'silver' THEN 2 WHEN 'platinum' THEN 3 ELSE 9 END,
                  CAST(r.purity AS INTEGER) DESC,r.id DESC
        """
    ).fetchall()
    return rowsdict(rows)


def _history_rows(conn, limit: int = 250) -> list[dict]:
    return rowsdict(
        conn.execute(
            "SELECT id,metal,purity,rate_per_gram,effective_at,created_by FROM metal_rates ORDER BY effective_at DESC,id DESC LIMIT ?",
            (max(1, min(int(limit), 1000)),),
        ).fetchall()
    )


def _row_business_date(row: dict, offset_minutes: int) -> str:
    raw = str(row.get("effective_at") or "")
    try:
        stamp = dt.datetime.fromisoformat(raw)
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=dt.timezone.utc)
        local = stamp.astimezone(dt.timezone.utc) + dt.timedelta(minutes=offset_minutes)
        return local.date().isoformat()
    except Exception:
        return raw[:10]


def _board_payload(conn) -> dict:
    today = business_date(conn)
    settings = {r[0]: r[1] for r in conn.execute("SELECT key,value FROM settings").fetchall()}
    try:
        offset = int(settings.get("business_timezone_offset_minutes", "330"))
    except ValueError:
        offset = 330
    current = _current_rows(conn)
    for row in current:
        rate_day = _row_business_date(row, offset)
        row["rate_business_date"] = rate_day
        row["fresh_today"] = rate_day == today
    return {
        "business_date": today,
        "current": current,
        "history": _history_rows(conn),
        "provider": _provider_public(),
        "reference": _read_json(_reference_path()),
    }


def _provider_public() -> dict:
    cfg = _read_json(_provider_path(), {"provider": "manual", "environment": "production"})
    return {
        "provider": cfg.get("provider", "manual"),
        "environment": cfg.get("environment", "production"),
        "configured": bool(str(cfg.get("access_token") or "").strip()),
        "last_saved_at": cfg.get("last_saved_at"),
        "note": "IBJA sync is optional. Manual shop rates always remain available offline.",
    }


def _insert_batch(conn, values: list[dict], user_id: int, source: str, note: str = "") -> list[dict]:
    if not values:
        raise ValueError("At least one metal rate is required")
    effective = utcnow()
    created = []
    seen: set[tuple[str, str]] = set()
    for item in values:
        metal = _normal_metal(item.get("metal"))
        purity = _normal_purity(item.get("purity"))
        key = (metal.lower(), purity.lower())
        if key in seen:
            raise ValueError(f"Duplicate rate in this update: {metal} {purity}")
        seen.add(key)
        rate = _rate(item.get("rate_per_gram"))
        cur = conn.execute(
            "INSERT INTO metal_rates(metal,purity,rate_per_gram,effective_at,created_by,rate_paise_per_gram) VALUES(?,?,?,?,?,?)",
            (metal, purity, rate, effective, user_id, money_paise(rate)),
        )
        created.append({"id": cur.lastrowid, "metal": metal, "purity": purity, "rate_per_gram": rate})
    audit(
        conn,
        user_id,
        "set_rate_board",
        "metal_rate",
        None,
        {"source": source, "note": note, "effective_at": effective, "rates": created},
    )
    return created


def _session_score(value: str) -> int:
    raw = str(value or "").upper().replace(" ", "")
    if raw in {"6PM", "18:00", "PM"} or raw.startswith("18"):
        return 2
    return 1


def parse_ibja_response(payload: Any) -> dict:
    if not isinstance(payload, list) or not payload:
        raise ValueError("IBJA returned an empty or invalid response")
    first = payload[0] if isinstance(payload[0], dict) else {}
    if str(first.get("status") or "").lower() in {"invalid", "error"}:
        raise ValueError(str(first.get("message") or "IBJA rejected the request"))
    if str(first.get("status") or "").lower() == "success" and first.get("message"):
        raise ValueError(str(first.get("message")))

    usable = [x for x in payload if isinstance(x, dict) and x.get("RateDate") and x.get("Purity")]
    if not usable:
        raise ValueError("IBJA response contained no rate rows")
    latest_score = max(_session_score(x.get("RateTime")) for x in usable)
    usable = [x for x in usable if _session_score(x.get("RateTime")) == latest_score]
    session = str(usable[0].get("RateTime") or "")
    rate_date = str(usable[0].get("RateDate") or "")
    rates: list[dict] = []
    silver_value = None
    for row in usable:
        purity = _normal_purity(row.get("Purity"))
        try:
            gold_per_10g = float(str(row.get("GoldRate") or "0").replace(",", ""))
        except ValueError:
            gold_per_10g = 0
        if gold_per_10g > 0:
            rates.append(
                {
                    "metal": "Gold",
                    "purity": purity,
                    "rate_per_gram": money(gold_per_10g / 10.0),
                    "source_unit": "INR/10g",
                    "source_value": gold_per_10g,
                }
            )
        if silver_value is None:
            try:
                silver_per_kg = float(str(row.get("SilverRate") or "0").replace(",", ""))
            except ValueError:
                silver_per_kg = 0
            if silver_per_kg > 0:
                silver_value = money(silver_per_kg / 1000.0)
    if silver_value:
        rates.append(
            {
                "metal": "Silver",
                "purity": "999",
                "rate_per_gram": silver_value,
                "source_unit": "INR/kg",
            }
        )
    if not rates:
        raise ValueError("IBJA response contained no usable Gold/Silver rates")
    return {"provider": "IBJA", "rate_date": rate_date, "session": session, "rates": rates}


def _fetch_ibja(token: str, environment: str, date_value: str) -> dict:
    try:
        day = dt.date.fromisoformat(date_value)
    except ValueError as exc:
        raise ValueError("Sync date must be YYYY-MM-DD") from exc
    url = IBJA_UAT_URL if environment == "uat" else IBJA_PROD_URL
    formatted = day.strftime("%d/%m/%Y")
    session = requests.Session()
    session.trust_env = False
    response = session.get(
        url,
        params={"ACCESS_TOKEN": token, "START_DATE": formatted, "END_DATE": formatted},
        timeout=(5, 15),
        headers={"User-Agent": "JewelLAN/1.2 rate-sync"},
    )
    response.raise_for_status()
    parsed = parse_ibja_response(response.json())
    parsed.update(
        {
            "environment": environment,
            "source_url": url,
            "fetched_at": utcnow(),
            "requested_business_date": date_value,
        }
    )
    return parsed


@router.get("")
def rate_board(u=Depends(current_user)):
    with read_db() as conn:
        return _board_payload(conn)


@router.post("/batch")
def set_rate_board(payload: dict = Body(...), u=Depends(require("rates"))):
    values = payload.get("rates") or []
    try:
        with write_db() as conn:
            created = _insert_batch(conn, values, u["id"], "manual", str(payload.get("note") or ""))
            return {"ok": True, "created": created, "business_date": business_date(conn)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/provider")
def provider_status(u=Depends(require("rates"))):
    return _provider_public()


@router.put("/provider")
def save_provider(payload: dict = Body(...), u=Depends(require("*"))):
    provider = str(payload.get("provider") or "manual").strip().lower()
    if provider not in {"manual", "ibja"}:
        raise HTTPException(400, "Provider must be manual or ibja")
    environment = str(payload.get("environment") or "production").strip().lower()
    if environment not in {"production", "uat"}:
        raise HTTPException(400, "Environment must be production or uat")
    existing = _read_json(_provider_path())
    token = str(payload.get("access_token") or "").strip()
    if not token and payload.get("keep_existing_token", True):
        token = str(existing.get("access_token") or "").strip()
    value = {
        "provider": provider,
        "environment": environment,
        "access_token": token,
        "last_saved_at": utcnow(),
    }
    _write_json(_provider_path(), value, secret=True)
    with write_db() as conn:
        audit(conn, u["id"], "update", "rate_provider", None, {"provider": provider, "environment": environment, "token_configured": bool(token)})
    return _provider_public()


@router.post("/sync")
def sync_reference(payload: dict = Body(default={}), u=Depends(require("rates"))):
    cfg = _read_json(_provider_path(), {"provider": "manual", "environment": "production"})
    provider = str(cfg.get("provider") or "manual").lower()
    if provider != "ibja":
        raise HTTPException(409, "Configure the IBJA provider first, or continue using manual shop rates")
    token = str(cfg.get("access_token") or "").strip()
    if not token:
        raise HTTPException(409, "IBJA access token is not configured")
    with read_db() as conn:
        date_value = str(payload.get("date") or business_date(conn))
    try:
        snapshot = _fetch_ibja(token, str(cfg.get("environment") or "production"), date_value)
    except requests.RequestException as exc:
        raise HTTPException(502, f"IBJA sync failed; existing JewelLAN shop rates are unchanged: {exc}") from exc
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(502, f"IBJA returned unusable data; existing shop rates are unchanged: {exc}") from exc
    _write_json(_reference_path(), snapshot)
    with write_db() as conn:
        audit(conn, u["id"], "sync", "market_rate_reference", None, {k: snapshot.get(k) for k in ("provider", "rate_date", "session", "fetched_at", "environment")})
    return {"ok": True, "applied": False, "reference": snapshot, "message": "Reference rates fetched. Review them before applying as shop rates."}


@router.get("/reference")
def reference_rate(u=Depends(require("rates"))):
    value = _read_json(_reference_path())
    if not value:
        return {"available": False}
    return {"available": True, "reference": value}


def _rounded(value: float, step: float) -> float:
    if step <= 0:
        return money(value)
    return money(round(value / step) * step)


@router.post("/apply-reference")
def apply_reference(payload: dict = Body(default={}), u=Depends(require("rates"))):
    snapshot = _read_json(_reference_path())
    if not snapshot or not snapshot.get("rates"):
        raise HTTPException(409, "No synced reference is available. Sync first.")
    gold_premium = float(payload.get("gold_premium_per_gram") or 0)
    silver_premium = float(payload.get("silver_premium_per_gram") or 0)
    round_to = float(payload.get("round_to") or 0)
    selected = {str(x).strip() for x in (payload.get("only") or []) if str(x).strip()}
    values = []
    for row in snapshot["rates"]:
        key = f"{row.get('metal')}:{row.get('purity')}"
        if selected and key not in selected:
            continue
        premium = gold_premium if row.get("metal") == "Gold" else silver_premium if row.get("metal") == "Silver" else 0
        values.append(
            {
                "metal": row.get("metal"),
                "purity": row.get("purity"),
                "rate_per_gram": _rounded(float(row.get("rate_per_gram") or 0) + premium, round_to),
            }
        )
    try:
        with write_db() as conn:
            created = _insert_batch(
                conn,
                values,
                u["id"],
                "IBJA reference",
                f"IBJA {snapshot.get('rate_date','')} {snapshot.get('session','')} premium gold={gold_premium} silver={silver_premium} round={round_to}",
            )
            return {"ok": True, "created": created, "reference": {k: snapshot.get(k) for k in ("provider", "rate_date", "session", "fetched_at")}}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def install(app) -> None:
    if any(getattr(route, "path", "") == "/api/rate-board" for route in app.routes):
        return
    app.include_router(router)
