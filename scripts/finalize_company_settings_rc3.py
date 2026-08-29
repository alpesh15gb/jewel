from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        if new in text:
            return text
        raise RuntimeError(f"Expected fragment not found: {label}")
    if text.count(old) != 1:
        raise RuntimeError(f"Expected exactly one fragment for {label}, found {text.count(old)}")
    return text.replace(old, new, 1)


def patch_db() -> None:
    path = ROOT / 'jewel_server' / 'db.py'
    text = path.read_text('utf-8')
    old = '''        conn.execute("INSERT OR IGNORE INTO counters(branch_id,name,active) VALUES(?,'Counter 1',1)",(bid,))
        conn.execute("INSERT OR IGNORE INTO counters(branch_id,name,active) VALUES(?,'Counter 2',1)",(bid,))
        conn.execute("INSERT OR IGNORE INTO counters(branch_id,name,active) VALUES(?,'Counter 3',1)",(bid,))'''
    new = '''        conn.execute("INSERT OR IGNORE INTO counters(branch_id,name,active) VALUES(?,'Counter 1',1)",(bid,))'''
    text = replace_once(text, old, new, 'migration 5 generic counter')
    text = replace_once(
        text,
        '("items", "sales", "purchases", "customers", "suppliers", "karigars", "repairs", "orders", "approvals")',
        '("items", "sales", "sale_returns", "purchases", "customers", "suppliers", "karigars", "repairs", "orders", "approvals", "stock_audits")',
        'legacy seed data table set',
    )
    old_reset = '''        conn.execute("UPDATE branches SET name='Main Showroom',gstin='',address='',phone='' WHERE id=?", (branch["id"],))'''
    new_reset = '''        conn.execute("UPDATE branches SET name='Main Showroom',gstin='',address='',phone='' WHERE id=?", (branch["id"],))
        conn.execute("UPDATE counters SET active=CASE WHEN name='Counter 1' THEN 1 ELSE 0 END WHERE branch_id=?", (branch["id"],))'''
    text = replace_once(text, old_reset, new_reset, 'legacy counter cleanup')
    path.write_text(text, 'utf-8')


def patch_client() -> None:
    path = ROOT / 'jewel_client' / 'main.py'
    text = path.read_text('utf-8')
    old = '''        if role in ("admin","manager"): pages.append(("TallyPrime", TallyPage)); pages.append(("Administration", AdminPage))'''
    new = '''        if role in ("admin","manager"):
            pages.append(("TallyPrime", TallyPage))
            pages.append(("Administration", AdminPage))'''
    text = replace_once(text, old, new, 'role-aware administration navigation')
    path.write_text(text, 'utf-8')


def write_migration_tests() -> None:
    path = ROOT / 'tests' / 'test_company_settings.py'
    path.write_text(r'''import sqlite3

from jewel_server.db import _migration_6


COUNT_TABLES = ("items", "sales", "sale_returns", "purchases", "customers", "suppliers", "karigars", "repairs", "orders", "approvals", "stock_audits")


def legacy_conn(with_business_data=False):
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL,updated_at TEXT NOT NULL)")
    c.execute("CREATE TABLE branches(id INTEGER PRIMARY KEY,code TEXT UNIQUE,name TEXT,gstin TEXT,address TEXT,phone TEXT,active INTEGER)")
    c.execute("CREATE TABLE counters(id INTEGER PRIMARY KEY,branch_id INTEGER,name TEXT,active INTEGER)")
    for table in COUNT_TABLES:
        c.execute(f"CREATE TABLE {table}(id INTEGER PRIMARY KEY)")
    c.execute("INSERT INTO settings VALUES('business_name','Bijoria','old')")
    c.execute("INSERT INTO settings VALUES('business_state_code','36','old')")
    c.execute("INSERT INTO branches VALUES(1,'MAIN','Bijoria Main Showroom','','','',1)")
    c.execute("INSERT INTO counters VALUES(1,1,'Counter 1',1)")
    c.execute("INSERT INTO counters VALUES(2,1,'Counter 2',1)")
    c.execute("INSERT INTO counters VALUES(3,1,'Counter 3',1)")
    if with_business_data:
        c.execute("INSERT INTO items VALUES(1)")
    return c


def test_migration_6_removes_only_untouched_release_candidate_seed():
    c = legacy_conn(False)
    _migration_6(c)
    assert c.execute("SELECT value FROM settings WHERE key='business_name'").fetchone()[0] == ''
    assert c.execute("SELECT value FROM settings WHERE key='business_state_code'").fetchone()[0] == ''
    assert c.execute("SELECT name FROM branches WHERE code='MAIN'").fetchone()[0] == 'Main Showroom'
    active = [r[0] for r in c.execute("SELECT name FROM counters WHERE active=1 ORDER BY id")]
    assert active == ['Counter 1']
    assert c.execute("SELECT value FROM settings WHERE key='company_setup_complete'").fetchone()[0] == '0'


def test_migration_6_never_renames_database_with_business_data():
    c = legacy_conn(True)
    _migration_6(c)
    assert c.execute("SELECT value FROM settings WHERE key='business_name'").fetchone()[0] == 'Bijoria'
    assert c.execute("SELECT name FROM branches WHERE code='MAIN'").fetchone()[0] == 'Bijoria Main Showroom'
''', 'utf-8')


def main() -> None:
    patch_db()
    patch_client()
    write_migration_tests()


if __name__ == '__main__':
    main()
