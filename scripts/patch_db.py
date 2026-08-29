from __future__ import annotations

from pathlib import Path

def write_if_changed(path: str, text: str) -> None:
    p = Path(path)
    old = p.read_text(encoding="utf-8")
    if old != text:
        p.write_text(text, encoding="utf-8")
        print("updated", path)
    else:
        print("unchanged", path)

def must_replace(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Could not find patch anchor: {label}")
    return text.replace(old, new, 1)

def patch_db() -> None:
    path = "jewel_server/db.py"
    text = Path(path).read_text(encoding="utf-8")
    if "CREATE TABLE IF NOT EXISTS tally_sync_queue" not in text:
        old = 'CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at DESC);\n"""'
        new = '''CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at DESC);\nCREATE TABLE IF NOT EXISTS tally_ledger_mappings (mapping_key TEXT PRIMARY KEY,tally_ledger_name TEXT NOT NULL,updated_at TEXT NOT NULL);\nCREATE TABLE IF NOT EXISTS tally_sync_queue (id INTEGER PRIMARY KEY AUTOINCREMENT,entity_type TEXT NOT NULL,entity_id INTEGER NOT NULL,operation TEXT NOT NULL CHECK(operation IN ('create','cancel')),remote_id TEXT NOT NULL,payload_hash TEXT,tally_master_id TEXT,tally_voucher_no TEXT,status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','sending','synced','failed','conflict')),attempt_count INTEGER NOT NULL DEFAULT 0,last_error TEXT,response_json TEXT,next_attempt_at TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,synced_at TEXT,UNIQUE(entity_type,entity_id,operation));\nCREATE INDEX IF NOT EXISTS idx_tally_queue_status ON tally_sync_queue(status,next_attempt_at,id);\nCREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL);\n"""'''
        text = must_replace(text, old, new, "Tally database tables")
    if "def _migrate_schema" not in text:
        anchor = 'DEFAULT_ACCOUNTS=['
        addition = '''TALLY_DEFAULT_MAPPINGS={"cash":"Cash","bank":"Bank / Card / UPI","sales":"Jewellery Sales","inventory":"Jewellery Inventory","cogs":"Cost of Goods Sold","old_gold":"Old Gold Inventory","customer_receivables":"Sundry Debtors Control","supplier_payables":"Sundry Creditors Control","input_gst":"Input GST","cgst":"Output CGST 1.5%","sgst":"Output SGST 1.5%","igst":"Output IGST 3%","round_off":"Round Off"}\n\ndef _migrate_schema(conn):\n    cols={r[1] for r in conn.execute("PRAGMA table_info(sales)").fetchall()}\n    additions={"place_of_supply_code":"TEXT","cgst":"REAL NOT NULL DEFAULT 0","sgst":"REAL NOT NULL DEFAULT 0","igst":"REAL NOT NULL DEFAULT 0"}\n    for name,spec in additions.items():\n        if name not in cols:conn.execute(f"ALTER TABLE sales ADD COLUMN {name} {spec}")\n    conn.execute("INSERT OR IGNORE INTO schema_migrations(version,applied_at) VALUES(1,?)",(utcnow(),))\n\n'''
        text = must_replace(text, anchor, addition + anchor, "schema migration helper")
    text = text.replace('conn.executescript(SCHEMA); now=utcnow();', 'conn.executescript(SCHEMA); _migrate_schema(conn); now=utcnow();', 1)
    if '"tally_enabled"' not in text:
        old = '"backup_interval_hours":"6","backup_retention_days":"30"}'
        new = '"backup_interval_hours":"6","backup_retention_days":"30","business_state_code":"","tally_enabled":"0","tally_bridge_url":"http://127.0.0.1:8767","tally_bridge_token":"","tally_company":"","tally_auto_create_parties":"1"}'
        text = must_replace(text, old, new, "Tally settings defaults")
    if 'for key,name in TALLY_DEFAULT_MAPPINGS.items()' not in text:
        old = 'for code,name,typ in DEFAULT_ACCOUNTS: conn.execute("INSERT OR IGNORE INTO accounts(code,name,account_type,active) VALUES(?,?,?,1)",(code,name,typ))'
        new = old + '\n        for key,name in TALLY_DEFAULT_MAPPINGS.items(): conn.execute("INSERT OR IGNORE INTO tally_ledger_mappings(mapping_key,tally_ledger_name,updated_at) VALUES(?,?,?)",(key,name,now))'
        text = must_replace(text, old, new, "Tally ledger defaults")
    write_if_changed(path, text)

if __name__ == "__main__":
    patch_db()
