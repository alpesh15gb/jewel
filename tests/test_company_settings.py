import sqlite3

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
