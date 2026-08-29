from __future__ import annotations

import datetime as dt
import hashlib
import json
import threading
import time
import uuid
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
import xml.etree.ElementTree as ET

import requests

from .db import app_data_dir, get_settings, read_db, rowsdict, utcnow, write_db

MONEY_Q = Decimal("0.01")
SYNC_NAMESPACE = uuid.UUID("72855cff-18a2-43a0-aacf-0df7ef3f8b4e")
DEFAULT_MAPPINGS = {
    "cash": "Cash",
    "bank": "Bank / Card / UPI",
    "sales": "Jewellery Sales",
    "inventory": "Jewellery Inventory",
    "cogs": "Cost of Goods Sold",
    "old_gold": "Old Gold Inventory",
    "customer_receivables": "Sundry Debtors Control",
    "supplier_payables": "Sundry Creditors Control",
    "input_gst": "Input GST",
    "cgst": "Output CGST 1.5%",
    "sgst": "Output SGST 1.5%",
    "igst": "Output IGST 3%",
    "round_off": "Round Off",
}


class TallySyncError(RuntimeError):
    pass


def D(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value or 0))


def qmoney(value: Any) -> Decimal:
    return D(value).quantize(MONEY_Q, rounding=ROUND_HALF_UP)


def money_text(value: Any) -> str:
    return f"{qmoney(value):.2f}"


def _setting(settings: dict[str, str], key: str, default: str = "") -> str:
    return str(settings.get(key, default) or default).strip()


def stable_remote_id(entity_type: str, entity_id: int) -> str:
    return str(uuid.uuid5(SYNC_NAMESPACE, f"{entity_type}:{entity_id}"))


def enqueue_tally(conn, entity_type: str, entity_id: int, operation: str = "create") -> None:
    now = utcnow()
    rid = stable_remote_id(entity_type, entity_id)
    conn.execute(
        """INSERT INTO tally_sync_queue(
               entity_type,entity_id,operation,remote_id,status,attempt_count,
               created_at,updated_at
           ) VALUES(?,?,?,?, 'pending',0,?,?)
           ON CONFLICT(entity_type,entity_id,operation) DO UPDATE SET
               status=CASE WHEN tally_sync_queue.status='synced' THEN tally_sync_queue.status ELSE 'pending' END,
               updated_at=excluded.updated_at""",
        (entity_type, entity_id, operation, rid, now, now),
    )


def get_mappings(conn) -> dict[str, str]:
    rows = conn.execute("SELECT mapping_key,tally_ledger_name FROM tally_ledger_mappings").fetchall()
    result = dict(DEFAULT_MAPPINGS)
    result.update({r["mapping_key"]: r["tally_ledger_name"] for r in rows})
    return result


def set_mappings(conn, mappings: dict[str, str]) -> None:
    now = utcnow()
    for key, value in mappings.items():
        if key not in DEFAULT_MAPPINGS:
            continue
        name = str(value or "").strip()
        if not name:
            raise ValueError(f"Tally ledger mapping {key} cannot be blank")
        conn.execute(
            """INSERT INTO tally_ledger_mappings(mapping_key,tally_ledger_name,updated_at)
               VALUES(?,?,?)
               ON CONFLICT(mapping_key) DO UPDATE SET
                 tally_ledger_name=excluded.tally_ledger_name,
                 updated_at=excluded.updated_at""",
            (key, name, now),
        )


def _local_bridge_token(settings: dict[str, str]) -> str:
    configured = _setting(settings, "tally_bridge_token")
    if configured:
        return configured
    base = _setting(settings, "tally_bridge_url", "http://127.0.0.1:8767").lower()
    if "127.0.0.1" in base or "localhost" in base:
        p = app_data_dir() / "tally-bridge-token.txt"
        if p.exists():
            return p.read_text(encoding="utf-8").strip()
    return ""


def _bridge_request(
    settings: dict[str, str],
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    timeout: float = 12.0,
) -> Any:
    base = _setting(settings, "tally_bridge_url", "http://127.0.0.1:8767").rstrip("/")
    token = _local_bridge_token(settings)
    if not token:
        raise TallySyncError("Tally Bridge token is not configured")
    try:
        r = requests.request(
            method,
            base + path,
            params=params,
            json=body,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise TallySyncError(f"Tally Bridge unavailable: {exc}") from exc
    if r.status_code >= 400:
        detail = r.text[:1000]
        try:
            detail = r.json().get("detail", detail)
        except Exception:
            pass
        raise TallySyncError(f"Tally Bridge error {r.status_code}: {detail}")
    try:
        return r.json()
    except Exception as exc:
        raise TallySyncError("Tally Bridge returned invalid JSON") from exc


def bridge_health(settings: dict[str, str]) -> dict[str, Any]:
    return _bridge_request(
        settings,
        "GET",
        "/health",
        params={"company": _setting(settings, "tally_company")},
        timeout=5,
    )


_LEDGER_CACHE: dict[tuple[str, str], tuple[float, set[str]]] = {}


def bridge_ledgers(settings: dict[str, str], *, force: bool = False) -> set[str]:
    base = _setting(settings, "tally_bridge_url", "http://127.0.0.1:8767")
    company = _setting(settings, "tally_company")
    key = (base, company)
    cached = _LEDGER_CACHE.get(key)
    if cached and not force and time.time() - cached[0] < 30:
        return set(cached[1])
    data = _bridge_request(settings, "GET", "/ledgers", params={"company": company}, timeout=20)
    names = {str(x).strip() for x in data.get("ledgers", []) if str(x).strip()}
    _LEDGER_CACHE[key] = (time.time(), names)
    return names


def _ensure_party_ledger(settings: dict[str, str], party: dict[str, Any] | None, parent: str) -> str | None:
    if not party:
        return None
    name = str(party.get("name") or "").strip()
    if not name:
        return None
    ledgers = bridge_ledgers(settings)
    if name in ledgers:
        return name
    if _setting(settings, "tally_auto_create_parties", "1").lower() not in {"1", "true", "yes", "on"}:
        raise TallySyncError(f"Tally ledger is missing for {name}")
    payload = {
        "company": _setting(settings, "tally_company"),
        "name": name,
        "parent": parent,
        "gstin": str(party.get("gstin") or ""),
        "address": str(party.get("address") or ""),
        "phone": str(party.get("phone") or ""),
    }
    result = _bridge_request(settings, "POST", "/ledgers", body=payload, timeout=20)
    if not result.get("ok"):
        raise TallySyncError(result.get("error") or f"Could not create Tally ledger {name}")
    bridge_ledgers(settings, force=True)
    return name


def _voucher_date(iso_value: str) -> str:
    raw = (iso_value or "")[:10]
    try:
        return dt.date.fromisoformat(raw).strftime("%Y%m%d")
    except Exception:
        return dt.date.today().strftime("%Y%m%d")


def _append_text(parent: ET.Element, tag: str, value: Any) -> ET.Element:
    el = ET.SubElement(parent, tag)
    el.text = str(value)
    return el


def build_voucher_xml(
    *,
    company: str,
    voucher_type: str,
    voucher_number: str,
    date: str,
    remote_id: str,
    entries: list[dict[str, Any]],
    narration: str,
    action: str = "Create",
) -> str:
    if action.lower() == "cancel":
        root = ET.Element("ENVELOPE")
        header = ET.SubElement(root, "HEADER")
        _append_text(header, "VERSION", 1)
        _append_text(header, "TALLYREQUEST", "Import")
        _append_text(header, "TYPE", "Data")
        _append_text(header, "ID", "Vouchers")
        body = ET.SubElement(root, "BODY")
        desc = ET.SubElement(body, "DESC")
        sv = ET.SubElement(desc, "STATICVARIABLES")
        if company:
            _append_text(sv, "SVCURRENTCOMPANY", company)
        data = ET.SubElement(body, "DATA")
        tm = ET.SubElement(data, "TALLYMESSAGE")
        voucher = ET.SubElement(
            tm,
            "VOUCHER",
            {
                "DATE": date,
                "TAGNAME": "VoucherNumber",
                "TAGVALUE": voucher_number,
                "ACTION": "Cancel",
                "VCHTYPE": voucher_type,
                "REMOTEID": remote_id,
            },
        )
        _append_text(voucher, "NARRATION", narration)
        return ET.tostring(root, encoding="unicode")

    debit = qmoney(sum(D(x["amount"]) for x in entries if x.get("debit")))
    credit = qmoney(sum(D(x["amount"]) for x in entries if not x.get("debit")))
    if debit != credit:
        raise TallySyncError(f"Refusing unbalanced Tally voucher: debit {debit} credit {credit}")

    root = ET.Element("ENVELOPE")
    header = ET.SubElement(root, "HEADER")
    _append_text(header, "VERSION", 1)
    _append_text(header, "TALLYREQUEST", "Import")
    _append_text(header, "TYPE", "Data")
    _append_text(header, "ID", "Vouchers")
    body = ET.SubElement(root, "BODY")
    desc = ET.SubElement(body, "DESC")
    sv = ET.SubElement(desc, "STATICVARIABLES")
    if company:
        _append_text(sv, "SVCURRENTCOMPANY", company)
    data = ET.SubElement(body, "DATA")
    tm = ET.SubElement(data, "TALLYMESSAGE")
    voucher = ET.SubElement(
        tm,
        "VOUCHER",
        {
            "REMOTEID": remote_id,
            "VCHTYPE": voucher_type,
            "ACTION": action,
            "OBJVIEW": "Accounting Voucher View",
        },
    )
    _append_text(voucher, "DATE", date)
    _append_text(voucher, "VOUCHERTYPENAME", voucher_type)
    _append_text(voucher, "VOUCHERNUMBER", voucher_number)
    _append_text(voucher, "PERSISTEDVIEW", "Accounting Voucher View")
    _append_text(voucher, "ISINVOICE", "No")
    _append_text(voucher, "NARRATION", narration)

    for item in entries:
        amount = qmoney(item["amount"])
        if not amount:
            continue
        debit_entry = bool(item.get("debit"))
        le = ET.SubElement(voucher, "LEDGERENTRIES.LIST")
        _append_text(le, "LEDGERNAME", item["ledger"])
        _append_text(le, "ISDEEMEDPOSITIVE", "Yes" if debit_entry else "No")
        _append_text(le, "ISLASTDEEMEDPOSITIVE", "Yes" if debit_entry else "No")
        if item.get("party"):
            _append_text(le, "ISPARTYLEDGER", "Yes")
        tally_amount = -amount if debit_entry else amount
        _append_text(le, "AMOUNT", money_text(tally_amount))
        if item.get("bill_ref"):
            bill = ET.SubElement(le, "BILLALLOCATIONS.LIST")
            _append_text(bill, "NAME", item["bill_ref"])
            _append_text(bill, "BILLTYPE", item.get("bill_type") or "New Ref")
            _append_text(bill, "AMOUNT", money_text(tally_amount))
    return ET.tostring(root, encoding="unicode")


def _mapping(mappings: dict[str, str], key: str) -> str:
    value = str(mappings.get(key) or "").strip()
    if not value:
        raise TallySyncError(f"Tally ledger mapping is blank: {key}")
    return value


def _tax_split_from_sale(sale: dict[str, Any]) -> tuple[Decimal, Decimal, Decimal]:
    cgst = qmoney(sale.get("cgst", 0))
    sgst = qmoney(sale.get("sgst", 0))
    igst = qmoney(sale.get("igst", 0))
    total = qmoney(sale.get("gst", 0))
    if cgst + sgst + igst == total:
        return cgst, sgst, igst
    if igst:
        return Decimal("0.00"), Decimal("0.00"), total
    cgst = qmoney(total / 2)
    return cgst, qmoney(total - cgst), Decimal("0.00")


def _required_static_ledgers(entries: list[dict[str, Any]], party_names: set[str]) -> set[str]:
    return {str(e["ledger"]) for e in entries if str(e["ledger"]) not in party_names and qmoney(e["amount"]) != 0}


def _load_payload(conn, row: dict[str, Any], settings: dict[str, str], mappings: dict[str, str]) -> tuple[str, set[str], list[tuple[dict[str, Any], str]]]:
    typ = row["entity_type"]
    entity_id = int(row["entity_id"])
    op = row["operation"]
    company = _setting(settings, "tally_company")
    party_to_create: list[tuple[dict[str, Any], str]] = []

    if typ in {"sale", "sale_cogs"}:
        sale_row = conn.execute("SELECT * FROM sales WHERE id=?", (entity_id,)).fetchone()
        if not sale_row:
            raise TallySyncError(f"Sale {entity_id} no longer exists")
        sale = dict(sale_row)
        customer_row = conn.execute("SELECT * FROM customers WHERE id=?", (sale["customer_id"],)).fetchone() if sale.get("customer_id") else None
        customer = dict(customer_row) if customer_row else None
        if typ == "sale":
            if qmoney(sale["payment_credit"]) and not customer:
                raise TallySyncError("Credit sale has no customer; Tally cannot create a debtor outstanding")
            entries: list[dict[str, Any]] = []
            if qmoney(sale["payment_cash"]):
                entries.append({"ledger": _mapping(mappings, "cash"), "amount": sale["payment_cash"], "debit": True})
            bank = qmoney(sale["payment_card"]) + qmoney(sale["payment_upi"])
            if bank:
                entries.append({"ledger": _mapping(mappings, "bank"), "amount": bank, "debit": True})
            party_names: set[str] = set()
            if qmoney(sale["payment_credit"]):
                party_name = str(customer["name"])
                party_names.add(party_name)
                party_to_create.append((customer, "Sundry Debtors"))
                entries.append({
                    "ledger": party_name,
                    "amount": sale["payment_credit"],
                    "debit": True,
                    "party": True,
                    "bill_ref": sale["invoice_no"],
                })
            if qmoney(sale["old_gold_value"]):
                entries.append({"ledger": _mapping(mappings, "old_gold"), "amount": sale["old_gold_value"], "debit": True})
            entries.append({"ledger": _mapping(mappings, "sales"), "amount": sale["taxable"], "debit": False})
            cgst, sgst, igst = _tax_split_from_sale(sale)
            if cgst:
                entries.append({"ledger": _mapping(mappings, "cgst"), "amount": cgst, "debit": False})
            if sgst:
                entries.append({"ledger": _mapping(mappings, "sgst"), "amount": sgst, "debit": False})
            if igst:
                entries.append({"ledger": _mapping(mappings, "igst"), "amount": igst, "debit": False})
            ro = qmoney(sale["round_off"])
            if ro:
                entries.append({"ledger": _mapping(mappings, "round_off"), "amount": abs(ro), "debit": ro < 0})
            xml = build_voucher_xml(
                company=company,
                voucher_type="Sales",
                voucher_number=sale["invoice_no"],
                date=_voucher_date(sale["created_at"]),
                remote_id=row["remote_id"],
                entries=entries,
                narration=f"JewelLAN sale {sale['invoice_no']}",
                action="Cancel" if op == "cancel" else "Create",
            )
            return xml, _required_static_ledgers(entries, party_names), party_to_create

        cost = qmoney(conn.execute("SELECT coalesce(sum(cost_amount),0) FROM sale_items WHERE sale_id=?", (entity_id,)).fetchone()[0])
        entries = [
            {"ledger": _mapping(mappings, "cogs"), "amount": cost, "debit": True},
            {"ledger": _mapping(mappings, "inventory"), "amount": cost, "debit": False},
        ]
        xml = build_voucher_xml(
            company=company,
            voucher_type="Journal",
            voucher_number=f"{sale['invoice_no']}-COGS",
            date=_voucher_date(sale["created_at"]),
            remote_id=row["remote_id"],
            entries=entries,
            narration=f"Cost of jewellery sold on {sale['invoice_no']}",
            action="Cancel" if op == "cancel" else "Create",
        )
        return xml, _required_static_ledgers(entries, set()), []

    if typ == "purchase":
        pur_row = conn.execute("SELECT * FROM purchases WHERE id=?", (entity_id,)).fetchone()
        if not pur_row:
            raise TallySyncError(f"Purchase {entity_id} no longer exists")
        pur = dict(pur_row)
        supplier_row = conn.execute("SELECT * FROM suppliers WHERE id=?", (pur["supplier_id"],)).fetchone() if pur.get("supplier_id") else None
        supplier = dict(supplier_row) if supplier_row else None
        payable = qmoney(pur["total"]) - qmoney(pur["paid"])
        if payable and not supplier:
            raise TallySyncError("Unpaid purchase has no supplier; Tally cannot create a creditor outstanding")
        entries: list[dict[str, Any]] = []
        party_names: set[str] = set()
        if qmoney(pur["subtotal"]):
            entries.append({"ledger": _mapping(mappings, "inventory"), "amount": pur["subtotal"], "debit": True})
        if qmoney(pur["gst"]):
            entries.append({"ledger": _mapping(mappings, "input_gst"), "amount": pur["gst"], "debit": True})
        if qmoney(pur["paid"]):
            entries.append({"ledger": _mapping(mappings, "cash"), "amount": pur["paid"], "debit": False})
        if payable:
            party_name = str(supplier["name"])
            party_names.add(party_name)
            party_to_create.append((supplier, "Sundry Creditors"))
            entries.append({
                "ledger": party_name,
                "amount": payable,
                "debit": False,
                "party": True,
                "bill_ref": pur["purchase_no"],
            })
        xml = build_voucher_xml(
            company=company,
            voucher_type="Purchase",
            voucher_number=pur["purchase_no"],
            date=_voucher_date(pur["created_at"]),
            remote_id=row["remote_id"],
            entries=entries,
            narration=f"JewelLAN purchase {pur['purchase_no']}",
            action="Create",
        )
        return xml, _required_static_ledgers(entries, party_names), party_to_create

    raise TallySyncError(f"Unsupported Tally queue entity type: {typ}")


def sync_queue_item(queue_id: int) -> dict[str, Any]:
    with read_db() as conn:
        row0 = conn.execute("SELECT * FROM tally_sync_queue WHERE id=?", (queue_id,)).fetchone()
        if not row0:
            raise TallySyncError("Queue item not found")
        row = dict(row0)
        settings = get_settings(conn)
        mappings = get_mappings(conn)
        xml, required_ledgers, parties = _load_payload(conn, row, settings, mappings)

    if _setting(settings, "tally_enabled", "0").lower() not in {"1", "true", "yes", "on"}:
        raise TallySyncError("Tally integration is disabled")
    if not _setting(settings, "tally_company"):
        raise TallySyncError("Tally company is not configured")

    for party, parent in parties:
        _ensure_party_ledger(settings, party, parent)
    ledgers = bridge_ledgers(settings)
    missing = sorted(required_ledgers - ledgers)
    if missing:
        raise TallySyncError("Missing mapped Tally ledgers: " + ", ".join(missing))

    payload_hash = hashlib.sha256(xml.encode("utf-8")).hexdigest()
    result = _bridge_request(settings, "POST", "/import", body={"company": _setting(settings, "tally_company"), "xml": xml}, timeout=30)
    errors = int(result.get("errors", 0) or 0)
    accepted = sum(int(result.get(k, 0) or 0) for k in ("created", "altered", "combined", "cancelled"))
    if errors or accepted < 1:
        message = result.get("line_error") or result.get("raw_summary") or json.dumps(result, ensure_ascii=False)
        raise TallySyncError(f"Tally did not accept voucher: {message}")
    return {
        "payload_hash": payload_hash,
        "tally_master_id": result.get("last_vch_id") or result.get("last_mid"),
        "tally_voucher_no": result.get("voucher_number"),
        "response": result,
    }


def process_pending(limit: int = 25) -> dict[str, int]:
    now = utcnow()
    with read_db() as conn:
        ids = [
            r["id"]
            for r in conn.execute(
                """SELECT id FROM tally_sync_queue
                   WHERE status IN ('pending','failed')
                     AND (next_attempt_at IS NULL OR next_attempt_at<=?)
                   ORDER BY id LIMIT ?""",
                (now, limit),
            ).fetchall()
        ]
    counts = {"processed": 0, "synced": 0, "failed": 0}
    for queue_id in ids:
        counts["processed"] += 1
        with write_db() as conn:
            conn.execute("UPDATE tally_sync_queue SET status='sending',updated_at=? WHERE id=?", (utcnow(), queue_id))
        try:
            result = sync_queue_item(queue_id)
        except Exception as exc:
            with write_db() as conn:
                row = conn.execute("SELECT attempt_count FROM tally_sync_queue WHERE id=?", (queue_id,)).fetchone()
                attempts = int(row[0] if row else 0) + 1
                delay = min(3600, 15 * (2 ** min(attempts, 8)))
                next_at = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=delay)).replace(microsecond=0).isoformat()
                conn.execute(
                    """UPDATE tally_sync_queue
                       SET status='failed',attempt_count=?,last_error=?,next_attempt_at=?,updated_at=?
                       WHERE id=?""",
                    (attempts, str(exc)[:2000], next_at, utcnow(), queue_id),
                )
            counts["failed"] += 1
            continue
        with write_db() as conn:
            conn.execute(
                """UPDATE tally_sync_queue
                   SET status='synced',payload_hash=?,tally_master_id=?,tally_voucher_no=?,
                       response_json=?,last_error=NULL,next_attempt_at=NULL,synced_at=?,updated_at=?
                   WHERE id=?""",
                (
                    result["payload_hash"],
                    str(result.get("tally_master_id") or ""),
                    str(result.get("tally_voucher_no") or ""),
                    json.dumps(result["response"], ensure_ascii=False),
                    utcnow(),
                    utcnow(),
                    queue_id,
                ),
            )
        counts["synced"] += 1
    return counts


def validate_mappings(settings: dict[str, str], mappings: dict[str, str]) -> dict[str, Any]:
    ledgers = bridge_ledgers(settings, force=True)
    required = {
        mappings[k]
        for k in ("cash", "bank", "sales", "inventory", "cogs", "old_gold", "input_gst", "cgst", "sgst", "igst", "round_off")
        if mappings.get(k)
    }
    missing = required - ledgers
    return {"ledger_count": len(ledgers), "missing": sorted(missing), "ok": not missing}


def backfill_queue() -> dict[str, int]:
    counts = {"sales": 0, "sale_cogs": 0, "purchases": 0}
    with write_db() as conn:
        for s in conn.execute("SELECT id,status FROM sales ORDER BY id").fetchall():
            op = "cancel" if s["status"] == "cancelled" else "create"
            enqueue_tally(conn, "sale", s["id"], op)
            counts["sales"] += 1
            cost = qmoney(conn.execute("SELECT coalesce(sum(cost_amount),0) FROM sale_items WHERE sale_id=?", (s["id"],)).fetchone()[0])
            if cost:
                enqueue_tally(conn, "sale_cogs", s["id"], op)
                counts["sale_cogs"] += 1
        for p in conn.execute("SELECT id FROM purchases ORDER BY id").fetchall():
            enqueue_tally(conn, "purchase", p["id"], "create")
            counts["purchases"] += 1
    return counts


def reconcile(date_from: str, date_to: str) -> dict[str, Any]:
    with read_db() as conn:
        settings = get_settings(conn)
        sales = rowsdict(
            conn.execute(
                """SELECT s.id,s.invoice_no,s.total,s.status,s.created_at,
                          coalesce(sum(si.cost_amount),0) cogs
                   FROM sales s LEFT JOIN sale_items si ON si.sale_id=s.id
                   WHERE substr(s.created_at,1,10) BETWEEN ? AND ?
                   GROUP BY s.id ORDER BY s.id""",
                (date_from, date_to),
            ).fetchall()
        )
        purchases = rowsdict(
            conn.execute(
                "SELECT id,purchase_no,total,created_at FROM purchases WHERE substr(created_at,1,10) BETWEEN ? AND ? ORDER BY id",
                (date_from, date_to),
            ).fetchall()
        )
    remote = _bridge_request(
        settings,
        "GET",
        "/daybook",
        params={"company": _setting(settings, "tally_company"), "date_from": date_from, "date_to": date_to},
        timeout=45,
    )
    vouchers = remote.get("vouchers", [])
    by_key = {(str(v.get("type") or "").lower(), str(v.get("number") or "")): v for v in vouchers}
    expected: list[dict[str, Any]] = []
    for s in sales:
        if s["status"] != "posted":
            continue
        expected.append({"type": "Sales", "number": s["invoice_no"], "amount": float(qmoney(s["total"]))})
        if qmoney(s["cogs"]):
            expected.append({"type": "Journal", "number": f"{s['invoice_no']}-COGS", "amount": float(qmoney(s["cogs"]))})
    for p in purchases:
        expected.append({"type": "Purchase", "number": p["purchase_no"], "amount": float(qmoney(p["total"]))})
    missing = []
    amount_mismatches = []
    for e in expected:
        r = by_key.get((e["type"].lower(), e["number"]))
        if not r:
            missing.append(e)
            continue
        if r.get("amount") is not None and abs(float(r["amount"]) - e["amount"]) > 0.05:
            amount_mismatches.append({"expected": e, "tally": r})
    return {
        "date_from": date_from,
        "date_to": date_to,
        "expected_count": len(expected),
        "found_count": len(expected) - len(missing),
        "missing": missing,
        "amount_mismatches": amount_mismatches,
        "tally_voucher_count": len(vouchers),
        "ok": not missing and not amount_mismatches,
    }


class TallySyncWorker(threading.Thread):
    daemon = True

    def __init__(self):
        super().__init__(name="JewelLAN-TallySync")
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()

    def wake(self) -> None:
        self.wake_event.set()

    def run(self) -> None:
        if self.stop_event.wait(10):
            return
        while not self.stop_event.is_set():
            try:
                with read_db() as conn:
                    settings = get_settings(conn)
                enabled = _setting(settings, "tally_enabled", "0").lower() in {"1", "true", "yes", "on"}
                if enabled:
                    process_pending(25)
            except Exception:
                pass
            self.wake_event.wait(20)
            self.wake_event.clear()

    def stop(self) -> None:
        self.stop_event.set()
        self.wake_event.set()
