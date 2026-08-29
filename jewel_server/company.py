from __future__ import annotations

import re

from .db import audit, get_settings, set_setting

GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
PREFIX_RE = re.compile(r"^[A-Z0-9/-]{1,12}$")


def get_company(conn) -> dict:
    settings = get_settings(conn)
    branch = conn.execute("SELECT * FROM branches WHERE code='MAIN'").fetchone()
    counters = conn.execute("SELECT * FROM counters WHERE branch_id=? AND active=1 ORDER BY id", (branch['id'],)).fetchall() if branch else []
    return {
        "configured": str(settings.get("company_setup_complete", "0")).lower() in ("1", "true", "yes", "on"),
        "settings": settings,
        "branch": dict(branch) if branch else None,
        "counters": [dict(x) for x in counters],
        "counter_count": len(counters),
    }


def _prefix(value, field: str) -> str:
    out = str(value or '').strip().upper()
    if not PREFIX_RE.fullmatch(out):
        raise ValueError(f"{field} must be 1-12 letters/numbers and may contain / or -")
    return out


def save_company(conn, payload: dict, user_id: int) -> dict:
    name = str(payload.get("business_name") or '').strip()
    if not name or len(name) > 120:
        raise ValueError("Company name is required and must be 120 characters or fewer")
    branch_name = str(payload.get("branch_name") or "Main Showroom").strip()
    if not branch_name or len(branch_name) > 120:
        raise ValueError("Main branch/showroom name is required")

    state_code = str(payload.get("business_state_code") or '').strip()
    if not re.fullmatch(r"[0-9]{2}", state_code):
        raise ValueError("GST state code must be exactly two digits")
    gstin = str(payload.get("business_gstin") or '').strip().upper()
    if gstin and not GSTIN_RE.fullmatch(gstin):
        raise ValueError("GSTIN must be a valid 15-character GSTIN")
    if gstin and gstin[:2] != state_code:
        raise ValueError("GSTIN state code does not match the company state code")

    pincode = str(payload.get("business_pincode") or '').strip()
    if pincode and not re.fullmatch(r"[0-9]{6}", pincode):
        raise ValueError("PIN code must be six digits")
    try:
        counter_count = int(payload.get("counter_count") or 1)
        timezone = int(payload.get("business_timezone_offset_minutes") or 330)
        gst_default = float(payload.get("gst_default") or 0)
    except (TypeError, ValueError):
        raise ValueError("Counter count, timezone and GST rate must be numeric")
    if not 1 <= counter_count <= 20:
        raise ValueError("Counter count must be between 1 and 20")
    if not -720 <= timezone <= 840:
        raise ValueError("Timezone offset is outside the supported range")
    if not 0 <= gst_default <= 100:
        raise ValueError("Default GST rate must be between 0 and 100")

    invoice_prefix = _prefix(payload.get("invoice_prefix") or "INV", "Invoice prefix")
    tag_prefix = _prefix(payload.get("tag_prefix") or "TAG", "Tag prefix")
    fields = {
        "business_name": name,
        "business_address": str(payload.get("business_address") or '').strip(),
        "business_phone": str(payload.get("business_phone") or '').strip(),
        "business_email": str(payload.get("business_email") or '').strip(),
        "business_gstin": gstin,
        "business_state_code": state_code,
        "business_state_name": str(payload.get("business_state_name") or '').strip(),
        "business_pincode": pincode,
        "business_timezone_offset_minutes": str(timezone),
        "invoice_prefix": invoice_prefix,
        "tag_prefix": tag_prefix,
        "gst_default": (f"{gst_default:g}"),
        "company_setup_complete": "1",
    }
    for key, value in fields.items():
        set_setting(conn, key, value)

    branch = conn.execute("SELECT * FROM branches WHERE code='MAIN'").fetchone()
    if not branch:
        cur = conn.execute(
            "INSERT INTO branches(code,name,gstin,address,phone,active) VALUES('MAIN',?,?,?,?,1)",
            (branch_name, gstin, fields['business_address'], fields['business_phone']),
        )
        branch_id = int(cur.lastrowid)
    else:
        branch_id = int(branch['id'])
        conn.execute(
            "UPDATE branches SET name=?,gstin=?,address=?,phone=?,active=1 WHERE id=?",
            (branch_name, gstin, fields['business_address'], fields['business_phone'], branch_id),
        )

    for number in range(1, counter_count + 1):
        counter_name = f"Counter {number}"
        conn.execute(
            "INSERT INTO counters(branch_id,name,active) VALUES(?,?,1) ON CONFLICT(branch_id,name) DO UPDATE SET active=1",
            (branch_id, counter_name),
        )

    # Reduce unused generic counters when an administrator lowers the configured
    # count.  Referenced counters are deliberately retained for audit/history.
    for row in conn.execute("SELECT id,name FROM counters WHERE branch_id=? AND active=1", (branch_id,)).fetchall():
        match = re.fullmatch(r"Counter ([0-9]+)", str(row['name']))
        if not match or int(match.group(1)) <= counter_count:
            continue
        cid = int(row['id'])
        used = any(
            conn.execute(f"SELECT 1 FROM {table} WHERE counter_id=? LIMIT 1", (cid,)).fetchone()
            for table in ("items", "sales", "stock_audits")
        )
        if not used:
            conn.execute("UPDATE counters SET active=0 WHERE id=?", (cid,))

    audit(conn, user_id, "update", "company_settings", branch_id, {**fields, "branch_name": branch_name, "counter_count": counter_count})
    return get_company(conn)
