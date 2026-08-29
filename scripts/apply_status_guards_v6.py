from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"v6 anchor missing: {label}")
    return text.replace(old, new, 1)


def patch_db() -> None:
    p = Path("jewel_server/db.py")
    t = p.read_text(encoding="utf-8")
    t = replace_once(t, "LATEST_SCHEMA_VERSION = 5", "LATEST_SCHEMA_VERSION = 6", "schema version")
    migration = r'''

def _migration_6(conn) -> None:
    conn.executescript(r"""
    CREATE TRIGGER IF NOT EXISTS sales_insert_must_be_posted
      BEFORE INSERT ON sales WHEN NEW.status<>'posted'
      BEGIN SELECT RAISE(ABORT,'new invoices must be posted; cancellation is a separate reversal'); END;
    CREATE TRIGGER IF NOT EXISTS sales_status_transition
      BEFORE UPDATE OF status ON sales
      WHEN OLD.status<>NEW.status AND NOT (OLD.status='posted' AND NEW.status='cancelled')
      BEGIN SELECT RAISE(ABORT,'invoice status transition is not allowed'); END;
    CREATE TRIGGER IF NOT EXISTS sales_cancel_requires_metadata
      BEFORE UPDATE OF status ON sales
      WHEN OLD.status='posted' AND NEW.status='cancelled' AND (NEW.cancelled_at IS NULL OR NEW.cancelled_by IS NULL)
      BEGIN SELECT RAISE(ABORT,'invoice cancellation requires timestamp and user'); END;
    CREATE TRIGGER IF NOT EXISTS sales_cancel_metadata_guard
      BEFORE UPDATE OF cancelled_at,cancelled_by ON sales
      WHEN OLD.status='cancelled' AND (NEW.cancelled_at IS NOT OLD.cancelled_at OR NEW.cancelled_by IS NOT OLD.cancelled_by)
      BEGIN SELECT RAISE(ABORT,'cancelled invoice metadata is immutable'); END;
    CREATE TRIGGER IF NOT EXISTS sales_posted_cancel_metadata_guard
      BEFORE UPDATE OF cancelled_at,cancelled_by ON sales
      WHEN OLD.status='posted' AND NEW.status='posted' AND (NEW.cancelled_at IS NOT OLD.cancelled_at OR NEW.cancelled_by IS NOT OLD.cancelled_by)
      BEGIN SELECT RAISE(ABORT,'posted invoice cannot contain cancellation metadata'); END;

    CREATE TRIGGER IF NOT EXISTS sale_returns_insert_must_be_posted
      BEFORE INSERT ON sale_returns WHEN NEW.status<>'posted'
      BEGIN SELECT RAISE(ABORT,'new credit notes must be posted; cancellation is a separate reversal'); END;
    CREATE TRIGGER IF NOT EXISTS sale_returns_status_transition
      BEFORE UPDATE OF status ON sale_returns
      WHEN OLD.status<>NEW.status AND NOT (OLD.status='posted' AND NEW.status='cancelled')
      BEGIN SELECT RAISE(ABORT,'credit-note status transition is not allowed'); END;
    CREATE TRIGGER IF NOT EXISTS sale_returns_cancel_requires_metadata
      BEFORE UPDATE OF status ON sale_returns
      WHEN OLD.status='posted' AND NEW.status='cancelled' AND (NEW.cancelled_at IS NULL OR NEW.cancelled_by IS NULL)
      BEGIN SELECT RAISE(ABORT,'credit-note cancellation requires timestamp and user'); END;
    CREATE TRIGGER IF NOT EXISTS sale_returns_cancel_metadata_guard
      BEFORE UPDATE OF cancelled_at,cancelled_by ON sale_returns
      WHEN OLD.status='cancelled' AND (NEW.cancelled_at IS NOT OLD.cancelled_at OR NEW.cancelled_by IS NOT OLD.cancelled_by)
      BEGIN SELECT RAISE(ABORT,'cancelled credit-note metadata is immutable'); END;
    CREATE TRIGGER IF NOT EXISTS sale_returns_posted_cancel_metadata_guard
      BEFORE UPDATE OF cancelled_at,cancelled_by ON sale_returns
      WHEN OLD.status='posted' AND NEW.status='posted' AND (NEW.cancelled_at IS NOT OLD.cancelled_at OR NEW.cancelled_by IS NOT OLD.cancelled_by)
      BEGIN SELECT RAISE(ABORT,'posted credit note cannot contain cancellation metadata'); END;

    CREATE TRIGGER IF NOT EXISTS sale_return_items_active_transition
      BEFORE UPDATE OF active ON sale_return_items
      WHEN OLD.active<>NEW.active AND NOT (
        OLD.active=1 AND NEW.active=0 AND
        EXISTS(SELECT 1 FROM sale_returns r WHERE r.id=OLD.return_id AND r.status='cancelled')
      )
      BEGIN SELECT RAISE(ABORT,'credit-note line activation transition is not allowed'); END;
    """)
'''
    t = replace_once(
        t,
        "\n\nMIGRATIONS = ((1, _migration_1), (2, _migration_2), (3, _migration_3), (4, _migration_4), (5, _migration_5))",
        migration + "\n\nMIGRATIONS = ((1, _migration_1), (2, _migration_2), (3, _migration_3), (4, _migration_4), (5, _migration_5), (6, _migration_6))",
        "migration registry",
    )
    p.write_text(t, encoding="utf-8")


def patch_returns() -> None:
    p = Path("jewel_server/returns.py")
    t = p.read_text(encoding="utf-8")
    old = '''    for line in lines:\n        conn.execute("UPDATE items SET status='sold',version=version+1,updated_at=? WHERE id=?", (now,line["item_id"]))\n        conn.execute("UPDATE sale_return_items SET active=0 WHERE id=?", (line["id"],))\n        conn.execute(\n            """INSERT INTO stock_movements(item_id,movement_type,ref_type,ref_id,from_location,to_location,gross_weight,user_id,note,created_at)\n               SELECT ?, 'sale_return_cancel','sale_return',?,'branch:'||?, 'customer',si.gross_weight,?,?,?\n               FROM sale_items si WHERE si.id=?""",\n            (line["item_id"],return_id,ret["branch_id"],user["id"],reason,now,line["sale_item_id"]),\n        )\n    conn.execute("UPDATE sale_returns SET status='cancelled',cancelled_at=?,cancelled_by=? WHERE id=?", (now,user["id"],return_id))\n'''
    new = '''    # Mark the credit note cancelled first inside the same transaction. The v6\n    # database guard permits active lines to move 1 -> 0 only under a cancelled\n    # parent; any later failure rolls the whole transaction back atomically.\n    conn.execute("UPDATE sale_returns SET status='cancelled',cancelled_at=?,cancelled_by=? WHERE id=?", (now,user["id"],return_id))\n    for line in lines:\n        conn.execute("UPDATE items SET status='sold',version=version+1,updated_at=? WHERE id=?", (now,line["item_id"]))\n        conn.execute("UPDATE sale_return_items SET active=0 WHERE id=?", (line["id"],))\n        conn.execute(\n            """INSERT INTO stock_movements(item_id,movement_type,ref_type,ref_id,from_location,to_location,gross_weight,user_id,note,created_at)\n               SELECT ?, 'sale_return_cancel','sale_return',?,'branch:'||?, 'customer',si.gross_weight,?,?,?\n               FROM sale_items si WHERE si.id=?""",\n            (line["item_id"],return_id,ret["branch_id"],user["id"],reason,now,line["sale_item_id"]),\n        )\n'''
    t = replace_once(t, old, new, "return cancellation ordering")
    p.write_text(t, encoding="utf-8")


if __name__ == "__main__":
    patch_db()
    patch_returns()
    print("status transition guards v6 applied")
