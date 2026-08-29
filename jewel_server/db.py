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


def app_data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
    else:
        base = Path(os.environ.get("JEWELLAN_DATA_DIR", Path.home() / ".jewellan"))
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

def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15, isolation_level=None, check_same_thread=False); conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON"); conn.execute("PRAGMA journal_mode=WAL"); conn.execute("PRAGMA synchronous=FULL"); conn.execute("PRAGMA busy_timeout=15000"); return conn

@contextlib.contextmanager
def read_db() -> Iterator[sqlite3.Connection]:
    conn=connect()
    try: yield conn
    finally: conn.close()

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

def _migrate_schema(conn):
    cols={r[1] for r in conn.execute("PRAGMA table_info(sales)").fetchall()}
    additions={"place_of_supply_code":"TEXT","cgst":"REAL NOT NULL DEFAULT 0","sgst":"REAL NOT NULL DEFAULT 0","igst":"REAL NOT NULL DEFAULT 0"}
    for name,spec in additions.items():
        if name not in cols:conn.execute(f"ALTER TABLE sales ADD COLUMN {name} {spec}")
    conn.execute("INSERT OR IGNORE INTO schema_migrations(version,applied_at) VALUES(1,?)",(utcnow(),))

DEFAULT_ACCOUNTS=[("1000","Cash","asset"),("1010","Bank / Card / UPI","asset"),("1100","Customer Receivables","asset"),("1200","Jewellery Inventory","asset"),("1210","Old Gold Inventory","asset"),("2000","Supplier Payables","liability"),("2100","GST Output Payable","liability"),("2110","GST Input Credit","asset"),("3000","Owner Equity","equity"),("4000","Jewellery Sales","income"),("4010","Making Charges Income","income"),("5000","Cost of Goods Sold","expense"),("6000","General Expenses","expense")]

def init_db(password_hasher)->None:
    with connect() as conn:
        conn.executescript(SCHEMA); _migrate_schema(conn); now=utcnow(); conn.execute("INSERT OR IGNORE INTO branches(code,name,gstin,address,phone,active) VALUES('MAIN','Main Showroom','','','',1)"); branch_id=conn.execute("SELECT id FROM branches WHERE code='MAIN'").fetchone()[0]; conn.execute("INSERT OR IGNORE INTO counters(branch_id,name,active) VALUES(?,'Main Counter',1)",(branch_id,))
        for code,name,typ in DEFAULT_ACCOUNTS: conn.execute("INSERT OR IGNORE INTO accounts(code,name,account_type,active) VALUES(?,?,?,1)",(code,name,typ))
        for key,name in TALLY_DEFAULT_MAPPINGS.items(): conn.execute("INSERT OR IGNORE INTO tally_ledger_mappings(mapping_key,tally_ledger_name,updated_at) VALUES(?,?,?)",(key,name,now))
        defaults={"business_name":"My Jewellery Store","business_address":"","business_phone":"","business_gstin":"","currency":"INR","invoice_prefix":"INV","tag_prefix":"TAG","gst_default":"3","label_width_mm":"60","label_height_mm":"25","backup_interval_hours":"6","backup_retention_days":"30","business_state_code":"","tally_enabled":"0","tally_bridge_url":"http://127.0.0.1:8767","tally_bridge_token":"","tally_company":"","tally_auto_create_parties":"1"}
        for k,v in defaults.items(): conn.execute("INSERT OR IGNORE INTO settings(key,value,updated_at) VALUES(?,?,?)",(k,v,now))
        if not conn.execute("SELECT id FROM users WHERE username='admin'").fetchone(): conn.execute("INSERT INTO users(username,password_hash,full_name,role,active,must_change_password,created_at,updated_at) VALUES(?,?,?,?,1,1,?,?)",("admin",password_hasher("Jewel@123"),"Administrator","admin",now,now))
        for seq in ("invoice","purchase","customer","supplier","karigar","repair","order","approval","audit","journal","tag"): conn.execute("INSERT OR IGNORE INTO sequences(name,value) VALUES(?,0)",(seq,))

def next_sequence(conn,name,prefix="",width=6):
    conn.execute("INSERT OR IGNORE INTO sequences(name,value) VALUES(?,0)",(name,));conn.execute("UPDATE sequences SET value=value+1 WHERE name=?",(name,));value=conn.execute("SELECT value FROM sequences WHERE name=?",(name,)).fetchone()[0];return f"{prefix}{value:0{width}d}"

def get_settings(conn): return {r["key"]:r["value"] for r in conn.execute("SELECT key,value FROM settings")}
def set_setting(conn,key,value): conn.execute("INSERT INTO settings(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",(key,value,utcnow()))
def audit(conn,user_id,action,entity,entity_id=None,details=None,client_ip=None): conn.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details_json,client_ip,created_at) VALUES(?,?,?,?,?,?,?)",(user_id,action,entity,None if entity_id is None else str(entity_id),None if details is None else json.dumps(details,ensure_ascii=False,default=str),client_ip,utcnow()))
