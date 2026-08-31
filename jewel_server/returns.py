from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from fastapi import HTTPException

from .db import audit, business_date, business_now, day_is_closed, next_sequence, request_fingerprint, utcnow
from .precision import money, money_paise
from .services import _journal, _record_payments, require_client_request_id
from .tally import enqueue_tally


def _rupees(paise: int) -> float:
    return money(Decimal(int(paise)) / Decimal(100))


def _round_off_allocations(conn, sale_id: int) -> dict[int, int]:
    sale = conn.execute("SELECT round_off_paise FROM sales WHERE id=?", (sale_id,)).fetchone()
    lines = conn.execute(
        "SELECT id,line_total_paise FROM sale_items WHERE sale_id=? ORDER BY id", (sale_id,)
    ).fetchall()
    if not sale or not lines:
        return {}
    target = int(sale["round_off_paise"] or 0)
    total_lines = sum(int(x["line_total_paise"] or 0) for x in lines)
    if not target or not total_lines:
        return {int(x["id"]): 0 for x in lines}
    out: dict[int, int] = {}
    remaining = target
    for line in lines[:-1]:
        share = int(
            (Decimal(target) * Decimal(int(line["line_total_paise"] or 0)) / Decimal(total_lines)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
        out[int(line["id"])] = share
        remaining -= share
    out[int(lines[-1]["id"])] = remaining
    return out


def _split_return_gst(sale: dict[str, Any], gst_paise: int) -> tuple[int, int, int]:
    if int(sale.get("igst_paise") or 0):
        return 0, 0, gst_paise
    cgst = int((Decimal(gst_paise) / Decimal(2)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return cgst, gst_paise - cgst, 0


def _adjust_customer_balance(conn, customer_id: int | None, delta_paise: int, now: str) -> None:
    if not customer_id or not delta_paise:
        return
    row = conn.execute("SELECT balance_paise FROM customers WHERE id=?", (customer_id,)).fetchone()
    if not row:
        raise HTTPException(409, "Customer no longer exists")
    new_paise = int(row["balance_paise"] or 0) + int(delta_paise)
    conn.execute(
        "UPDATE customers SET balance=?,balance_paise=?,updated_at=? WHERE id=?",
        (_rupees(new_paise), new_paise, now, customer_id),
    )


def _return_payload(conn, return_id: int) -> dict[str, Any]:
    row = conn.execute(
        """SELECT r.*,s.invoice_no,c.name customer_name
           FROM sale_returns r
           JOIN sales s ON s.id=r.sale_id
           LEFT JOIN customers c ON c.id=r.customer_id
           WHERE r.id=?""",
        (return_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Return not found")
    r = dict(row)
    for key in (
        "taxable","gst","cgst","sgst","igst","round_off","total",
        "refund_cash","refund_card","refund_upi","refund_credit",
    ):
        r[key] = _rupees(int(r.get(key + "_paise") or 0))
    items = []
    for line in conn.execute(
        "SELECT * FROM sale_return_items WHERE return_id=? ORDER BY id", (return_id,)
    ).fetchall():
        item = dict(line)
        for key in ("taxable","gst_amount","round_off","line_total","cost_amount"):
            item[key] = _rupees(int(item.get(key + "_paise") or 0))
        items.append(item)
    return {"return": r, "items": items}


def quote_sale_return(conn, sale_id: int, sale_item_ids: list[int] | None = None) -> dict[str, Any]:
    sale_row=conn.execute("SELECT * FROM sales WHERE id=?",(sale_id,)).fetchone()
    if not sale_row:raise HTTPException(404,"Sale not found")
    sale=dict(sale_row)
    if sale["status"]!="posted":raise HTTPException(409,"Cancelled invoices cannot be returned")
    requested=[] if sale_item_ids is None else [int(x) for x in sale_item_ids]
    if len(requested)!=len(set(requested)):raise HTTPException(400,"Select unique invoice items")
    all_lines=conn.execute("SELECT si.*,i.status item_status FROM sale_items si JOIN items i ON i.id=si.item_id WHERE si.sale_id=? ORDER BY si.id",(sale_id,)).fetchall()
    line_ids={int(x["id"]) for x in all_lines}
    if any(i not in line_ids for i in requested):raise HTTPException(400,"A selected item does not belong to this invoice")
    active={int(x[0]) for x in conn.execute("SELECT ri.sale_item_id FROM sale_return_items ri JOIN sale_returns r ON r.id=ri.return_id WHERE r.status='posted' AND ri.active=1 AND ri.sale_item_id IN (SELECT id FROM sale_items WHERE sale_id=?)",(sale_id,)).fetchall()}
    allocations=_round_off_allocations(conn,sale_id);selected=set(requested);lines=[];taxable=gst=round_off=total=cost=0
    for raw in all_lines:
        line=dict(raw);line_id=int(line["id"]);already=line_id in active;returnable=(not already and line["item_status"]=="sold")
        ro=int(allocations.get(line_id,0));line_total=int(line["line_total_paise"] or 0)+ro
        if line_id in selected and not returnable:raise HTTPException(409,f"Tag {line['tag_no']} is not currently returnable")
        entry={"sale_item_id":line_id,"item_id":line["item_id"],"tag_no":line["tag_no"],"description":line["description"],"metal":line["metal"],"purity":line["purity"],"item_status":line["item_status"],"already_returned":already,"returnable":returnable,"selected":line_id in selected,"taxable":_rupees(int(line["taxable_paise"] or 0)),"gst":_rupees(int(line["gst_amount_paise"] or 0)),"round_off":_rupees(ro),"total":_rupees(line_total),"cost":_rupees(int(line["cost_amount_paise"] or 0))}
        lines.append(entry)
        if line_id in selected:
            taxable+=int(line["taxable_paise"] or 0);gst+=int(line["gst_amount_paise"] or 0);round_off+=ro;total+=line_total;cost+=int(line["cost_amount_paise"] or 0)
    cgst,sgst,igst=_split_return_gst(sale,gst)
    customer=None
    if sale.get("customer_id"):
        row=conn.execute("SELECT id,code,name,phone,gstin,balance,balance_paise FROM customers WHERE id=?",(sale["customer_id"],)).fetchone();customer=dict(row) if row else None
    return {"sale":{"id":sale["id"],"invoice_no":sale["invoice_no"],"business_date":sale.get("business_date"),"customer_id":sale.get("customer_id"),"total":_rupees(int(sale["total_paise"] or 0))},"customer":customer,"lines":lines,"selected_count":len(selected),"taxable":_rupees(taxable),"gst":_rupees(gst),"cgst":_rupees(cgst),"sgst":_rupees(sgst),"igst":_rupees(igst),"round_off":_rupees(round_off),"total":_rupees(total),"cost":_rupees(cost)}


def post_sale_return(conn, sale_id: int, payload: dict[str, Any], user: dict[str, Any], client_ip: str | None = None) -> dict[str, Any]:
    req = require_client_request_id(payload, "sale return")
    fingerprint = request_fingerprint("sale_return", payload)
    old = conn.execute("SELECT id,request_fingerprint FROM sale_returns WHERE client_request_id=?", (req,)).fetchone()
    if old:
        if old["request_fingerprint"] and old["request_fingerprint"] != fingerprint:
            raise HTTPException(409, detail={"code":"IDEMPOTENCY_CONFLICT","message":"This request ID was already used for different return data","request_id":req})
        return _return_payload(conn, int(old["id"])) | {"idempotent": True}

    reason = str(payload.get("reason") or "").strip()
    if len(reason) < 3:
        raise HTTPException(400, "Return reason is required")
    sale_row = conn.execute("SELECT * FROM sales WHERE id=?", (sale_id,)).fetchone()
    if not sale_row:
        raise HTTPException(404, "Sale not found")
    sale = dict(sale_row)
    if sale["status"] != "posted":
        raise HTTPException(409, "Cancelled invoices cannot be returned")
    return_business_day = business_date(conn)
    if day_is_closed(conn, int(sale["branch_id"]), return_business_day):
        raise HTTPException(409, detail={"code":"DAY_CLOSED","message":"Returns cannot be posted on a closed business date"})

    requested = payload.get("sale_item_ids") or []
    try:
        selected_ids = [int(x) for x in requested]
    except (TypeError, ValueError):
        raise HTTPException(400, "Invalid sale item selection")
    if not selected_ids or len(set(selected_ids)) != len(selected_ids):
        raise HTTPException(400, "Select one or more unique invoice items to return")

    all_lines = conn.execute("SELECT * FROM sale_items WHERE sale_id=? ORDER BY id", (sale_id,)).fetchall()
    line_map = {int(x["id"]): x for x in all_lines}
    if any(i not in line_map for i in selected_ids):
        raise HTTPException(400, "A selected item does not belong to this invoice")

    placeholders = ",".join("?" for _ in selected_ids)
    active = conn.execute(
        f"SELECT sale_item_id FROM sale_return_items WHERE active=1 AND sale_item_id IN ({placeholders})",
        selected_ids,
    ).fetchall()
    if active:
        raise HTTPException(409, "One or more selected invoice items have already been returned")

    allocations = _round_off_allocations(conn, sale_id)
    dispositions = payload.get("dispositions") if isinstance(payload.get("dispositions"), dict) else {}
    default_disposition = str(payload.get("disposition") or "in_stock").strip().lower()
    allowed_dispositions = {"in_stock", "damaged", "scrap"}
    taxable_paise = 0
    gst_paise = 0
    round_off_paise = 0
    total_paise = 0
    cost_paise = 0
    selected = []
    for line_id in selected_ids:
        line = line_map[line_id]
        item = conn.execute("SELECT status FROM items WHERE id=?", (line["item_id"],)).fetchone()
        if not item or item["status"] != "sold":
            raise HTTPException(409, f"Tag {line['tag_no']} is not currently sold and cannot be returned")
        disposition = str(dispositions.get(str(line_id), dispositions.get(line_id, default_disposition))).strip().lower()
        if disposition not in allowed_dispositions:
            raise HTTPException(400, "Return disposition must be in_stock, damaged, or scrap")
        ro = int(allocations.get(line_id, 0))
        taxable = int(line["taxable_paise"] or 0)
        gst = int(line["gst_amount_paise"] or 0)
        line_total = int(line["line_total_paise"] or 0) + ro
        cost = int(line["cost_amount_paise"] or 0)
        if line_total < 0:
            raise HTTPException(409, "Stored invoice line is invalid")
        selected.append((line, taxable, gst, ro, line_total, cost, disposition))
        taxable_paise += taxable
        gst_paise += gst
        round_off_paise += ro
        total_paise += line_total
        cost_paise += cost

    refund_cash = money_paise(payload.get("refund_cash", 0))
    refund_card = money_paise(payload.get("refund_card", 0))
    refund_upi = money_paise(payload.get("refund_upi", 0))
    refund_credit = money_paise(payload.get("refund_credit", 0))
    refunds = refund_cash + refund_card + refund_upi + refund_credit
    if min(refund_cash, refund_card, refund_upi, refund_credit) < 0:
        raise HTTPException(400, "Refund amounts cannot be negative")
    if refunds != total_paise:
        raise HTTPException(400, f"Refunds ({_rupees(refunds):.2f}) must equal return total ({_rupees(total_paise):.2f})")
    if refund_credit and not sale.get("customer_id"):
        raise HTTPException(400, "Customer account credit requires an invoice customer")

    cgst_paise, sgst_paise, igst_paise = _split_return_gst(sale, gst_paise)
    now = utcnow()
    ret_no = next_sequence(conn, "return", "CN-" + business_now(conn).strftime("%y%m") + "-", 6)
    cur = conn.execute(
        """INSERT INTO sale_returns(
             return_no,client_request_id,request_fingerprint,print_snapshot_json,sale_id,customer_id,branch_id,business_date,
             taxable_paise,gst_paise,cgst_paise,sgst_paise,igst_paise,round_off_paise,total_paise,
             refund_cash_paise,refund_card_paise,refund_upi_paise,refund_credit_paise,
             reason,status,user_id,created_at
           ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'posted',?,?)""",
        (
            ret_no,req,fingerprint,sale.get("print_snapshot_json") or "{}",sale_id,sale.get("customer_id"),sale["branch_id"],return_business_day,
            taxable_paise,gst_paise,cgst_paise,sgst_paise,igst_paise,round_off_paise,total_paise,
            refund_cash,refund_card,refund_upi,refund_credit,reason,user["id"],now,
        ),
    )
    return_id = int(cur.lastrowid)
    refs = payload.get("refund_references") if isinstance(payload.get("refund_references"), dict) else {}
    _record_payments(conn, "sale_return", return_id, [
        ("cash", refund_cash, "1000", refs.get("cash")),
        ("card", refund_card, "1010", refs.get("card")),
        ("upi", refund_upi, "1010", refs.get("upi")),
        ("credit", refund_credit, "1100", refs.get("credit")),
    ], user["id"], now, direction="out")

    for line, taxable, gst, ro, line_total, cost, disposition in selected:
        conn.execute(
        """INSERT INTO sale_return_items(
                 return_id,sale_item_id,item_id,tag_no,taxable_paise,gst_amount_paise,
                 round_off_paise,line_total_paise,cost_amount_paise,active,disposition
               ) VALUES(?,?,?,?,?,?,?,?,?,1,?)""",
            (return_id,line["id"],line["item_id"],line["tag_no"],taxable,gst,ro,line_total,cost,disposition),
        )
        target_status = disposition
        updated = conn.execute(
            "UPDATE items SET status=?,version=version+1,updated_at=? WHERE id=? AND status='sold'",
            (target_status, now, line["item_id"]),
        )
        if updated.rowcount != 1:
            raise HTTPException(409, f"Tag {line['tag_no']} changed on another counter")
        conn.execute(
            """INSERT INTO stock_movements(item_id,movement_type,ref_type,ref_id,from_location,to_location,gross_weight,user_id,note,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (line["item_id"],"sale_return","sale_return",return_id,"customer",f"branch:{sale['branch_id']}",line["gross_weight"],user["id"],f"{ret_no}:{disposition}",now),
        )

    _adjust_customer_balance(conn, sale.get("customer_id"), -refund_credit, now)

    journal_lines = []
    if taxable_paise:
        journal_lines.append(("4000", _rupees(taxable_paise), 0, None, None))
    if gst_paise:
        journal_lines.append(("2100", _rupees(gst_paise), 0, None, None))
    if round_off_paise > 0:
        journal_lines.append(("4000", _rupees(round_off_paise), 0, None, None))
    elif round_off_paise < 0:
        journal_lines.append(("4000", 0, _rupees(-round_off_paise), None, None))
    if refund_cash:
        journal_lines.append(("1000", 0, _rupees(refund_cash), None, None))
    if refund_card + refund_upi:
        journal_lines.append(("1010", 0, _rupees(refund_card + refund_upi), None, None))
    if refund_credit:
        journal_lines.append(("1100", 0, _rupees(refund_credit), "customer", sale.get("customer_id")))
    if cost_paise:
        journal_lines += [
            ("1200", _rupees(cost_paise), 0, None, None),
            ("5000", 0, _rupees(cost_paise), None, None),
        ]
    _journal(conn,user["id"],f"Sales return {ret_no} against {sale['invoice_no']}","sale_return",return_id,journal_lines)
    audit(conn,user["id"],"create","sale_return",return_id,{"return_no":ret_no,"invoice_no":sale["invoice_no"],"total_paise":total_paise,"reason":reason},client_ip)
    enqueue_tally(conn,"sale_return",return_id,"create")
    if cost_paise:
        enqueue_tally(conn,"sale_return_cogs",return_id,"create")
    return _return_payload(conn, return_id) | {"idempotent": False}


def cancel_sale_return(conn, return_id: int, user: dict[str, Any], reason: str, client_ip: str | None = None) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM sale_returns WHERE id=?", (return_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Return not found")
    ret = dict(row)
    if ret["status"] == "cancelled":
        return {"ok": True, "already_cancelled": True, "return_no": ret["return_no"]}
    reason = str(reason or "").strip()
    if len(reason) < 3:
        raise HTTPException(400, "Cancellation reason is required")
    if day_is_closed(conn, int(ret["branch_id"]), str(ret.get("business_date") or business_date(conn))):
        raise HTTPException(409, detail={"code": "DAY_CLOSED", "message": "Credit notes cannot be cancelled after day close"})
    now = utcnow()
    lines = conn.execute("SELECT * FROM sale_return_items WHERE return_id=? AND active=1", (return_id,)).fetchall()
    for line in lines:
        item = conn.execute("SELECT status FROM items WHERE id=?", (line["item_id"],)).fetchone()
        disposition = str(line["disposition"] or "in_stock")
        if not item or item["status"] != disposition:
            raise HTTPException(409, f"Cannot cancel return: tag {line['tag_no']} has already moved from stock")
    for line in lines:
        conn.execute("UPDATE items SET status='sold',version=version+1,updated_at=? WHERE id=?", (now,line["item_id"]))
        conn.execute("UPDATE sale_return_items SET active=0 WHERE id=?", (line["id"],))
        conn.execute(
            """INSERT INTO stock_movements(item_id,movement_type,ref_type,ref_id,from_location,to_location,gross_weight,user_id,note,created_at)
               SELECT ?, 'sale_return_cancel','sale_return',?,'branch:'||?, 'customer',si.gross_weight,?,?,?
               FROM sale_items si WHERE si.id=?""",
            (line["item_id"],return_id,ret["branch_id"],user["id"],reason,now,line["sale_item_id"]),
        )
    conn.execute("UPDATE sale_returns SET status='cancelled',cancelled_at=?,cancelled_by=? WHERE id=?", (now,user["id"],return_id))
    _adjust_customer_balance(conn, ret.get("customer_id"), int(ret["refund_credit_paise"] or 0), now)
    je = conn.execute("SELECT id FROM journal_entries WHERE ref_type='sale_return' AND ref_id=? ORDER BY id LIMIT 1", (return_id,)).fetchone()
    if je:
        reversed_lines = [
            (x["account_code"],x["credit"],x["debit"],x["party_type"],x["party_id"])
            for x in conn.execute("SELECT * FROM journal_lines WHERE entry_id=?", (je["id"],)).fetchall()
        ]
        _journal(conn,user["id"],f"Cancel sales return {ret['return_no']}: {reason}","sale_return_cancel",return_id,reversed_lines)
    audit(conn,user["id"],"cancel","sale_return",return_id,{"reason":reason},client_ip)
    enqueue_tally(conn,"sale_return",return_id,"cancel")
    if conn.execute("SELECT coalesce(sum(cost_amount_paise),0) v FROM sale_return_items WHERE return_id=?", (return_id,)).fetchone()["v"]:
        enqueue_tally(conn,"sale_return_cogs",return_id,"cancel")
    return {"ok": True, "return_no": ret["return_no"]}


def list_returns(conn, limit: int = 500) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT r.*,s.invoice_no,c.name customer_name FROM sale_returns r
           JOIN sales s ON s.id=r.sale_id LEFT JOIN customers c ON c.id=r.customer_id
           ORDER BY r.id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["total"] = _rupees(int(item["total_paise"] or 0))
        out.append(item)
    return out


def return_detail(conn, return_id: int) -> dict[str, Any]:
    return _return_payload(conn, return_id)
