from __future__ import annotations
import datetime as dt, hashlib, json, re, sqlite3, uuid
from typing import Any
from fastapi import HTTPException
from .db import audit,business_date,business_now,day_is_closed,get_settings,next_sequence,request_fingerprint,utcnow,valid_branch_counter
from .tally import enqueue_tally
from .precision import decimal_value,money,money_decimal,money_equal,money_paise,money_sum,nearest_rupee,paise_money,weight,weight_decimal,weight_equal,weight_mg

PRODUCTION_HARDENED_V1 = True

def require_client_request_id(payload: dict[str, Any], operation: str = "operation") -> str:
    raw = str(payload.get("client_request_id") or "").strip()
    if not raw:
        raise HTTPException(400, detail={"code":"REQUEST_ID_REQUIRED","message":f"client_request_id is required for {operation}"})
    try:
        parsed = uuid.UUID(raw)
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(400, detail={"code":"INVALID_REQUEST_ID","message":"client_request_id must be a valid UUID"})
    return str(parsed)


def purity_fraction(purity:str)->float:
    p=str(purity).upper().strip().replace('K','');known={'999':.999,'995':.995,'990':.990,'958':.958,'950':.950,'925':.925,'916':.916,'875':.875,'833':.833,'750':.750,'585':.585,'417':.417,'375':.375,'24':.999,'23':.958,'22':.916,'21':.875,'20':.833,'18':.750,'14':.585,'10':.417,'9':.375}
    if p in known:return known[p]
    try:
        v=float(p);return min(v/1000 if v>24 else v/24,1)
    except:return 1.0

def _gst_state_code(value):
    s=str(value or '').strip()
    return s[:2] if len(s)>=2 and s[:2].isdigit() else ''

def gst_components(conn,customer_id,gst,payload):
    total=money(gst);settings=get_settings(conn);business=_gst_state_code(settings.get('business_state_code')) or _gst_state_code(settings.get('business_gstin'));customer=None
    if customer_id:customer=conn.execute('SELECT gstin FROM customers WHERE id=?',(customer_id,)).fetchone()
    place=_gst_state_code(payload.get('place_of_supply_code')) or (_gst_state_code(customer['gstin']) if customer else '') or business
    if business and place and business!=place:return place,0.0,0.0,total
    cgst=money(total/2);return place,cgst,money(total-cgst),0.0

def latest_rate(conn,metal,purity):
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
    return {'item_id':i['id'],'item_version':i.get('version'),'tag_no':i['tag_no'],'description':i['name'],'metal':i['metal'],'purity':i['purity'],'gross_weight':weight(i['gross_weight']),'net_weight':weight(net_d),'metal_rate':money(rate_d),'metal_value':money(metal_d),'wastage_percent':float(wp_d),'wastage_value':money(wastage_d),'making_type':making_type,'making_value':float(making_value_d),'making_charge':money(making_d),'stone_value':money(stone_d),'discount':money(discount_d),'taxable':money(taxable_d),'gst_rate':float(gst_rate_d),'gst_amount':money(gst_d),'line_total':money(taxable_d+gst_d),'cost_amount':money(i.get('cost_amount',0))}


def quote_sale(conn,lines,header_discount=0,old_gold_value=0,context=None,trusted_overrides=False):
    out=[];seen=set();ctx=context or {}
    branch_id=ctx.get('branch_id');branch_id=int(branch_id) if branch_id not in (None,'') else None
    counter_id=ctx.get('counter_id');counter_id=int(counter_id) if counter_id not in (None,'') else None
    allowed_client_fields={'item_id','item_version'}
    for ln in lines:
        if not isinstance(ln,dict):raise HTTPException(400,'Each invoice line must be an object')
        iid=int(ln.get('item_id') or 0)
        if iid in seen:raise HTTPException(400,'Same tag scanned twice')
        seen.add(iid);item=conn.execute('SELECT * FROM items WHERE id=?',(iid,)).fetchone()
        if not item:raise HTTPException(404,f'Item {iid} not found')
        item_d=dict(item)
        if item_d['status']!='in_stock':raise HTTPException(409,f"Tag {item_d['tag_no']} is {item_d['status']}")
        if branch_id is not None and int(item_d.get('branch_id') or 0)!=branch_id:
            raise HTTPException(409,detail={'code':'CROSS_BRANCH_ITEM','message':f"Tag {item_d['tag_no']} belongs to another branch",'item_id':iid,'item_branch_id':item_d.get('branch_id'),'sale_branch_id':branch_id})
        if counter_id is not None and item_d.get('counter_id') not in (None,counter_id):
            raise HTTPException(409,detail={'code':'CROSS_COUNTER_ITEM','message':f"Tag {item_d['tag_no']} is assigned to another counter",'item_id':iid,'item_counter_id':item_d.get('counter_id'),'sale_counter_id':counter_id})
        supplied_version=ln.get('item_version')
        if supplied_version not in (None,'') and int(supplied_version)!=int(item_d.get('version') or 0):
            raise HTTPException(409,detail={'code':'VERSION_CONFLICT','message':f"Tag {item_d['tag_no']} changed after it was loaded",'item_id':iid,'current_version':item_d.get('version')})
        if trusted_overrides:
            pricing_overrides=ln
        else:
            unexpected=sorted(set(ln)-allowed_client_fields)
            if unexpected:
                raise HTTPException(400,detail={'code':'PRICE_OVERRIDE_NOT_ALLOWED','message':'Sale-line pricing is server controlled; submit item_id/item_version only','fields':unexpected})
            pricing_overrides={}
        out.append(calculate_item_price(conn,item,pricing_overrides))
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
    quote_body={'lines':out,'discount':money(header_d),'old_gold_value':old_value,'context':ctx}
    quote_hash=hashlib.sha256(json.dumps(quote_body,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=str).encode('utf-8')).hexdigest()
    return {'lines':out,'subtotal':money(subtotal_d),'discount':money(header_d),'taxable':money(taxable_d),'gst':money(gst_d),'round_off':round_off,'total':total,'old_gold_value':old_value,'payable':payable,'quote_id':'Q-'+quote_hash[:20],'quote_version':quote_hash[:16],'quote_hash':quote_hash}


def _journal(conn,user_id,memo,ref_type,ref_id,lines):
    debit_paise=sum(money_paise(x[1]) for x in lines);credit_paise=sum(money_paise(x[2]) for x in lines)
    if debit_paise!=credit_paise:raise RuntimeError(f'Unbalanced journal: debit {debit_paise}p credit {credit_paise}p')
    no=next_sequence(conn,'journal','JE',7);cur=conn.execute('INSERT INTO journal_entries(entry_no,entry_date,memo,ref_type,ref_id,user_id,created_at) VALUES(?,?,?,?,?,?,?)',(no,business_date(conn),memo,ref_type,ref_id,user_id,utcnow()));eid=cur.lastrowid
    for code,dr,cr,pt,pid in lines:
        dr=money(dr);cr=money(cr)
        if dr or cr:conn.execute('INSERT INTO journal_lines(entry_id,account_code,debit,credit,party_type,party_id,debit_paise,credit_paise) VALUES(?,?,?,?,?,?,?,?)',(eid,code,dr,cr,pt,pid,money_paise(dr),money_paise(cr)))
    return eid

def _print_snapshot(conn, branch_id: int, customer_id: int | None, user: dict[str, Any]) -> str:
    settings = get_settings(conn)
    branch = conn.execute("SELECT id,code,name,gstin,address,phone FROM branches WHERE id=?", (branch_id,)).fetchone()
    customer = conn.execute("SELECT id,code,name,phone,email,address,gstin FROM customers WHERE id=?", (customer_id,)).fetchone() if customer_id else None
    snapshot = {
        "seller": {key: settings.get(key, "") for key in ("business_name", "business_address", "business_phone", "business_email", "business_gstin", "business_state_code", "business_state_name", "business_pincode")},
        "branch": dict(branch) if branch else {"id": branch_id},
        "customer": dict(customer) if customer else {"name": "Walk-in Customer", "phone": "", "gstin": ""},
        "tax": {key: settings.get(key, "") for key in ("gst_default", "business_state_code")},
        "posted_by": {"id": user.get("id"), "username": user.get("username"), "full_name": user.get("full_name")},
    }
    return json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _record_payments(conn, transaction_type: str, transaction_id: int, rows: list[tuple[str, Any, str, str | None]], user_id: int, paid_at: str, direction: str = "in") -> None:
    for method, amount, account_code, reference in rows:
        amount_paise = money_paise(amount)
        if amount_paise <= 0:
            continue
        conn.execute(
            """INSERT INTO payments(transaction_type,transaction_id,method,direction,amount_paise,reference,account_code,paid_at,actor_id)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (transaction_type, transaction_id, method, direction, amount_paise, reference, account_code, paid_at, user_id),
        )


def post_sale(conn,payload,user,client_ip=None):
    req=require_client_request_id(payload,'sale')
    fingerprint=request_fingerprint("sale",payload)
    e=conn.execute('SELECT id,invoice_no,total,request_fingerprint FROM sales WHERE client_request_id=?',(req,)).fetchone()
    if e:
        if e['request_fingerprint'] and e['request_fingerprint'] != fingerprint:
            raise HTTPException(409, detail={"code":"IDEMPOTENCY_CONFLICT","message":"This request ID was already used for different sale data","request_id":req})
        return {'id':e['id'],'invoice_no':e['invoice_no'],'total':e['total'],'idempotent':True}
    olds=payload.get('old_gold') or [];old_value=money_sum(x.get('value',0) for x in olds)
    bid=int(payload.get('branch_id') or 1);counter=payload.get('counter_id') or None;counter=int(counter) if counter is not None else None
    if not valid_branch_counter(conn,bid,counter):
        raise HTTPException(400, detail={"code":"INVALID_LOCATION","message":"The selected branch and counter are not a valid active pairing"})
    business_day=business_date(conn)
    if day_is_closed(conn,bid,business_day):
        raise HTTPException(409, detail={"code":"DAY_CLOSED","message":"This branch is closed for the current business date"})
    context={"branch_id":bid,"counter_id":counter}
    q=quote_sale(conn,payload.get('lines') or [],payload.get('discount',0),old_value,context)
    supplied_quote=payload.get('quote_hash') or payload.get('quote_id')
    if not supplied_quote:
        raise HTTPException(400,detail={'code':'QUOTE_REQUIRED','message':'A current server quote is required before posting a sale','request_id':req,'fresh_quote':q})
    if supplied_quote not in (q['quote_hash'],q['quote_id']):
        raise HTTPException(409, detail={"code":"QUOTE_STALE","message":"The quote changed before posting","request_id":req,"fresh_quote":q})
    if not q['lines']:raise HTTPException(400,'Invoice must contain at least one item')
    cash=money(payload.get('payment_cash'));card=money(payload.get('payment_card'));upi=money(payload.get('payment_upi'));credit=money(payload.get('payment_credit'));paid=money_sum((cash,card,upi,credit,old_value))
    if not money_equal(paid,q['total']):raise HTTPException(400,f"Payments ({paid:.2f}) must equal invoice total ({q['total']:.2f})")
    s=get_settings(conn);inv=next_sequence(conn,'invoice',s.get('invoice_prefix','INV')+'-'+business_now(conn).strftime('%y%m')+'-',6);now=utcnow();cid=payload.get('customer_id') or None
    if credit and not cid:raise HTTPException(400,'Credit payment requires a customer')
    place,cgst,sgst,igst=gst_components(conn,cid,q['gst'],payload)
    snapshot=_print_snapshot(conn,bid,int(cid) if cid else None,user)
    cur=conn.execute("""INSERT INTO sales(
        invoice_no,client_request_id,request_fingerprint,print_snapshot_json,branch_id,counter_id,customer_id,business_date,
        subtotal,discount,taxable,gst,place_of_supply_code,cgst,sgst,igst,round_off,total,
        payment_cash,payment_card,payment_upi,payment_credit,old_gold_value,notes,
        subtotal_paise,discount_paise,taxable_paise,gst_paise,cgst_paise,sgst_paise,igst_paise,round_off_paise,total_paise,
        payment_cash_paise,payment_card_paise,payment_upi_paise,payment_credit_paise,old_gold_value_paise,status,user_id,created_at
    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
        inv,req,fingerprint,snapshot,bid,counter,cid,business_day,q['subtotal'],q['discount'],q['taxable'],q['gst'],place,cgst,sgst,igst,q['round_off'],q['total'],cash,card,upi,credit,old_value,payload.get('notes'),
        money_paise(q['subtotal']),money_paise(q['discount']),money_paise(q['taxable']),money_paise(q['gst']),money_paise(cgst),money_paise(sgst),money_paise(igst),money_paise(q['round_off']),money_paise(q['total']),money_paise(cash),money_paise(card),money_paise(upi),money_paise(credit),money_paise(old_value),'posted',user['id'],now
    ));sid=cur.lastrowid;cost=0
    refs = payload.get('payment_references') if isinstance(payload.get('payment_references'), dict) else {}
    _record_payments(conn, 'sale', sid, [
        ('cash', cash, '1000', refs.get('cash')),
        ('card', card, '1010', refs.get('card')),
        ('upi', upi, '1010', refs.get('upi')),
        ('credit', credit, '1100', refs.get('credit')),
        ('old_gold', old_value, '1210', refs.get('old_gold')),
    ], user['id'], now)
    for l in q['lines']:
        params=[now,l['item_id'],bid]
        where="id=? AND status='in_stock' AND branch_id=?"
        if counter is not None:
            where += " AND (counter_id IS NULL OR counter_id=?)";params.append(counter)
        u=conn.execute("UPDATE items SET status='sold',version=version+1,updated_at=? WHERE "+where,params)
        if u.rowcount!=1:raise HTTPException(409,detail={'code':'STOCK_CHANGED','message':f"Tag {l['tag_no']} was sold, moved, or reassigned by another counter"})
        conn.execute('INSERT INTO sale_items(sale_id,item_id,tag_no,description,metal,purity,gross_weight,net_weight,metal_rate,metal_value,wastage_value,making_charge,stone_value,discount,taxable,gst_rate,gst_amount,line_total,cost_amount,gross_mg,net_mg,metal_rate_paise,metal_value_paise,wastage_value_paise,making_charge_paise,stone_value_paise,discount_paise,taxable_paise,gst_amount_paise,line_total_paise,cost_amount_paise) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(sid,l['item_id'],l['tag_no'],l['description'],l['metal'],l['purity'],l['gross_weight'],l['net_weight'],l['metal_rate'],l['metal_value'],l['wastage_value'],l['making_charge'],l['stone_value'],l['discount'],l['taxable'],l['gst_rate'],l['gst_amount'],l['line_total'],l['cost_amount'],weight_mg(l['gross_weight']),weight_mg(l['net_weight']),money_paise(l['metal_rate']),money_paise(l['metal_value']),money_paise(l['wastage_value']),money_paise(l['making_charge']),money_paise(l['stone_value']),money_paise(l['discount']),money_paise(l['taxable']),money_paise(l['gst_amount']),money_paise(l['line_total']),money_paise(l['cost_amount'])));cost=money(cost+l['cost_amount']);conn.execute('INSERT INTO stock_movements(item_id,movement_type,ref_type,ref_id,from_location,to_location,gross_weight,user_id,note,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(l['item_id'],'sale','sale',sid,f'branch:{bid}/counter:{counter}','customer',l['gross_weight'],user['id'],inv,now))
    for og in olds:
        gross=weight(og.get('gross_weight'));ded=decimal_value(og.get('deduction_percent',0));net=weight(weight_decimal(gross)*(decimal_value(100)-ded)/decimal_value(100));pure=weight(weight_decimal(net)*decimal_value(purity_fraction(str(og.get('purity','999')))));conn.execute('INSERT INTO old_gold(sale_id,customer_id,metal,purity,gross_weight,deduction_percent,net_weight,pure_weight,rate,value,notes,received_at,received_by,gross_mg,net_mg,pure_mg,rate_paise,value_paise) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(sid,cid,og.get('metal','Gold'),og.get('purity','999'),gross,ded,net,pure,money(og.get('rate')),money(og.get('value')),og.get('notes'),now,user['id'],weight_mg(gross),weight_mg(net),weight_mg(pure),money_paise(og.get('rate')),money_paise(og.get('value'))))
    if cid and credit:
        row=conn.execute('SELECT balance_paise FROM customers WHERE id=?',(cid,)).fetchone();newp=int(row['balance_paise'] or 0)+money_paise(credit);conn.execute('UPDATE customers SET balance=?,balance_paise=?,updated_at=? WHERE id=?',(paise_money(newp),newp,now,cid))
    jl=[]
    if cash:jl.append(('1000',cash,0,None,None))
    if card+upi:jl.append(('1010',money(card+upi),0,None,None))
    if credit:jl.append(('1100',credit,0,'customer',cid))
    if old_value:jl.append(('1210',old_value,0,'customer',cid))
    jl.append(('4000',0,q['taxable'],None,None))
    if q['gst']:jl.append(('2100',0,q['gst'],None,None))
    if q['round_off']>0:jl.append(('4000',0,q['round_off'],None,None))
    elif q['round_off']<0:jl.append(('4000',-q['round_off'],0,None,None))
    if cost:jl += [('5000',money(cost),0,None,None),('1200',0,money(cost),None,None)]
    _journal(conn,user['id'],f'Sale {inv}','sale',sid,jl);audit(conn,user['id'],'create','sale',sid,{'invoice_no':inv,'total':q['total']},client_ip);enqueue_tally(conn,'sale',sid,'create');
    if cost:enqueue_tally(conn,'sale_cogs',sid,'create')
    return {'id':sid,'invoice_no':inv,'total':q['total'],'payable':q['payable'],'idempotent':False}

def cancel_sale(conn,sale_id,user,reason='',client_ip=None):
    sale=conn.execute('SELECT * FROM sales WHERE id=?',(sale_id,)).fetchone()
    if not sale:raise HTTPException(404,'Sale not found')
    if sale['status']=='cancelled':return {'ok':True,'already_cancelled':True}
    reason=str(reason or '').strip()
    if len(reason)<3:raise HTTPException(400,'Cancellation reason is required')
    if day_is_closed(conn,int(sale['branch_id']),str(sale['business_date'] or business_date(conn))):
        raise HTTPException(409,detail={'code':'DAY_CLOSED','message':'Invoices cannot be cancelled after day close'})
    if conn.execute("""SELECT 1 FROM sale_return_items ri
        JOIN sale_returns r ON r.id=ri.return_id
        JOIN sale_items si ON si.id=ri.sale_item_id
        WHERE si.sale_id=? AND ri.active=1 AND r.status='posted' LIMIT 1""",(sale_id,)).fetchone():
        raise HTTPException(409,'Cannot cancel an invoice with an effective credit note')
    now=utcnow()
    for si in conn.execute('SELECT * FROM sale_items WHERE sale_id=?',(sale_id,)).fetchall():
        item=conn.execute('SELECT status FROM items WHERE id=?',(si['item_id'],)).fetchone()
        if item and item['status']!='sold':raise HTTPException(409,f"Cannot cancel: tag {si['tag_no']} is currently {item['status']}")
        conn.execute("UPDATE items SET status='in_stock',version=version+1,updated_at=? WHERE id=?",(now,si['item_id']));conn.execute('INSERT INTO stock_movements(item_id,movement_type,ref_type,ref_id,from_location,to_location,gross_weight,user_id,note,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(si['item_id'],'sale_cancel','sale',sale_id,'customer',f"branch:{sale['branch_id']}",si['gross_weight'],user['id'],reason,now))
    conn.execute("UPDATE sales SET status='cancelled',cancelled_at=?,cancelled_by=? WHERE id=?",(now,user['id'],sale_id))
    if sale['customer_id'] and sale['payment_credit']:
        row=conn.execute('SELECT balance_paise FROM customers WHERE id=?',(sale['customer_id'],)).fetchone();newp=int(row['balance_paise'] or 0)-money_paise(sale['payment_credit']);conn.execute('UPDATE customers SET balance=?,balance_paise=?,updated_at=? WHERE id=?',(paise_money(newp),newp,now,sale['customer_id']))
    je=conn.execute("SELECT id FROM journal_entries WHERE ref_type='sale' AND ref_id=? ORDER BY id LIMIT 1",(sale_id,)).fetchone()
    if je:_journal(conn,user['id'],f"Cancel sale {sale['invoice_no']}: {reason}",'sale_cancel',sale_id,[(x['account_code'],x['credit'],x['debit'],x['party_type'],x['party_id']) for x in conn.execute('SELECT * FROM journal_lines WHERE entry_id=?',(je['id'],)).fetchall()])
    audit(conn,user['id'],'cancel','sale',sale_id,{'reason':reason},client_ip);enqueue_tally(conn,'sale',sale_id,'cancel');
    cost=money(conn.execute('SELECT coalesce(sum(cost_amount),0) FROM sale_items WHERE sale_id=?',(sale_id,)).fetchone()[0])
    if cost:enqueue_tally(conn,'sale_cogs',sale_id,'cancel')
    return {'ok':True,'invoice_no':sale['invoice_no']}

_HUID_RE=re.compile(r'^[A-Z0-9]{6}$')


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
    try:cur=conn.execute('INSERT INTO items(tag_no,barcode,name,category,metal,purity,gross_weight,stone_weight,net_weight,fine_weight,stone_value,cost_amount,making_type,making_value,wastage_percent,huid,certificate_no,rfid_epc,hsn_code,gst_rate,status,branch_id,counter_id,supplier_id,purchase_date,notes,created_at,updated_at,net_weight_override_reason,gross_mg,stone_mg,net_mg,fine_mg,stone_value_paise,cost_amount_paise) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(tag,barcode,data.get('name') or data.get('category') or 'Jewellery',data.get('category') or 'Other',data.get('metal') or 'Gold',purity,gross,stone,net,fine,money(data.get('stone_value')),money(data.get('cost_amount')),making_type,making_value,wastage,huid,data.get('certificate_no') or None,data.get('rfid_epc') or None,data.get('hsn_code') or '7113',gst_rate,'in_stock',branch_id,counter_id,data.get('supplier_id') or None,data.get('purchase_date') or business_date(conn),data.get('notes') or None,now,now,override_reason,weight_mg(gross),weight_mg(stone),weight_mg(net),weight_mg(fine),money_paise(data.get('stone_value')),money_paise(data.get('cost_amount'))))
    except sqlite3.IntegrityError as e:raise HTTPException(409,f'Tag/barcode/HUID/RFID already exists or item data is invalid: {e}')
    iid=cur.lastrowid;conn.execute('INSERT INTO stock_movements(item_id,movement_type,ref_type,ref_id,from_location,to_location,gross_weight,user_id,note,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(iid,'stock_in',data.get('ref_type'),data.get('ref_id'),'supplier',f"branch:{branch_id}",gross,user_id,data.get('notes'),now));audit(conn,user_id,'create','item',iid,{'tag_no':tag,'huid':huid,'gross_weight':gross,'stone_weight':stone,'net_weight':net,'net_weight_override_reason':override_reason},client_ip);return dict(conn.execute('SELECT * FROM items WHERE id=?',(iid,)).fetchone())


def update_item(conn,item_id,data,user,client_ip=None):
    user_id=int(user['id']) if isinstance(user,dict) else int(user);role=str(user.get('role') or '') if isinstance(user,dict) else ''
    old=conn.execute('SELECT * FROM items WHERE id=?',(item_id,)).fetchone()
    if not old:raise HTTPException(404,'Item not found')
    expected_version=data.get('expected_version')
    if expected_version in (None,''):
        raise HTTPException(400,detail={'code':'VERSION_REQUIRED','message':'expected_version is required when updating an item','item_id':item_id,'current_version':old['version']})
    try:expected_version=int(expected_version)
    except (TypeError,ValueError):raise HTTPException(400,detail={'code':'INVALID_VERSION','message':'expected_version must be an integer'})
    if expected_version!=int(old['version']):
        raise HTTPException(409,detail={'code':'VERSION_CONFLICT','message':'This item changed on another workstation; reload before saving','item_id':item_id,'current_version':old['version']})
    critical={'barcode','name','category','metal','purity','gross_weight','stone_weight','net_weight','fine_weight','stone_value','cost_amount','making_type','making_value','wastage_percent','huid','rfid_epc','hsn_code','gst_rate','counter_id','supplier_id'}
    if old['status']!='in_stock' and any(k in data for k in critical):raise HTTPException(409,f"Tag {old['tag_no']} is {old['status']}; return it to in-stock before changing controlled item data")
    allowed=critical|{'certificate_no','notes','allow_net_weight_override','net_weight_override_reason'};v=dict(old);v.update({k:x for k,x in data.items() if k in allowed});gross,stone,net,fine,override_reason=_validated_weights(data,old,user if isinstance(user,dict) else {'id':user_id,'role':role});huid=normalize_huid(v.get('huid'));_assert_unique_huid(conn,huid,item_id);now=utcnow();making_type=str(v['making_type'])
    if making_type not in {'per_gram','percent','fixed'}:raise HTTPException(400,'Invalid making type')
    making_value=float(decimal_value(v['making_value']));wastage=float(decimal_value(v['wastage_percent']));gst_rate=float(decimal_value(v['gst_rate']))
    if making_value<0 or wastage<0:raise HTTPException(400,'Making and wastage values cannot be negative')
    if gst_rate<0 or gst_rate>100:raise HTTPException(400,'GST rate must be between 0 and 100')
    if v.get('counter_id') and not conn.execute('SELECT id FROM counters WHERE id=? AND branch_id=? AND active=1',(v['counter_id'],old['branch_id'])).fetchone():raise HTTPException(400,'Counter does not belong to this item branch')
    try:
        params=(v['barcode'],v['name'],v['category'],v['metal'],v['purity'],gross,stone,net,fine,money(v['stone_value']),money(v['cost_amount']),making_type,making_value,wastage,huid,v['certificate_no'],v['rfid_epc'],v['hsn_code'],gst_rate,v['counter_id'],v['supplier_id'],v['notes'],override_reason,weight_mg(gross),weight_mg(stone),weight_mg(net),weight_mg(fine),money_paise(v['stone_value']),money_paise(v['cost_amount']),now,item_id,expected_version)
        updated=conn.execute('UPDATE items SET barcode=?,name=?,category=?,metal=?,purity=?,gross_weight=?,stone_weight=?,net_weight=?,fine_weight=?,stone_value=?,cost_amount=?,making_type=?,making_value=?,wastage_percent=?,huid=?,certificate_no=?,rfid_epc=?,hsn_code=?,gst_rate=?,counter_id=?,supplier_id=?,notes=?,net_weight_override_reason=?,gross_mg=?,stone_mg=?,net_mg=?,fine_mg=?,stone_value_paise=?,cost_amount_paise=?,version=version+1,updated_at=? WHERE id=? AND version=?',params)
        if updated.rowcount!=1:raise HTTPException(409,detail={'code':'VERSION_CONFLICT','message':'This item changed on another workstation; reload before saving','item_id':item_id})
    except sqlite3.IntegrityError as e:raise HTTPException(409,f'Duplicate barcode/HUID/RFID or invalid item data: {e}')
    audit(conn,user_id,'update','item',item_id,{'changes':data,'gross_weight':gross,'stone_weight':stone,'net_weight':net,'net_weight_override_reason':override_reason},client_ip);return dict(conn.execute('SELECT * FROM items WHERE id=?',(item_id,)).fetchone())

def transfer_item(conn,item_id,branch_id,counter_id,user_id,note='',client_ip=None):
    item=conn.execute('SELECT * FROM items WHERE id=?',(item_id,)).fetchone()
    if not item:raise HTTPException(404,'Item not found')
    if item['status'] not in ('in_stock','transit'):raise HTTPException(409,f"Cannot transfer item in status {item['status']}")
    if not valid_branch_counter(conn,int(branch_id),int(counter_id) if counter_id is not None else None):raise HTTPException(400,'Counter does not belong to the selected branch')
    now=utcnow();conn.execute("UPDATE items SET branch_id=?,counter_id=?,status='in_stock',version=version+1,updated_at=? WHERE id=?",(branch_id,counter_id,now,item_id));conn.execute('INSERT INTO stock_movements(item_id,movement_type,from_location,to_location,gross_weight,user_id,note,created_at) VALUES(?,?,?,?,?,?,?,?)',(item_id,'transfer',f"branch:{item['branch_id']}/counter:{item['counter_id']}",f'branch:{branch_id}/counter:{counter_id}',item['gross_weight'],user_id,note,now));audit(conn,user_id,'transfer','item',item_id,{'branch_id':branch_id,'counter_id':counter_id},client_ip);return dict(conn.execute('SELECT * FROM items WHERE id=?',(item_id,)).fetchone())
