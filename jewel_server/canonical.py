from __future__ import annotations

from typing import Any

from .precision import money, money_paise, weight_mg


MIRROR_FIELDS: dict[str, tuple[str, tuple[tuple[str, str, int], ...]]] = {
    "items": (
        "tag_no",
        (
            ("gross_weight", "gross_mg", 1000),
            ("stone_weight", "stone_mg", 1000),
            ("net_weight", "net_mg", 1000),
            ("fine_weight", "fine_mg", 1000),
            ("stone_value", "stone_value_paise", 100),
            ("cost_amount", "cost_amount_paise", 100),
        ),
    ),
    "metal_rates": ("metal || ' ' || purity", (("rate_per_gram", "rate_paise_per_gram", 100),)),
    "sales": (
        "invoice_no",
        (
            ("subtotal", "subtotal_paise", 100),
            ("discount", "discount_paise", 100),
            ("taxable", "taxable_paise", 100),
            ("gst", "gst_paise", 100),
            ("cgst", "cgst_paise", 100),
            ("sgst", "sgst_paise", 100),
            ("igst", "igst_paise", 100),
            ("round_off", "round_off_paise", 100),
            ("total", "total_paise", 100),
            ("payment_cash", "payment_cash_paise", 100),
            ("payment_card", "payment_card_paise", 100),
            ("payment_upi", "payment_upi_paise", 100),
            ("payment_credit", "payment_credit_paise", 100),
            ("old_gold_value", "old_gold_value_paise", 100),
        ),
    ),
    "sale_items": (
        "tag_no",
        (
            ("gross_weight", "gross_mg", 1000),
            ("net_weight", "net_mg", 1000),
            ("metal_rate", "metal_rate_paise", 100),
            ("metal_value", "metal_value_paise", 100),
            ("wastage_value", "wastage_value_paise", 100),
            ("making_charge", "making_charge_paise", 100),
            ("stone_value", "stone_value_paise", 100),
            ("discount", "discount_paise", 100),
            ("taxable", "taxable_paise", 100),
            ("gst_amount", "gst_amount_paise", 100),
            ("line_total", "line_total_paise", 100),
            ("cost_amount", "cost_amount_paise", 100),
        ),
    ),
    "old_gold": (
        "'old-gold#' || id",
        (
            ("gross_weight", "gross_mg", 1000),
            ("net_weight", "net_mg", 1000),
            ("pure_weight", "pure_mg", 1000),
            ("rate", "rate_paise", 100),
            ("value", "value_paise", 100),
        ),
    ),
    "purchases": (
        "purchase_no",
        (
            ("subtotal", "subtotal_paise", 100),
            ("gst", "gst_paise", 100),
            ("total", "total_paise", 100),
            ("paid", "paid_paise", 100),
        ),
    ),
    "purchase_items": (
        "'purchase-item#' || id",
        (("cost_amount", "cost_amount_paise", 100), ("gst_amount", "gst_amount_paise", 100)),
    ),
    "journal_lines": (
        "'journal-line#' || id",
        (("debit", "debit_paise", 100), ("credit", "credit_paise", 100)),
    ),
}


def _columns(conn, table: str) -> set[str]:
    return {str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def canonical_integrity(conn, max_errors: int = 100) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    by_table: dict[str, int] = {}
    for table, (label_expr, fields) in MIRROR_FIELDS.items():
        columns = _columns(conn, table)
        missing = [exact for _, exact, _ in fields if exact not in columns]
        if missing:
            by_table[table] = len(missing)
            for name in missing[: max(0, max_errors - len(errors))]:
                errors.append({"table": table, "kind": "missing_column", "column": name})
            continue
        predicates = []
        for legacy, exact, scale in fields:
            predicates.append(f"{exact} IS NULL OR {exact} != CAST(ROUND(COALESCE({legacy},0)*{scale}) AS INTEGER)")
        where = " OR ".join(predicates)
        count = int(conn.execute(f"SELECT count(*) FROM {table} WHERE {where}").fetchone()[0])
        by_table[table] = count
        if count and len(errors) < max_errors:
            rows = conn.execute(
                f"SELECT id,{label_expr} AS label FROM {table} WHERE {where} ORDER BY id LIMIT ?",
                (max_errors - len(errors),),
            ).fetchall()
            for row in rows:
                errors.append({"table": table, "kind": "mirror_mismatch", "id": row["id"], "label": row["label"]})
    return {"ok": not errors, "mismatches": sum(by_table.values()), "by_table": by_table, "errors": errors}


def paise_to_money(value: Any) -> float:
    return money((int(value or 0)) / 100)


def mg_to_weight(value: Any) -> float:
    return int(value or 0) / 1000.0


def expected_exact_value(value: Any, scale: int) -> int:
    return weight_mg(value) if scale == 1000 else money_paise(value)
