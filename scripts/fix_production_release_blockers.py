from __future__ import annotations

from pathlib import Path


def patch_db() -> None:
    path = Path("jewel_server/db.py")
    text = path.read_text(encoding="utf-8")

    helper_marker = "def _execute_script_in_transaction(conn, script: str) -> None:"
    if helper_marker not in text:
        anchor = '''def _add_column_if_missing(conn, table: str, name: str, spec: str) -> None:\n    if name not in _table_columns(conn, table):\n        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {spec}")\n'''
        helper = '''\n\ndef _execute_script_in_transaction(conn, script: str) -> None:\n    """Execute multi-statement migration SQL without sqlite3.executescript().\n\n    sqlite3.executescript() implicitly commits any active transaction, which breaks\n    our atomic migration wrapper. sqlite3.complete_statement() understands trigger\n    bodies, so statements can be executed one by one while the caller's transaction\n    remains active.\n    """\n    pending = ""\n    for line in script.splitlines():\n        pending += line + "\\n"\n        if sqlite3.complete_statement(pending):\n            statement = pending.strip()\n            if statement:\n                conn.execute(statement)\n            pending = ""\n    if pending.strip():\n        raise sqlite3.OperationalError("Incomplete SQL statement in schema migration")\n'''
        if anchor not in text:
            raise RuntimeError("db helper insertion anchor not found")
        text = text.replace(anchor, anchor + helper, 1)

    migration_anchor = "def _migration_5(conn) -> None:"
    if migration_anchor not in text:
        raise RuntimeError("migration 5 anchor not found")
    before, after = text.split(migration_anchor, 1)
    old = '    conn.executescript(r"""'
    new = '    _execute_script_in_transaction(conn, r"""'
    if new not in after:
        if old not in after:
            raise RuntimeError("migration 5 executescript anchor not found")
        after = after.replace(old, new, 1)
    text = before + migration_anchor + after
    path.write_text(text, encoding="utf-8")


def patch_services() -> None:
    path = Path("jewel_server/services.py")
    text = path.read_text(encoding="utf-8")
    old = "row=c.execute('SELECT balance_paise FROM customers WHERE id=?',(cid,)).fetchone();newp=int(row['balance_paise'] or 0)+money_paise(credit);c.execute('UPDATE customers SET balance=?,balance_paise=?,updated_at=? WHERE id=?',(paise_money(newp),newp,now,cid))"
    new = "row=conn.execute('SELECT balance_paise FROM customers WHERE id=?',(cid,)).fetchone();newp=int(row['balance_paise'] or 0)+money_paise(credit);conn.execute('UPDATE customers SET balance=?,balance_paise=?,updated_at=? WHERE id=?',(paise_money(newp),newp,now,cid))"
    if new not in text:
        if old not in text:
            raise RuntimeError("customer credit balance anchor not found")
        text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    patch_db()
    patch_services()
    print("Production release blockers fixed")
