from __future__ import annotations

import re
from typing import Any

from .audit_chain import verify_audit_chain
from .precision import money, money_equal, money_paise, weight_equal

_HUID_RE = re.compile(r"^[A-Z0-9]{6}$")


def assert_storage_integrity(conn) -> None:
    """Fail server startup only for physical DB/FK corruption, not fixable business warnings."""
    quick = conn.execute("PRAGMA quick_check").fetchone()
    quick_value = str(quick[0]) if quick else "missing quick_check result"
    if quick_value.lower() != "ok":
        raise RuntimeError(f"SQLite quick_check failed: {quick_value}")
    fk = conn.execute("PRAGMA foreign_key_check").fetchmany(20)
    if fk:
        raise RuntimeError(f"SQLite foreign_key_check failed: {len(fk)} violation(s) found")


def _append(issues: list[dict[str, Any]], kind: str, message: str, **details: Any) -> None:
    issues.append({"kind": kind, "message": message, **details})


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
        _append(
            issues,
            "foreign_key",
            "Foreign key violation",
            table=row[0],
            rowid=row[1],
            parent=row[2],
            fk_index=row[3],
        )

    weight_rows = conn.execute(
        "SELECT id,tag_no,gross_weight,stone_weight,net_weight,net_weight_override_reason "
        "FROM items WHERE stone_weight>gross_weight+0.0005 OR net_weight<0 OR "
        "(abs(net_weight-(gross_weight-stone_weight))>0.0015 AND "
        "coalesce(trim(net_weight_override_reason),'')='') ORDER BY id LIMIT 100"
    ).fetchall()
    for row in weight_rows:
        _append(
            issues,
            "weight",
            f"Tag {row['tag_no']} has inconsistent jewellery weights",
            item_id=row["id"],
            gross_weight=row["gross_weight"],
            stone_weight=row["stone_weight"],
            net_weight=row["net_weight"],
        )

    invalid_huid = []
    for row in conn.execute("SELECT id,tag_no,huid FROM items WHERE huid IS NOT NULL AND trim(huid)<>'' ORDER BY id"):
        value = str(row["huid"] or "").strip().upper()
        if not _HUID_RE.fullmatch(value):
            invalid_huid.append(row)
            if len(invalid_huid) <= 50:
                _append(issues, "huid", f"Tag {row['tag_no']} has invalid HUID format", item_id=row["id"], huid=row["huid"])

    duplicate_huid = conn.execute(
        "SELECT upper(trim(huid)) huid,count(*) c,group_concat(tag_no) tags "
        "FROM items WHERE huid IS NOT NULL AND trim(huid)<>'' "
        "GROUP BY upper(trim(huid)) HAVING count(*)>1 ORDER BY c DESC"
    ).fetchall()
    for row in duplicate_huid[:20]:
        _append(issues, "huid_duplicate", f"HUID {row['huid']} is used by multiple tags", huid=row["huid"], tags=row["tags"])

    unbalanced = []
    for row in conn.execute(
        "SELECT e.id,e.entry_no,coalesce(sum(l.debit),0) debit,coalesce(sum(l.credit),0) credit "
        "FROM journal_entries e LEFT JOIN journal_lines l ON l.entry_id=e.id GROUP BY e.id ORDER BY e.id"
    ):
        if not money_equal(row["debit"], row["credit"], tolerance_paise=0):
            unbalanced.append(row)
            if len(unbalanced) <= 50:
                _append(
                    issues,
                    "journal",
                    f"Journal {row['entry_no']} is unbalanced",
                    entry_id=row["id"],
                    debit=money(row["debit"]),
                    credit=money(row["credit"]),
                )

    sale_total_errors = 0
    payment_errors = 0
    missing_journal = 0
    stock_state_errors = 0
    sales = conn.execute(
        "SELECT id,invoice_no,status,total,round_off,payment_cash,payment_card,payment_upi,payment_credit,old_gold_value "
        "FROM sales ORDER BY id"
    ).fetchall()
    for sale in sales:
        line_total = conn.execute("SELECT coalesce(sum(line_total),0) FROM sale_items WHERE sale_id=?", (sale["id"],)).fetchone()[0]
        expected_total_paise = money_paise(money(line_total + sale["round_off"]))
        if expected_total_paise != money_paise(sale["total"]):
            sale_total_errors += 1
            if sale_total_errors <= 50:
                _append(
                    issues,
                    "sale_total",
                    f"Invoice {sale['invoice_no']} total does not match its lines",
                    sale_id=sale["id"],
                    stored_total=money(sale["total"]),
                    expected_total=money(line_total + sale["round_off"]),
                )
        paid = money(
            sale["payment_cash"] + sale["payment_card"] + sale["payment_upi"] + sale["payment_credit"] + sale["old_gold_value"]
        )
        if not money_equal(paid, sale["total"], tolerance_paise=0):
            payment_errors += 1
            if payment_errors <= 50:
                _append(
                    issues,
                    "payment",
                    f"Invoice {sale['invoice_no']} payment split does not equal total",
                    sale_id=sale["id"],
                    paid=paid,
                    total=money(sale["total"]),
                )
        journal = conn.execute(
            "SELECT id FROM journal_entries WHERE ref_type=? AND ref_id=? ORDER BY id LIMIT 1",
            ("sale" if sale["status"] == "posted" else "sale_cancel", sale["id"]),
        ).fetchone()
        if not journal:
            missing_journal += 1
            if missing_journal <= 50:
                _append(issues, "journal_missing", f"Invoice {sale['invoice_no']} is missing its accounting journal", sale_id=sale["id"])
        if sale["status"] == "posted":
            wrong = conn.execute(
                "SELECT si.item_id,si.tag_no,i.status FROM sale_items si JOIN items i ON i.id=si.item_id "
                "WHERE si.sale_id=? AND i.status<>'sold'",
                (sale["id"],),
            ).fetchall()
            for row in wrong[:20]:
                stock_state_errors += 1
                _append(
                    issues,
                    "stock_state",
                    f"Posted invoice {sale['invoice_no']} has tag {row['tag_no']} in state {row['status']}",
                    sale_id=sale["id"],
                    item_id=row["item_id"],
                )

    orphan_sold = conn.execute(
        "SELECT i.id,i.tag_no FROM items i WHERE i.status='sold' AND NOT EXISTS ("
        "SELECT 1 FROM sale_items si JOIN sales s ON s.id=si.sale_id "
        "WHERE si.item_id=i.id AND s.status='posted') ORDER BY i.id LIMIT 100"
    ).fetchall()
    for row in orphan_sold:
        _append(issues, "stock_state", f"Sold tag {row['tag_no']} has no posted invoice", item_id=row["id"])

    audit = verify_audit_chain(conn)
    if not audit["ok"]:
        for row in audit["errors"][:20]:
            _append(issues, "audit_chain", f"Audit chain mismatch at entry {row['id']}", audit_id=row["id"])

    all_issues = issues
    return {
        "ok": quick_ok and not fk_rows and not all_issues,
        "sqlite_quick_check": quick_messages,
        "foreign_key_violations": len(fk_rows),
        "weight_violations": len(weight_rows),
        "invalid_huid": len(invalid_huid),
        "duplicate_huid_groups": len(duplicate_huid),
        "unbalanced_journals": len(unbalanced),
        "sale_total_mismatches": sale_total_errors,
        "payment_mismatches": payment_errors,
        "missing_journals": missing_journal,
        "stock_state_mismatches": stock_state_errors + len(orphan_sold),
        "audit_chain": audit,
        "issues": all_issues[:max_details],
        "issue_count": len(all_issues),
    }


def day_close(conn, business_date: str) -> dict[str, Any]:
    sale = conn.execute(
        "SELECT count(*) c,coalesce(sum(total),0) total,coalesce(sum(taxable),0) taxable,coalesce(sum(gst),0) gst,"
        "coalesce(sum(payment_cash),0) cash,coalesce(sum(payment_card),0) card,coalesce(sum(payment_upi),0) upi,"
        "coalesce(sum(payment_credit),0) credit,coalesce(sum(old_gold_value),0) old_gold "
        "FROM sales WHERE status='posted' AND substr(created_at,1,10)=?",
        (business_date,),
    ).fetchone()
    cancelled = conn.execute(
        "SELECT count(*) FROM sales WHERE status='cancelled' AND substr(cancelled_at,1,10)=?",
        (business_date,),
    ).fetchone()[0]
    purchase = conn.execute(
        "SELECT count(*) c,coalesce(sum(total),0) total,coalesce(sum(paid),0) paid FROM purchases WHERE substr(created_at,1,10)=?",
        (business_date,),
    ).fetchone()
    journal = conn.execute(
        "SELECT coalesce(sum(l.debit),0) debit,coalesce(sum(l.credit),0) credit "
        "FROM journal_entries e JOIN journal_lines l ON l.entry_id=e.id WHERE e.entry_date=?",
        (business_date,),
    ).fetchone()
    movement_count = conn.execute(
        "SELECT count(*) FROM stock_movements WHERE substr(created_at,1,10)=?",
        (business_date,),
    ).fetchone()[0]
    payment_total = money(sale["cash"] + sale["card"] + sale["upi"] + sale["credit"] + sale["old_gold"])
    return {
        "date": business_date,
        "sales": {
            "count": sale["c"],
            "total": money(sale["total"]),
            "taxable": money(sale["taxable"]),
            "gst": money(sale["gst"]),
            "cash": money(sale["cash"]),
            "card": money(sale["card"]),
            "upi": money(sale["upi"]),
            "credit": money(sale["credit"]),
            "old_gold": money(sale["old_gold"]),
            "payment_total": payment_total,
            "payments_match_sales": money_equal(payment_total, sale["total"]),
        },
        "cancelled_sales": cancelled,
        "purchases": {"count": purchase["c"], "total": money(purchase["total"]), "paid": money(purchase["paid"])},
        "journal": {
            "debit": money(journal["debit"]),
            "credit": money(journal["credit"]),
            "balanced": money_equal(journal["debit"], journal["credit"]),
        },
        "stock_movements": movement_count,
    }
