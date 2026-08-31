from __future__ import annotations

import re
from typing import Any

from .audit_chain import verify_audit_chain
from .canonical import canonical_integrity, paise_to_money

_HUID_RE = re.compile(r"^[A-Z0-9]{6}$")


def assert_storage_integrity(conn) -> None:
    """Fail startup only for physical SQLite/FK corruption; business problems remain visible in Data Health."""
    quick = conn.execute("PRAGMA quick_check").fetchone()
    quick_value = str(quick[0]) if quick else "missing quick_check result"
    if quick_value.lower() != "ok":
        raise RuntimeError(f"SQLite quick_check failed: {quick_value}")
    fk = conn.execute("PRAGMA foreign_key_check").fetchmany(20)
    if fk:
        raise RuntimeError(f"SQLite foreign_key_check failed: {len(fk)} violation(s) found")


def _append(issues: list[dict[str, Any]], kind: str, message: str, **details: Any) -> None:
    issues.append({"kind": kind, "message": message, **details})


def _has_table(conn, table: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


def database_integrity(conn, max_details: int = 100) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []

    quick_rows = conn.execute("PRAGMA quick_check").fetchall()
    quick_messages = [str(r[0]) for r in quick_rows]
    quick_ok = quick_messages == ["ok"]
    if not quick_ok:
        for msg in quick_messages[:10]:
            _append(issues, "sqlite", f"quick_check: {msg}")

    fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
    for row in fk_rows[:20]:
        _append(issues, "foreign_key", "Foreign key violation", table=row[0], rowid=row[1], parent=row[2], fk_index=row[3])

    weight_rows = conn.execute(
        "SELECT id,tag_no,gross_weight,stone_weight,net_weight,net_weight_override_reason "
        "FROM items WHERE stone_weight>gross_weight+0.0005 OR net_weight<0 OR "
        "(abs(net_weight-(gross_weight-stone_weight))>0.0015 AND coalesce(trim(net_weight_override_reason),'')='') "
        "ORDER BY id LIMIT 100"
    ).fetchall()
    for row in weight_rows:
        _append(issues, "weight", f"Tag {row['tag_no']} has inconsistent jewellery weights", item_id=row["id"], gross_weight=row["gross_weight"], stone_weight=row["stone_weight"], net_weight=row["net_weight"])

    invalid_huid = []
    for row in conn.execute("SELECT id,tag_no,huid FROM items WHERE huid IS NOT NULL AND trim(huid)<>'' ORDER BY id"):
        value = str(row["huid"] or "").strip().upper()
        if not _HUID_RE.fullmatch(value):
            invalid_huid.append(row)
            if len(invalid_huid) <= 50:
                _append(issues, "huid", f"Tag {row['tag_no']} has invalid HUID format", item_id=row["id"], huid=row["huid"])

    duplicate_huid = conn.execute(
        "SELECT upper(trim(huid)) huid,count(*) c,group_concat(tag_no) tags FROM items "
        "WHERE huid IS NOT NULL AND trim(huid)<>'' GROUP BY upper(trim(huid)) HAVING count(*)>1 ORDER BY c DESC"
    ).fetchall()
    for row in duplicate_huid[:20]:
        _append(issues, "huid_duplicate", f"HUID {row['huid']} is used by multiple tags", huid=row["huid"], tags=row["tags"])

    unbalanced = []
    for row in conn.execute(
        "SELECT e.id,e.entry_no,coalesce(sum(l.debit_paise),0) debit,coalesce(sum(l.credit_paise),0) credit "
        "FROM journal_entries e LEFT JOIN journal_lines l ON l.entry_id=e.id GROUP BY e.id ORDER BY e.id"
    ):
        if int(row["debit"]) != int(row["credit"]):
            unbalanced.append(row)
            if len(unbalanced) <= 50:
                _append(issues, "journal", f"Journal {row['entry_no']} is unbalanced", entry_id=row["id"], debit=paise_to_money(row["debit"]), credit=paise_to_money(row["credit"]))

    sale_total_errors = payment_errors = missing_journal = stock_state_errors = 0
    sales = conn.execute(
        "SELECT id,invoice_no,status,total_paise,round_off_paise,payment_cash_paise,payment_card_paise,payment_upi_paise,payment_credit_paise,old_gold_value_paise FROM sales ORDER BY id"
    ).fetchall()
    returns_enabled = _has_table(conn, "sale_return_items")
    for sale in sales:
        line_total_paise = int(conn.execute("SELECT coalesce(sum(line_total_paise),0) FROM sale_items WHERE sale_id=?", (sale["id"],)).fetchone()[0])
        expected_total = line_total_paise + int(sale["round_off_paise"] or 0)
        if expected_total != int(sale["total_paise"]):
            sale_total_errors += 1
            if sale_total_errors <= 50:
                _append(issues, "sale_total", f"Invoice {sale['invoice_no']} total does not match its lines", sale_id=sale["id"], stored_total=paise_to_money(sale["total_paise"]), expected_total=paise_to_money(expected_total))
        paid = sum(int(sale[k] or 0) for k in ("payment_cash_paise","payment_card_paise","payment_upi_paise","payment_credit_paise","old_gold_value_paise"))
        if paid != int(sale["total_paise"]):
            payment_errors += 1
            if payment_errors <= 50:
                _append(issues, "payment", f"Invoice {sale['invoice_no']} payment split does not equal total", sale_id=sale["id"], paid=paise_to_money(paid), total=paise_to_money(sale["total_paise"]))

        original_journal = conn.execute("SELECT id FROM journal_entries WHERE ref_type='sale' AND ref_id=? ORDER BY id LIMIT 1", (sale["id"],)).fetchone()
        if not original_journal:
            missing_journal += 1
            _append(issues, "journal_missing", f"Invoice {sale['invoice_no']} is missing its original accounting journal", sale_id=sale["id"])
        if sale["status"] == "cancelled":
            cancel_journal = conn.execute("SELECT id FROM journal_entries WHERE ref_type='sale_cancel' AND ref_id=? ORDER BY id LIMIT 1", (sale["id"],)).fetchone()
            if not cancel_journal:
                missing_journal += 1
                _append(issues, "journal_missing", f"Cancelled invoice {sale['invoice_no']} is missing its reversal journal", sale_id=sale["id"])

        if sale["status"] == "posted":
            if returns_enabled:
                wrong = conn.execute(
                    """SELECT si.item_id,si.tag_no,i.status FROM sale_items si JOIN items i ON i.id=si.item_id
                       WHERE si.sale_id=? AND i.status<>'sold' AND NOT EXISTS (
                         SELECT 1 FROM sale_return_items ri JOIN sale_returns r ON r.id=ri.return_id
                         WHERE ri.sale_item_id=si.id AND ri.active=1 AND r.status='posted'
                       )""",
                    (sale["id"],),
                ).fetchall()
            else:
                wrong = conn.execute(
                    "SELECT si.item_id,si.tag_no,i.status FROM sale_items si JOIN items i ON i.id=si.item_id WHERE si.sale_id=? AND i.status<>'sold'",
                    (sale["id"],),
                ).fetchall()
            for row in wrong[:20]:
                stock_state_errors += 1
                _append(issues, "stock_state", f"Posted invoice {sale['invoice_no']} has unreturned tag {row['tag_no']} in state {row['status']}", sale_id=sale["id"], item_id=row["item_id"])
        else:
            wrong = conn.execute(
                "SELECT si.item_id,si.tag_no,i.status FROM sale_items si JOIN items i ON i.id=si.item_id WHERE si.sale_id=? AND i.status='sold'",
                (sale["id"],),
            ).fetchall()
            for row in wrong[:20]:
                stock_state_errors += 1
                _append(issues, "stock_state", f"Cancelled invoice {sale['invoice_no']} still has tag {row['tag_no']} marked sold", sale_id=sale["id"], item_id=row["item_id"])

    return_total_errors = return_payment_errors = return_journal_errors = return_state_errors = 0
    if _has_table(conn, "sale_returns"):
        for ret in conn.execute("SELECT * FROM sale_returns ORDER BY id"):
            line = conn.execute(
                "SELECT coalesce(sum(line_total_paise),0) total,coalesce(sum(taxable_paise),0) taxable,coalesce(sum(gst_amount_paise),0) gst FROM sale_return_items WHERE return_id=?",
                (ret["id"],),
            ).fetchone()
            if int(line["total"]) != int(ret["total_paise"]) or int(line["taxable"]) != int(ret["taxable_paise"]) or int(line["gst"]) != int(ret["gst_paise"]):
                return_total_errors += 1
                _append(issues, "return_total", f"Credit note {ret['return_no']} does not match its item lines", return_id=ret["id"])
            refunds = sum(int(ret[k] or 0) for k in ("refund_cash_paise","refund_card_paise","refund_upi_paise","refund_credit_paise"))
            if refunds != int(ret["total_paise"]):
                return_payment_errors += 1
                _append(issues, "return_payment", f"Credit note {ret['return_no']} refund split does not equal total", return_id=ret["id"])
            if int(ret["cgst_paise"] or 0) + int(ret["sgst_paise"] or 0) + int(ret["igst_paise"] or 0) != int(ret["gst_paise"] or 0):
                return_total_errors += 1
                _append(issues, "return_tax", f"Credit note {ret['return_no']} GST components do not equal GST total", return_id=ret["id"])
            ref_type = "sale_return" if ret["status"] == "posted" else "sale_return_cancel"
            if not conn.execute("SELECT 1 FROM journal_entries WHERE ref_type=? AND ref_id=?", (ref_type,ret["id"])).fetchone():
                return_journal_errors += 1
                _append(issues, "journal_missing", f"Credit note {ret['return_no']} is missing its {ref_type} journal", return_id=ret["id"])
            active_count = int(conn.execute("SELECT count(*) FROM sale_return_items WHERE return_id=? AND active=1", (ret["id"],)).fetchone()[0])
            if (ret["status"] == "posted" and active_count == 0) or (ret["status"] == "cancelled" and active_count != 0):
                return_state_errors += 1
                _append(issues, "return_state", f"Credit note {ret['return_no']} active-line state is inconsistent", return_id=ret["id"])

    if returns_enabled:
        orphan_sold = conn.execute(
            """SELECT i.id,i.tag_no FROM items i WHERE i.status='sold' AND NOT EXISTS (
                 SELECT 1 FROM sale_items si JOIN sales s ON s.id=si.sale_id
                 WHERE si.item_id=i.id AND s.status='posted' AND NOT EXISTS (
                   SELECT 1 FROM sale_return_items ri JOIN sale_returns r ON r.id=ri.return_id
                   WHERE ri.sale_item_id=si.id AND ri.active=1 AND r.status='posted'
                 )
               ) ORDER BY i.id LIMIT 100"""
        ).fetchall()
    else:
        orphan_sold = conn.execute(
            "SELECT i.id,i.tag_no FROM items i WHERE i.status='sold' AND NOT EXISTS (SELECT 1 FROM sale_items si JOIN sales s ON s.id=si.sale_id WHERE si.item_id=i.id AND s.status='posted') ORDER BY i.id LIMIT 100"
        ).fetchall()
    for row in orphan_sold:
        _append(issues, "stock_state", f"Sold tag {row['tag_no']} has no active posted invoice ownership", item_id=row["id"])

    audit = verify_audit_chain(conn)
    if not audit["ok"]:
        for row in audit["errors"][:20]:
            _append(issues, "audit_chain", f"Audit chain mismatch at entry {row['id']}", audit_id=row["id"])

    canonical = canonical_integrity(conn, max_errors=max_details)
    if not canonical["ok"]:
        for row in canonical["errors"][:20]:
            _append(issues, "canonical", f"Exact paise/milligram mirror mismatch in {row['table']}", **row)

    return {
        "ok": quick_ok and not fk_rows and not issues,
        "sqlite_quick_check": quick_messages,
        "foreign_key_violations": len(fk_rows),
        "weight_violations": len(weight_rows),
        "invalid_huid": len(invalid_huid),
        "duplicate_huid_groups": len(duplicate_huid),
        "unbalanced_journals": len(unbalanced),
        "sale_total_mismatches": sale_total_errors,
        "payment_mismatches": payment_errors,
        "missing_journals": missing_journal + return_journal_errors,
        "stock_state_mismatches": stock_state_errors + len(orphan_sold),
        "return_total_mismatches": return_total_errors,
        "return_payment_mismatches": return_payment_errors,
        "return_state_mismatches": return_state_errors,
        "audit_chain": audit,
        "canonical": canonical,
        "issues": issues[:max_details],
        "issue_count": len(issues),
    }


def day_close(conn, business_date: str, branch_id: int = 1) -> dict[str, Any]:
    branch_id = int(branch_id)
    sale = conn.execute(
        "SELECT count(*) c,coalesce(sum(total_paise),0) total,coalesce(sum(taxable_paise),0) taxable,coalesce(sum(gst_paise),0) gst,"
        "coalesce(sum(payment_cash_paise),0) cash,coalesce(sum(payment_card_paise),0) card,coalesce(sum(payment_upi_paise),0) upi,"
        "coalesce(sum(payment_credit_paise),0) credit,coalesce(sum(old_gold_value_paise),0) old_gold "
        "FROM sales WHERE status='posted' AND business_date=? AND branch_id=?",
        (business_date, branch_id),
    ).fetchone()
    cancelled = int(conn.execute("SELECT count(*) FROM sales WHERE status='cancelled' AND business_date=? AND branch_id=?", (business_date,branch_id)).fetchone()[0])
    if _has_table(conn, "sale_returns"):
        ret = conn.execute(
            "SELECT count(*) c,coalesce(sum(total_paise),0) total,coalesce(sum(taxable_paise),0) taxable,coalesce(sum(gst_paise),0) gst,"
            "coalesce(sum(refund_cash_paise),0) cash,coalesce(sum(refund_card_paise),0) card,coalesce(sum(refund_upi_paise),0) upi,coalesce(sum(refund_credit_paise),0) credit "
            "FROM sale_returns WHERE status='posted' AND business_date=? AND branch_id=?",
            (business_date, branch_id),
        ).fetchone()
        cancelled_returns = int(conn.execute("SELECT count(*) FROM sale_returns WHERE status='cancelled' AND business_date=? AND branch_id=?", (business_date,branch_id)).fetchone()[0])
    else:
        ret = {"c":0,"total":0,"taxable":0,"gst":0,"cash":0,"card":0,"upi":0,"credit":0}
        cancelled_returns = 0
    purchase = conn.execute(
        "SELECT count(*) c,coalesce(sum(total_paise),0) total,coalesce(sum(paid_paise),0) paid FROM purchases WHERE business_date=? AND branch_id=?",
        (business_date, branch_id),
    ).fetchone()
    journal = conn.execute(
        """SELECT coalesce(sum(l.debit_paise),0) debit,coalesce(sum(l.credit_paise),0) credit
           FROM journal_entries e JOIN journal_lines l ON l.entry_id=e.id
           WHERE e.entry_date=? AND (
             (e.ref_type IN ('sale','sale_cancel') AND EXISTS (SELECT 1 FROM sales s WHERE s.id=e.ref_id AND s.branch_id=?)) OR
             (e.ref_type IN ('sale_return','sale_return_cancel') AND EXISTS (SELECT 1 FROM sale_returns r WHERE r.id=e.ref_id AND r.branch_id=?)) OR
             (e.ref_type='purchase' AND EXISTS (SELECT 1 FROM purchases p WHERE p.id=e.ref_id AND p.branch_id=?))
           )""",
        (business_date, branch_id, branch_id, branch_id),
    ).fetchone()

    sale_payment = int(sale["cash"])+int(sale["card"])+int(sale["upi"])+int(sale["credit"])+int(sale["old_gold"])
    refund_payment = int(ret["cash"])+int(ret["card"])+int(ret["upi"])+int(ret["credit"])
    net_total = int(sale["total"])-int(ret["total"])
    net_payment = sale_payment-refund_payment
    return {
        "date": business_date,
        "branch_id": branch_id,
        "sales": {
            "count": int(sale["c"]), "total": paise_to_money(sale["total"]), "taxable": paise_to_money(sale["taxable"]), "gst": paise_to_money(sale["gst"]),
            "cash": paise_to_money(sale["cash"]), "card": paise_to_money(sale["card"]), "upi": paise_to_money(sale["upi"]), "credit": paise_to_money(sale["credit"]), "old_gold": paise_to_money(sale["old_gold"]),
            "payment_total": paise_to_money(sale_payment), "payments_match_sales": sale_payment == int(sale["total"]),
        },
        "returns": {
            "count": int(ret["c"]), "total": paise_to_money(ret["total"]), "taxable": paise_to_money(ret["taxable"]), "gst": paise_to_money(ret["gst"]),
            "cash": paise_to_money(ret["cash"]), "card": paise_to_money(ret["card"]), "upi": paise_to_money(ret["upi"]), "credit": paise_to_money(ret["credit"]),
            "refund_total": paise_to_money(refund_payment), "refunds_match_returns": refund_payment == int(ret["total"]),
        },
        "net_sales": {
            "total": paise_to_money(net_total), "taxable": paise_to_money(int(sale["taxable"])-int(ret["taxable"])), "gst": paise_to_money(int(sale["gst"])-int(ret["gst"])),
            "cash": paise_to_money(int(sale["cash"])-int(ret["cash"])), "card": paise_to_money(int(sale["card"])-int(ret["card"])), "upi": paise_to_money(int(sale["upi"])-int(ret["upi"])), "credit": paise_to_money(int(sale["credit"])-int(ret["credit"])),
            "payment_total": paise_to_money(net_payment), "payments_match_net_sales": net_payment == net_total,
        },
        "cancelled_sales": cancelled,
        "cancelled_returns": cancelled_returns,
        "purchases": {"count": int(purchase["c"]), "total": paise_to_money(purchase["total"]), "paid": paise_to_money(purchase["paid"])},
        "journal": {"debit": paise_to_money(journal["debit"]), "credit": paise_to_money(journal["credit"]), "balanced": int(journal["debit"]) == int(journal["credit"])},
    }
