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
    text = replace_once(text, "LATEST_SCHEMA_VERSION = 3", "LATEST_SCHEMA_VERSION = 4", "schema version")
    text = replace_once(
        text,
        'def utcnow() -> str: return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()\n',
        '''def utcnow() -> str: return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


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
''',
        "business timezone helpers",
    )

    migration4 = r'''def _migration_4(conn) -> None:
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


MIGRATIONS = ((1, _migration_1), (2, _migration_2), (3, _migration_3), (4, _migration_4))'''
    text = replace_between(text, "MIGRATIONS = ((1, _migration_1), (2, _migration_2), (3, _migration_3))", "def _migrate_schema(conn) -> None:", migration4, "canonical migration")
    text = replace_once(
        text,
        '"business_name":"My Jewellery Store","business_address":"","business_phone":"","business_gstin":"","currency":"INR"',
        '"business_name":"My Jewellery Store","business_address":"","business_phone":"","business_gstin":"","business_timezone_offset_minutes":"330","currency":"INR"',
        "business timezone default",
    )
    path.write_text(text, encoding="utf-8")
    print("updated", path)


def patch_services() -> None:
    path = Path("jewel_server/services.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from .db import audit,get_settings,next_sequence,utcnow",
        "from .db import audit,business_date,business_now,get_settings,next_sequence,utcnow",
        "business time imports",
    )
    text = replace_once(
        text,
        "no=next_sequence(conn,'journal','JE',7);cur=conn.execute('INSERT INTO journal_entries(entry_no,entry_date,memo,ref_type,ref_id,user_id,created_at) VALUES(?,?,?,?,?,?,?)',(no,dt.date.today().isoformat(),memo,ref_type,ref_id,user_id,utcnow()));eid=cur.lastrowid",
        "no=next_sequence(conn,'journal','JE',7);cur=conn.execute('INSERT INTO journal_entries(entry_no,entry_date,memo,ref_type,ref_id,user_id,created_at) VALUES(?,?,?,?,?,?,?)',(no,business_date(conn),memo,ref_type,ref_id,user_id,utcnow()));eid=cur.lastrowid",
        "journal business date",
    )
    text = replace_once(
        text,
        "if dr or cr:conn.execute('INSERT INTO journal_lines(entry_id,account_code,debit,credit,party_type,party_id) VALUES(?,?,?,?,?,?)',(eid,code,dr,cr,pt,pid))",
        "if dr or cr:conn.execute('INSERT INTO journal_lines(entry_id,account_code,debit,credit,party_type,party_id,debit_paise,credit_paise) VALUES(?,?,?,?,?,?,?,?)',(eid,code,dr,cr,pt,pid,money_paise(dr),money_paise(cr)))",
        "journal canonical inserts",
    )
    text = replace_once(
        text,
        "s=get_settings(conn);inv=next_sequence(conn,'invoice',s.get('invoice_prefix','INV')+'-'+dt.datetime.now().strftime('%y%m')+'-',6);now=utcnow();cid=payload.get('customer_id') or None;bid=int(payload.get('branch_id') or 1);counter=payload.get('counter_id') or None",
        "s=get_settings(conn);inv=next_sequence(conn,'invoice',s.get('invoice_prefix','INV')+'-'+business_now(conn).strftime('%y%m')+'-',6);now=utcnow();business_day=business_date(conn);cid=payload.get('customer_id') or None;bid=int(payload.get('branch_id') or 1);counter=payload.get('counter_id') or None",
        "sale business date",
    )
    old_sale_insert = "cur=conn.execute(\"INSERT INTO sales(invoice_no,client_request_id,branch_id,counter_id,customer_id,subtotal,discount,taxable,gst,place_of_supply_code,cgst,sgst,igst,round_off,total,payment_cash,payment_card,payment_upi,payment_credit,old_gold_value,notes,status,user_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'posted',?,?)\",(inv,req,bid,counter,cid,q['subtotal'],q['discount'],q['taxable'],q['gst'],place,cgst,sgst,igst,q['round_off'],q['total'],cash,card,upi,credit,old_value,payload.get('notes'),user['id'],now));sid=cur.lastrowid;cost=0"
    new_sale_insert = "cur=conn.execute(\"INSERT INTO sales(invoice_no,client_request_id,branch_id,counter_id,customer_id,business_date,subtotal,discount,taxable,gst,place_of_supply_code,cgst,sgst,igst,round_off,total,payment_cash,payment_card,payment_upi,payment_credit,old_gold_value,notes,subtotal_paise,discount_paise,taxable_paise,gst_paise,cgst_paise,sgst_paise,igst_paise,round_off_paise,total_paise,payment_cash_paise,payment_card_paise,payment_upi_paise,payment_credit_paise,old_gold_value_paise,status,user_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'posted',?,?)\",(inv,req,bid,counter,cid,business_day,q['subtotal'],q['discount'],q['taxable'],q['gst'],place,cgst,sgst,igst,q['round_off'],q['total'],cash,card,upi,credit,old_value,payload.get('notes'),money_paise(q['subtotal']),money_paise(q['discount']),money_paise(q['taxable']),money_paise(q['gst']),money_paise(cgst),money_paise(sgst),money_paise(igst),money_paise(q['round_off']),money_paise(q['total']),money_paise(cash),money_paise(card),money_paise(upi),money_paise(credit),money_paise(old_value),user['id'],now));sid=cur.lastrowid;cost=0"
    text = replace_once(text, old_sale_insert, new_sale_insert, "canonical sale insert")
    old_line = "conn.execute('INSERT INTO sale_items(sale_id,item_id,tag_no,description,metal,purity,gross_weight,net_weight,metal_rate,metal_value,wastage_value,making_charge,stone_value,discount,taxable,gst_rate,gst_amount,line_total,cost_amount) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(sid,l['item_id'],l['tag_no'],l['description'],l['metal'],l['purity'],l['gross_weight'],l['net_weight'],l['metal_rate'],l['metal_value'],l['wastage_value'],l['making_charge'],l['stone_value'],l['discount'],l['taxable'],l['gst_rate'],l['gst_amount'],l['line_total'],l['cost_amount']))"
    new_line = "conn.execute('INSERT INTO sale_items(sale_id,item_id,tag_no,description,metal,purity,gross_weight,net_weight,metal_rate,metal_value,wastage_value,making_charge,stone_value,discount,taxable,gst_rate,gst_amount,line_total,cost_amount,gross_mg,net_mg,metal_rate_paise,metal_value_paise,wastage_value_paise,making_charge_paise,stone_value_paise,discount_paise,taxable_paise,gst_amount_paise,line_total_paise,cost_amount_paise) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(sid,l['item_id'],l['tag_no'],l['description'],l['metal'],l['purity'],l['gross_weight'],l['net_weight'],l['metal_rate'],l['metal_value'],l['wastage_value'],l['making_charge'],l['stone_value'],l['discount'],l['taxable'],l['gst_rate'],l['gst_amount'],l['line_total'],l['cost_amount'],weight_mg(l['gross_weight']),weight_mg(l['net_weight']),money_paise(l['metal_rate']),money_paise(l['metal_value']),money_paise(l['wastage_value']),money_paise(l['making_charge']),money_paise(l['stone_value']),money_paise(l['discount']),money_paise(l['taxable']),money_paise(l['gst_amount']),money_paise(l['line_total']),money_paise(l['cost_amount'])))"
    text = replace_once(text, old_line, new_line, "canonical sale item insert")
    old_oldgold = "conn.execute('INSERT INTO old_gold(sale_id,customer_id,metal,purity,gross_weight,deduction_percent,net_weight,pure_weight,rate,value,notes,received_at,received_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(sid,cid,og.get('metal','Gold'),og.get('purity','999'),gross,ded,net,pure,money(og.get('rate')),money(og.get('value')),og.get('notes'),now,user['id']))"
    new_oldgold = "conn.execute('INSERT INTO old_gold(sale_id,customer_id,metal,purity,gross_weight,deduction_percent,net_weight,pure_weight,rate,value,notes,received_at,received_by,gross_mg,net_mg,pure_mg,rate_paise,value_paise) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(sid,cid,og.get('metal','Gold'),og.get('purity','999'),gross,ded,net,pure,money(og.get('rate')),money(og.get('value')),og.get('notes'),now,user['id'],weight_mg(gross),weight_mg(net),weight_mg(pure),money_paise(og.get('rate')),money_paise(og.get('value'))))"
    text = replace_once(text, old_oldgold, new_oldgold, "canonical old gold insert")

    old_item_insert = "try:cur=conn.execute('INSERT INTO items(tag_no,barcode,name,category,metal,purity,gross_weight,stone_weight,net_weight,fine_weight,stone_value,cost_amount,making_type,making_value,wastage_percent,huid,certificate_no,rfid_epc,hsn_code,gst_rate,status,branch_id,counter_id,supplier_id,purchase_date,notes,created_at,updated_at,net_weight_override_reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(tag,barcode,data.get('name') or data.get('category') or 'Jewellery',data.get('category') or 'Other',data.get('metal') or 'Gold',purity,gross,stone,net,fine,money(data.get('stone_value')),money(data.get('cost_amount')),making_type,making_value,wastage,huid,data.get('certificate_no') or None,data.get('rfid_epc') or None,data.get('hsn_code') or '7113',gst_rate,'in_stock',branch_id,counter_id,data.get('supplier_id') or None,data.get('purchase_date') or dt.date.today().isoformat(),data.get('notes') or None,now,now,override_reason))"
    new_item_insert = "try:cur=conn.execute('INSERT INTO items(tag_no,barcode,name,category,metal,purity,gross_weight,stone_weight,net_weight,fine_weight,stone_value,cost_amount,making_type,making_value,wastage_percent,huid,certificate_no,rfid_epc,hsn_code,gst_rate,status,branch_id,counter_id,supplier_id,purchase_date,notes,created_at,updated_at,net_weight_override_reason,gross_mg,stone_mg,net_mg,fine_mg,stone_value_paise,cost_amount_paise) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(tag,barcode,data.get('name') or data.get('category') or 'Jewellery',data.get('category') or 'Other',data.get('metal') or 'Gold',purity,gross,stone,net,fine,money(data.get('stone_value')),money(data.get('cost_amount')),making_type,making_value,wastage,huid,data.get('certificate_no') or None,data.get('rfid_epc') or None,data.get('hsn_code') or '7113',gst_rate,'in_stock',branch_id,counter_id,data.get('supplier_id') or None,data.get('purchase_date') or business_date(conn),data.get('notes') or None,now,now,override_reason,weight_mg(gross),weight_mg(stone),weight_mg(net),weight_mg(fine),money_paise(data.get('stone_value')),money_paise(data.get('cost_amount'))))"
    text = replace_once(text, old_item_insert, new_item_insert, "canonical item insert")
    old_item_update = "try:conn.execute('UPDATE items SET barcode=?,name=?,category=?,metal=?,purity=?,gross_weight=?,stone_weight=?,net_weight=?,fine_weight=?,stone_value=?,cost_amount=?,making_type=?,making_value=?,wastage_percent=?,huid=?,certificate_no=?,rfid_epc=?,hsn_code=?,gst_rate=?,counter_id=?,supplier_id=?,notes=?,net_weight_override_reason=?,version=version+1,updated_at=? WHERE id=?',(v['barcode'],v['name'],v['category'],v['metal'],v['purity'],gross,stone,net,fine,money(v['stone_value']),money(v['cost_amount']),making_type,making_value,wastage,huid,v['certificate_no'],v['rfid_epc'],v['hsn_code'],gst_rate,v['counter_id'],v['supplier_id'],v['notes'],override_reason,now,item_id))"
    new_item_update = "try:conn.execute('UPDATE items SET barcode=?,name=?,category=?,metal=?,purity=?,gross_weight=?,stone_weight=?,net_weight=?,fine_weight=?,stone_value=?,cost_amount=?,making_type=?,making_value=?,wastage_percent=?,huid=?,certificate_no=?,rfid_epc=?,hsn_code=?,gst_rate=?,counter_id=?,supplier_id=?,notes=?,net_weight_override_reason=?,gross_mg=?,stone_mg=?,net_mg=?,fine_mg=?,stone_value_paise=?,cost_amount_paise=?,version=version+1,updated_at=? WHERE id=?',(v['barcode'],v['name'],v['category'],v['metal'],v['purity'],gross,stone,net,fine,money(v['stone_value']),money(v['cost_amount']),making_type,making_value,wastage,huid,v['certificate_no'],v['rfid_epc'],v['hsn_code'],gst_rate,v['counter_id'],v['supplier_id'],v['notes'],override_reason,weight_mg(gross),weight_mg(stone),weight_mg(net),weight_mg(fine),money_paise(v['stone_value']),money_paise(v['cost_amount']),now,item_id))"
    text = replace_once(text, old_item_update, new_item_update, "canonical item update")
    path.write_text(text, encoding="utf-8")
    print("updated", path)


def patch_security() -> None:
    path = Path("jewel_server/security.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''    def dep(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        perms = ROLE_PERMISSIONS.get(user["role"], set())
        if "*" not in perms and permission not in perms:
            raise HTTPException(status_code=403, detail="Permission denied")
        return user
''',
        '''    def dep(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        if user.get("must_change_password"):
            raise HTTPException(status_code=428, detail="Password change required before using JewelLAN")
        perms = ROLE_PERMISSIONS.get(user["role"], set())
        if "*" not in perms and permission not in perms:
            raise HTTPException(status_code=403, detail="Permission denied")
        return user
''',
        "server-side mandatory password change",
    )
    path.write_text(text, encoding="utf-8")
    print("updated", path)


def patch_integrity() -> None:
    path = Path("jewel_server/integrity.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from .audit_chain import verify_audit_chain\nfrom .precision import money, money_equal, money_paise, weight_equal\n",
        "from .audit_chain import verify_audit_chain\nfrom .canonical import canonical_integrity, paise_to_money\nfrom .precision import money, money_equal, money_paise, weight_equal\n",
        "canonical integrity import",
    )
    text = replace_once(
        text,
        '''    audit = verify_audit_chain(conn)
    if not audit["ok"]:
        for row in audit["errors"][:20]:
            _append(issues, "audit_chain", f"Audit chain mismatch at entry {row['id']}", audit_id=row["id"])

    all_issues = issues
''',
        '''    audit = verify_audit_chain(conn)
    if not audit["ok"]:
        for row in audit["errors"][:20]:
            _append(issues, "audit_chain", f"Audit chain mismatch at entry {row['id']}", audit_id=row["id"])

    canonical = canonical_integrity(conn, max_errors=max_details)
    if not canonical["ok"]:
        for row in canonical["errors"][:20]:
            _append(issues, "canonical", f"Exact paise/milligram mirror mismatch in {row['table']}", **row)

    all_issues = issues
''',
        "canonical integrity checks",
    )
    text = replace_once(
        text,
        '''        "audit_chain": audit,
        "issues": all_issues[:max_details],
''',
        '''        "audit_chain": audit,
        "canonical": canonical,
        "issues": all_issues[:max_details],
''',
        "canonical integrity response",
    )
    day_close = r'''def day_close(conn, business_date: str) -> dict[str, Any]:
    sale = conn.execute(
        "SELECT count(*) c,coalesce(sum(total_paise),0) total,coalesce(sum(taxable_paise),0) taxable,coalesce(sum(gst_paise),0) gst,"
        "coalesce(sum(payment_cash_paise),0) cash,coalesce(sum(payment_card_paise),0) card,coalesce(sum(payment_upi_paise),0) upi,"
        "coalesce(sum(payment_credit_paise),0) credit,coalesce(sum(old_gold_value_paise),0) old_gold "
        "FROM sales WHERE status='posted' AND business_date=?",
        (business_date,),
    ).fetchone()
    cancelled = conn.execute(
        "SELECT count(*) FROM sales WHERE status='cancelled' AND business_date=?",
        (business_date,),
    ).fetchone()[0]
    purchase = conn.execute(
        "SELECT count(*) c,coalesce(sum(total_paise),0) total,coalesce(sum(paid_paise),0) paid FROM purchases WHERE business_date=?",
        (business_date,),
    ).fetchone()
    journal = conn.execute(
        "SELECT coalesce(sum(l.debit_paise),0) debit,coalesce(sum(l.credit_paise),0) credit "
        "FROM journal_entries e JOIN journal_lines l ON l.entry_id=e.id WHERE e.entry_date=?",
        (business_date,),
    ).fetchone()
    movement_count = conn.execute(
        "SELECT count(*) FROM stock_movements WHERE substr(created_at,1,10)=?",
        (business_date,),
    ).fetchone()[0]
    payment_paise = int(sale["cash"] + sale["card"] + sale["upi"] + sale["credit"] + sale["old_gold"])
    return {
        "date": business_date,
        "sales": {
            "count": sale["c"], "total": paise_to_money(sale["total"]), "taxable": paise_to_money(sale["taxable"]),
            "gst": paise_to_money(sale["gst"]), "cash": paise_to_money(sale["cash"]), "card": paise_to_money(sale["card"]),
            "upi": paise_to_money(sale["upi"]), "credit": paise_to_money(sale["credit"]), "old_gold": paise_to_money(sale["old_gold"]),
            "payment_total": paise_to_money(payment_paise), "payments_match_sales": payment_paise == int(sale["total"]),
        },
        "cancelled_sales": cancelled,
        "purchases": {"count": purchase["c"], "total": paise_to_money(purchase["total"]), "paid": paise_to_money(purchase["paid"])},
        "journal": {"debit": paise_to_money(journal["debit"]), "credit": paise_to_money(journal["credit"]), "balanced": int(journal["debit"]) == int(journal["credit"])},
        "stock_movements": movement_count,
    }
'''
    text = replace_between(text, "def day_close(conn, business_date: str) -> dict[str, Any]:", "", day_close, "exact day close") if False else text
    # day_close is the final function in this module, so replace from its start through EOF.
    start = text.find("def day_close(conn, business_date: str) -> dict[str, Any]:")
    if start < 0:
        raise RuntimeError("day_close start not found")
    text = text[:start] + day_close.rstrip() + "\n"
    path.write_text(text, encoding="utf-8")
    print("updated", path)


def patch_main() -> None:
    path = Path("jewel_server/main.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from .db import audit,get_settings,init_db,next_sequence,read_db,rowdict,rowsdict,set_setting,utcnow,write_db",
        "from .db import audit,business_date,business_now,get_settings,init_db,next_sequence,read_db,rowdict,rowsdict,set_setting,utcnow,write_db",
        "main business time imports",
    )
    text = replace_once(text, "from .precision import money_sum", "from .precision import money_paise,money_sum", "main canonical precision import")
    text = replace_once(text, "APP_VERSION='1.1.0-rc1'", "APP_VERSION='1.2.0-rc1'", "app version")
    text = replace_once(
        text,
        "allowed={'business_name','business_address','business_phone','business_gstin','business_state_code','currency'",
        "allowed={'business_name','business_address','business_phone','business_gstin','business_state_code','business_timezone_offset_minutes','currency'",
        "timezone setting allowlist",
    )
    old_rate = "with write_db() as c:cur=c.execute('INSERT INTO metal_rates(metal,purity,rate_per_gram,effective_at,created_by) VALUES(?,?,?,?,?)',(p.get('metal') or 'Gold',p.get('purity') or '916',rate,p.get('effective_at') or utcnow(),u['id']));audit(c,u['id'],'create','metal_rate',cur.lastrowid,p);return {'id':cur.lastrowid}"
    new_rate = "with write_db() as c:cur=c.execute('INSERT INTO metal_rates(metal,purity,rate_per_gram,effective_at,created_by,rate_paise_per_gram) VALUES(?,?,?,?,?,?)',(p.get('metal') or 'Gold',p.get('purity') or '916',rate,p.get('effective_at') or utcnow(),u['id'],money_paise(rate)));audit(c,u['id'],'create','metal_rate',cur.lastrowid,p);return {'id':cur.lastrowid}"
    text = replace_once(text, old_rate, new_rate, "canonical rate insert")
    text = text.replace("if date_from:w.append('substr(s.created_at,1,10)>=?');a.append(date_from)", "if date_from:w.append('s.business_date>=?');a.append(date_from)", 1)
    text = text.replace("if date_to:w.append('substr(s.created_at,1,10)<=?');a.append(date_to)", "if date_to:w.append('s.business_date<=?');a.append(date_to)", 1)

    purchase_fn = r'''@app.post('/api/purchases')
def purchase(p:dict=Body(...),u=Depends(require('purchases'))):
    req=str(p.get('client_request_id') or '').strip() or None
    with write_db() as c:
        if req:
            old=c.execute('SELECT id,purchase_no,total FROM purchases WHERE client_request_id=?',(req,)).fetchone()
            if old:return dict(old)|{'idempotent':True}
        its=p.get('items') or []
        if not its:raise HTTPException(400,'Purchase must have at least one item')
        no=next_sequence(c,'purchase','PUR-'+business_now(c).strftime('%y%m')+'-',6);now=utcnow();business_day=business_date(c);sid=p.get('supplier_id') or None;bid=int(p.get('branch_id') or 1);sub=money_sum(x.get('cost_amount',0) for x in its);gst=money(p.get('gst'));total=money(sub+gst);paid=money(p.get('paid'))
        if paid<0 or money_paise(paid)>money_paise(total):raise HTTPException(400,'Paid amount cannot exceed purchase total')
        cur=c.execute('INSERT INTO purchases(purchase_no,client_request_id,supplier_id,branch_id,business_date,subtotal,gst,total,paid,notes,user_id,created_at,subtotal_paise,gst_paise,total_paise,paid_paise) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(no,req,sid,bid,business_day,sub,gst,total,paid,p.get('notes'),u['id'],now,money_paise(sub),money_paise(gst),money_paise(total),money_paise(paid)));pid=cur.lastrowid
        for x in its:
            x=dict(x);x.update({'branch_id':bid,'supplier_id':sid,'ref_type':'purchase','ref_id':pid});it=create_item(c,x,u);c.execute('INSERT INTO purchase_items(purchase_id,item_id,cost_amount,gst_amount,cost_amount_paise,gst_amount_paise) VALUES(?,?,?,0,?,0)',(pid,it['id'],it['cost_amount'],money_paise(it['cost_amount'])))
        payable=money(total-paid)
        if sid and payable:c.execute('UPDATE suppliers SET balance=balance+?,updated_at=? WHERE id=?',(payable,now,sid))
        je=next_sequence(c,'journal','JE',7);j=c.execute('INSERT INTO journal_entries(entry_no,entry_date,memo,ref_type,ref_id,user_id,created_at) VALUES(?,?,?,?,?,?,?)',(je,business_day,f'Purchase {no}','purchase',pid,u['id'],now)).lastrowid;lines=[('1200',sub,0,None,None)]
        if gst:lines.append(('2110',gst,0,None,None))
        if paid:lines.append(('1000',0,paid,None,None))
        if payable:lines.append(('2000',0,payable,'supplier',sid))
        for code,dr,cr,pt,party in lines:c.execute('INSERT INTO journal_lines(entry_id,account_code,debit,credit,party_type,party_id,debit_paise,credit_paise) VALUES(?,?,?,?,?,?,?,?)',(j,code,dr,cr,pt,party,money_paise(dr),money_paise(cr)))
        audit(c,u['id'],'create','purchase',pid,{'purchase_no':no,'total':total});enqueue_tally(c,'purchase',pid,'create');return {'id':pid,'purchase_no':no,'total':total}
'''
    text = replace_between(text, "@app.post('/api/purchases')", "@app.get('/api/purchases')", purchase_fn, "exact purchase workflow")
    text = text.replace("p.get('received_on') or dt.date.today().isoformat()", "p.get('received_on') or business_date(c)", 1)

    old_summary = "with read_db() as c:s=c.execute(\"SELECT count(*) invoices,coalesce(sum(taxable),0) taxable,coalesce(sum(gst),0) gst,coalesce(sum(total),0) total FROM sales WHERE status='posted' AND substr(created_at,1,10) BETWEEN ? AND ?\",(date_from,date_to)).fetchone();stock=c.execute(\"SELECT count(*) pieces,coalesce(sum(gross_weight),0) gross_weight,coalesce(sum(net_weight),0) net_weight,coalesce(sum(cost_amount),0) cost FROM items WHERE status='in_stock'\").fetchone();met=rowsdict(c.execute(\"SELECT metal,purity,count(*) pieces,sum(gross_weight) gross_weight,sum(net_weight) net_weight,sum(cost_amount) cost FROM items WHERE status='in_stock' GROUP BY metal,purity ORDER BY metal,purity\").fetchall());pay=c.execute(\"SELECT coalesce(sum(payment_cash),0) cash,coalesce(sum(payment_card),0) card,coalesce(sum(payment_upi),0) upi,coalesce(sum(payment_credit),0) credit,coalesce(sum(old_gold_value),0) old_gold FROM sales WHERE status='posted' AND substr(created_at,1,10) BETWEEN ? AND ?\",(date_from,date_to)).fetchone();return {'date_from':date_from,'date_to':date_to,'sales':dict(s),'stock':dict(stock),'stock_by_metal':met,'payments':dict(pay)}"
    new_summary = "with read_db() as c:s=c.execute(\"SELECT count(*) invoices,coalesce(sum(taxable_paise),0)/100.0 taxable,coalesce(sum(gst_paise),0)/100.0 gst,coalesce(sum(total_paise),0)/100.0 total FROM sales WHERE status='posted' AND business_date BETWEEN ? AND ?\",(date_from,date_to)).fetchone();stock=c.execute(\"SELECT count(*) pieces,coalesce(sum(gross_mg),0)/1000.0 gross_weight,coalesce(sum(net_mg),0)/1000.0 net_weight,coalesce(sum(cost_amount_paise),0)/100.0 cost FROM items WHERE status='in_stock'\").fetchone();met=rowsdict(c.execute(\"SELECT metal,purity,count(*) pieces,sum(gross_mg)/1000.0 gross_weight,sum(net_mg)/1000.0 net_weight,sum(cost_amount_paise)/100.0 cost FROM items WHERE status='in_stock' GROUP BY metal,purity ORDER BY metal,purity\").fetchall());pay=c.execute(\"SELECT coalesce(sum(payment_cash_paise),0)/100.0 cash,coalesce(sum(payment_card_paise),0)/100.0 card,coalesce(sum(payment_upi_paise),0)/100.0 upi,coalesce(sum(payment_credit_paise),0)/100.0 credit,coalesce(sum(old_gold_value_paise),0)/100.0 old_gold FROM sales WHERE status='posted' AND business_date BETWEEN ? AND ?\",(date_from,date_to)).fetchone();return {'date_from':date_from,'date_to':date_to,'sales':dict(s),'stock':dict(stock),'stock_by_metal':met,'payments':dict(pay)}"
    text = replace_once(text, old_summary, new_summary, "canonical summary report")
    text = replace_once(
        text,
        "coalesce(sum(x.debit),0) debit,coalesce(sum(x.credit),0) credit,coalesce(sum(x.debit-x.credit),0) balance",
        "coalesce(sum(x.debit_paise),0)/100.0 debit,coalesce(sum(x.credit_paise),0)/100.0 credit,coalesce(sum(x.debit_paise-x.credit_paise),0)/100.0 balance",
        "canonical trial balance",
    )
    text = replace_once(
        text,
        "SELECT je.entry_no,je.entry_date,je.memo,je.ref_type,je.ref_id,jl.debit,jl.credit FROM journal_lines",
        "SELECT je.entry_no,je.entry_date,je.memo,je.ref_type,je.ref_id,jl.debit_paise/100.0 debit,jl.credit_paise/100.0 credit FROM journal_lines",
        "canonical ledger report",
    )
    path.write_text(text, encoding="utf-8")
    print("updated", path)


def patch_client() -> None:
    path = Path("jewel_client/main.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(text, "self.load_settings(); self.build()\n        if user.get(\"must_change_password\"): root.after(400, lambda: self.change_password(True))", "self.load_settings(); self.build()", "remove client-only forced password scheduling")

    password_dialog = r'''def password_change_dialog(parent, title="Change password", forced=False):
    d=tk.Toplevel(parent);d.title(title);d.configure(bg=PALETTE["bg"]);center(d,500,360);d.resizable(False,False);d.transient(parent);d.grab_set();result={"value":None}
    shell=ttk.Frame(d,style="Surface.TFrame",padding=24);shell.pack(fill="both",expand=True,padx=18,pady=18)
    ttk.Label(shell,text=title,style="Section.TLabel",font=("Segoe UI Semibold",15)).pack(anchor="w")
    ttk.Label(shell,text="Use at least 10 characters. This password is stored only as a secure hash on your JewelLAN server.",style="SurfaceMuted.TLabel",wraplength=420).pack(anchor="w",pady=(4,16))
    vars_={k:tk.StringVar() for k in ("old_password","new_password","again")};labels=(("old_password","Current password"),("new_password","New password"),("again","Repeat new password"))
    first=None
    for key,label in labels:
        ttk.Label(shell,text=label,style="SurfaceMuted.TLabel").pack(anchor="w",pady=(5,3));e=ttk.Entry(shell,textvariable=vars_[key],show="●");e.pack(fill="x",ipady=3)
        if first is None:first=e
    def save():result["value"]={k:v.get() for k,v in vars_.items()};d.destroy()
    b=ttk.Frame(shell,style="Surface.TFrame");b.pack(fill="x",pady=(18,0));ttk.Button(b,text="Save password",style="Primary.TButton",command=save).pack(side="right")
    if not forced:ttk.Button(b,text="Cancel",style="Secondary.TButton",command=d.destroy).pack(side="right",padx=(0,8))
    else:d.protocol("WM_DELETE_WINDOW",lambda:None)
    d.bind("<Return>",lambda _e:save());
    if not forced:d.bind("<Escape>",lambda _e:d.destroy())
    if first:first.focus_set()
    parent.wait_window(d);return result["value"]


def force_initial_password_change(root,api,user):
    while user.get("must_change_password"):
        data=password_change_dialog(root,"Password change required",True)
        if not data:return False
        if len(data["new_password"])<10:
            messagebox.showerror("Password","New password must be at least 10 characters.",parent=root);continue
        if data["new_password"]!=data["again"]:
            messagebox.showerror("Password","New passwords do not match.",parent=root);continue
        try:
            api.post("/api/auth/change-password",{"old_password":data["old_password"],"new_password":data["new_password"]});user["must_change_password"]=0;messagebox.showinfo("Password","Password changed. JewelLAN is ready to use.",parent=root);return True
        except Exception as e:messagebox.showerror("Password change failed",str(e),parent=root)
    return True


'''
    text = replace_once(text, "class LoginDialog(tk.Toplevel):", password_dialog + "\n\nclass LoginDialog(tk.Toplevel):", "masked mandatory password dialog")
    old_change = '''    def change_password(self, forced=False):
        data = form_dialog(self.root, "Change password", [("old_password","Current password"),("new_password","New password"),("again","Repeat new password")])
        if not data:
            if forced: self.root.after(300, lambda: self.change_password(True))
            return
        if data["new_password"] != data["again"]: self.error("New passwords do not match"); return
        try:
            self.api.post("/api/auth/change-password", {"old_password": data["old_password"], "new_password": data["new_password"]}); self.user["must_change_password"] = 0
            messagebox.showinfo("Password", "Password changed.", parent=self.root)
        except Exception as e:
            self.error(e); self.root.after(300, lambda: self.change_password(True)) if forced else None
'''
    new_change = '''    def change_password(self, forced=False):
        data=password_change_dialog(self.root,"Change password",forced)
        if not data:return
        if len(data["new_password"])<10:self.error("New password must be at least 10 characters");return
        if data["new_password"]!=data["again"]:self.error("New passwords do not match");return
        try:self.api.post("/api/auth/change-password",{"old_password":data["old_password"],"new_password":data["new_password"]});self.user["must_change_password"]=0;messagebox.showinfo("Password","Password changed.",parent=self.root)
        except Exception as e:self.error(e)
'''
    text = replace_once(text, old_change, new_change, "masked normal password change")
    text = replace_once(
        text,
        'super().__init__(parent,app);self.heading("Administration","Metal rates, users, backups, business settings and this workstation.");self.nb=ttk.Notebook(self);self.nb.pack(fill="both",expand=True);self.make_rates();self.make_backup();self.make_pc();',
        'super().__init__(parent,app);self.heading("Administration","Metal rates, users, backups, integrity, business settings and this workstation.");self.nb=ttk.Notebook(self);self.nb.pack(fill="both",expand=True);self.make_rates();self.make_health();self.make_backup();self.make_pc();',
        "administration health tab",
    )
    health_method = r'''    def make_health(self):
        f=ttk.Frame(self.nb,padding=12);self.nb.add(f,text="Data health");bar=ttk.Frame(f);bar.pack(fill="x");ttk.Button(bar,text="Refresh checks",command=self.refresh_health).pack(side="left");ttk.Button(bar,text="Create verified backup",command=self.health_backup).pack(side="left",padx=6);self.health_status=tk.StringVar(value="Not checked yet");ttk.Label(f,textvariable=self.health_status,style="SurfaceMuted.TLabel",wraplength=900).pack(anchor="w",pady=(10,8));self.health_text=tk.Text(f,height=18,wrap="word",font=("Consolas",9));self.health_text.pack(fill="both",expand=True);self.refresh_health()
    def refresh_health(self):
        try:
            i=self.api.get('/api/integrity');d=self.api.get('/api/reports/day-close');b=self.api.get('/api/health').get('backup',{});ok=bool(i.get('ok')) and bool(d.get('journal',{}).get('balanced')) and bool(d.get('sales',{}).get('payments_match_sales'));self.health_status.set(('PASS' if ok else 'ATTENTION REQUIRED')+f" · integrity issues {i.get('issue_count',0)} · canonical mismatches {i.get('canonical',{}).get('mismatches',0)}")
            lines=[f"Database quick check: {i.get('sqlite_quick_check')}",f"Foreign-key violations: {i.get('foreign_key_violations')}",f"Audit chain: {'OK' if i.get('audit_chain',{}).get('ok') else 'FAILED'}",f"Exact paise/mg mirrors: {'OK' if i.get('canonical',{}).get('ok') else 'FAILED'}",f"Today sales: {d.get('sales',{}).get('count',0)} · {money(d.get('sales',{}).get('total',0))}",f"Payment reconciliation: {'OK' if d.get('sales',{}).get('payments_match_sales') else 'FAILED'}",f"Journal balance: {'OK' if d.get('journal',{}).get('balanced') else 'FAILED'}",f"Last backup: {b.get('at','none')} · {'OK' if b.get('ok') else 'not verified'}"]
            if i.get('issues'):lines.append("\nIssues:\n"+"\n".join(f"- {x.get('message',x)}" for x in i['issues'][:30]));self.health_text.delete('1.0','end');self.health_text.insert('1.0','\n'.join(lines))
        except Exception as e:self.health_status.set('Health check failed');self.health_text.delete('1.0','end');self.health_text.insert('1.0',str(e))
    def health_backup(self):
        try:r=self.api.post('/api/backups',{'label':'health-check'});messagebox.showinfo('Verified backup',f"Created {r['name']}\nSHA-256 {r.get('sha256','')}\nVerified: {r.get('verified')}",parent=self);self.refresh_health()
        except Exception as e:self.app.error(e)
'''
    text = replace_once(text, "    def make_backup(self):", health_method + "\n    def make_backup(self):", "data health methods")
    text = replace_once(
        text,
        'keys=("business_name","business_address","business_phone","business_gstin","invoice_prefix"',
        'keys=("business_name","business_address","business_phone","business_gstin","business_timezone_offset_minutes","invoice_prefix"',
        "timezone business UI",
    )
    text = replace_once(
        text,
        '''    if not login.user:return
    root.deiconify();App(root,api,cfg,login.user);root.mainloop()
''',
        '''    if not login.user:return
    if login.user.get("must_change_password") and not force_initial_password_change(root,api,login.user):return
    root.deiconify();App(root,api,cfg,login.user);root.mainloop()
''',
        "mandatory password before app construction",
    )
    path.write_text(text, encoding="utf-8")
    print("updated", path)


def main() -> None:
    patch_db();patch_services();patch_security();patch_integrity();patch_main();patch_client()


if __name__ == "__main__":
    main()
