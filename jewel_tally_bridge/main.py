from __future__ import annotations

import argparse
import datetime as dt
import os
import secrets
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from .xml_compat import parse_tally_xml

import requests
import uvicorn
from fastapi import Body, FastAPI, Header, HTTPException, Query

APP_VERSION = "1.1.0"


def data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
    else:
        base = Path(os.environ.get("JEWELLAN_DATA_DIR", Path.home() / ".jewellan"))
    p = base / "JewelLAN"
    p.mkdir(parents=True, exist_ok=True)
    return p


def token_path() -> Path:
    return data_dir() / "tally-bridge-token.txt"


def get_or_create_token() -> str:
    env = str(os.environ.get("JEWELLAN_TALLY_BRIDGE_TOKEN") or "").strip()
    if env:
        return env
    p = token_path()
    if p.exists():
        token = p.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = secrets.token_urlsafe(32)
    p.write_text(token, encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return token


BRIDGE_TOKEN = get_or_create_token()
TALLY_URL = str(os.environ.get("JEWELLAN_TALLY_URL") or "http://127.0.0.1:9000").rstrip("/")
app = FastAPI(title="JewelLAN Tally Bridge", version=APP_VERSION, docs_url=None, redoc_url=None)


def require_token(authorization: str | None) -> None:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Bridge authentication required")
    supplied = authorization.split(" ", 1)[1].strip()
    if not secrets.compare_digest(supplied, BRIDGE_TOKEN):
        raise HTTPException(403, "Invalid bridge token")


def _post_tally(xml: str, timeout: float = 20) -> str:
    try:
        r = requests.post(TALLY_URL, data=xml.encode("utf-8"), headers={"Content-Type": "text/xml; charset=utf-8"}, timeout=timeout)
    except requests.RequestException as exc:
        raise HTTPException(503, f"TallyPrime is unavailable at {TALLY_URL}: {exc}") from exc
    if r.status_code >= 400:
        raise HTTPException(502, f"TallyPrime returned HTTP {r.status_code}")
    return r.content.decode(r.encoding or "utf-8", errors="replace")


def _tag_name(tag: str) -> str:
    return tag.split("}")[-1].upper()


def _child_text(el: ET.Element, name: str) -> str:
    wanted = name.upper()
    for child in list(el):
        if _tag_name(child.tag) == wanted:
            return (child.text or "").strip()
    return ""


def _int_any(root: ET.Element, name: str) -> int:
    wanted = name.upper()
    for el in root.iter():
        if _tag_name(el.tag) == wanted:
            try:
                return int(float((el.text or "0").strip() or 0))
            except ValueError:
                return 0
    return 0


def parse_import_response(xml: str) -> dict[str, Any]:
    try:
        root = parse_tally_xml(xml)
    except ET.ParseError as exc:
        raise HTTPException(502, f"TallyPrime returned malformed XML: {exc}") from exc
    line_errors = []
    for el in root.iter():
        if _tag_name(el.tag) in {"LINEERROR", "DESC"}:
            txt = (el.text or "").strip()
            if txt and txt not in line_errors:
                line_errors.append(txt)
    result = {
        "created": _int_any(root, "CREATED"),
        "altered": _int_any(root, "ALTERED"),
        "deleted": _int_any(root, "DELETED"),
        "combined": _int_any(root, "COMBINED"),
        "ignored": _int_any(root, "IGNORED"),
        "errors": _int_any(root, "ERRORS"),
        "cancelled": _int_any(root, "CANCELLED"),
        "last_vch_id": _int_any(root, "LASTVCHID"),
        "last_mid": _int_any(root, "LASTMID"),
        "voucher_number": next(((el.text or "").strip() for el in root.iter() if _tag_name(el.tag) == "VCHNUMBER" and (el.text or "").strip()), ""),
        "line_error": " | ".join(line_errors[:6]),
    }
    result["raw_summary"] = f"created={result['created']} altered={result['altered']} cancelled={result['cancelled']} ignored={result['ignored']} errors={result['errors']}"
    return result


def _company_static(desc: ET.Element, company: str) -> None:
    sv = ET.SubElement(desc, "STATICVARIABLES")
    ET.SubElement(sv, "SVEXPORTFORMAT").text = "$$SysName:XML"
    if company:
        ET.SubElement(sv, "SVCURRENTCOMPANY").text = company


def list_ledgers_xml(company: str) -> str:
    root = ET.Element("ENVELOPE")
    h = ET.SubElement(root, "HEADER")
    ET.SubElement(h, "VERSION").text = "1"
    ET.SubElement(h, "TALLYREQUEST").text = "Export"
    ET.SubElement(h, "TYPE").text = "Collection"
    ET.SubElement(h, "ID").text = "JewelLAN Ledgers"
    body = ET.SubElement(root, "BODY")
    desc = ET.SubElement(body, "DESC")
    _company_static(desc, company)
    tdl = ET.SubElement(desc, "TDL")
    msg = ET.SubElement(tdl, "TDLMESSAGE")
    coll = ET.SubElement(msg, "COLLECTION", {"NAME": "JewelLAN Ledgers", "ISINITIALIZE": "Yes"})
    ET.SubElement(coll, "TYPE").text = "Ledger"
    ET.SubElement(coll, "NATIVEMETHOD").text = "Name"
    return ET.tostring(root, encoding="unicode")


def parse_ledgers(xml: str) -> list[str]:
    try:
        root = parse_tally_xml(xml)
    except ET.ParseError as exc:
        raise HTTPException(502, f"Could not parse Tally ledger response: {exc}") from exc
    names = set()
    for el in root.iter():
        if _tag_name(el.tag) != "LEDGER":
            continue
        name = (el.attrib.get("NAME") or _child_text(el, "NAME") or "").strip()
        if name:
            names.add(name)
    return sorted(names, key=str.casefold)


def build_ledger_xml(company: str, name: str, parent: str, gstin: str = "", address: str = "", phone: str = "") -> str:
    root = ET.Element("ENVELOPE")
    h = ET.SubElement(root, "HEADER")
    ET.SubElement(h, "VERSION").text = "1"
    ET.SubElement(h, "TALLYREQUEST").text = "Import"
    ET.SubElement(h, "TYPE").text = "Data"
    ET.SubElement(h, "ID").text = "All Masters"
    body = ET.SubElement(root, "BODY")
    desc = ET.SubElement(body, "DESC")
    sv = ET.SubElement(desc, "STATICVARIABLES")
    if company:
        ET.SubElement(sv, "SVCURRENTCOMPANY").text = company
    data = ET.SubElement(body, "DATA")
    tm = ET.SubElement(data, "TALLYMESSAGE")
    ledger = ET.SubElement(tm, "LEDGER", {"NAME": name, "ACTION": "Create"})
    names = ET.SubElement(ledger, "NAME.LIST", {"TYPE": "String"})
    ET.SubElement(names, "NAME").text = name
    ET.SubElement(ledger, "PARENT").text = parent
    if address:
        al = ET.SubElement(ledger, "ADDRESS.LIST", {"TYPE": "String"})
        for line in [x.strip() for x in address.replace("\r", "").split("\n") if x.strip()]:
            ET.SubElement(al, "ADDRESS").text = line
    if gstin:
        ET.SubElement(ledger, "PARTYGSTIN").text = gstin
    if phone:
        ET.SubElement(ledger, "LEDGERPHONE").text = phone
    return ET.tostring(root, encoding="unicode")


def _tally_date(iso_date: str) -> str:
    try:
        d = dt.date.fromisoformat(iso_date)
    except ValueError:
        raise HTTPException(400, f"Invalid date: {iso_date}")
    return f"{d.day}-{d.strftime('%b-%Y')}"


def daybook_xml(company: str, date_from: str, date_to: str) -> str:
    root = ET.Element("ENVELOPE")
    h = ET.SubElement(root, "HEADER")
    ET.SubElement(h, "VERSION").text = "1"
    ET.SubElement(h, "TALLYREQUEST").text = "Export"
    ET.SubElement(h, "TYPE").text = "Data"
    ET.SubElement(h, "ID").text = "DayBook"
    body = ET.SubElement(root, "BODY")
    desc = ET.SubElement(body, "DESC")
    sv = ET.SubElement(desc, "STATICVARIABLES")
    ET.SubElement(sv, "SVEXPORTFORMAT").text = "$$SysName:XML"
    if company:
        ET.SubElement(sv, "SVCURRENTCOMPANY").text = company
    ET.SubElement(sv, "SVFROMDATE", {"TYPE": "Date"}).text = _tally_date(date_from)
    ET.SubElement(sv, "SVTODATE", {"TYPE": "Date"}).text = _tally_date(date_to)
    return ET.tostring(root, encoding="unicode")


def parse_daybook(xml: str) -> list[dict[str, Any]]:
    try:
        root = parse_tally_xml(xml)
    except ET.ParseError as exc:
        raise HTTPException(502, f"Could not parse Tally Day Book: {exc}") from exc
    out = []
    for v in root.iter():
        if _tag_name(v.tag) != "VOUCHER":
            continue
        number = _child_text(v, "VOUCHERNUMBER") or v.attrib.get("VOUCHERNUMBER", "")
        vtype = _child_text(v, "VOUCHERTYPENAME") or v.attrib.get("VCHTYPE", "")
        if not number or not vtype:
            continue
        positives = []
        absolutes = []
        for le in list(v):
            if _tag_name(le.tag) not in {"LEDGERENTRIES.LIST", "ALLLEDGERENTRIES.LIST"}:
                continue
            raw = _child_text(le, "AMOUNT")
            try:
                amount = float(raw.replace(",", ""))
            except ValueError:
                continue
            absolutes.append(abs(amount))
            if amount > 0:
                positives.append(amount)
        amount = round(sum(positives), 2) if positives else (round(max(absolutes), 2) if absolutes else None)
        out.append({
            "number": number,
            "type": vtype,
            "date": _child_text(v, "DATE"),
            "remote_id": v.attrib.get("REMOTEID", ""),
            "master_id": _child_text(v, "MASTERID"),
            "amount": amount,
        })
    return out


@app.get("/health")
def health(company: str = Query(default=""), authorization: str | None = Header(default=None)):
    require_token(authorization)
    xml = list_ledgers_xml(company)
    response = _post_tally(xml, timeout=5)
    ledgers = parse_ledgers(response)
    return {"ok": True, "bridge_version": APP_VERSION, "tally_url": TALLY_URL, "company": company, "ledger_count": len(ledgers)}


@app.get("/ledgers")
def ledgers(company: str = Query(default=""), authorization: str | None = Header(default=None)):
    require_token(authorization)
    response = _post_tally(list_ledgers_xml(company), timeout=20)
    return {"ok": True, "ledgers": parse_ledgers(response)}


@app.post("/ledgers")
def create_ledger(payload: dict = Body(...), authorization: str | None = Header(default=None)):
    require_token(authorization)
    company = str(payload.get("company") or "")
    name = str(payload.get("name") or "").strip()
    parent = str(payload.get("parent") or "").strip()
    if not name or not parent:
        raise HTTPException(400, "Ledger name and parent are required")
    current = set(parse_ledgers(_post_tally(list_ledgers_xml(company), timeout=20)))
    if name in current:
        return {"ok": True, "existing": True}
    xml = build_ledger_xml(company, name, parent, str(payload.get("gstin") or ""), str(payload.get("address") or ""), str(payload.get("phone") or ""))
    result = parse_import_response(_post_tally(xml, timeout=20))
    if result["errors"] or (result["created"] + result["altered"] + result["combined"] < 1):
        return {"ok": False, "error": result["line_error"] or result["raw_summary"], "result": result}
    return {"ok": True, "existing": False, "result": result}


@app.post("/import")
def import_xml(payload: dict = Body(...), authorization: str | None = Header(default=None)):
    require_token(authorization)
    xml = str(payload.get("xml") or "").strip()
    if not xml.startswith("<ENVELOPE"):
        raise HTTPException(400, "Only Tally ENVELOPE XML is accepted")
    return parse_import_response(_post_tally(xml, timeout=30))


@app.get("/daybook")
def daybook(
    company: str = Query(default=""),
    date_from: str = Query(...),
    date_to: str = Query(...),
    authorization: str | None = Header(default=None),
):
    require_token(authorization)
    response = _post_tally(daybook_xml(company, date_from, date_to), timeout=45)
    return {"ok": True, "vouchers": parse_daybook(response)}


def cli() -> None:
    global TALLY_URL
    p = argparse.ArgumentParser(description="JewelLAN local TallyPrime bridge")
    p.add_argument("--host", default=os.environ.get("JEWELLAN_TALLY_BRIDGE_HOST", "0.0.0.0"))
    p.add_argument("--port", type=int, default=int(os.environ.get("JEWELLAN_TALLY_BRIDGE_PORT", "8767")))
    p.add_argument("--tally-url", default=TALLY_URL)
    p.add_argument("--show-token", action="store_true")
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    TALLY_URL = str(args.tally_url).rstrip("/")
    if args.self_test:
        assert BRIDGE_TOKEN and token_path().parent.exists()
        print("JewelTallyBridge self-test OK")
        return
    if args.show_token:
        print(BRIDGE_TOKEN)
        print(f"Token file: {token_path()}")
        try: input("Press Enter to close…")
        except EOFError: pass
        return
    print("JewelLAN Tally Bridge")
    print("TallyPrime:", TALLY_URL)
    print("Bridge token file:", token_path())
    uvicorn.run(app, host=args.host, port=args.port, log_level="info", access_log=False)


if __name__ == "__main__":
    cli()
