from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterator

APP_NAME = "JewelLAN"
PRODUCTION_HARDENED_V1 = True
LATEST_SCHEMA_VERSION = 5


def app_data_dir() -> Path:
    override = os.environ.get("JEWELLAN_DATA_DIR")
    if override:
        base = Path(override).expanduser().resolve()
    elif os.name == "nt":
        base = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
    else:
        base = Path.home() / ".jewellan"
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def database_path() -> Path:
    override = os.environ.get("JEWELLAN_DB")
    if override:
        p = Path(override).expanduser().resolve(); p.parent.mkdir(parents=True, exist_ok=True); return p
    return app_data_dir() / "jewellan.db"

DB_PATH = database_path()
_WRITE_LOCK = threading.RLock()

def utcnow() -> str: return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def business_now(conn) -> dt.datetime:
    row = conn.execute("SELECT value FROM settings WHERE key='business_timezone_offset_minutes'").fetchone()
    try:
        offset = int(str(row[0] if row else "330").strip())
    except (TypeError, ValueError):
        offset = 330
    offset = max(-720, min(840, offset))
    return dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=offset)


def business_date(conn) -> str:
    return business_now(conn).date().isoformat()

def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA busy_timeout=15000")
    conn.execute("PRAGMA wal_autocheckpoint=1000")
    conn.execute("PRAGMA journal_size_limit=67108864")
    return conn

@contextlib.contextmanager
def read_db() -> Iterator[sqlite3.Connection]:
    conn = connect()
    conn.execute("PRAGMA query_only=ON")
    try:
        yield conn
    finally:
        conn.close()

@contextlib.contextmanager
def write_db() -> Iterator[sqlite3.Connection]:
    with _WRITE_LOCK:
        conn=connect()
        try:
            conn.execute("BEGIN IMMEDIATE"); yield conn; conn.execute("COMMIT")
        except Exception:
            with contextlib.suppress(Exception): conn.execute("ROLLBACK")
            raise
        finally: conn.close()

def rowdict(row): return dict(row) if row is not None else None
def rowsdict(rows): return [dict(r) for r in rows]

SCHEMA = r"""
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY,value TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT NOT NULL UNIQUE COLLATE NOCASE,password_hash TEXT NOT NULL,full_name TEXT NOT NULL,role TEXT NOT NULL CHECK(role IN ('admin','manager','cashier','inventory','accounts')),active INTEGER NOT NULL DEFAULT 1,must_change_password INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,created_at TEXT NOT NULL,expires_at TEXT NOT NULL,last_seen_at TEXT NOT NULL,client_name TEXT);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS branches (id INTEGER PRIMARY KEY AUTOINCREMENT,code TEXT NOT NULL UNIQUE,name TEXT NOT NULL,gstin TEXT,address TEXT,phone TEXT,active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS counters (id INTEGER PRIMARY KEY AUTOINCREMENT,branch_id INTEGER NOT NULL REFERENCES branches(id),name TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,UNIQUE(branch_id,name));
CREATE TABLE IF NOT EXISTS metal_rates (id INTEGER PRIMARY KEY AUTOINCREMENT,metal TEXT NOT NULL,purity TEXT NOT NULL,rate_per_gram REAL NOT NULL CHECK(rate_per_gram>=0),effective_at TEXT NOT NULL,created_by INTEGER REFERENCES users(id));
CREATE INDEX IF NOT EXISTS idx_rates_lookup ON metal_rates(metal,purity,effective_at DESC);
CREATE TABLE IF NOT EXISTS customers (id INTEGER PRIMARY KEY AUTOINCREMENT,code TEXT NOT NULL UNIQUE,name TEXT NOT NULL,phone TEXT,email TEXT,address TEXT,gstin TEXT,birthday TEXT,anniversary TEXT,loyalty_points REAL NOT NULL DEFAULT 0,balance REAL NOT NULL DEFAULT 0,notes TEXT,active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers(phone);
CREATE TABLE IF NOT EXISTS suppliers (id INTEGER PRIMARY KEY AUTOINCREMENT,code TEXT NOT NULL UNIQUE,name TEXT NOT NULL,phone TEXT,email TEXT,address TEXT,gstin TEXT,balance REAL NOT NULL DEFAULT 0,notes TEXT,active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS karigars (id INTEGER PRIMARY KEY AUTOINCREMENT,code TEXT NOT NULL UNIQUE,name TEXT NOT NULL,phone TEXT,address TEXT,cash_balance REAL NOT NULL DEFAULT 0,metal_balance_grams REAL NOT NULL DEFAULT 0,notes TEXT,active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY AUTOINCREMENT,tag_no TEXT NOT NULL UNIQUE COLLATE NOCASE,barcode TEXT NOT NULL UNIQUE COLLATE NOCASE,name TEXT NOT NULL,category TEXT NOT NULL,metal TEXT NOT NULL,purity TEXT NOT NULL,gross_weight REAL NOT NULL CHECK(gross_weight>=0),stone_weight REAL NOT NULL DEFAULT 0 CHECK(stone_weight>=0),net_weight REAL NOT NULL CHECK(net_weight>=0),fine_weight REAL NOT NULL DEFAULT 0 CHECK(fine_weight>=0),stone_value REAL NOT NULL DEFAULT 0 CHECK(stone_value>=0),cost_amount REAL NOT NULL DEFAULT 0 CHECK(cost_amount>=0),making_type TEXT NOT NULL DEFAULT 'per_gram' CHECK(making_type IN ('per_gram','percent','fixed')),making_value REAL NOT NULL DEFAULT 0 CHECK(making_value>=0),wastage_percent REAL NOT NULL DEFAULT 0 CHECK(wastage_percent>=0),huid TEXT,certificate_no TEXT,rfid_epc TEXT UNIQUE,hsn_code TEXT NOT NULL DEFAULT '7113',gst_rate REAL NOT NULL DEFAULT 3 CHECK(gst_rate>=0),status TEXT NOT NULL DEFAULT 'in_stock' CHECK(status IN ('in_stock','sold','repair','approval','karigar','transit','damaged','scrap')),branch_id INTEGER NOT NULL REFERENCES branches(id),counter_id INTEGER REFERENCES counters(id),supplier_id INTEGER REFERENCES suppliers(id),purchase_date TEXT,notes TEXT,version INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_items_status ON items(status); CREATE INDEX IF NOT EXISTS idx_items_branch ON items(branch_id,status); CREATE INDEX IF NOT EXISTS idx_items_huid ON items(huid); CREATE INDEX IF NOT EXISTS idx_items_category ON items(category);
CREATE TABLE IF NOT EXISTS stock_movements (id INTEGER PRIMARY KEY AUTOINCREMENT,item_id INTEGER NOT NULL REFERENCES items(id),movement_type TEXT NOT NULL,ref_type TEXT,ref_id INTEGER,from_location TEXT,to_location TEXT,gross_weight REAL NOT NULL DEFAULT 0,user_id INTEGER REFERENCES users(id),note TEXT,created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_stock_mov_item ON stock_movements(item_id,created_at DESC);
CREATE TABLE IF NOT EXISTS sales (id INTEGER PRIMARY KEY AUTOINCREMENT,invoice_no TEXT NOT NULL UNIQUE,client_request_id TEXT UNIQUE,branch_id INTEGER NOT NULL REFERENCES branches(id),counter_id INTEGER REFERENCES counters(id),customer_id INTEGER REFERENCES customers(id),subtotal REAL NOT NULL,discount REAL NOT NULL DEFAULT 0,taxable REAL NOT NULL,gst REAL NOT NULL,round_off REAL NOT NULL DEFAULT 0,total REAL NOT NULL,payment_cash REAL NOT NULL DEFAULT 0,payment_card REAL NOT NULL DEFAULT 0,payment_upi REAL NOT NULL DEFAULT 0,payment_credit REAL NOT NULL DEFAULT 0,old_gold_value REAL NOT NULL DEFAULT 0,notes TEXT,status TEXT NOT NULL DEFAULT 'posted' CHECK(status IN ('posted','cancelled')),user_id INTEGER NOT NULL REFERENCES users(id),created_at TEXT NOT NULL,cancelled_at TEXT,cancelled_by INTEGER REFERENCES users(id));
CREATE INDEX IF NOT EXISTS idx_sales_date ON sales(created_at); CREATE INDEX IF NOT EXISTS idx_sales_customer ON sales(customer_id);
CREATE TABLE IF NOT EXISTS sale_items (id INTEGER PRIMARY KEY AUTOINCREMENT,sale_id INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE,item_id INTEGER NOT NULL REFERENCES items(id),tag_no TEXT NOT NULL,description TEXT NOT NULL,metal TEXT NOT NULL,purity TEXT NOT NULL,gross_weight REAL NOT NULL,net_weight REAL NOT NULL,metal_rate REAL NOT NULL,metal_value REAL NOT NULL,wastage_value REAL NOT NULL DEFAULT 0,making_charge REAL NOT NULL,stone_value REAL NOT NULL,discount REAL NOT NULL DEFAULT 0,taxable REAL NOT NULL,gst_rate REAL NOT NULL,gst_amount REAL NOT NULL,line_total REAL NOT NULL,cost_amount REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS old_gold (id INTEGER PRIMARY KEY AUTOINCREMENT,sale_id INTEGER REFERENCES sales(id) ON DELETE SET NULL,customer_id INTEGER REFERENCES customers(id),metal TEXT NOT NULL,purity TEXT NOT NULL,gross_weight REAL NOT NULL,deduction_percent REAL NOT NULL DEFAULT 0,net_weight REAL NOT NULL,pure_weight REAL NOT NULL,rate REAL NOT NULL,value REAL NOT NULL,notes TEXT,received_at TEXT NOT NULL,received_by INTEGER REFERENCES users(id));
CREATE TABLE IF NOT EXISTS purchases (id INTEGER PRIMARY KEY AUTOINCREMENT,purchase_no TEXT NOT NULL UNIQUE,client_request_id TEXT UNIQUE,supplier_id INTEGER REFERENCES suppliers(id),branch_id INTEGER NOT NULL REFERENCES branches(id),subtotal REAL NOT NULL DEFAULT 0,gst REAL NOT NULL DEFAULT 0,total REAL NOT NULL DEFAULT 0,paid REAL NOT NULL DEFAULT 0,notes TEXT,user_id INTEGER NOT NULL REFERENCES users(id),created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS purchase_items (id INTEGER PRIMARY KEY AUTOINCREMENT,purchase_id INTEGER NOT NULL REFERENCES purchases(id) ON DELETE CASCADE,item_id INTEGER NOT NULL REFERENCES items(id),cost_amount REAL NOT NULL,gst_amount REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS repairs (id INTEGER PRIMARY KEY AUTOINCREMENT,repair_no TEXT NOT NULL UNIQUE,customer_id INTEGER REFERENCES customers(id),item_description TEXT NOT NULL,tag_no TEXT,gross_weight REAL NOT NULL DEFAULT 0,received_on TEXT NOT NULL,promised_on TEXT,status TEXT NOT NULL DEFAULT 'received' CHECK(status IN ('received','assigned','in_progress','ready','delivered','cancelled')),karigar_id INTEGER REFERENCES karigars(id),estimated_amount REAL NOT NULL DEFAULT 0,advance REAL NOT NULL DEFAULT 0,final_amount REAL NOT NULL DEFAULT 0,notes TEXT,created_by INTEGER NOT NULL REFERENCES users(id),updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT,order_no TEXT NOT NULL UNIQUE,customer_id INTEGER REFERENCES customers(id),description TEXT NOT NULL,metal TEXT NOT NULL,purity TEXT NOT NULL,target_weight REAL NOT NULL DEFAULT 0,karigar_id INTEGER REFERENCES karigars(id),status TEXT NOT NULL DEFAULT 'new' CHECK(status IN ('new','assigned','in_progress','ready','delivered','cancelled')),estimated_amount REAL NOT NULL DEFAULT 0,advance REAL NOT NULL DEFAULT 0,due_date TEXT,notes TEXT,created_by INTEGER NOT NULL REFERENCES users(id),created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS karigar_ledger (id INTEGER PRIMARY KEY AUTOINCREMENT,karigar_id INTEGER NOT NULL REFERENCES karigars(id),entry_type TEXT NOT NULL CHECK(entry_type IN ('metal_issue','metal_receive','cash_debit','cash_credit','making_charge','adjustment')),metal TEXT,weight REAL NOT NULL DEFAULT 0,amount REAL NOT NULL DEFAULT 0,ref_type TEXT,ref_id INTEGER,note TEXT,user_id INTEGER REFERENCES users(id),created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS approvals (id INTEGER PRIMARY KEY AUTOINCREMENT,approval_no TEXT NOT NULL UNIQUE,party_name TEXT NOT NULL,party_phone TEXT,issued_at TEXT NOT NULL,due_at TEXT,status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','partial','closed','cancelled')),note TEXT,user_id INTEGER NOT NULL REFERENCES users(id));
CREATE TABLE IF NOT EXISTS approval_items (id INTEGER PRIMARY KEY AUTOINCREMENT,approval_id INTEGER NOT NULL REFERENCES approvals(id) ON DELETE CASCADE,item_id INTEGER NOT NULL REFERENCES items(id),status TEXT NOT NULL DEFAULT 'out' CHECK(status IN ('out','returned','sold')),returned_at TEXT);
CREATE TABLE IF NOT EXISTS stock_audits (id INTEGER PRIMARY KEY AUTOINCREMENT,audit_no TEXT NOT NULL UNIQUE,branch_id INTEGER NOT NULL REFERENCES branches(id),counter_id INTEGER REFERENCES counters(id),status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','closed')),started_by INTEGER NOT NULL REFERENCES users(id),started_at TEXT NOT NULL,closed_at TEXT);
CREATE TABLE IF NOT EXISTS stock_audit_scans (id INTEGER PRIMARY KEY AUTOINCREMENT,audit_id INTEGER NOT NULL REFERENCES stock_audits(id) ON DELETE CASCADE,item_id INTEGER NOT NULL REFERENCES items(id),scanned_by INTEGER NOT NULL REFERENCES users(id),scanned_at TEXT NOT NULL,UNIQUE(audit_id,item_id));
CREATE TABLE IF NOT EXISTS accounts (code TEXT PRIMARY KEY,name TEXT NOT NULL,account_type TEXT NOT NULL CHECK(account_type IN ('asset','liability','income','expense','equity')),active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS journal_entries (id INTEGER PRIMARY KEY AUTOINCREMENT,entry_no TEXT NOT NULL UNIQUE,entry_date TEXT NOT NULL,memo TEXT,ref_type TEXT,ref_id INTEGER,user_id INTEGER REFERENCES users(id),created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS journal_lines (id INTEGER PRIMARY KEY AUTOINCREMENT,entry_id INTEGER NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE,account_code TEXT NOT NULL REFERENCES accounts(code),debit REAL NOT NULL DEFAULT 0,credit REAL NOT NULL DEFAULT 0,party_type TEXT,party_id INTEGER,CHECK(debit>=0 AND credit>=0),CHECK(NOT (debit>0 AND credit>0)));
CREATE INDEX IF NOT EXISTS idx_journal_lines_account ON journal_lines(account_code);
CREATE TABLE IF NOT EXISTS sequences (name TEXT PRIMARY KEY,value INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER REFERENCES users(id),action TEXT NOT NULL,entity TEXT NOT NULL,entity_id TEXT,details_json TEXT,client_ip TEXT,created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at DESC);
CREATE TABLE IF NOT EXISTS tally_ledger_mappings (mapping_key TEXT PRIMARY KEY,tally_ledger_name TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tally_sync_queue (id INTEGER PRIMARY KEY AUTOINCREMENT,entity_type TEXT NOT NULL,entity_id INTEGER NOT NULL,operation TEXT NOT NULL CHECK(operation IN ('create','cancel')),remote_id TEXT NOT NULL,payload_hash TEXT,tally_master_id TEXT,tally_voucher_no TEXT,status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','sending','synced','failed','conflict')),attempt_count INTEGER NOT NULL DEFAULT 0,last_error TEXT,response_json TEXT,next_attempt_at TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,synced_at TEXT,UNIQUE(entity_type,entity_id,operation));
CREATE INDEX IF NOT EXISTS idx_tally_queue_status ON tally_sync_queue(status,next_attempt_at,id);
CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL);
"""

TALLY_DEFAULT_MAPPINGS={"cash":"Cash","bank":"Bank / Card / UPI","sales":"Jewellery Sales","inventory":"Jewellery Inventory","cogs":"Cost of Goods Sold","old_gold":"Old Gold Inventory","customer_receivables":"Sundry Debtors Control","supplier_payables":"Sundry Creditors Control","input_gst":"Input GST","cgst":"Output CGST 1.5%","sgst":"Output SGST 1.5%","igst":"Output IGST 3%","round_off":"Round Off"}


def _table_columns(conn, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _add_column_if_missing(conn, table: str, name: str, spec: str) -> None:
    if name not in _table_columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {spec}")


def _migration_1(conn) -> None:
    for name, spec in {
        "place_of_supply_code": "TEXT",
        "cgst": "REAL NOT NULL DEFAULT 0",
        "sgst": "REAL NOT NULL DEFAULT 0",
        "igst": "REAL NOT NULL DEFAULT 0",
    }.items():
        _add_column_if_missing(conn, "sales", name, spec)


def _migration_2(conn) -> None:
    _add_column_if_missing(conn, "items", "net_weight_override_reason", "TEXT")
    _add_column_if_missing(conn, "audit_log", "prev_hash", "TEXT")
    _add_column_if_missing(conn, "audit_log", "entry_hash", "TEXT")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS auth_failures (identity TEXT PRIMARY KEY,fail_count INTEGER NOT NULL DEFAULT 0,"
        "window_started TEXT NOT NULL,locked_until TEXT,updated_at TEXT NOT NULL)"
    )
    conn.execute("UPDATE items SET huid=upper(trim(huid)) WHERE huid IS NOT NULL AND trim(huid)<>''")
    from .audit_chain import GENESIS_HASH, compute_audit_hash
    prev = GENESIS_HASH
    rows = conn.execute(
        "SELECT id,user_id,action,entity,entity_id,details_json,client_ip,created_at FROM audit_log ORDER BY id"
    ).fetchall()
    for row in rows:
        entry_hash = compute_audit_hash(
            prev,row["user_id"],row["action"],row["entity"],row["entity_id"],row["details_json"],row["client_ip"],row["created_at"]
        )
        conn.execute("UPDATE audit_log SET prev_hash=?,entry_hash=? WHERE id=?", (prev, entry_hash, row["id"]))
        prev = entry_hash


def _migration_3(conn) -> None:
    statements = [
        """CREATE TRIGGER IF NOT EXISTS items_weight_guard_insert BEFORE INSERT ON items
        WHEN NEW.stone_weight>NEW.gross_weight+0.0005 OR NEW.net_weight<0 OR
        (abs(NEW.net_weight-(NEW.gross_weight-NEW.stone_weight))>0.0015 AND coalesce(trim(NEW.net_weight_override_reason),'')='')
        BEGIN SELECT RAISE(ABORT,'inconsistent jewellery weights'); END""",
        """CREATE TRIGGER IF NOT EXISTS items_weight_guard_update BEFORE UPDATE OF gross_weight,stone_weight,net_weight,net_weight_override_reason ON items
        WHEN NEW.stone_weight>NEW.gross_weight+0.0005 OR NEW.net_weight<0 OR
        (abs(NEW.net_weight-(NEW.gross_weight-NEW.stone_weight))>0.0015 AND coalesce(trim(NEW.net_weight_override_reason),'')='')
        BEGIN SELECT RAISE(ABORT,'inconsistent jewellery weights'); END""",
        """CREATE TRIGGER IF NOT EXISTS items_huid_guard_insert BEFORE INSERT ON items
        WHEN NEW.huid IS NOT NULL AND trim(NEW.huid)<>'' AND (length(trim(NEW.huid))<>6 OR upper(trim(NEW.huid)) GLOB '*[^A-Z0-9]*')
        BEGIN SELECT RAISE(ABORT,'HUID must be six alphanumeric characters'); END""",
        """CREATE TRIGGER IF NOT EXISTS items_huid_guard_update BEFORE UPDATE OF huid ON items
        WHEN NEW.huid IS NOT NULL AND trim(NEW.huid)<>'' AND (length(trim(NEW.huid))<>6 OR upper(trim(NEW.huid)) GLOB '*[^A-Z0-9]*')
        BEGIN SELECT RAISE(ABORT,'HUID must be six alphanumeric characters'); END""",
        "CREATE TRIGGER IF NOT EXISTS audit_log_no_update BEFORE UPDATE ON audit_log BEGIN SELECT RAISE(ABORT,'audit log is append-only'); END",
        "CREATE TRIGGER IF NOT EXISTS audit_log_no_delete BEFORE DELETE ON audit_log BEGIN SELECT RAISE(ABORT,'audit log is append-only'); END",
        "CREATE TRIGGER IF NOT EXISTS stock_movements_no_update BEFORE UPDATE ON stock_movements BEGIN SELECT RAISE(ABORT,'stock movements are immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS stock_movements_no_delete BEFORE DELETE ON stock_movements BEGIN SELECT RAISE(ABORT,'stock movements are immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS sale_items_no_update BEFORE UPDATE ON sale_items BEGIN SELECT RAISE(ABORT,'posted sale lines are immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS sale_items_no_delete BEFORE DELETE ON sale_items BEGIN SELECT RAISE(ABORT,'posted sale lines are immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS journal_entries_no_update BEFORE UPDATE ON journal_entries BEGIN SELECT RAISE(ABORT,'journal entries are immutable; post a reversal'); END",
        "CREATE TRIGGER IF NOT EXISTS journal_entries_no_delete BEFORE DELETE ON journal_entries BEGIN SELECT RAISE(ABORT,'journal entries are immutable; post a reversal'); END",
        "CREATE TRIGGER IF NOT EXISTS journal_lines_no_update BEFORE UPDATE ON journal_lines BEGIN SELECT RAISE(ABORT,'journal lines are immutable; post a reversal'); END",
        "CREATE TRIGGER IF NOT EXISTS journal_lines_no_delete BEFORE DELETE ON journal_lines BEGIN SELECT RAISE(ABORT,'journal lines are immutable; post a reversal'); END",
        "CREATE TRIGGER IF NOT EXISTS old_gold_no_update BEFORE UPDATE ON old_gold BEGIN SELECT RAISE(ABORT,'old-gold receipt lines are immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS old_gold_no_delete BEFORE DELETE ON old_gold BEGIN SELECT RAISE(ABORT,'old-gold receipt lines are immutable'); END",
        """CREATE TRIGGER IF NOT EXISTS sales_financial_no_update BEFORE UPDATE OF invoice_no,client_request_id,branch_id,counter_id,customer_id,subtotal,discount,taxable,gst,place_of_supply_code,cgst,sgst,igst,round_off,total,payment_cash,payment_card,payment_upi,payment_credit,old_gold_value,user_id,created_at ON sales
        BEGIN SELECT RAISE(ABORT,'posted invoice financial fields are immutable; cancel/reverse instead'); END""",
        "CREATE TRIGGER IF NOT EXISTS purchases_no_update BEFORE UPDATE ON purchases BEGIN SELECT RAISE(ABORT,'posted purchases are immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS purchases_no_delete BEFORE DELETE ON purchases BEGIN SELECT RAISE(ABORT,'posted purchases are immutable'); END",
        "CREATE INDEX IF NOT EXISTS idx_auth_failures_updated ON auth_failures(updated_at)",
    ]
    for statement in statements:
        conn.execute(statement)


def _migration_4(conn) -> None:
    # Canonical integer mirrors make paise/milligram values exact while the
    # legacy REAL fields remain for compatibility with the v1 API and PDFs.
    column_specs = {
        "items": {
            "gross_mg": "INTEGER", "stone_mg": "INTEGER", "net_mg": "INTEGER", "fine_mg": "INTEGER",
            "stone_value_paise": "INTEGER", "cost_amount_paise": "INTEGER",
        },
        "metal_rates": {"rate_paise_per_gram": "INTEGER"},
        "sales": {
            "business_date": "TEXT", "subtotal_paise": "INTEGER", "discount_paise": "INTEGER",
            "taxable_paise": "INTEGER", "gst_paise": "INTEGER", "cgst_paise": "INTEGER",
            "sgst_paise": "INTEGER", "igst_paise": "INTEGER", "round_off_paise": "INTEGER",
            "total_paise": "INTEGER", "payment_cash_paise": "INTEGER", "payment_card_paise": "INTEGER",
            "payment_upi_paise": "INTEGER", "payment_credit_paise": "INTEGER", "old_gold_value_paise": "INTEGER",
        },
        "sale_items": {
            "gross_mg": "INTEGER", "net_mg": "INTEGER", "metal_rate_paise": "INTEGER",
            "metal_value_paise": "INTEGER", "wastage_value_paise": "INTEGER", "making_charge_paise": "INTEGER",
            "stone_value_paise": "INTEGER", "discount_paise": "INTEGER", "taxable_paise": "INTEGER",
            "gst_amount_paise": "INTEGER", "line_total_paise": "INTEGER", "cost_amount_paise": "INTEGER",
        },
        "old_gold": {
            "gross_mg": "INTEGER", "net_mg": "INTEGER", "pure_mg": "INTEGER",
            "rate_paise": "INTEGER", "value_paise": "INTEGER",
        },
        "purchases": {
            "business_date": "TEXT", "subtotal_paise": "INTEGER", "gst_paise": "INTEGER",
            "total_paise": "INTEGER", "paid_paise": "INTEGER",
        },
        "purchase_items": {"cost_amount_paise": "INTEGER", "gst_amount_paise": "INTEGER"},
        "journal_lines": {"debit_paise": "INTEGER", "credit_paise": "INTEGER"},
    }
    for table, specs in column_specs.items():
        for name, spec in specs.items():
            _add_column_if_missing(conn, table, name, spec)

    # Full UPDATE immutability triggers need to be temporarily removed only
    # while existing rows receive their canonical mirrors in this transaction.
    for trigger in (
        "sale_items_no_update", "old_gold_no_update", "purchases_no_update", "journal_lines_no_update"
    ):
        conn.execute(f"DROP TRIGGER IF EXISTS {trigger}")

    conn.execute("""UPDATE items SET
        gross_mg=CAST(ROUND(gross_weight*1000) AS INTEGER),
        stone_mg=CAST(ROUND(stone_weight*1000) AS INTEGER),
        net_mg=CAST(ROUND(net_weight*1000) AS INTEGER),
        fine_mg=CAST(ROUND(fine_weight*1000) AS INTEGER),
        stone_value_paise=CAST(ROUND(stone_value*100) AS INTEGER),
        cost_amount_paise=CAST(ROUND(cost_amount*100) AS INTEGER)""")
    conn.execute("UPDATE metal_rates SET rate_paise_per_gram=CAST(ROUND(rate_per_gram*100) AS INTEGER)")
    conn.execute("""UPDATE sales SET
        business_date=coalesce(business_date,substr(created_at,1,10)),
        subtotal_paise=CAST(ROUND(subtotal*100) AS INTEGER),discount_paise=CAST(ROUND(discount*100) AS INTEGER),
        taxable_paise=CAST(ROUND(taxable*100) AS INTEGER),gst_paise=CAST(ROUND(gst*100) AS INTEGER),
        cgst_paise=CAST(ROUND(cgst*100) AS INTEGER),sgst_paise=CAST(ROUND(sgst*100) AS INTEGER),
        igst_paise=CAST(ROUND(igst*100) AS INTEGER),round_off_paise=CAST(ROUND(round_off*100) AS INTEGER),
        total_paise=CAST(ROUND(total*100) AS INTEGER),payment_cash_paise=CAST(ROUND(payment_cash*100) AS INTEGER),
        payment_card_paise=CAST(ROUND(payment_card*100) AS INTEGER),payment_upi_paise=CAST(ROUND(payment_upi*100) AS INTEGER),
        payment_credit_paise=CAST(ROUND(payment_credit*100) AS INTEGER),old_gold_value_paise=CAST(ROUND(old_gold_value*100) AS INTEGER)""")
    conn.execute("""UPDATE sale_items SET
        gross_mg=CAST(ROUND(gross_weight*1000) AS INTEGER),net_mg=CAST(ROUND(net_weight*1000) AS INTEGER),
        metal_rate_paise=CAST(ROUND(metal_rate*100) AS INTEGER),metal_value_paise=CAST(ROUND(metal_value*100) AS INTEGER),
        wastage_value_paise=CAST(ROUND(wastage_value*100) AS INTEGER),making_charge_paise=CAST(ROUND(making_charge*100) AS INTEGER),
        stone_value_paise=CAST(ROUND(stone_value*100) AS INTEGER),discount_paise=CAST(ROUND(discount*100) AS INTEGER),
        taxable_paise=CAST(ROUND(taxable*100) AS INTEGER),gst_amount_paise=CAST(ROUND(gst_amount*100) AS INTEGER),
        line_total_paise=CAST(ROUND(line_total*100) AS INTEGER),cost_amount_paise=CAST(ROUND(cost_amount*100) AS INTEGER)""")
    conn.execute("""UPDATE old_gold SET gross_mg=CAST(ROUND(gross_weight*1000) AS INTEGER),
        net_mg=CAST(ROUND(net_weight*1000) AS INTEGER),pure_mg=CAST(ROUND(pure_weight*1000) AS INTEGER),
        rate_paise=CAST(ROUND(rate*100) AS INTEGER),value_paise=CAST(ROUND(value*100) AS INTEGER)""")
    conn.execute("""UPDATE purchases SET business_date=coalesce(business_date,substr(created_at,1,10)),
        subtotal_paise=CAST(ROUND(subtotal*100) AS INTEGER),gst_paise=CAST(ROUND(gst*100) AS INTEGER),
        total_paise=CAST(ROUND(total*100) AS INTEGER),paid_paise=CAST(ROUND(paid*100) AS INTEGER)""")
    conn.execute("UPDATE purchase_items SET cost_amount_paise=CAST(ROUND(cost_amount*100) AS INTEGER),gst_amount_paise=CAST(ROUND(gst_amount*100) AS INTEGER)")
    conn.execute("UPDATE journal_lines SET debit_paise=CAST(ROUND(debit*100) AS INTEGER),credit_paise=CAST(ROUND(credit*100) AS INTEGER)")

    # Recreate v3 update guards, then add v4 canonical guards.
    _migration_3(conn)
    statements = [
        "CREATE TRIGGER IF NOT EXISTS purchase_items_no_update BEFORE UPDATE ON purchase_items BEGIN SELECT RAISE(ABORT,'posted purchase lines are immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS purchase_items_no_delete BEFORE DELETE ON purchase_items BEGIN SELECT RAISE(ABORT,'posted purchase lines are immutable'); END",
        """CREATE TRIGGER IF NOT EXISTS canonical_items_insert BEFORE INSERT ON items WHEN
        NEW.gross_mg IS NULL OR NEW.gross_mg!=CAST(ROUND(NEW.gross_weight*1000) AS INTEGER) OR
        NEW.stone_mg IS NULL OR NEW.stone_mg!=CAST(ROUND(NEW.stone_weight*1000) AS INTEGER) OR
        NEW.net_mg IS NULL OR NEW.net_mg!=CAST(ROUND(NEW.net_weight*1000) AS INTEGER) OR
        NEW.fine_mg IS NULL OR NEW.fine_mg!=CAST(ROUND(NEW.fine_weight*1000) AS INTEGER) OR
        NEW.stone_value_paise IS NULL OR NEW.stone_value_paise!=CAST(ROUND(NEW.stone_value*100) AS INTEGER) OR
        NEW.cost_amount_paise IS NULL OR NEW.cost_amount_paise!=CAST(ROUND(NEW.cost_amount*100) AS INTEGER)
        BEGIN SELECT RAISE(ABORT,'item canonical mirror mismatch'); END""",
        """CREATE TRIGGER IF NOT EXISTS canonical_items_update BEFORE UPDATE OF gross_weight,stone_weight,net_weight,fine_weight,stone_value,cost_amount,gross_mg,stone_mg,net_mg,fine_mg,stone_value_paise,cost_amount_paise ON items WHEN
        NEW.gross_mg IS NULL OR NEW.gross_mg!=CAST(ROUND(NEW.gross_weight*1000) AS INTEGER) OR
        NEW.stone_mg IS NULL OR NEW.stone_mg!=CAST(ROUND(NEW.stone_weight*1000) AS INTEGER) OR
        NEW.net_mg IS NULL OR NEW.net_mg!=CAST(ROUND(NEW.net_weight*1000) AS INTEGER) OR
        NEW.fine_mg IS NULL OR NEW.fine_mg!=CAST(ROUND(NEW.fine_weight*1000) AS INTEGER) OR
        NEW.stone_value_paise IS NULL OR NEW.stone_value_paise!=CAST(ROUND(NEW.stone_value*100) AS INTEGER) OR
        NEW.cost_amount_paise IS NULL OR NEW.cost_amount_paise!=CAST(ROUND(NEW.cost_amount*100) AS INTEGER)
        BEGIN SELECT RAISE(ABORT,'item canonical mirror mismatch'); END""",
        """CREATE TRIGGER IF NOT EXISTS canonical_rate_insert BEFORE INSERT ON metal_rates WHEN
        NEW.rate_paise_per_gram IS NULL OR NEW.rate_paise_per_gram!=CAST(ROUND(NEW.rate_per_gram*100) AS INTEGER)
        BEGIN SELECT RAISE(ABORT,'metal-rate canonical mirror mismatch'); END""",
        """CREATE TRIGGER IF NOT EXISTS canonical_sales_insert BEFORE INSERT ON sales WHEN
        NEW.business_date IS NULL OR length(NEW.business_date)!=10 OR
        NEW.subtotal_paise IS NULL OR NEW.subtotal_paise!=CAST(ROUND(NEW.subtotal*100) AS INTEGER) OR
        NEW.discount_paise IS NULL OR NEW.discount_paise!=CAST(ROUND(NEW.discount*100) AS INTEGER) OR
        NEW.taxable_paise IS NULL OR NEW.taxable_paise!=CAST(ROUND(NEW.taxable*100) AS INTEGER) OR
        NEW.gst_paise IS NULL OR NEW.gst_paise!=CAST(ROUND(NEW.gst*100) AS INTEGER) OR
        NEW.cgst_paise IS NULL OR NEW.cgst_paise!=CAST(ROUND(NEW.cgst*100) AS INTEGER) OR
        NEW.sgst_paise IS NULL OR NEW.sgst_paise!=CAST(ROUND(NEW.sgst*100) AS INTEGER) OR
        NEW.igst_paise IS NULL OR NEW.igst_paise!=CAST(ROUND(NEW.igst*100) AS INTEGER) OR
        NEW.round_off_paise IS NULL OR NEW.round_off_paise!=CAST(ROUND(NEW.round_off*100) AS INTEGER) OR
        NEW.total_paise IS NULL OR NEW.total_paise!=CAST(ROUND(NEW.total*100) AS INTEGER) OR
        NEW.payment_cash_paise IS NULL OR NEW.payment_cash_paise!=CAST(ROUND(NEW.payment_cash*100) AS INTEGER) OR
        NEW.payment_card_paise IS NULL OR NEW.payment_card_paise!=CAST(ROUND(NEW.payment_card*100) AS INTEGER) OR
        NEW.payment_upi_paise IS NULL OR NEW.payment_upi_paise!=CAST(ROUND(NEW.payment_upi*100) AS INTEGER) OR
        NEW.payment_credit_paise IS NULL OR NEW.payment_credit_paise!=CAST(ROUND(NEW.payment_credit*100) AS INTEGER) OR
        NEW.old_gold_value_paise IS NULL OR NEW.old_gold_value_paise!=CAST(ROUND(NEW.old_gold_value*100) AS INTEGER)
        BEGIN SELECT RAISE(ABORT,'sale canonical mirror mismatch'); END""",
        """CREATE TRIGGER IF NOT EXISTS canonical_sale_items_insert BEFORE INSERT ON sale_items WHEN
        NEW.gross_mg IS NULL OR NEW.gross_mg!=CAST(ROUND(NEW.gross_weight*1000) AS INTEGER) OR
        NEW.net_mg IS NULL OR NEW.net_mg!=CAST(ROUND(NEW.net_weight*1000) AS INTEGER) OR
        NEW.metal_rate_paise IS NULL OR NEW.metal_rate_paise!=CAST(ROUND(NEW.metal_rate*100) AS INTEGER) OR
        NEW.metal_value_paise IS NULL OR NEW.metal_value_paise!=CAST(ROUND(NEW.metal_value*100) AS INTEGER) OR
        NEW.wastage_value_paise IS NULL OR NEW.wastage_value_paise!=CAST(ROUND(NEW.wastage_value*100) AS INTEGER) OR
        NEW.making_charge_paise IS NULL OR NEW.making_charge_paise!=CAST(ROUND(NEW.making_charge*100) AS INTEGER) OR
        NEW.stone_value_paise IS NULL OR NEW.stone_value_paise!=CAST(ROUND(NEW.stone_value*100) AS INTEGER) OR
        NEW.discount_paise IS NULL OR NEW.discount_paise!=CAST(ROUND(NEW.discount*100) AS INTEGER) OR
        NEW.taxable_paise IS NULL OR NEW.taxable_paise!=CAST(ROUND(NEW.taxable*100) AS INTEGER) OR
        NEW.gst_amount_paise IS NULL OR NEW.gst_amount_paise!=CAST(ROUND(NEW.gst_amount*100) AS INTEGER) OR
        NEW.line_total_paise IS NULL OR NEW.line_total_paise!=CAST(ROUND(NEW.line_total*100) AS INTEGER) OR
        NEW.cost_amount_paise IS NULL OR NEW.cost_amount_paise!=CAST(ROUND(NEW.cost_amount*100) AS INTEGER)
        BEGIN SELECT RAISE(ABORT,'sale-line canonical mirror mismatch'); END""",
        """CREATE TRIGGER IF NOT EXISTS canonical_old_gold_insert BEFORE INSERT ON old_gold WHEN
        NEW.gross_mg IS NULL OR NEW.gross_mg!=CAST(ROUND(NEW.gross_weight*1000) AS INTEGER) OR
        NEW.net_mg IS NULL OR NEW.net_mg!=CAST(ROUND(NEW.net_weight*1000) AS INTEGER) OR
        NEW.pure_mg IS NULL OR NEW.pure_mg!=CAST(ROUND(NEW.pure_weight*1000) AS INTEGER) OR
        NEW.rate_paise IS NULL OR NEW.rate_paise!=CAST(ROUND(NEW.rate*100) AS INTEGER) OR
        NEW.value_paise IS NULL OR NEW.value_paise!=CAST(ROUND(NEW.value*100) AS INTEGER)
        BEGIN SELECT RAISE(ABORT,'old-gold canonical mirror mismatch'); END""",
        """CREATE TRIGGER IF NOT EXISTS canonical_purchases_insert BEFORE INSERT ON purchases WHEN
        NEW.business_date IS NULL OR length(NEW.business_date)!=10 OR
        NEW.subtotal_paise IS NULL OR NEW.subtotal_paise!=CAST(ROUND(NEW.subtotal*100) AS INTEGER) OR
        NEW.gst_paise IS NULL OR NEW.gst_paise!=CAST(ROUND(NEW.gst*100) AS INTEGER) OR
        NEW.total_paise IS NULL OR NEW.total_paise!=CAST(ROUND(NEW.total*100) AS INTEGER) OR
        NEW.paid_paise IS NULL OR NEW.paid_paise!=CAST(ROUND(NEW.paid*100) AS INTEGER)
        BEGIN SELECT RAISE(ABORT,'purchase canonical mirror mismatch'); END""",
        """CREATE TRIGGER IF NOT EXISTS canonical_purchase_items_insert BEFORE INSERT ON purchase_items WHEN
        NEW.cost_amount_paise IS NULL OR NEW.cost_amount_paise!=CAST(ROUND(NEW.cost_amount*100) AS INTEGER) OR
        NEW.gst_amount_paise IS NULL OR NEW.gst_amount_paise!=CAST(ROUND(NEW.gst_amount*100) AS INTEGER)
        BEGIN SELECT RAISE(ABORT,'purchase-line canonical mirror mismatch'); END""",
        """CREATE TRIGGER IF NOT EXISTS canonical_journal_lines_insert BEFORE INSERT ON journal_lines WHEN
        NEW.debit_paise IS NULL OR NEW.debit_paise!=CAST(ROUND(NEW.debit*100) AS INTEGER) OR
        NEW.credit_paise IS NULL OR NEW.credit_paise!=CAST(ROUND(NEW.credit*100) AS INTEGER)
        BEGIN SELECT RAISE(ABORT,'journal-line canonical mirror mismatch'); END""",
    ]
    conn.execute("DROP TRIGGER IF EXISTS sales_financial_no_update")
    conn.execute("""CREATE TRIGGER sales_financial_no_update BEFORE UPDATE OF invoice_no,client_request_id,branch_id,counter_id,customer_id,business_date,subtotal,discount,taxable,gst,place_of_supply_code,cgst,sgst,igst,round_off,total,payment_cash,payment_card,payment_upi,payment_credit,old_gold_value,subtotal_paise,discount_paise,taxable_paise,gst_paise,cgst_paise,sgst_paise,igst_paise,round_off_paise,total_paise,payment_cash_paise,payment_card_paise,payment_upi_paise,payment_credit_paise,old_gold_value_paise,user_id,created_at ON sales
    BEGIN SELECT RAISE(ABORT,'posted invoice financial fields are immutable; cancel/reverse instead'); END""")
    for statement in statements:
        conn.execute(statement)


def _migration_5(conn) -> None:
    _add_column_if_missing(conn, "customers", "balance_paise", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "suppliers", "balance_paise", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "karigars", "cash_balance_paise", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "karigars", "metal_balance_mg", "INTEGER NOT NULL DEFAULT 0")
    conn.execute("UPDATE customers SET balance_paise=CAST(ROUND(balance*100) AS INTEGER)")
    conn.execute("UPDATE suppliers SET balance_paise=CAST(ROUND(balance*100) AS INTEGER)")
    conn.execute("UPDATE karigars SET cash_balance_paise=CAST(ROUND(cash_balance*100) AS INTEGER),metal_balance_mg=CAST(ROUND(metal_balance_grams*1000) AS INTEGER)")
    conn.executescript(r"""
    CREATE TABLE IF NOT EXISTS sale_returns (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      return_no TEXT NOT NULL UNIQUE,
      client_request_id TEXT UNIQUE,
      sale_id INTEGER NOT NULL REFERENCES sales(id),
      customer_id INTEGER REFERENCES customers(id),
      branch_id INTEGER NOT NULL REFERENCES branches(id),
      business_date TEXT NOT NULL,
      taxable_paise INTEGER NOT NULL CHECK(taxable_paise>=0),
      gst_paise INTEGER NOT NULL CHECK(gst_paise>=0),
      cgst_paise INTEGER NOT NULL DEFAULT 0 CHECK(cgst_paise>=0),
      sgst_paise INTEGER NOT NULL DEFAULT 0 CHECK(sgst_paise>=0),
      igst_paise INTEGER NOT NULL DEFAULT 0 CHECK(igst_paise>=0),
      round_off_paise INTEGER NOT NULL DEFAULT 0,
      total_paise INTEGER NOT NULL CHECK(total_paise>=0),
      refund_cash_paise INTEGER NOT NULL DEFAULT 0 CHECK(refund_cash_paise>=0),
      refund_card_paise INTEGER NOT NULL DEFAULT 0 CHECK(refund_card_paise>=0),
      refund_upi_paise INTEGER NOT NULL DEFAULT 0 CHECK(refund_upi_paise>=0),
      refund_credit_paise INTEGER NOT NULL DEFAULT 0 CHECK(refund_credit_paise>=0),
      reason TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'posted' CHECK(status IN ('posted','cancelled')),
      user_id INTEGER NOT NULL REFERENCES users(id),
      created_at TEXT NOT NULL,
      cancelled_at TEXT,
      cancelled_by INTEGER REFERENCES users(id),
      CHECK(cgst_paise+sgst_paise+igst_paise=gst_paise),
      CHECK(refund_cash_paise+refund_card_paise+refund_upi_paise+refund_credit_paise=total_paise)
    );
    CREATE INDEX IF NOT EXISTS idx_sale_returns_sale ON sale_returns(sale_id,id);
    CREATE INDEX IF NOT EXISTS idx_sale_returns_date ON sale_returns(business_date,id);
    CREATE TABLE IF NOT EXISTS sale_return_items (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      return_id INTEGER NOT NULL REFERENCES sale_returns(id),
      sale_item_id INTEGER NOT NULL REFERENCES sale_items(id),
      item_id INTEGER NOT NULL REFERENCES items(id),
      tag_no TEXT NOT NULL,
      taxable_paise INTEGER NOT NULL CHECK(taxable_paise>=0),
      gst_amount_paise INTEGER NOT NULL CHECK(gst_amount_paise>=0),
      round_off_paise INTEGER NOT NULL DEFAULT 0,
      line_total_paise INTEGER NOT NULL CHECK(line_total_paise>=0),
      cost_amount_paise INTEGER NOT NULL DEFAULT 0 CHECK(cost_amount_paise>=0),
      active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1))
    );
    CREATE INDEX IF NOT EXISTS idx_sale_return_items_return ON sale_return_items(return_id,id);
    CREATE UNIQUE INDEX IF NOT EXISTS uq_sale_return_item_active ON sale_return_items(sale_item_id) WHERE active=1;

    CREATE TRIGGER IF NOT EXISTS canonical_customer_balance_insert BEFORE INSERT ON customers
    WHEN NEW.balance_paise!=CAST(ROUND(NEW.balance*100) AS INTEGER)
    BEGIN SELECT RAISE(ABORT,'customer balance mirror mismatch'); END;
    CREATE TRIGGER IF NOT EXISTS canonical_customer_balance_update BEFORE UPDATE OF balance,balance_paise ON customers
    WHEN NEW.balance_paise!=CAST(ROUND(NEW.balance*100) AS INTEGER)
    BEGIN SELECT RAISE(ABORT,'customer balance mirror mismatch'); END;
    CREATE TRIGGER IF NOT EXISTS canonical_supplier_balance_insert BEFORE INSERT ON suppliers
    WHEN NEW.balance_paise!=CAST(ROUND(NEW.balance*100) AS INTEGER)
    BEGIN SELECT RAISE(ABORT,'supplier balance mirror mismatch'); END;
    CREATE TRIGGER IF NOT EXISTS canonical_supplier_balance_update BEFORE UPDATE OF balance,balance_paise ON suppliers
    WHEN NEW.balance_paise!=CAST(ROUND(NEW.balance*100) AS INTEGER)
    BEGIN SELECT RAISE(ABORT,'supplier balance mirror mismatch'); END;
    CREATE TRIGGER IF NOT EXISTS canonical_karigar_balance_insert BEFORE INSERT ON karigars
    WHEN NEW.cash_balance_paise!=CAST(ROUND(NEW.cash_balance*100) AS INTEGER) OR NEW.metal_balance_mg!=CAST(ROUND(NEW.metal_balance_grams*1000) AS INTEGER)
    BEGIN SELECT RAISE(ABORT,'karigar balance mirror mismatch'); END;
    CREATE TRIGGER IF NOT EXISTS canonical_karigar_balance_update BEFORE UPDATE OF cash_balance,cash_balance_paise,metal_balance_grams,metal_balance_mg ON karigars
    WHEN NEW.cash_balance_paise!=CAST(ROUND(NEW.cash_balance*100) AS INTEGER) OR NEW.metal_balance_mg!=CAST(ROUND(NEW.metal_balance_grams*1000) AS INTEGER)
    BEGIN SELECT RAISE(ABORT,'karigar balance mirror mismatch'); END;

    CREATE TRIGGER IF NOT EXISTS sale_returns_financial_no_update BEFORE UPDATE OF
      return_no,client_request_id,sale_id,customer_id,branch_id,business_date,taxable_paise,gst_paise,cgst_paise,sgst_paise,igst_paise,round_off_paise,total_paise,refund_cash_paise,refund_card_paise,refund_upi_paise,refund_credit_paise,reason,user_id,created_at
      ON sale_returns BEGIN SELECT RAISE(ABORT,'posted credit-note financial fields are immutable'); END;
    CREATE TRIGGER IF NOT EXISTS sale_returns_no_delete BEFORE DELETE ON sale_returns
      BEGIN SELECT RAISE(ABORT,'credit notes cannot be deleted; cancel/reverse instead'); END;
    CREATE TRIGGER IF NOT EXISTS sale_return_items_financial_no_update BEFORE UPDATE OF
      return_id,sale_item_id,item_id,tag_no,taxable_paise,gst_amount_paise,round_off_paise,line_total_paise,cost_amount_paise
      ON sale_return_items BEGIN SELECT RAISE(ABORT,'posted credit-note lines are immutable'); END;
    CREATE TRIGGER IF NOT EXISTS sale_return_items_no_delete BEFORE DELETE ON sale_return_items
      BEGIN SELECT RAISE(ABORT,'credit-note lines cannot be deleted'); END;
    """)
    main_branch = conn.execute("SELECT id FROM branches WHERE code='MAIN'").fetchone()
    if main_branch:
        bid=int(main_branch[0])
        if conn.execute("SELECT 1 FROM counters WHERE branch_id=? AND name='Main Counter'",(bid,)).fetchone() and not conn.execute("SELECT 1 FROM counters WHERE branch_id=? AND name='Counter 1'",(bid,)).fetchone():
            conn.execute("UPDATE counters SET name='Counter 1' WHERE branch_id=? AND name='Main Counter'",(bid,))
        conn.execute("INSERT OR IGNORE INTO counters(branch_id,name,active) VALUES(?,'Counter 1',1)",(bid,))
        conn.execute("INSERT OR IGNORE INTO counters(branch_id,name,active) VALUES(?,'Counter 2',1)",(bid,))
        conn.execute("INSERT OR IGNORE INTO counters(branch_id,name,active) VALUES(?,'Counter 3',1)",(bid,))
        conn.execute("UPDATE branches SET name='Bijoria Main Showroom' WHERE id=? AND name='Main Showroom'",(bid,))
    conn.execute("UPDATE settings SET value='Bijoria',updated_at=? WHERE key='business_name' AND value='My Jewellery Store'",(utcnow(),))
    conn.execute("UPDATE settings SET value='36',updated_at=? WHERE key='business_state_code' AND trim(value)=''",(utcnow(),))
    conn.execute("INSERT OR IGNORE INTO sequences(name,value) VALUES('return',0)")


MIGRATIONS = ((1, _migration_1), (2, _migration_2), (3, _migration_3), (4, _migration_4), (5, _migration_5))

def _migrate_schema(conn) -> None:
    applied = {int(r[0]) for r in conn.execute("SELECT version FROM schema_migrations").fetchall()}
    for version, migration in MIGRATIONS:
        if version in applied:
            continue
        conn.execute("BEGIN IMMEDIATE")
        try:
            migration(conn)
            conn.execute("INSERT INTO schema_migrations(version,applied_at) VALUES(?,?)", (version, utcnow()))
            conn.execute(f"PRAGMA user_version={version}")
            conn.execute("COMMIT")
        except Exception:
            with contextlib.suppress(Exception):
                conn.execute("ROLLBACK")
            raise


def _ensure_optional_indexes(conn) -> None:
    duplicate = conn.execute(
        "SELECT 1 FROM items WHERE huid IS NOT NULL AND trim(huid)<>'' GROUP BY upper(trim(huid)) HAVING count(*)>1 LIMIT 1"
    ).fetchone()
    if not duplicate:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_items_huid ON items(huid COLLATE NOCASE) "
            "WHERE huid IS NOT NULL AND trim(huid)<>''"
        )

DEFAULT_ACCOUNTS=[("1000","Cash","asset"),("1010","Bank / Card / UPI","asset"),("1100","Customer Receivables","asset"),("1200","Jewellery Inventory","asset"),("1210","Old Gold Inventory","asset"),("2000","Supplier Payables","liability"),("2100","GST Output Payable","liability"),("2110","GST Input Credit","asset"),("3000","Owner Equity","equity"),("4000","Jewellery Sales","income"),("4010","Making Charges Income","income"),("5000","Cost of Goods Sold","expense"),("6000","General Expenses","expense")]

def init_db(password_hasher)->None:
    with connect() as conn:
        conn.executescript(SCHEMA); _migrate_schema(conn); _ensure_optional_indexes(conn); now=utcnow(); conn.execute("INSERT OR IGNORE INTO branches(code,name,gstin,address,phone,active) VALUES('MAIN','Main Showroom','','','',1)"); branch_id=conn.execute("SELECT id FROM branches WHERE code='MAIN'").fetchone()[0]; conn.execute("INSERT OR IGNORE INTO counters(branch_id,name,active) VALUES(?,'Counter 1',1)",(branch_id,)); conn.execute("INSERT OR IGNORE INTO counters(branch_id,name,active) VALUES(?,'Counter 2',1)",(branch_id,)); conn.execute("INSERT OR IGNORE INTO counters(branch_id,name,active) VALUES(?,'Counter 3',1)",(branch_id,))
        for code,name,typ in DEFAULT_ACCOUNTS: conn.execute("INSERT OR IGNORE INTO accounts(code,name,account_type,active) VALUES(?,?,?,1)",(code,name,typ))
        for key,name in TALLY_DEFAULT_MAPPINGS.items(): conn.execute("INSERT OR IGNORE INTO tally_ledger_mappings(mapping_key,tally_ledger_name,updated_at) VALUES(?,?,?)",(key,name,now))
        defaults={"business_name":"Bijoria","business_address":"","business_phone":"","business_gstin":"","business_timezone_offset_minutes":"330","currency":"INR","invoice_prefix":"INV","tag_prefix":"TAG","gst_default":"3","label_width_mm":"60","label_height_mm":"25","backup_interval_hours":"6","backup_retention_days":"30","business_state_code":"36","tally_enabled":"0","tally_bridge_url":"http://127.0.0.1:8767","tally_bridge_token":"","tally_company":"","tally_auto_create_parties":"1"}
        for k,v in defaults.items(): conn.execute("INSERT OR IGNORE INTO settings(key,value,updated_at) VALUES(?,?,?)",(k,v,now))
        if not conn.execute("SELECT id FROM users WHERE username='admin'").fetchone(): conn.execute("INSERT INTO users(username,password_hash,full_name,role,active,must_change_password,created_at,updated_at) VALUES(?,?,?,?,1,1,?,?)",("admin",password_hasher("Jewel@123"),"Administrator","admin",now,now))
        for seq in ("invoice","purchase","return","customer","supplier","karigar","repair","order","approval","audit","journal","tag"): conn.execute("INSERT OR IGNORE INTO sequences(name,value) VALUES(?,0)",(seq,))
        from .integrity import assert_storage_integrity
        assert_storage_integrity(conn)

def next_sequence(conn,name,prefix="",width=6):
    conn.execute("INSERT OR IGNORE INTO sequences(name,value) VALUES(?,0)",(name,));conn.execute("UPDATE sequences SET value=value+1 WHERE name=?",(name,));value=conn.execute("SELECT value FROM sequences WHERE name=?",(name,)).fetchone()[0];return f"{prefix}{value:0{width}d}"

def get_settings(conn): return {r["key"]:r["value"] for r in conn.execute("SELECT key,value FROM settings")}
def set_setting(conn,key,value): conn.execute("INSERT INTO settings(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",(key,value,utcnow()))
def audit(conn,user_id,action,entity,entity_id=None,details=None,client_ip=None):
    from .audit_chain import GENESIS_HASH, compute_audit_hash
    entity_id_s = None if entity_id is None else str(entity_id)
    details_json = None if details is None else json.dumps(details,ensure_ascii=False,default=str,sort_keys=True,separators=(",", ":"))
    created_at = utcnow()
    row = conn.execute("SELECT entry_hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    prev_hash = (row[0] if row and row[0] else GENESIS_HASH)
    entry_hash = compute_audit_hash(prev_hash,user_id,action,entity,entity_id_s,details_json,client_ip,created_at)
    conn.execute(
        "INSERT INTO audit_log(user_id,action,entity,entity_id,details_json,client_ip,created_at,prev_hash,entry_hash) VALUES(?,?,?,?,?,?,?,?,?)",
        (user_id,action,entity,entity_id_s,details_json,client_ip,created_at,prev_hash,entry_hash),
    )
