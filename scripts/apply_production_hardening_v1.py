from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Patch anchor not found for {label}")
    return text.replace(old, new, 1)


def replace_between(text: str, start: str, end: str, replacement: str, label: str) -> str:
    a = text.find(start)
    if a < 0:
        raise RuntimeError(f"Start anchor not found for {label}: {start!r}")
    b = text.find(end, a)
    if b < 0:
        raise RuntimeError(f"End anchor not found for {label}: {end!r}")
    return text[:a] + replacement.rstrip() + "\n\n" + text[b:]


def patch_db() -> None:
    path = Path("jewel_server/db.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        'APP_NAME = "JewelLAN"\n\n\ndef app_data_dir() -> Path:\n    if os.name == "nt":\n        base = Path(os.environ.get("PROGRAMDATA", r"C:\\ProgramData"))\n    else:\n        base = Path(os.environ.get("JEWELLAN_DATA_DIR", Path.home() / ".jewellan"))\n    path = base / APP_NAME\n',
        'APP_NAME = "JewelLAN"\nPRODUCTION_HARDENED_V1 = True\nLATEST_SCHEMA_VERSION = 3\n\n\ndef app_data_dir() -> Path:\n    override = os.environ.get("JEWELLAN_DATA_DIR")\n    if override:\n        base = Path(override).expanduser().resolve()\n    elif os.name == "nt":\n        base = Path(os.environ.get("PROGRAMDATA", r"C:\\ProgramData"))\n    else:\n        base = Path.home() / ".jewellan"\n    path = base / APP_NAME\n',
        "app data override and marker",
    )
    text = replace_between(
        text,
        "def connect() -> sqlite3.Connection:",
        "@contextlib.contextmanager\ndef read_db()",
        '''def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA busy_timeout=15000")
    conn.execute("PRAGMA wal_autocheckpoint=1000")
    conn.execute("PRAGMA journal_size_limit=67108864")
    return conn''',
        "database connection pragmas",
    )
    text = replace_once(
        text,
        '''@contextlib.contextmanager
def read_db() -> Iterator[sqlite3.Connection]:
    conn=connect()
    try: yield conn
    finally: conn.close()
''',
        '''@contextlib.contextmanager
def read_db() -> Iterator[sqlite3.Connection]:
    conn = connect()
    conn.execute("PRAGMA query_only=ON")
    try:
        yield conn
    finally:
        conn.close()
''',
        "query-only read connections",
    )

    migration_block = r'''TALLY_DEFAULT_MAPPINGS={"cash":"Cash","bank":"Bank / Card / UPI","sales":"Jewellery Sales","inventory":"Jewellery Inventory","cogs":"Cost of Goods Sold","old_gold":"Old Gold Inventory","customer_receivables":"Sundry Debtors Control","supplier_payables":"Sundry Creditors Control","input_gst":"Input GST","cgst":"Output CGST 1.5%","sgst":"Output SGST 1.5%","igst":"Output IGST 3%","round_off":"Round Off"}


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


MIGRATIONS = ((1, _migration_1), (2, _migration_2), (3, _migration_3))


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
'''
    text = replace_between(text, "TALLY_DEFAULT_MAPPINGS=", "DEFAULT_ACCOUNTS=", migration_block, "versioned database migrations")
    text = replace_once(
        text,
        "conn.executescript(SCHEMA); _migrate_schema(conn); now=utcnow();",
        "conn.executescript(SCHEMA); _migrate_schema(conn); _ensure_optional_indexes(conn); now=utcnow();",
        "optional HUID unique index",
    )
    text = replace_once(
        text,
        '        for seq in ("invoice","purchase","customer","supplier","karigar","repair","order","approval","audit","journal","tag"): conn.execute("INSERT OR IGNORE INTO sequences(name,value) VALUES(?,0)",(seq,))\n',
        '        for seq in ("invoice","purchase","customer","supplier","karigar","repair","order","approval","audit","journal","tag"): conn.execute("INSERT OR IGNORE INTO sequences(name,value) VALUES(?,0)",(seq,))\n        from .integrity import assert_storage_integrity\n        assert_storage_integrity(conn)\n',
        "startup storage integrity check",
    )
    text = replace_once(
        text,
        'def audit(conn,user_id,action,entity,entity_id=None,details=None,client_ip=None): conn.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details_json,client_ip,created_at) VALUES(?,?,?,?,?,?,?)",(user_id,action,entity,None if entity_id is None else str(entity_id),None if details is None else json.dumps(details,ensure_ascii=False,default=str),client_ip,utcnow()))',
        '''def audit(conn,user_id,action,entity,entity_id=None,details=None,client_ip=None):
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
    )''',
        "audit hash chain writer",
    )
    path.write_text(text, encoding="utf-8")
    print("updated", path)


def patch_services() -> None:
    path = Path("jewel_server/services.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(text, "import datetime as dt, sqlite3\n", "import datetime as dt, re, sqlite3\n", "services regex import")
    text = replace_once(
        text,
        'from .tally import enqueue_tally\n\ndef money(v): return round(float(v or 0)+1e-9,2)\ndef weight(v): return round(float(v or 0)+1e-12,3)\n',
        'from .tally import enqueue_tally\nfrom .precision import decimal_value,money,money_decimal,money_equal,money_paise,money_sum,nearest_rupee,weight,weight_decimal,weight_equal,weight_mg\n\nPRODUCTION_HARDENED_V1 = True\n',
        "deterministic precision helpers",
    )

    pricing = r'''def latest_rate(conn,metal,purity):
    r=conn.execute("SELECT rate_per_gram FROM metal_rates WHERE lower(metal)=lower(?) AND lower(purity)=lower(?) ORDER BY effective_at DESC,id DESC LIMIT 1",(metal,purity)).fetchone()
    if r:return money(r[0])
    r=conn.execute("SELECT purity,rate_per_gram FROM metal_rates WHERE lower(metal)=lower(?) ORDER BY effective_at DESC,id DESC LIMIT 1",(metal,)).fetchone()
    if r:
        source=decimal_value(purity_fraction(r[0]));target=decimal_value(purity_fraction(purity))
        return money(decimal_value(r[1])*target/max(source,decimal_value("0.001")))
    raise HTTPException(409,f"No metal rate configured for {metal} {purity}")


def calculate_item_price(conn,item,overrides=None):
    i=dict(item);o=overrides or {}
    raw_rate=o.get('metal_rate')
    rate_d=money_decimal(latest_rate(conn,i['metal'],i['purity']) if raw_rate in (None,'') else raw_rate)
    net_d=weight_decimal(i['net_weight'])
    metal_d=money_decimal(net_d*rate_d)
    wp_d=decimal_value(o.get('wastage_percent',i.get('wastage_percent',0)))
    if wp_d<0:raise HTTPException(400,'Wastage percentage cannot be negative')
    wastage_d=money_decimal(metal_d*wp_d/decimal_value(100))
    making_type=str(o.get('making_type',i.get('making_type','per_gram')))
    making_value_d=decimal_value(o.get('making_value',i.get('making_value',0)))
    if making_value_d<0:raise HTTPException(400,'Making value cannot be negative')
    if making_type=='percent':making_d=money_decimal(metal_d*making_value_d/decimal_value(100))
    elif making_type=='fixed':making_d=money_decimal(making_value_d)
    elif making_type=='per_gram':making_d=money_decimal(net_d*making_value_d)
    else:raise HTTPException(400,'Invalid making type')
    stone_d=money_decimal(o.get('stone_value',i.get('stone_value',0)))
    discount_d=money_decimal(o.get('discount',0))
    if discount_d<0:raise HTTPException(400,'Discount cannot be negative')
    taxable_d=money_decimal(max(decimal_value(0),metal_d+wastage_d+making_d+stone_d-discount_d))
    gst_rate_d=decimal_value(o.get('gst_rate',i.get('gst_rate',3)))
    if gst_rate_d<0 or gst_rate_d>100:raise HTTPException(400,'GST rate must be between 0 and 100')
    gst_d=money_decimal(taxable_d*gst_rate_d/decimal_value(100))
    return {'item_id':i['id'],'tag_no':i['tag_no'],'description':i['name'],'metal':i['metal'],'purity':i['purity'],'gross_weight':weight(i['gross_weight']),'net_weight':weight(net_d),'metal_rate':money(rate_d),'metal_value':money(metal_d),'wastage_percent':float(wp_d),'wastage_value':money(wastage_d),'making_type':making_type,'making_value':float(making_value_d),'making_charge':money(making_d),'stone_value':money(stone_d),'discount':money(discount_d),'taxable':money(taxable_d),'gst_rate':float(gst_rate_d),'gst_amount':money(gst_d),'line_total':money(taxable_d+gst_d),'cost_amount':money(i.get('cost_amount',0))}


def quote_sale(conn,lines,header_discount=0,old_gold_value=0):
    out=[];seen=set()
    for ln in lines:
        iid=int(ln.get('item_id') or 0)
        if iid in seen:raise HTTPException(400,'Same tag scanned twice')
        seen.add(iid);item=conn.execute('SELECT * FROM items WHERE id=?',(iid,)).fetchone()
        if not item:raise HTTPException(404,f'Item {iid} not found')
        if item['status']!='in_stock':raise HTTPException(409,f"Tag {item['tag_no']} is {item['status']}")
        out.append(calculate_item_price(conn,item,ln))
    subtotal_d=sum((money_decimal(x['taxable']) for x in out),decimal_value(0))
    requested_discount=money_decimal(max(decimal_value(0),decimal_value(header_discount)))
    header_d=min(requested_discount,subtotal_d);remaining=header_d
    for n,line in enumerate(out):
        line_taxable=money_decimal(line['taxable'])
        if not header_d or not subtotal_d:allocation=money_decimal(0)
        elif n==len(out)-1:allocation=remaining
        else:allocation=min(money_decimal(header_d*line_taxable/subtotal_d),remaining,line_taxable)
        remaining=money_decimal(remaining-allocation)
        line['discount']=money(money_decimal(line['discount'])+allocation)
        line_taxable=money_decimal(max(decimal_value(0),line_taxable-allocation));line['taxable']=money(line_taxable)
        gst_d=money_decimal(line_taxable*decimal_value(line['gst_rate'])/decimal_value(100));line['gst_amount']=money(gst_d);line['line_total']=money(line_taxable+gst_d)
    taxable_d=sum((money_decimal(x['taxable']) for x in out),decimal_value(0));gst_d=sum((money_decimal(x['gst_amount']) for x in out),decimal_value(0));gross_d=money_decimal(taxable_d+gst_d)
    rounded=nearest_rupee(gross_d);round_off=money(money_decimal(rounded)-gross_d);total=money(gross_d+money_decimal(round_off));old_value=money(old_gold_value);payable=money(max(decimal_value(0),money_decimal(total)-money_decimal(old_value)))
    return {'lines':out,'subtotal':money(subtotal_d),'discount':money(header_d),'taxable':money(taxable_d),'gst':money(gst_d),'round_off':round_off,'total':total,'old_gold_value':old_value,'payable':payable}


def _journal(conn,user_id,memo,ref_type,ref_id,lines):
    debit_paise=sum(money_paise(x[1]) for x in lines);credit_paise=sum(money_paise(x[2]) for x in lines)
    if debit_paise!=credit_paise:raise RuntimeError(f'Unbalanced journal: debit {debit_paise}p credit {credit_paise}p')
    no=next_sequence(conn,'journal','JE',7);cur=conn.execute('INSERT INTO journal_entries(entry_no,entry_date,memo,ref_type,ref_id,user_id,created_at) VALUES(?,?,?,?,?,?,?)',(no,dt.date.today().isoformat(),memo,ref_type,ref_id,user_id,utcnow()));eid=cur.lastrowid
    for code,dr,cr,pt,pid in lines:
        dr=money(dr);cr=money(cr)
        if dr or cr:conn.execute('INSERT INTO journal_lines(entry_id,account_code,debit,credit,party_type,party_id) VALUES(?,?,?,?,?,?)',(eid,code,dr,cr,pt,pid))
    return eid
'''
    text = replace_between(text, "def latest_rate(conn,metal,purity):", "def post_sale(conn,payload,user,client_ip=None):", pricing, "exact pricing and journal logic")
    text = replace_once(
        text,
        "olds=payload.get('old_gold') or [];old_value=money(sum(float(x.get('value',0) or 0) for x in olds));q=quote_sale(conn,payload.get('lines') or [],float(payload.get('discount',0) or 0),old_value)",
        "olds=payload.get('old_gold') or [];old_value=money_sum(x.get('value',0) for x in olds);q=quote_sale(conn,payload.get('lines') or [],payload.get('discount',0),old_value)",
        "sale exact old-gold and discount",
    )
    text = replace_once(
        text,
        "cash=money(payload.get('payment_cash'));card=money(payload.get('payment_card'));upi=money(payload.get('payment_upi'));credit=money(payload.get('payment_credit'));paid=money(cash+card+upi+credit+old_value)\n    if abs(paid-q['total'])>.05:raise HTTPException(400,f\"Payments ({paid:.2f}) must equal invoice total ({q['total']:.2f})\")",
        "cash=money(payload.get('payment_cash'));card=money(payload.get('payment_card'));upi=money(payload.get('payment_upi'));credit=money(payload.get('payment_credit'));paid=money_sum((cash,card,upi,credit,old_value))\n    if not money_equal(paid,q['total']):raise HTTPException(400,f\"Payments ({paid:.2f}) must equal invoice total ({q['total']:.2f})\")",
        "exact payment equality",
    )
    text = text.replace("cost+=l['cost_amount']", "cost=money(cost+l['cost_amount'])", 1)
    text = replace_once(
        text,
        "gross=weight(og.get('gross_weight'));ded=float(og.get('deduction_percent',0) or 0);net=weight(gross*(1-ded/100));pure=weight(net*purity_fraction(str(og.get('purity','999'))));",
        "gross=weight(og.get('gross_weight'));ded=decimal_value(og.get('deduction_percent',0));net=weight(weight_decimal(gross)*(decimal_value(100)-ded)/decimal_value(100));pure=weight(weight_decimal(net)*decimal_value(purity_fraction(str(og.get('purity','999')))));",
        "old gold exact weight math",
    )
    text = text.replace("('1010',card+upi,0,None,None)", "('1010',money(card+upi),0,None,None)", 1)
    text = text.replace("balance=max(0,balance-?)", "balance=balance-?", 1)

    item_block = r'''_HUID_RE=re.compile(r'^[A-Z0-9]{6}$')


def normalize_huid(value):
    raw=str(value or '').strip().upper()
    if not raw:return None
    if not _HUID_RE.fullmatch(raw):raise HTTPException(400,'HUID must be exactly six alphanumeric characters, e.g. ABC123')
    return raw


def _assert_unique_huid(conn,huid,item_id=None):
    if not huid:return
    if item_id is None:r=conn.execute('SELECT id,tag_no FROM items WHERE huid=? COLLATE NOCASE',(huid,)).fetchone()
    else:r=conn.execute('SELECT id,tag_no FROM items WHERE huid=? COLLATE NOCASE AND id<>?',(huid,item_id)).fetchone()
    if r:raise HTTPException(409,f"HUID {huid} is already assigned to tag {r['tag_no']}")


def _validated_weights(data,current,user):
    old=dict(current) if current is not None else {}
    role=str((user or {}).get('role') or '') if isinstance(user,dict) else ''
    weight_keys={'gross_weight','stone_weight','net_weight','fine_weight','purity'}
    values=dict(old);values.update(data)
    gross=weight(values.get('gross_weight'));stone=weight(values.get('stone_weight'));purity=str(values.get('purity') or '916')
    if weight_mg(stone)>weight_mg(gross):raise HTTPException(400,'Stone weight cannot exceed gross weight')
    expected=weight(weight_decimal(gross)-weight_decimal(stone))
    unchanged_override=bool(old.get('net_weight_override_reason')) and current is not None and all(
        weight_equal(values.get(k),old.get(k)) if k in {'gross_weight','stone_weight','net_weight','fine_weight'} else str(values.get(k))==str(old.get(k))
        for k in weight_keys
    )
    if current is not None and not any(k in data for k in weight_keys):
        return weight(old['gross_weight']),weight(old['stone_weight']),weight(old['net_weight']),weight(old['fine_weight']),old.get('net_weight_override_reason')
    raw_net=values.get('net_weight')
    if raw_net in (None,'') or (current is not None and 'net_weight' not in data):net=expected
    else:net=weight(raw_net)
    reason=old.get('net_weight_override_reason') if unchanged_override else None
    if not weight_equal(net,expected,tolerance_mg=1):
        requested=bool(data.get('allow_net_weight_override'))
        supplied_reason=str(data.get('net_weight_override_reason') or '').strip()
        if unchanged_override:
            reason=old.get('net_weight_override_reason')
        elif role in {'admin','manager'} and requested and len(supplied_reason)>=3:
            reason=supplied_reason[:250]
        else:
            raise HTTPException(400,f'Net weight must equal gross minus stone weight ({expected:.3f} g). Manager override requires a reason.')
    else:
        net=expected;reason=None
    recalc_fine=current is None or any(k in data for k in {'gross_weight','stone_weight','net_weight','purity'}) or 'fine_weight' in data
    if recalc_fine:
        if data.get('fine_weight') not in (None,''):fine=weight(data.get('fine_weight'))
        else:fine=weight(weight_decimal(net)*decimal_value(purity_fraction(purity)))
    else:fine=weight(old['fine_weight'])
    if weight_mg(fine)<0 or weight_mg(fine)>weight_mg(net)+1:raise HTTPException(400,'Fine weight cannot exceed net weight')
    return gross,stone,net,fine,reason


def create_item(conn,data,user,client_ip=None):
    user_id=int(user['id']) if isinstance(user,dict) else int(user)
    s=get_settings(conn);tag=str(data.get('tag_no') or '').strip() or next_sequence(conn,'tag',s.get('tag_prefix','TAG')+'-',7);barcode=str(data.get('barcode') or tag).strip();purity=str(data.get('purity') or '916')
    gross,stone,net,fine,override_reason=_validated_weights(data,None,user if isinstance(user,dict) else {'id':user_id})
    huid=normalize_huid(data.get('huid'));_assert_unique_huid(conn,huid);now=utcnow();making_type=str(data.get('making_type') or 'per_gram')
    if making_type not in {'per_gram','percent','fixed'}:raise HTTPException(400,'Invalid making type')
    making_value=float(decimal_value(data.get('making_value',0)));wastage=float(decimal_value(data.get('wastage_percent',0)));gst_rate=float(decimal_value(data.get('gst_rate',3)))
    if making_value<0 or wastage<0:raise HTTPException(400,'Making and wastage values cannot be negative')
    if gst_rate<0 or gst_rate>100:raise HTTPException(400,'GST rate must be between 0 and 100')
    branch_id=int(data.get('branch_id') or 1);counter_id=data.get('counter_id') or None
    if counter_id and not conn.execute('SELECT id FROM counters WHERE id=? AND branch_id=? AND active=1',(counter_id,branch_id)).fetchone():raise HTTPException(400,'Counter does not belong to the selected branch')
    try:cur=conn.execute('INSERT INTO items(tag_no,barcode,name,category,metal,purity,gross_weight,stone_weight,net_weight,fine_weight,stone_value,cost_amount,making_type,making_value,wastage_percent,huid,certificate_no,rfid_epc,hsn_code,gst_rate,status,branch_id,counter_id,supplier_id,purchase_date,notes,created_at,updated_at,net_weight_override_reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(tag,barcode,data.get('name') or data.get('category') or 'Jewellery',data.get('category') or 'Other',data.get('metal') or 'Gold',purity,gross,stone,net,fine,money(data.get('stone_value')),money(data.get('cost_amount')),making_type,making_value,wastage,huid,data.get('certificate_no') or None,data.get('rfid_epc') or None,data.get('hsn_code') or '7113',gst_rate,'in_stock',branch_id,counter_id,data.get('supplier_id') or None,data.get('purchase_date') or dt.date.today().isoformat(),data.get('notes') or None,now,now,override_reason))
    except sqlite3.IntegrityError as e:raise HTTPException(409,f'Tag/barcode/HUID/RFID already exists or item data is invalid: {e}')
    iid=cur.lastrowid;conn.execute('INSERT INTO stock_movements(item_id,movement_type,ref_type,ref_id,from_location,to_location,gross_weight,user_id,note,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(iid,'stock_in',data.get('ref_type'),data.get('ref_id'),'supplier',f"branch:{branch_id}",gross,user_id,data.get('notes'),now));audit(conn,user_id,'create','item',iid,{'tag_no':tag,'huid':huid,'gross_weight':gross,'stone_weight':stone,'net_weight':net,'net_weight_override_reason':override_reason},client_ip);return dict(conn.execute('SELECT * FROM items WHERE id=?',(iid,)).fetchone())


def update_item(conn,item_id,data,user,client_ip=None):
    user_id=int(user['id']) if isinstance(user,dict) else int(user);role=str(user.get('role') or '') if isinstance(user,dict) else ''
    old=conn.execute('SELECT * FROM items WHERE id=?',(item_id,)).fetchone()
    if not old:raise HTTPException(404,'Item not found')
    critical={'barcode','name','category','metal','purity','gross_weight','stone_weight','net_weight','fine_weight','stone_value','cost_amount','making_type','making_value','wastage_percent','huid','rfid_epc','hsn_code','gst_rate','counter_id','supplier_id'}
    if old['status']!='in_stock' and any(k in data for k in critical):raise HTTPException(409,f"Tag {old['tag_no']} is {old['status']}; return it to in-stock before changing controlled item data")
    allowed=critical|{'certificate_no','notes','allow_net_weight_override','net_weight_override_reason'};v=dict(old);v.update({k:x for k,x in data.items() if k in allowed});gross,stone,net,fine,override_reason=_validated_weights(data,old,user if isinstance(user,dict) else {'id':user_id,'role':role});huid=normalize_huid(v.get('huid'));_assert_unique_huid(conn,huid,item_id);now=utcnow();making_type=str(v['making_type'])
    if making_type not in {'per_gram','percent','fixed'}:raise HTTPException(400,'Invalid making type')
    making_value=float(decimal_value(v['making_value']));wastage=float(decimal_value(v['wastage_percent']));gst_rate=float(decimal_value(v['gst_rate']))
    if making_value<0 or wastage<0:raise HTTPException(400,'Making and wastage values cannot be negative')
    if gst_rate<0 or gst_rate>100:raise HTTPException(400,'GST rate must be between 0 and 100')
    if v.get('counter_id') and not conn.execute('SELECT id FROM counters WHERE id=? AND branch_id=? AND active=1',(v['counter_id'],old['branch_id'])).fetchone():raise HTTPException(400,'Counter does not belong to this item branch')
    try:conn.execute('UPDATE items SET barcode=?,name=?,category=?,metal=?,purity=?,gross_weight=?,stone_weight=?,net_weight=?,fine_weight=?,stone_value=?,cost_amount=?,making_type=?,making_value=?,wastage_percent=?,huid=?,certificate_no=?,rfid_epc=?,hsn_code=?,gst_rate=?,counter_id=?,supplier_id=?,notes=?,net_weight_override_reason=?,version=version+1,updated_at=? WHERE id=?',(v['barcode'],v['name'],v['category'],v['metal'],v['purity'],gross,stone,net,fine,money(v['stone_value']),money(v['cost_amount']),making_type,making_value,wastage,huid,v['certificate_no'],v['rfid_epc'],v['hsn_code'],gst_rate,v['counter_id'],v['supplier_id'],v['notes'],override_reason,now,item_id))
    except sqlite3.IntegrityError as e:raise HTTPException(409,f'Duplicate barcode/HUID/RFID or invalid item data: {e}')
    audit(conn,user_id,'update','item',item_id,{'changes':data,'gross_weight':gross,'stone_weight':stone,'net_weight':net,'net_weight_override_reason':override_reason},client_ip);return dict(conn.execute('SELECT * FROM items WHERE id=?',(item_id,)).fetchone())
'''
    text = replace_between(text, "def create_item(conn,data,user_id,client_ip=None):", "def transfer_item(conn,item_id,branch_id,counter_id,user_id,note='',client_ip=None):", item_block, "item validation and HUID controls")
    path.write_text(text, encoding="utf-8")
    print("updated", path)


def patch_main() -> None:
    path = Path("jewel_server/main.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from .backup import BackupWorker,create_backup,list_backups,restore_backup\n",
        "from .backup import BackupWorker,backup_status,create_backup,list_backups,restore_backup,verify_backup\n",
        "backup imports",
    )
    text = replace_once(
        text,
        "from .security import create_session,current_user,hash_password,require,verify_password\n",
        "from .security import VALID_ROLES,clear_login_failures,create_session,current_user,hash_password,login_lock_seconds,password_needs_rehash,record_login_failure,require,verify_password\n",
        "security imports",
    )
    text = replace_once(
        text,
        "from .services import cancel_sale,create_item,latest_rate,money,post_sale,purity_fraction,quote_sale,transfer_item,update_item,weight\n",
        "from .services import cancel_sale,create_item,latest_rate,money,post_sale,purity_fraction,quote_sale,transfer_item,update_item,weight\nfrom .integrity import database_integrity,day_close\nfrom .precision import money_sum\n",
        "integrity and precision imports",
    )
    text = replace_once(text, "backup_worker=None;discovery=None;tally_worker=None\n", "PRODUCTION_HARDENED_V1 = True\nAPP_VERSION='1.1.0-rc1'\nbackup_worker=None;discovery=None;tally_worker=None\n", "main production marker")
    text = text.replace("app=FastAPI(title='JewelLAN Server',version='1.0.0',lifespan=lifespan,docs_url='/api/docs',redoc_url=None)", "app=FastAPI(title='JewelLAN Server',version=APP_VERSION,lifespan=lifespan,docs_url='/api/docs' if os.environ.get('JEWELLAN_ENABLE_DOCS')=='1' else None,redoc_url=None)", 1)

    health_login = r'''@app.get('/api/health')
def health():
    with read_db() as c:
        quick=str(c.execute('PRAGMA quick_check(1)').fetchone()[0]);s=get_settings(c)
    return {'ok':quick.lower()=='ok','product':'JewelLAN','version':APP_VERSION,'business':s.get('business_name','Jewellery Store'),'time':utcnow(),'database':{'quick_check':quick},'backup':backup_status()}


@app.post('/api/auth/login')
def login(req:Request,p:dict=Body(...)):
    username=str(p.get('username') or '').strip();password=str(p.get('password') or '');client=ip(req)
    wait=login_lock_seconds(username,client)
    if wait:raise HTTPException(429,f'Too many failed sign-in attempts. Try again in {wait} seconds.',headers={'Retry-After':str(wait)})
    with read_db() as c:u=c.execute('SELECT * FROM users WHERE username=? COLLATE NOCASE',(username,)).fetchone()
    valid=bool(u and u['active'] and verify_password(password,u['password_hash']))
    if not valid:
        locked=record_login_failure(username,client)
        with write_db() as c:audit(c,u['id'] if u else None,'login_failed','user',u['id'] if u else username,{'username':username,'locked_seconds':locked},client)
        raise HTTPException(401,'Invalid username or password')
    clear_login_failures(username,client)
    if password_needs_rehash(u['password_hash']):
        with write_db() as c:c.execute('UPDATE users SET password_hash=?,updated_at=? WHERE id=?',(hash_password(password),utcnow(),u['id']))
    token=create_session(u['id'],str(p.get('client_name') or 'Windows Client'))
    with write_db() as c:audit(c,u['id'],'login','user',u['id'],None,client)
    return {'token':token,'user':{k:u[k] for k in ('id','username','full_name','role','must_change_password')}}
'''
    text = replace_between(text, "@app.get('/api/health')", "@app.post('/api/auth/logout')", health_login, "health and throttled login")
    text = replace_once(
        text,
        "    if len(new)<8:raise HTTPException(400,'New password must be at least 8 characters')",
        "    if len(new)<10:raise HTTPException(400,'New password must be at least 10 characters')\n    if new=='Jewel@123':raise HTTPException(400,'Choose a password different from the initial password')",
        "stronger password change policy",
    )
    text = replace_once(
        text,
        "        c.execute('UPDATE users SET password_hash=?,must_change_password=0,updated_at=? WHERE id=?',(hash_password(new),utcnow(),u['id']));audit(c,u['id'],'change_password','user',u['id'])",
        "        c.execute('UPDATE users SET password_hash=?,must_change_password=0,updated_at=? WHERE id=?',(hash_password(new),utcnow(),u['id']));c.execute('DELETE FROM sessions WHERE user_id=? AND token_hash<>?',(u['id'],u['token_hash']));audit(c,u['id'],'change_password','user',u['id'])",
        "revoke other sessions after password change",
    )
    text = replace_once(
        text,
        "    if not username or len(password)<8 or role not in {'admin','manager','cashier','inventory','accounts'}:raise HTTPException(400,'Valid username, role and 8+ character password required')",
        "    if not username or len(password)<10 or role not in VALID_ROLES:raise HTTPException(400,'Valid username, role and 10+ character temporary password required')",
        "new user validation",
    )
    edit_user = r'''@app.put('/api/users/{uid}')
def edit_user(uid:int,p:dict=Body(...),u=Depends(require('*'))):
    with write_db() as c:
        r=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
        if not r:raise HTTPException(404,'User not found')
        role=str(p.get('role',r['role']))
        if role not in VALID_ROLES:raise HTTPException(400,'Invalid role')
        active=1 if p.get('active',bool(r['active'])) else 0
        if uid==u['id'] and not active:raise HTTPException(400,'Cannot deactivate yourself')
        if uid==u['id'] and role!=r['role']:raise HTTPException(400,'Cannot change your own role')
        if r['role']=='admin' and (role!='admin' or not active):
            admins=c.execute("SELECT count(*) FROM users WHERE role='admin' AND active=1").fetchone()[0]
            if admins<=1:raise HTTPException(400,'Cannot remove or deactivate the last active administrator')
        c.execute('UPDATE users SET full_name=?,role=?,active=?,updated_at=? WHERE id=?',(p.get('full_name',r['full_name']),role,active,utcnow(),uid))
        if p.get('password'):
            if len(str(p['password']))<10:raise HTTPException(400,'Temporary password must be at least 10 characters')
            c.execute('UPDATE users SET password_hash=?,must_change_password=1,updated_at=? WHERE id=?',(hash_password(str(p['password'])),utcnow(),uid))
        if role!=r['role'] or active!=r['active'] or p.get('password'):c.execute('DELETE FROM sessions WHERE user_id=?',(uid,))
        audit(c,u['id'],'update','user',uid,{k:('***' if k=='password' else v) for k,v in p.items()})
    return {'ok':True}
'''
    text = replace_between(text, "@app.put('/api/users/{uid}')", "@app.get('/api/rates')", edit_user, "safe user administration")
    text = replace_once(text, "    rate=float(p.get('rate_per_gram') or 0)", "    rate=money(p.get('rate_per_gram'))", "exact metal rate input")
    text = text.replace("with write_db() as c:return create_item(c,p,u['id'],ip(req))", "with write_db() as c:return create_item(c,p,u,ip(req))", 1)
    text = text.replace("with write_db() as c:return update_item(c,iid,p,u['id'],ip(req))", "with write_db() as c:return update_item(c,iid,p,u,ip(req))", 1)
    text = replace_once(
        text,
        "with read_db() as c:return quote_sale(c,p.get('lines') or [],float(p.get('discount',0) or 0),sum(float(x.get('value',0) or 0) for x in p.get('old_gold') or []))",
        "with read_db() as c:return quote_sale(c,p.get('lines') or [],p.get('discount',0),money_sum(x.get('value',0) for x in p.get('old_gold') or []))",
        "exact sale quote request",
    )
    text = replace_once(
        text,
        "sub=money(sum(float(x.get('cost_amount',0) or 0) for x in its));gst=money(p.get('gst'));total=money(sub+gst);paid=money(p.get('paid'))",
        "sub=money_sum(x.get('cost_amount',0) for x in its);gst=money(p.get('gst'));total=money(sub+gst);paid=money(p.get('paid'))",
        "exact purchase totals",
    )
    text = text.replace("it=create_item(c,x,u['id'])", "it=create_item(c,x,u)", 1)
    text = text.replace("float(p.get('gross_weight',0) or 0)", "weight(p.get('gross_weight',0))", 1)
    text = text.replace("float(p.get('target_weight',0) or 0)", "weight(p.get('target_weight',0))", 1)

    report_anchor = "@app.get('/api/backups')\ndef backups(u=Depends(require('backup'))):return list_backups()"
    report_extra = r'''@app.get('/api/integrity')
def integrity_report(u=Depends(require('reports'))):
    with read_db() as c:return database_integrity(c)


@app.get('/api/reports/day-close')
def day_close_report(date:str='',u=Depends(require('reports'))):
    business_date=date or dt.date.today().isoformat()
    try:dt.date.fromisoformat(business_date)
    except ValueError:raise HTTPException(400,'Date must be YYYY-MM-DD')
    with read_db() as c:return day_close(c,business_date)


@app.get('/api/backups')
def backups(u=Depends(require('backup'))):return list_backups()'''
    text = replace_once(text, report_anchor, report_extra, "integrity and day-close endpoints")
    text = replace_once(
        text,
        "    f=create_backup(str(p.get('label') or 'manual'));return {'ok':True,'name':f.name,'size':f.stat().st_size}",
        "    f=create_backup(str(p.get('label') or 'manual'));v=verify_backup(f);return {'ok':True,'name':f.name,'size':f.stat().st_size,'sha256':v['sha256'],'verified':v['ok']}",
        "verified backup response",
    )
    text = replace_once(
        text,
        "    if a.restore:init_db(hash_password);restore_backup(a.restore);print('Backup restored.');return",
        "    if a.restore:init_db(hash_password);result=restore_backup(a.restore);init_db(hash_password);print('Backup restored and migrated:',result);return",
        "restore then migrate",
    )
    text = text.replace("Default first login: admin / Jewel@123 (change it immediately)", "Default first login: admin / Jewel@123 (change it immediately; new passwords require 10+ characters)", 1)
    path.write_text(text, encoding="utf-8")
    print("updated", path)


def patch_client() -> None:
    path = Path("jewel_client/main.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(text, 'APP_TITLE = "JewelLAN Jewellery ERP"\n', 'APP_TITLE = "JewelLAN Jewellery ERP"\nPRODUCTION_HARDENED_V1 = True\n', "client production marker")
    text = replace_once(
        text,
        '("gross_weight","Gross weight"),("stone_weight","Stone weight"),("net_weight","Net weight"),',
        '("gross_weight","Gross weight (g)"),("stone_weight","Stone weight (g)"),("net_weight","Net weight (auto = gross - stone)"),',
        "inventory weight labels",
    )
    text = replace_once(text, '("huid","HUID"),', '("huid","HUID (6 alphanumeric)"),', "HUID field label")
    values_block = r'''    def values(self, defaults=None):
        original=defaults or {}
        d=form_dialog(self,"Jewellery item",self.FIELDS,original or {"metal":"Gold","purity":"916","making_type":"per_gram","category":"Ring"})
        if not d:return None
        for k in ("gross_weight","stone_weight","net_weight","stone_value","cost_amount","making_value","wastage_percent"):
            try:d[k]=float(d.get(k) or 0)
            except ValueError:raise RuntimeError(f"{k} must be numeric")
        if d['stone_weight']>d['gross_weight']+0.0005:raise RuntimeError('Stone weight cannot exceed gross weight')
        expected=round(d['gross_weight']-d['stone_weight']+1e-12,3);entered=round(d['net_weight'],3)
        unchanged_existing_override=bool(original.get('net_weight_override_reason')) and all(abs(float(d.get(k) or 0)-float(original.get(k) or 0))<=0.001 for k in ('gross_weight','stone_weight','net_weight')) and str(d.get('purity'))==str(original.get('purity'))
        if unchanged_existing_override:
            d['net_weight_override_reason']=original.get('net_weight_override_reason')
        elif abs(entered-expected)>0.001:
            if self.app.user.get('role') in ('admin','manager'):
                use_override=messagebox.askyesno('Net weight differs',f'Gross − stone is {expected:.3f} g but you entered {entered:.3f} g.\n\nUse a manager override instead of auto-correcting?',parent=self)
                if use_override:
                    reason=simpledialog.askstring('Net weight override','Enter the reason for overriding calculated net weight:',parent=self)
                    if not reason or len(reason.strip())<3:raise RuntimeError('A reason is required for a net-weight override')
                    d['allow_net_weight_override']=True;d['net_weight_override_reason']=reason.strip();d['net_weight']=entered
                else:d['net_weight']=expected
            else:
                messagebox.showwarning('Net weight corrected',f'Net weight has been set to Gross − Stone = {expected:.3f} g.',parent=self);d['net_weight']=expected
        else:d['net_weight']=expected
        huid=str(d.get('huid') or '').strip().upper();d['huid']=huid
        if huid and (len(huid)!=6 or not huid.isalnum()):raise RuntimeError('HUID must be exactly six letters/numbers, for example ABC123')
        d["branch_id"]=int(self.app.cfg.get("branch_id",1));d["counter_id"]=self.app.cfg.get("counter_id") or None;return d
'''
    text = replace_between(text, "    def values(self, defaults=None):", "    def add(self):", values_block, "inventory auto net-weight workflow")
    path.write_text(text, encoding="utf-8")
    print("updated", path)


def patch_ui_upgrade_guard() -> None:
    path = Path("scripts/apply_ui_redesign.py")
    text = path.read_text(encoding="utf-8")
    anchor = 'text = PATH.read_text(encoding="utf-8")\n'
    guard = anchor + '\nif "PRODUCTION_HARDENED_V1 = True" in text:\n    print("Professional UI redesign already incorporated in production-hardened source.")\n    raise SystemExit(0)\n'
    text = replace_once(text, anchor, guard, "legacy UI patch guard")
    path.write_text(text, encoding="utf-8")
    print("updated", path)


def main() -> None:
    patch_db()
    patch_services()
    patch_main()
    patch_client()
    patch_ui_upgrade_guard()


if __name__ == "__main__":
    main()
