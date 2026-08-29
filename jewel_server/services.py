from __future__ import annotations
import datetime as dt, sqlite3
from typing import Any
from fastapi import HTTPException
from .db import audit,get_settings,next_sequence,utcnow
from .tally import enqueue_tally

def money(v): return round(float(v or 0)+1e-9,2)
def weight(v): return round(float(v or 0)+1e-12,3)
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
    if r:return float(r[0])
    r=conn.execute("SELECT purity,rate_per_gram FROM metal_rates WHERE lower(metal)=lower(?) ORDER BY effective_at DESC,id DESC LIMIT 1",(metal,)).fetchone()
    if r:return float(r[1])*purity_fraction(purity)/max(purity_fraction(r[0]),.001)
    raise HTTPException(409,f"No metal rate configured for {metal} {purity}")

def calculate_item_price(conn,item,overrides=None):
    i=dict(item);o=overrides or {};rate=float(o.get('metal_rate') or latest_rate(conn,i['metal'],i['purity']));net=float(i['net_weight']);metal=money(net*rate);wp=float(o.get('wastage_percent',i.get('wastage_percent',0)) or 0);wv=money(metal*wp/100);mt=str(o.get('making_type',i.get('making_type','per_gram')));mv=float(o.get('making_value',i.get('making_value',0)) or 0);making=money(metal*mv/100 if mt=='percent' else mv if mt=='fixed' else net*mv);stone=money(o.get('stone_value',i.get('stone_value',0)));disc=money(o.get('discount',0));taxable=max(0,money(metal+wv+making+stone-disc));gst_rate=float(o.get('gst_rate',i.get('gst_rate',3)) or 0);gst=money(taxable*gst_rate/100)
    return {'item_id':i['id'],'tag_no':i['tag_no'],'description':i['name'],'metal':i['metal'],'purity':i['purity'],'gross_weight':float(i['gross_weight']),'net_weight':net,'metal_rate':money(rate),'metal_value':metal,'wastage_percent':wp,'wastage_value':wv,'making_type':mt,'making_value':mv,'making_charge':making,'stone_value':stone,'discount':disc,'taxable':taxable,'gst_rate':gst_rate,'gst_amount':gst,'line_total':money(taxable+gst),'cost_amount':money(i.get('cost_amount',0))}

def quote_sale(conn,lines,header_discount=0,old_gold_value=0):
    out=[];seen=set()
    for ln in lines:
        iid=int(ln.get('item_id') or 0)
        if iid in seen:raise HTTPException(400,'Same tag scanned twice')
        seen.add(iid);item=conn.execute('SELECT * FROM items WHERE id=?',(iid,)).fetchone()
        if not item:raise HTTPException(404,f'Item {iid} not found')
        if item['status']!='in_stock':raise HTTPException(409,f"Tag {item['tag_no']} is {item['status']}")
        out.append(calculate_item_price(conn,item,ln))
    subtotal=money(sum(x['taxable'] for x in out));hd=min(money(max(0,header_discount)),subtotal);rem=hd
    for n,line in enumerate(out):
        alloc=0 if not hd or not subtotal else rem if n==len(out)-1 else min(money(hd*line['taxable']/subtotal),rem,line['taxable']);rem=money(rem-alloc);line['discount']=money(line['discount']+alloc);line['taxable']=money(max(0,line['taxable']-alloc));line['gst_amount']=money(line['taxable']*line['gst_rate']/100);line['line_total']=money(line['taxable']+line['gst_amount'])
    taxable=money(sum(x['taxable'] for x in out));gst=money(sum(x['gst_amount'] for x in out));gross=money(taxable+gst);rounded=round(gross);round_off=money(rounded-gross);total=money(gross+round_off)
    return {'lines':out,'subtotal':subtotal,'discount':hd,'taxable':taxable,'gst':gst,'round_off':round_off,'total':total,'old_gold_value':money(old_gold_value),'payable':money(max(0,total-float(old_gold_value or 0)))}

def _journal(conn,user_id,memo,ref_type,ref_id,lines):
    if abs(money(sum(x[1] for x in lines))-money(sum(x[2] for x in lines)))>.02:raise RuntimeError('Unbalanced journal')
    no=next_sequence(conn,'journal','JE',7);cur=conn.execute('INSERT INTO journal_entries(entry_no,entry_date,memo,ref_type,ref_id,user_id,created_at) VALUES(?,?,?,?,?,?,?)',(no,dt.date.today().isoformat(),memo,ref_type,ref_id,user_id,utcnow()));eid=cur.lastrowid
    for code,dr,cr,pt,pid in lines:
        if dr or cr:conn.execute('INSERT INTO journal_lines(entry_id,account_code,debit,credit,party_type,party_id) VALUES(?,?,?,?,?,?)',(eid,code,money(dr),money(cr),pt,pid))
    return eid

def post_sale(conn,payload,user,client_ip=None):
    req=str(payload.get('client_request_id') or '').strip() or None
    if req:
        e=conn.execute('SELECT id,invoice_no,total FROM sales WHERE client_request_id=?',(req,)).fetchone()
        if e:return {'id':e['id'],'invoice_no':e['invoice_no'],'total':e['total'],'idempotent':True}
    olds=payload.get('old_gold') or [];old_value=money(sum(float(x.get('value',0) or 0) for x in olds));q=quote_sale(conn,payload.get('lines') or [],float(payload.get('discount',0) or 0),old_value)
    if not q['lines']:raise HTTPException(400,'Invoice must contain at least one item')
    cash=money(payload.get('payment_cash'));card=money(payload.get('payment_card'));upi=money(payload.get('payment_upi'));credit=money(payload.get('payment_credit'));paid=money(cash+card+upi+credit+old_value)
    if abs(paid-q['total'])>.05:raise HTTPException(400,f"Payments ({paid:.2f}) must equal invoice total ({q['total']:.2f})")
    s=get_settings(conn);inv=next_sequence(conn,'invoice',s.get('invoice_prefix','INV')+'-'+dt.datetime.now().strftime('%y%m')+'-',6);now=utcnow();cid=payload.get('customer_id') or None;bid=int(payload.get('branch_id') or 1);counter=payload.get('counter_id') or None
    if credit and not cid:raise HTTPException(400,'Credit payment requires a customer')
    place,cgst,sgst,igst=gst_components(conn,cid,q['gst'],payload)
    if credit and not cid:raise HTTPException(400,'Credit payment requires a customer')
    place,cgst,sgst,igst=gst_components(conn,cid,q['gst'],payload)
    cur=conn.execute("INSERT INTO sales(invoice_no,client_request_id,branch_id,counter_id,customer_id,subtotal,discount,taxable,gst,place_of_supply_code,cgst,sgst,igst,round_off,total,payment_cash,payment_card,payment_upi,payment_credit,old_gold_value,notes,status,user_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'posted',?,?)",(inv,req,bid,counter,cid,q['subtotal'],q['discount'],q['taxable'],q['gst'],place,cgst,sgst,igst,q['round_off'],q['total'],cash,card,upi,credit,old_value,payload.get('notes'),user['id'],now));sid=cur.lastrowid;cost=0
    for l in q['lines']:
        u=conn.execute("UPDATE items SET status='sold',version=version+1,updated_at=? WHERE id=? AND status='in_stock'",(now,l['item_id']))
        if u.rowcount!=1:raise HTTPException(409,f"Tag {l['tag_no']} was sold/moved by another counter")
        conn.execute('INSERT INTO sale_items(sale_id,item_id,tag_no,description,metal,purity,gross_weight,net_weight,metal_rate,metal_value,wastage_value,making_charge,stone_value,discount,taxable,gst_rate,gst_amount,line_total,cost_amount) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(sid,l['item_id'],l['tag_no'],l['description'],l['metal'],l['purity'],l['gross_weight'],l['net_weight'],l['metal_rate'],l['metal_value'],l['wastage_value'],l['making_charge'],l['stone_value'],l['discount'],l['taxable'],l['gst_rate'],l['gst_amount'],l['line_total'],l['cost_amount']));cost+=l['cost_amount'];conn.execute('INSERT INTO stock_movements(item_id,movement_type,ref_type,ref_id,from_location,to_location,gross_weight,user_id,note,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(l['item_id'],'sale','sale',sid,f'branch:{bid}','customer',l['gross_weight'],user['id'],inv,now))
    for og in olds:
        gross=weight(og.get('gross_weight'));ded=float(og.get('deduction_percent',0) or 0);net=weight(gross*(1-ded/100));pure=weight(net*purity_fraction(str(og.get('purity','999'))));conn.execute('INSERT INTO old_gold(sale_id,customer_id,metal,purity,gross_weight,deduction_percent,net_weight,pure_weight,rate,value,notes,received_at,received_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(sid,cid,og.get('metal','Gold'),og.get('purity','999'),gross,ded,net,pure,money(og.get('rate')),money(og.get('value')),og.get('notes'),now,user['id']))
    if cid and credit:conn.execute('UPDATE customers SET balance=balance+?,updated_at=? WHERE id=?',(credit,now,cid))
    jl=[]
    if cash:jl.append(('1000',cash,0,None,None))
    if card+upi:jl.append(('1010',card+upi,0,None,None))
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
    now=utcnow()
    for si in conn.execute('SELECT * FROM sale_items WHERE sale_id=?',(sale_id,)).fetchall():
        item=conn.execute('SELECT status FROM items WHERE id=?',(si['item_id'],)).fetchone()
        if item and item['status']!='sold':raise HTTPException(409,f"Cannot cancel: tag {si['tag_no']} is currently {item['status']}")
        conn.execute("UPDATE items SET status='in_stock',version=version+1,updated_at=? WHERE id=?",(now,si['item_id']));conn.execute('INSERT INTO stock_movements(item_id,movement_type,ref_type,ref_id,from_location,to_location,gross_weight,user_id,note,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(si['item_id'],'sale_cancel','sale',sale_id,'customer',f"branch:{sale['branch_id']}",si['gross_weight'],user['id'],reason,now))
    conn.execute("UPDATE sales SET status='cancelled',cancelled_at=?,cancelled_by=? WHERE id=?",(now,user['id'],sale_id))
    if sale['customer_id'] and sale['payment_credit']:conn.execute('UPDATE customers SET balance=max(0,balance-?),updated_at=? WHERE id=?',(sale['payment_credit'],now,sale['customer_id']))
    je=conn.execute("SELECT id FROM journal_entries WHERE ref_type='sale' AND ref_id=? ORDER BY id LIMIT 1",(sale_id,)).fetchone()
    if je:_journal(conn,user['id'],f"Cancel sale {sale['invoice_no']}: {reason}",'sale_cancel',sale_id,[(x['account_code'],x['credit'],x['debit'],x['party_type'],x['party_id']) for x in conn.execute('SELECT * FROM journal_lines WHERE entry_id=?',(je['id'],)).fetchall()])
    audit(conn,user['id'],'cancel','sale',sale_id,{'reason':reason},client_ip);enqueue_tally(conn,'sale',sale_id,'cancel');
    cost=money(conn.execute('SELECT coalesce(sum(cost_amount),0) FROM sale_items WHERE sale_id=?',(sale_id,)).fetchone()[0])
    if cost:enqueue_tally(conn,'sale_cogs',sale_id,'cancel')
    return {'ok':True,'invoice_no':sale['invoice_no']}

def create_item(conn,data,user_id,client_ip=None):
    s=get_settings(conn);tag=str(data.get('tag_no') or '').strip() or next_sequence(conn,'tag',s.get('tag_prefix','TAG')+'-',7);barcode=str(data.get('barcode') or tag).strip();gross=weight(data.get('gross_weight'));stone=weight(data.get('stone_weight'));net=weight(data.get('net_weight',gross-stone));purity=str(data.get('purity') or '916')
    if net<0 or stone>gross+.001:raise HTTPException(400,'Invalid weights')
    fine=weight(data.get('fine_weight',net*purity_fraction(purity)));now=utcnow()
    try:cur=conn.execute('INSERT INTO items(tag_no,barcode,name,category,metal,purity,gross_weight,stone_weight,net_weight,fine_weight,stone_value,cost_amount,making_type,making_value,wastage_percent,huid,certificate_no,rfid_epc,hsn_code,gst_rate,status,branch_id,counter_id,supplier_id,purchase_date,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(tag,barcode,data.get('name') or data.get('category') or 'Jewellery',data.get('category') or 'Other',data.get('metal') or 'Gold',purity,gross,stone,net,fine,money(data.get('stone_value')),money(data.get('cost_amount')),data.get('making_type') or 'per_gram',float(data.get('making_value',0) or 0),float(data.get('wastage_percent',0) or 0),data.get('huid') or None,data.get('certificate_no') or None,data.get('rfid_epc') or None,data.get('hsn_code') or '7113',float(data.get('gst_rate',3) or 0),data.get('status') or 'in_stock',int(data.get('branch_id') or 1),data.get('counter_id') or None,data.get('supplier_id') or None,data.get('purchase_date') or dt.date.today().isoformat(),data.get('notes') or None,now,now))
    except sqlite3.IntegrityError as e:raise HTTPException(409,f'Tag/barcode/RFID already exists: {e}')
    iid=cur.lastrowid;conn.execute('INSERT INTO stock_movements(item_id,movement_type,ref_type,ref_id,from_location,to_location,gross_weight,user_id,note,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(iid,'stock_in',data.get('ref_type'),data.get('ref_id'),'supplier',f"branch:{int(data.get('branch_id') or 1)}",gross,user_id,data.get('notes'),now));audit(conn,user_id,'create','item',iid,{'tag_no':tag},client_ip);return dict(conn.execute('SELECT * FROM items WHERE id=?',(iid,)).fetchone())

def update_item(conn,item_id,data,user_id,client_ip=None):
    old=conn.execute('SELECT * FROM items WHERE id=?',(item_id,)).fetchone()
    if not old:raise HTTPException(404,'Item not found')
    allowed={'barcode','name','category','metal','purity','gross_weight','stone_weight','net_weight','fine_weight','stone_value','cost_amount','making_type','making_value','wastage_percent','huid','certificate_no','rfid_epc','hsn_code','gst_rate','counter_id','supplier_id','notes'};v=dict(old);v.update({k:x for k,x in data.items() if k in allowed});gross=weight(v['gross_weight']);stone=weight(v['stone_weight']);net=weight(v.get('net_weight') if v.get('net_weight') is not None else gross-stone);fine=weight(v.get('fine_weight') or net*purity_fraction(str(v['purity'])));now=utcnow()
    if net<0 or stone>gross+.001:raise HTTPException(400,'Invalid weights')
    try:conn.execute('UPDATE items SET barcode=?,name=?,category=?,metal=?,purity=?,gross_weight=?,stone_weight=?,net_weight=?,fine_weight=?,stone_value=?,cost_amount=?,making_type=?,making_value=?,wastage_percent=?,huid=?,certificate_no=?,rfid_epc=?,hsn_code=?,gst_rate=?,counter_id=?,supplier_id=?,notes=?,version=version+1,updated_at=? WHERE id=?',(v['barcode'],v['name'],v['category'],v['metal'],v['purity'],gross,stone,net,fine,money(v['stone_value']),money(v['cost_amount']),v['making_type'],float(v['making_value']),float(v['wastage_percent']),v['huid'],v['certificate_no'],v['rfid_epc'],v['hsn_code'],float(v['gst_rate']),v['counter_id'],v['supplier_id'],v['notes'],now,item_id))
    except sqlite3.IntegrityError as e:raise HTTPException(409,f'Duplicate barcode/RFID: {e}')
    audit(conn,user_id,'update','item',item_id,data,client_ip);return dict(conn.execute('SELECT * FROM items WHERE id=?',(item_id,)).fetchone())

def transfer_item(conn,item_id,branch_id,counter_id,user_id,note='',client_ip=None):
    item=conn.execute('SELECT * FROM items WHERE id=?',(item_id,)).fetchone()
    if not item:raise HTTPException(404,'Item not found')
    if item['status'] not in ('in_stock','transit'):raise HTTPException(409,f"Cannot transfer item in status {item['status']}")
    now=utcnow();conn.execute("UPDATE items SET branch_id=?,counter_id=?,status='in_stock',version=version+1,updated_at=? WHERE id=?",(branch_id,counter_id,now,item_id));conn.execute('INSERT INTO stock_movements(item_id,movement_type,from_location,to_location,gross_weight,user_id,note,created_at) VALUES(?,?,?,?,?,?,?,?)',(item_id,'transfer',f"branch:{item['branch_id']}/counter:{item['counter_id']}",f'branch:{branch_id}/counter:{counter_id}',item['gross_weight'],user_id,note,now));audit(conn,user_id,'transfer','item',item_id,{'branch_id':branch_id,'counter_id':counter_id},client_ip);return dict(conn.execute('SELECT * FROM items WHERE id=?',(item_id,)).fetchone())
