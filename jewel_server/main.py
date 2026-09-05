from __future__ import annotations
import argparse,datetime as dt,hashlib,json,os,socket,uuid
from contextlib import asynccontextmanager
from typing import Any
import uvicorn
from fastapi import Body,Depends,FastAPI,HTTPException,Query,Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse,Response
from .backup import BackupWorker,backup_status,create_backup,list_backups,restore_backup,verify_backup
from .company import get_company,save_company
from .db import audit,business_date,business_now,day_is_closed,get_settings,init_db,next_sequence,read_db,request_fingerprint,rowdict,rowsdict,set_setting,utcnow,valid_branch_counter,write_db
from .discovery import DiscoveryResponder
from .pdfs import bulk_label_pdf, credit_note_pdf,invoice_pdf,label_pdf,stock_report_pdf
from .security import VALID_ROLES,clear_login_failures,create_session,current_user,hash_password,login_lock_seconds,password_needs_rehash,record_login_failure,require,verify_password
from .services import _journal,cancel_sale,create_item,latest_rate,money,post_sale,purity_fraction,quote_sale,require_client_request_id,transfer_item,update_item,weight
from .returns import cancel_sale_return,list_returns,post_sale_return,quote_sale_return,return_detail
from .integrity import database_integrity,day_close
from .precision import mg_weight,money_decimal,money_paise,money_sum,paise_money,weight_mg
from .tally import TallySyncWorker,backfill_queue,bridge_health,enqueue_tally,get_mappings,process_pending,reconcile,set_mappings,validate_mappings
from .tls import tls_identity

PRODUCTION_HARDENED_V1 = True
APP_VERSION='1.2.0-rc6'
backup_worker=None;discovery=None;tally_worker=None
@asynccontextmanager
async def lifespan(app):
    global backup_worker,discovery,tally_worker
    init_db(hash_password);backup_worker=BackupWorker();backup_worker.start();tally_worker=TallySyncWorker();tally_worker.start();port=int(os.environ.get('JEWELLAN_PORT','8765'));discovery=DiscoveryResponder(port);discovery.start();yield
    if backup_worker:backup_worker.stop()
    if tally_worker:tally_worker.stop()
    if discovery:discovery.stop()
app=FastAPI(title='JewelLAN Server',version=APP_VERSION,lifespan=lifespan,docs_url='/api/docs' if os.environ.get('JEWELLAN_ENABLE_DOCS')=='1' else None,redoc_url=None)


def _error_code(status_code: int) -> str:
    return {400:'VALIDATION_ERROR',401:'AUTH_REQUIRED',403:'FORBIDDEN',404:'NOT_FOUND',409:'BUSINESS_CONFLICT',428:'PASSWORD_CHANGE_REQUIRED',429:'RATE_LIMITED'}.get(status_code,'INTERNAL_ERROR')


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, dict):
        code = str(detail.get('code') or _error_code(exc.status_code))
        message = str(detail.get('message') or detail.get('detail') or 'Request failed')
        extra = {k:v for k,v in detail.items() if k not in {'code','message','detail'}}
    else:
        code = _error_code(exc.status_code)
        message = str(detail or 'Request failed')
        extra = {}
    request_id = request.headers.get('X-Request-ID') or str(uuid.uuid4())
    error = {'code':code,'message':message,'retryable':code in {'CONNECTIVITY_UNKNOWN','QUOTE_STALE','RATE_LIMITED'},'request_id':request_id,**extra}
    return JSONResponse(status_code=exc.status_code,content={'detail':message,'error':error},headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    request_id = request.headers.get('X-Request-ID') or str(uuid.uuid4())
    error = {'code':'VALIDATION_ERROR','message':'Request validation failed','retryable':False,'request_id':request_id,'fields':exc.errors()}
    return JSONResponse(status_code=422,content={'detail':error['message'],'error':error})
def ip(req):return req.client.host if req.client else 'unknown'

@app.get('/api/health')
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

@app.post('/api/auth/logout')
def logout(u=Depends(current_user)):
    with write_db() as c:c.execute('DELETE FROM sessions WHERE token_hash=?',(u['token_hash'],))
    return {'ok':True}
@app.get('/api/auth/me')
def me(u=Depends(current_user)):return {k:u[k] for k in ('id','username','full_name','role','must_change_password')}
@app.post('/api/auth/change-password')
def change_password(p:dict=Body(...),u=Depends(current_user)):
    new=str(p.get('new_password') or '')
    if len(new)<10:raise HTTPException(400,'New password must be at least 10 characters')
    if new=='Jewel@123':raise HTTPException(400,'Choose a password different from the initial password')
    with write_db() as c:
        r=c.execute('SELECT password_hash FROM users WHERE id=?',(u['id'],)).fetchone()
        if not r or not verify_password(str(p.get('old_password') or ''),r[0]):raise HTTPException(400,'Current password is incorrect')
        c.execute('UPDATE users SET password_hash=?,must_change_password=0,updated_at=? WHERE id=?',(hash_password(new),utcnow(),u['id']));c.execute('DELETE FROM sessions WHERE user_id=? AND token_hash<>?',(u['id'],u['token_hash']));audit(c,u['id'],'change_password','user',u['id'])
    return {'ok':True}

@app.get('/api/dashboard')
def dashboard(u=Depends(require('dashboard'))):
    with read_db() as c:
        today=business_date(c)
        stock=c.execute("SELECT count(*) c,coalesce(sum(gross_mg),0)/1000.0 gw,coalesce(sum(net_mg),0)/1000.0 nw,coalesce(sum(cost_amount_paise),0)/100.0 cost FROM items WHERE status='in_stock'").fetchone();sales=c.execute("SELECT count(*) c,coalesce(sum(total_paise),0) total_paise FROM sales WHERE status='posted' AND business_date=?",(today,)).fetchone();rets=c.execute("SELECT count(*) c,coalesce(sum(total_paise),0) total_paise FROM sale_returns WHERE status='posted' AND business_date=?",(today,)).fetchone();rep=c.execute("SELECT count(*) FROM repairs WHERE status NOT IN ('delivered','cancelled')").fetchone()[0];orders=c.execute("SELECT count(*) FROM orders WHERE status NOT IN ('delivered','cancelled')").fetchone()[0];cats=rowsdict(c.execute("SELECT category,count(*) c FROM items WHERE status='in_stock' GROUP BY category ORDER BY c DESC LIMIT 6").fetchall());rates=rowsdict(c.execute("SELECT r.metal,r.purity,r.rate_per_gram,r.effective_at FROM metal_rates r JOIN (SELECT metal,purity,max(id) id FROM metal_rates GROUP BY metal,purity) x ON x.id=r.id ORDER BY r.metal,r.purity").fetchall())
    return {'business_date':today,'stock':dict(stock),'today_sales':{'c':sales['c'],'total':paise_money(int(sales['total_paise'])-int(rets['total_paise']))},'gross_sales':{'c':sales['c'],'total':paise_money(sales['total_paise'])},'today_returns':{'c':rets['c'],'total':paise_money(rets['total_paise'])},'pending_repairs':rep,'pending_orders':orders,'categories':cats,'rates':rates}
@app.get('/api/settings')
def settings(u=Depends(current_user)):
    with read_db() as c:return {'settings':get_settings(c),'branches':rowsdict(c.execute('SELECT * FROM branches WHERE active=1 ORDER BY name').fetchall()),'counters':rowsdict(c.execute('SELECT * FROM counters WHERE active=1 ORDER BY branch_id,name').fetchall())}
@app.put('/api/settings')
def save_settings(p:dict=Body(...),u=Depends(require('*'))):
    allowed={'business_name','business_address','business_phone','business_email','business_gstin','business_state_code','business_state_name','business_pincode','business_timezone_offset_minutes','currency','invoice_prefix','tag_prefix','gst_default','label_width_mm','label_height_mm','backup_interval_hours','backup_retention_days','tally_enabled','tally_bridge_url','tally_bridge_token','tally_company','tally_auto_create_parties'}
    with write_db() as c:
        for k,v in p.items():
            if k in allowed:set_setting(c,k,str(v))
        audit(c,u['id'],'update','settings',None,p)
    return {'ok':True}

@app.get('/api/company')
def company_settings(u=Depends(current_user)):
    with read_db() as c:return get_company(c)

@app.put('/api/company')
def company_settings_save(p:dict=Body(...),u=Depends(require('*'))):
    try:
        with write_db() as c:return save_company(c,p,u['id'])
    except ValueError as e:raise HTTPException(400,str(e))

@app.get('/api/users')
def users(u=Depends(require('*'))):
    with read_db() as c:return rowsdict(c.execute('SELECT id,username,full_name,role,active,must_change_password,created_at,updated_at FROM users ORDER BY username').fetchall())
@app.post('/api/users')
def add_user(p:dict=Body(...),u=Depends(require('*'))):
    username=str(p.get('username') or '').strip();password=str(p.get('password') or '');role=str(p.get('role') or 'cashier')
    if not username or len(password)<10 or role not in VALID_ROLES:raise HTTPException(400,'Valid username, role and 10+ character temporary password required')
    with write_db() as c:
        try:cur=c.execute('INSERT INTO users(username,password_hash,full_name,role,active,must_change_password,created_at,updated_at) VALUES(?,?,?,?,1,1,?,?)',(username,hash_password(password),p.get('full_name') or username,role,utcnow(),utcnow()))
        except Exception as e:raise HTTPException(409,f'Could not create user: {e}')
        audit(c,u['id'],'create','user',cur.lastrowid,{'username':username,'role':role});return {'id':cur.lastrowid}
@app.put('/api/users/{uid}')
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

@app.get('/api/rates')
def rates(u=Depends(current_user)):
    with read_db() as c:return rowsdict(c.execute('SELECT * FROM metal_rates ORDER BY effective_at DESC,id DESC LIMIT 100').fetchall())
@app.post('/api/rates')
def add_rate(p:dict=Body(...),u=Depends(require('rates'))):
    metal=str(p.get('metal') or '').strip()
    purity=str(p.get('purity') or '').strip()
    if not metal or not purity:
        raise HTTPException(400,'Metal and purity are required')
    if len(metal)>20 or len(purity)>10:
        raise HTTPException(400,'Metal/purity value is too long')
    rate=money(p.get('rate_per_gram'))
    if rate<=0:raise HTTPException(400,'Rate must be positive')
    eff=str(p.get('effective_at') or utcnow()).strip()
    try:
        # Accept both date and datetime ISO strings.
        dt.datetime.fromisoformat(eff.replace('Z','+00:00'))
    except ValueError:
        raise HTTPException(400,'Effective date must be ISO format (YYYY-MM-DD or datetime)')
    with write_db() as c:cur=c.execute('INSERT INTO metal_rates(metal,purity,rate_per_gram,effective_at,created_by,rate_paise_per_gram) VALUES(?,?,?,?,?,?)',(metal,purity,rate,eff,u['id'],money_paise(rate)));audit(c,u['id'],'create','metal_rate',cur.lastrowid,{'metal':metal,'purity':purity,'rate':rate,'effective_at':eff});return {'id':cur.lastrowid}

@app.get('/api/items')
def items(q:str='',status:str='',branch_id:int|None=None,category:str='',limit:int=Query(500,le=2000),u=Depends(require('inventory.read'))):
    w=[];a=[]
    if q:w.append('(tag_no LIKE ? OR barcode LIKE ? OR name LIKE ? OR huid LIKE ? OR certificate_no LIKE ? OR rfid_epc LIKE ?)');a += [f'%{q}%']*6
    if status:w.append('status=?');a.append(status)
    if branch_id:w.append('branch_id=?');a.append(branch_id)
    if category:w.append('category=?');a.append(category)
    a.append(limit);sql='SELECT * FROM items'+(' WHERE '+' AND '.join(w) if w else '')+' ORDER BY id DESC LIMIT ?'
    with read_db() as c:return rowsdict(c.execute(sql,a).fetchall())
@app.get('/api/items/barcode/{code}')
def by_barcode(code:str,branch_id:int|None=None,counter_id:int|None=None,u=Depends(require('inventory.read'))):
    with read_db() as c:
        where='(barcode=? COLLATE NOCASE OR tag_no=? COLLATE NOCASE OR rfid_epc=?)';args=[code,code,code]
        if branch_id is not None:where+=' AND branch_id=?';args.append(branch_id)
        if counter_id is not None:where+=' AND (counter_id IS NULL OR counter_id=?)';args.append(counter_id)
        r=c.execute('SELECT * FROM items WHERE '+where,args).fetchone()
        if not r:raise HTTPException(404,'Tag/barcode not found in the selected branch/counter')
        out=dict(r)
        try:out['current_rate']=latest_rate(c,r['metal'],r['purity'])
        except:out['current_rate']=0
        return out
@app.get('/api/items/{iid}')
def item(iid:int,u=Depends(require('inventory.read'))):
    with read_db() as c:
        r=c.execute('SELECT * FROM items WHERE id=?',(iid,)).fetchone()
        if not r:raise HTTPException(404,'Item not found')
        return {'item':dict(r),'movements':rowsdict(c.execute('SELECT * FROM stock_movements WHERE item_id=? ORDER BY id DESC LIMIT 100',(iid,)).fetchall())}
@app.post('/api/items')
def add_item(req:Request,p:dict=Body(...),u=Depends(require('inventory.write'))):
    with write_db() as c:return create_item(c,p,u,ip(req))

@app.post('/api/opening-stock')
def opening_stock(req:Request,p:dict=Body(...),u=Depends(require('inventory.write'))):
    """Receive initial serialized stock and balance it to opening equity."""
    items = p.get('items') or []
    if not items:
        raise HTTPException(400, 'Opening stock must contain at least one item')
    branch_id = int(p.get('branch_id') or 1)
    counter_id = p.get('counter_id') or None
    counter_id = int(counter_id) if counter_id is not None else None
    with write_db() as c:
        if not valid_branch_counter(c, branch_id, counter_id):
            raise HTTPException(400, detail={'code':'INVALID_LOCATION','message':'The selected branch and counter are not a valid active pairing'})
        if day_is_closed(c, branch_id, business_date(c)):
            raise HTTPException(409, detail={'code':'DAY_CLOSED','message':'Opening stock cannot be posted after day close'})
        created=[]
        total=0.0
        for raw in items:
            data=dict(raw);data.update({'branch_id':branch_id,'counter_id':counter_id,'ref_type':'opening_stock','ref_id':None})
            created.append(create_item(c,data,u,ip(req)))
            total=money(total+money(data.get('cost_amount')))
        journal_id=_journal(c,u['id'],str(p.get('reference') or 'Opening stock'),'opening_stock',None,[('1200',total,0,None,None),('3000',0,total,None,None)])
        audit(c,u['id'],'create','opening_stock',journal_id,{'item_count':len(created),'total':total},ip(req))
        return {'ok':True,'journal_id':journal_id,'item_count':len(created),'total':total,'items':[x['id'] for x in created]}
@app.put('/api/items/{iid}')
def edit_item(iid:int,req:Request,p:dict=Body(...),u=Depends(require('inventory.write'))):
    with write_db() as c:return update_item(c,iid,p,u,ip(req))
@app.post('/api/items/{iid}/transfer')
def move_item(iid:int,req:Request,p:dict=Body(...),u=Depends(require('inventory.write'))):
    with write_db() as c:return transfer_item(c,iid,int(p.get('branch_id') or 1),p.get('counter_id'),u['id'],str(p.get('note') or ''),ip(req))
@app.get('/api/items/{iid}/label.pdf')
def tag_pdf(iid:int,u=Depends(require('inventory.read'))):
    with read_db() as c:
        r=c.execute('SELECT * FROM items WHERE id=?',(iid,)).fetchone()
        if not r:raise HTTPException(404,'Item not found')
        data=label_pdf(dict(r),get_settings(c));name=r['tag_no']
    return Response(data,media_type='application/pdf',headers={'Content-Disposition':f'inline; filename="tag-{name}.pdf"'})
@app.get('/api/items/{iid}/label.zpl')
def tag_zpl(iid:int,u=Depends(require('inventory.read'))):
    from .label_printer import zpl_label as _z
    with read_db() as c:
        r=c.execute('SELECT * FROM items WHERE id=?',(iid,)).fetchone()
        if not r:raise HTTPException(404,'Item not found')
        try:data=_z(dict(r),get_settings(c))
        except ValueError as e:raise HTTPException(400,str(e))
        name=r['tag_no']
    return Response(data,media_type='text/plain',headers={'Content-Disposition':f'attachment; filename="tag-{name}.zpl"'})
@app.get('/api/items/{iid}/label.tspl')
def tag_tspl(iid:int,u=Depends(require('inventory.read'))):
    from .label_printer import tspl_label as _t
    with read_db() as c:
        r=c.execute('SELECT * FROM items WHERE id=?',(iid,)).fetchone()
        if not r:raise HTTPException(404,'Item not found')
        try:data=_t(dict(r),get_settings(c))
        except ValueError as e:raise HTTPException(400,str(e))
        name=r['tag_no']
    return Response(data,media_type='text/plain',headers={'Content-Disposition':f'attachment; filename="tag-{name}.tspl"'})
@app.post('/api/items/labels.pdf')
def bulk_tag_pdf(p:dict=Body(...),u=Depends(require('inventory.read'))):
    """Bulk re-print: one page per tag, max 100. Offline."""
    ids=p.get('item_ids') or p.get('ids') or []
    try:ids=[int(x) for x in ids][:100]
    except Exception:raise HTTPException(400,'item_ids must be numeric (max 100)')
    if not ids:raise HTTPException(400,'Select at least one tag')
    with read_db() as c:
        rows=[]
        for iid in ids:
            r=c.execute('SELECT * FROM items WHERE id=?',(iid,)).fetchone()
            if not r:raise HTTPException(404,f'Item {iid} not found')
            rows.append(dict(r))
        from .pdfs import bulk_label_pdf as _bulk
        data=_bulk(rows,get_settings(c))
    return Response(data,media_type='application/pdf',headers={'Content-Disposition':'inline; filename="tags-bulk.pdf"'})
@app.post('/api/items/labels.zpl')
def bulk_tag_zpl(p:dict=Body(...),u=Depends(require('inventory.read'))):
    ids=p.get('item_ids') or p.get('ids') or []
    try:ids=[int(x) for x in ids][:100]
    except Exception:raise HTTPException(400,'item_ids must be numeric (max 100)')
    if not ids:raise HTTPException(400,'Select at least one tag')
    from .label_printer import bulk_zpl as _bz
    with read_db() as c:
        rows=[]
        for iid in ids:
            r=c.execute('SELECT * FROM items WHERE id=?',(iid,)).fetchone()
            if not r:raise HTTPException(404,f'Item {iid} not found')
            rows.append(dict(r))
        try:data=_bz(rows,get_settings(c))
        except ValueError as e:raise HTTPException(400,str(e))
    return Response(data,media_type='text/plain',headers={'Content-Disposition':'attachment; filename="tags-bulk.zpl"'})
@app.post('/api/items/labels.tspl')
def bulk_tag_tspl(p:dict=Body(...),u=Depends(require('inventory.read'))):
    ids=p.get('item_ids') or p.get('ids') or []
    try:ids=[int(x) for x in ids][:100]
    except Exception:raise HTTPException(400,'item_ids must be numeric (max 100)')
    if not ids:raise HTTPException(400,'Select at least one tag')
    from .label_printer import bulk_tspl as _bt
    with read_db() as c:
        rows=[]
        for iid in ids:
            r=c.execute('SELECT * FROM items WHERE id=?',(iid,)).fetchone()
            if not r:raise HTTPException(404,f'Item {iid} not found')
            rows.append(dict(r))
        try:data=_bt(rows,get_settings(c))
        except ValueError as e:raise HTTPException(400,str(e))
    return Response(data,media_type='text/plain',headers={'Content-Disposition':'attachment; filename="tags-bulk.tspl"'})

def party_list(table,q=''):
    with read_db() as c:
        if q:return rowsdict(c.execute(f'SELECT * FROM {table} WHERE active=1 AND (name LIKE ? OR code LIKE ? OR phone LIKE ?) ORDER BY name LIMIT 500',(f'%{q}%',)*3).fetchall())
        return rowsdict(c.execute(f'SELECT * FROM {table} WHERE active=1 ORDER BY name LIMIT 500').fetchall())
def party_add(c,table,seq,prefix,p,u):
    code=str(p.get('code') or '').strip() or next_sequence(c,seq,prefix,5);now=utcnow()
    if table=='karigars':cur=c.execute('INSERT INTO karigars(code,name,phone,address,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(code,p.get('name'),p.get('phone'),p.get('address'),p.get('notes'),now,now))
    else:
        extra=""
        if table=='customers':
            # offline CRM fields
            cur=c.execute(f'INSERT INTO {table}(code,name,phone,email,address,gstin,birthday,anniversary,loyalty_points,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(code,p.get('name'),p.get('phone'),p.get('email'),p.get('address'),p.get('gstin'),p.get('birthday'),p.get('anniversary'),0,p.get('notes'),now,now))
        else:cur=c.execute(f'INSERT INTO {table}(code,name,phone,email,address,gstin,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',(code,p.get('name'),p.get('phone'),p.get('email'),p.get('address'),p.get('gstin'),p.get('notes'),now,now))
    audit(c,u['id'],'create',table[:-1],cur.lastrowid,{'code':code});return dict(c.execute(f'SELECT * FROM {table} WHERE id=?',(cur.lastrowid,)).fetchone())

def party_update(c,table,pid,p,u):
    row=c.execute(f'SELECT * FROM {table} WHERE id=?',(pid,)).fetchone()
    if not row:raise HTTPException(404,'Party not found')
    now=utcnow()
    if table=='karigars':
        c.execute('UPDATE karigars SET name=?,phone=?,address=?,notes=?,updated_at=? WHERE id=?',(p.get('name',row['name']),p.get('phone',row['phone']),p.get('address',row['address']),p.get('notes',row['notes']),now,pid))
    else:
        # validate birthday/anniversary offline (YYYY-MM-DD or blank)
        for dk in ('birthday','anniversary'):
            if dk in p and p[dk]:
                try:dt.date.fromisoformat(str(p[dk]).strip())
                except ValueError:raise HTTPException(400,f'{dk} must be YYYY-MM-DD or blank')
        if table=='customers':
            c.execute('UPDATE customers SET name=?,phone=?,email=?,address=?,gstin=?,birthday=?,anniversary=?,notes=?,updated_at=? WHERE id=?',(p.get('name',row['name']),p.get('phone',row['phone']),p.get('email',row['email']),p.get('address',row['address']),p.get('gstin',row['gstin']),p.get('birthday',row['birthday']),p.get('anniversary',row['anniversary']),p.get('notes',row['notes']),now,pid))
        else:
            c.execute(f'UPDATE {table} SET name=?,phone=?,email=?,address=?,gstin=?,notes=?,updated_at=? WHERE id=?',(p.get('name',row['name']),p.get('phone',row['phone']),p.get('email',row['email']),p.get('address',row['address']),p.get('gstin',row['gstin']),p.get('notes',row['notes']),now,pid))
    audit(c,u['id'],'update',table[:-1],pid,{k:v for k,v in p.items() if k!='password'})
    return dict(c.execute(f'SELECT * FROM {table} WHERE id=?',(pid,)).fetchone())
@app.get('/api/customers')
def customers(q:str='',u=Depends(require('contacts'))):return party_list('customers',q)
@app.post('/api/customers')
def customer_add(p:dict=Body(...),u=Depends(require('contacts'))):
    if not str(p.get('name') or '').strip():raise HTTPException(400,'Customer name is required')
    with write_db() as c:return party_add(c,'customers','customer','C',p,u)
@app.put('/api/customers/{pid}')
def customer_edit(pid:int,p:dict=Body(...),u=Depends(require('contacts'))):
    with write_db() as c:return party_update(c,'customers',pid,p,u)
@app.get('/api/suppliers')
def suppliers(q:str='',u=Depends(require('contacts'))):return party_list('suppliers',q)
@app.post('/api/suppliers')
def supplier_add(p:dict=Body(...),u=Depends(require('contacts'))):
    if not str(p.get('name') or '').strip():raise HTTPException(400,'Supplier name is required')
    with write_db() as c:return party_add(c,'suppliers','supplier','S',p,u)
@app.put('/api/suppliers/{pid}')
def supplier_edit(pid:int,p:dict=Body(...),u=Depends(require('contacts'))):
    with write_db() as c:return party_update(c,'suppliers',pid,p,u)
@app.get('/api/karigars')
def karigars(q:str='',u=Depends(require('contacts'))):return party_list('karigars',q)
@app.post('/api/karigars')
def karigar_add(p:dict=Body(...),u=Depends(require('contacts'))):
    with write_db() as c:return party_add(c,'karigars','karigar','K',p,u)

@app.post('/api/sales/quote')
def sales_quote(p:dict=Body(...),u=Depends(require('sales'))):
    context={'branch_id':p.get('branch_id'),'counter_id':p.get('counter_id')}
    with read_db() as c:
        if context['branch_id'] not in (None,'') and not valid_branch_counter(c,int(context['branch_id']),int(context['counter_id']) if context['counter_id'] not in (None,'') else None):
            raise HTTPException(400,detail={'code':'INVALID_LOCATION','message':'The selected branch and counter are not a valid active pairing'})
        try:loyal_pts=int(p.get('loyalty_redeem_points') or 0)
        except Exception:loyal_pts=0
        eff_disc=money(money_decimal(p.get('discount',0))+money_decimal(loyal_pts))
        return quote_sale(c,p.get('lines') or [],eff_disc,money_sum(x.get('value',0) for x in p.get('old_gold') or []),context)
@app.post('/api/sales')
def sale(req:Request,p:dict=Body(...),u=Depends(require('sales'))):
    with write_db() as c:return post_sale(c,p,u,ip(req))

@app.get('/api/operations/reconcile/{operation}/{request_id}')
def reconcile_operation(operation: str, request_id: str, u=Depends(current_user)):
    """Resolve a client timeout without guessing whether a financial write committed."""
    operation = operation.strip().lower()
    if not request_id.strip():
        raise HTTPException(400, "Request ID is required")
    queries = {
        "sale": ("SELECT id,invoice_no AS reference,status,total FROM sales WHERE client_request_id=?", "sales"),
        "purchase": ("SELECT id,purchase_no AS reference,status,total FROM purchases WHERE client_request_id=?", "purchases"),
        "sale_return": ("SELECT id,return_no AS reference,status,total_paise/100.0 AS total FROM sale_returns WHERE client_request_id=?", "sale_returns"),
        "return": ("SELECT id,return_no AS reference,status,total_paise/100.0 AS total FROM sale_returns WHERE client_request_id=?", "sale_returns"),
    }
    if operation not in queries:
        raise HTTPException(400, detail={"code": "UNSUPPORTED_OPERATION", "message": "This operation cannot be reconciled"})
    with read_db() as c:
        row = c.execute(queries[operation][0], (request_id,)).fetchone()
    if not row:
        return {"operation": operation, "request_id": request_id, "state": "not_found", "safe_to_retry": True}
    result = dict(row)
    result.update({"operation": operation, "request_id": request_id, "state": "confirmed", "safe_to_retry": False})
    return result

@app.get('/api/sales')
def sales(date_from:str='',date_to:str='',q:str='',limit:int=Query(500,le=2000),u=Depends(require('sales'))):
    w=[];a=[]
    if date_from:w.append('s.business_date>=?');a.append(date_from)
    if date_to:w.append('s.business_date<=?');a.append(date_to)
    if q:w.append('(s.invoice_no LIKE ? OR c.name LIKE ? OR c.phone LIKE ?)');a += [f'%{q}%']*3
    a.append(limit);sql='SELECT s.*,c.name customer_name,c.phone customer_phone,u.full_name user_name FROM sales s LEFT JOIN customers c ON c.id=s.customer_id LEFT JOIN users u ON u.id=s.user_id'+(' WHERE '+' AND '.join(w) if w else '')+' ORDER BY s.id DESC LIMIT ?'
    with read_db() as c:return rowsdict(c.execute(sql,a).fetchall())
@app.get('/api/sales/{sid}')
def sale_detail(sid:int,u=Depends(require('sales'))):
    with read_db() as c:
        s=c.execute('SELECT * FROM sales WHERE id=?',(sid,)).fetchone()
        if not s:raise HTTPException(404,'Sale not found')
        return {'sale':dict(s),'lines':rowsdict(c.execute('SELECT * FROM sale_items WHERE sale_id=?',(sid,)).fetchall()),'customer':rowdict(c.execute('SELECT * FROM customers WHERE id=?',(s['customer_id'],)).fetchone()) if s['customer_id'] else None,'old_gold':rowsdict(c.execute('SELECT * FROM old_gold WHERE sale_id=?',(sid,)).fetchall())}
@app.get('/api/sales/{sid}/invoice.pdf')
def invoice(sid:int,u=Depends(require('sales'))):
    d=sale_detail(sid,u)
    with read_db() as c:data=invoice_pdf(d['sale'],d['lines'],d['customer'],get_settings(c),d['old_gold'])
    return Response(data,media_type='application/pdf',headers={'Content-Disposition':f'inline; filename="{d["sale"]["invoice_no"]}.pdf"'})
@app.post('/api/sales/{sid}/cancel')
def sale_cancel(sid:int,req:Request,p:dict=Body(default={}),u=Depends(require('sales'))):
    if u['role'] not in ('admin','manager'):raise HTTPException(403,'Manager permission required to cancel invoices')
    with write_db() as c:return cancel_sale(c,sid,u,str(p.get('reason') or ''),ip(req))

@app.get('/api/returns')
def returns_list(limit:int=Query(500,le=2000),u=Depends(require('returns'))):
    with read_db() as c:return list_returns(c,limit)
@app.get('/api/returns/{rid}')
def returns_detail(rid:int,u=Depends(require('returns'))):
    with read_db() as c:return return_detail(c,rid)
@app.post('/api/sales/{sid}/return-quote')
def sales_return_quote(sid:int,p:dict=Body(default={}),u=Depends(require('returns'))):
    with read_db() as c:return quote_sale_return(c,sid,p.get('sale_item_ids'))
@app.get('/api/returns/{rid}/credit-note.pdf')
def return_credit_note(rid:int,u=Depends(require('returns'))):
    with read_db() as c:
        d=return_detail(c,rid);customer=None
        if d['return'].get('customer_id'):
            row=c.execute('SELECT * FROM customers WHERE id=?',(d['return']['customer_id'],)).fetchone();customer=dict(row) if row else None
        data=credit_note_pdf(d['return'],d['items'],customer,get_settings(c));name=d['return']['return_no']
    return Response(data,media_type='application/pdf',headers={'Content-Disposition':f'inline; filename="{name}.pdf"'})
@app.post('/api/sales/{sid}/return')
def sales_return(sid:int,req:Request,p:dict=Body(...),u=Depends(require('returns'))):
    with write_db() as c:return post_sale_return(c,sid,p,u,ip(req))
@app.post('/api/returns/{rid}/cancel')
def returns_cancel(rid:int,req:Request,p:dict=Body(default={}),u=Depends(require('returns'))):
    if u['role'] not in ('admin','manager'):raise HTTPException(403,'Manager permission required to cancel credit notes')
    with write_db() as c:return cancel_sale_return(c,rid,u,str(p.get('reason') or ''),ip(req))

@app.post('/api/purchases')
def purchase(p:dict=Body(...),u=Depends(require('purchases'))):
    req=require_client_request_id(p,'purchase')
    fingerprint=request_fingerprint('purchase',p)
    with write_db() as c:
        old=c.execute('SELECT id,purchase_no,total,request_fingerprint FROM purchases WHERE client_request_id=?',(req,)).fetchone()
        if old:
            if old['request_fingerprint'] and old['request_fingerprint'] != fingerprint:
                raise HTTPException(409,detail={'code':'IDEMPOTENCY_CONFLICT','message':'This request ID was already used for different purchase data','request_id':req})
            return dict(old)|{'idempotent':True}
        its=p.get('items') or []
        if not its:raise HTTPException(400,'Purchase must have at least one item')
        no=next_sequence(c,'purchase','PUR-'+business_now(c).strftime('%y%m')+'-',6);now=utcnow();business_day=business_date(c);sid=p.get('supplier_id') or None;bid=int(p.get('branch_id') or 1);counter=p.get('counter_id') or None;counter=int(counter) if counter is not None else None
        if not valid_branch_counter(c,bid,counter):raise HTTPException(400,detail={'code':'INVALID_LOCATION','message':'The selected branch and counter are not a valid active pairing'})
        if day_is_closed(c,bid,business_day):raise HTTPException(409,detail={'code':'DAY_CLOSED','message':'This branch is closed for the current business date'})
        sub=money_sum(x.get('cost_amount',0) for x in its);gst=money(p.get('gst'));total=money(sub+gst);paid=money(p.get('paid'))
        if paid<0 or money_paise(paid)>money_paise(total):raise HTTPException(400,'Paid amount cannot exceed purchase total')
        cur=c.execute('INSERT INTO purchases(purchase_no,client_request_id,request_fingerprint,print_snapshot_json,supplier_id,branch_id,counter_id,business_date,subtotal,gst,total,paid,notes,user_id,created_at,subtotal_paise,gst_paise,total_paise,paid_paise) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(no,req,fingerprint,'{}',sid,bid,counter,business_day,sub,gst,total,paid,p.get('notes'),u['id'],now,money_paise(sub),money_paise(gst),money_paise(total),money_paise(paid)));pid=cur.lastrowid
        refs=p.get('payment_references') if isinstance(p.get('payment_references'),dict) else {}
        if paid:
            c.execute("INSERT INTO payments(transaction_type,transaction_id,method,direction,amount_paise,reference,account_code,paid_at,actor_id) VALUES('purchase',?,?,?,?,?,?,?,?)",(pid,'cash','out',money_paise(paid),refs.get('cash'),'1000',now,u['id']))
        for x in its:
            x=dict(x);x.update({'branch_id':bid,'supplier_id':sid,'ref_type':'purchase','ref_id':pid});it=create_item(c,x,u);c.execute('INSERT INTO purchase_items(purchase_id,item_id,cost_amount,gst_amount,cost_amount_paise,gst_amount_paise) VALUES(?,?,?,0,?,0)',(pid,it['id'],it['cost_amount'],money_paise(it['cost_amount'])))
        payable=money(total-paid)
        if sid and payable:
            row=c.execute('SELECT balance_paise FROM suppliers WHERE id=?',(sid,)).fetchone();newp=int(row['balance_paise'] or 0)+money_paise(payable);c.execute('UPDATE suppliers SET balance=?,balance_paise=?,updated_at=? WHERE id=?',(paise_money(newp),newp,now,sid))
        je=next_sequence(c,'journal','JE',7);j=c.execute('INSERT INTO journal_entries(entry_no,entry_date,memo,ref_type,ref_id,user_id,created_at) VALUES(?,?,?,?,?,?,?)',(je,business_day,f'Purchase {no}','purchase',pid,u['id'],now)).lastrowid;lines=[('1200',sub,0,None,None)]
        if gst:lines.append(('2110',gst,0,None,None))
        if paid:lines.append(('1000',0,paid,None,None))
        if payable:lines.append(('2000',0,payable,'supplier',sid))
        for code,dr,cr,pt,party in lines:c.execute('INSERT INTO journal_lines(entry_id,account_code,debit,credit,party_type,party_id,debit_paise,credit_paise) VALUES(?,?,?,?,?,?,?,?)',(j,code,dr,cr,pt,party,money_paise(dr),money_paise(cr)))
        audit(c,u['id'],'create','purchase',pid,{'purchase_no':no,'total':total});enqueue_tally(c,'purchase',pid,'create');return {'id':pid,'purchase_no':no,'total':total}

@app.get('/api/purchases')
def purchases(u=Depends(require('purchases'))):
    with read_db() as c:return rowsdict(c.execute('SELECT p.*,s.name supplier_name FROM purchases p LEFT JOIN suppliers s ON s.id=p.supplier_id ORDER BY p.id DESC LIMIT 500').fetchall())

@app.get('/api/estimations')
def estimations_list(limit:int=Query(200,le=1000),u=Depends(require('sales'))):
    with read_db() as c:return rowsdict(c.execute('SELECT e.*,cu.name customer_name FROM estimations e LEFT JOIN customers cu ON cu.id=e.customer_id ORDER BY e.id DESC LIMIT ?',(limit,)).fetchall())
@app.get('/api/estimations/{eid}')
def estimation_detail(eid:int,u=Depends(require('sales'))):
    with read_db() as c:
        e=c.execute('SELECT * FROM estimations WHERE id=?',(eid,)).fetchone()
        if not e:raise HTTPException(404,'Estimation not found')
        items=rowsdict(c.execute('SELECT * FROM estimation_items WHERE estimation_id=? ORDER BY id',(eid,)).fetchall())
        return {'estimation':dict(e),'items':items}
@app.post('/api/estimations')
def estimation_create(p:dict=Body(...),u=Depends(require('sales'))):
    """Offline estimation: server-priced quote saved without touching stock."""
    from .services import quote_sale as _quote
    lines=p.get('lines') or []
    if not lines:raise HTTPException(400,'Estimation must contain at least one tag')
    bid=int(p.get('branch_id') or 1);counter=p.get('counter_id') or None;counter=int(counter) if counter is not None else None
    ctx={'branch_id':bid,'counter_id':counter}
    with write_db() as c:
        if not valid_branch_counter(c,bid,counter):raise HTTPException(400,'Invalid branch/counter')
        q=_quote(c,lines,p.get('discount',0),0,ctx)
        no=next_sequence(c,'estimation','EST-',6);now=utcnow();cid=p.get('customer_id') or None
        cur=c.execute('INSERT INTO estimations(est_no,customer_id,branch_id,counter_id,subtotal_paise,discount_paise,taxable_paise,gst_paise,total_paise,status,notes,user_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?, ?,?)',(no,cid,bid,counter,money_paise(q['subtotal']),money_paise(q['discount']),money_paise(q['taxable']),money_paise(q['gst']),money_paise(q['total']),'open',p.get('notes'),u['id'],now))
        eid=cur.lastrowid
        for l in q['lines']:
            c.execute('INSERT INTO estimation_items(estimation_id,item_id,tag_no,description,metal,purity,gross_weight,net_weight,metal_rate,metal_value,wastage_value,making_charge,stone_value,discount,taxable,gst_rate,gst_amount,line_total) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(eid,l['item_id'],l['tag_no'],l['description'],l['metal'],l['purity'],l['gross_weight'],l['net_weight'],l['metal_rate'],l['metal_value'],l['wastage_value'],l['making_charge'],l['stone_value'],l['discount'],l['taxable'],l['gst_rate'],l['gst_amount'],l['line_total']))
        audit(c,u['id'],'create','estimation',eid,{'est_no':no,'total':q['total']})
        return {'id':eid,'est_no':no,'total':q['total'],'quote':q}
@app.get('/api/estimations/{eid}/estimation.pdf')
def estimation_pdf_route(eid:int,u=Depends(require('sales'))):
    from .pdfs import estimation_pdf as _epdf
    with read_db() as c:
        e=c.execute('SELECT * FROM estimations WHERE id=?',(eid,)).fetchone()
        if not e:raise HTTPException(404,'Estimation not found')
        items=rowsdict(c.execute('SELECT * FROM estimation_items WHERE estimation_id=?',(eid,)).fetchall())
        cust=None
        if e['customer_id']:cust=rowdict(c.execute('SELECT * FROM customers WHERE id=?',(e['customer_id'],)).fetchone())
        data=_epdf(dict(e),items,cust,get_settings(c))
    return Response(data,media_type='application/pdf',headers={'Content-Disposition':f'inline; filename="EST-{eid}.pdf"'})
@app.post('/api/estimations/{eid}/cancel')
def estimation_cancel(eid:int,u=Depends(require('sales'))):
    with write_db() as c:
        e=c.execute('SELECT * FROM estimations WHERE id=?',(eid,)).fetchone()
        if not e:raise HTTPException(404,'Estimation not found')
        c.execute("UPDATE estimations SET status='cancelled' WHERE id=?",(eid,));audit(c,u['id'],'cancel','estimation',eid,{})
        return {'ok':True}

# ---- Offline chit schemes + gold loans (local ledgers, no internet) ----
@app.get('/api/chit-schemes')
def chit_schemes(u=Depends(require('contacts'))):
    with read_db() as c:return rowsdict(c.execute('SELECT * FROM chit_schemes ORDER BY id DESC').fetchall())
@app.post('/api/chit-schemes')
def chit_scheme_add(p:dict=Body(...),u=Depends(require('contacts'))):
    name=str(p.get('name') or '').strip()
    if not name:raise HTTPException(400,'Scheme name is required')
    try:tenure=int(p.get('tenure_months') or 11);amt=money(p.get('monthly_amount',0))
    except Exception:raise HTTPException(400,'Tenure and amount must be numeric')
    if tenure<=0 or amt<=0:raise HTTPException(400,'Tenure and monthly amount must be positive')
    with write_db() as c:
        code=str(p.get('code') or '').strip() or next_sequence(c,'chit','CHIT-',4)
        cur=c.execute('INSERT INTO chit_schemes(code,name,metal,tenure_months,monthly_amount_paise,target_weight_mg,making_discount_percent,active,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(code,name,str(p.get('metal') or 'Gold'),tenure,money_paise(amt),weight_mg(p.get('target_weight',0)),float(p.get('making_discount_percent') or 0),1,utcnow()))
        audit(c,u['id'],'create','chit_scheme',cur.lastrowid,{'name':name});return {'id':cur.lastrowid,'code':code}
@app.get('/api/chit-members')
def chit_members(scheme_id:int|None=None,u=Depends(require('contacts'))):
    with read_db() as c:
        if scheme_id:return rowsdict(c.execute('SELECT m.*,cu.name customer_name,s.name scheme_name FROM chit_members m JOIN customers cu ON cu.id=m.customer_id JOIN chit_schemes s ON s.id=m.scheme_id WHERE m.scheme_id=? ORDER BY m.id DESC',(scheme_id,)).fetchall())
        return rowsdict(c.execute('SELECT m.*,cu.name customer_name,s.name scheme_name FROM chit_members m JOIN customers cu ON cu.id=m.customer_id JOIN chit_schemes s ON s.id=m.scheme_id ORDER BY m.id DESC LIMIT 500').fetchall())
@app.post('/api/chit-members')
def chit_member_add(p:dict=Body(...),u=Depends(require('contacts'))):
    try:sid=int(p.get('scheme_id'));cid=int(p.get('customer_id'))
    except Exception:raise HTTPException(400,'Scheme and customer are required')
    with write_db() as c:
        if not c.execute('SELECT id FROM chit_schemes WHERE id=?',(sid,)).fetchone():raise HTTPException(400,'Scheme not found')
        if not c.execute('SELECT id FROM customers WHERE id=?',(cid,)).fetchone():raise HTTPException(400,'Customer not found')
        try:cur=c.execute('INSERT INTO chit_members(scheme_id,customer_id,start_date,status,total_paid_paise,created_at) VALUES(?,?,?,\"active\",0,?)',(sid,cid,str(p.get('start_date') or business_date(c)),utcnow()))
        except Exception:raise HTTPException(409,'Customer already enrolled for that start date')
        audit(c,u['id'],'create','chit_member',cur.lastrowid,{});return {'id':cur.lastrowid}
@app.post('/api/chit-members/{mid}/pay')
def chit_pay(mid:int,p:dict=Body(...),u=Depends(require('contacts'))):
    try:amt=money(p.get('amount',0))
    except Exception:raise HTTPException(400,'Amount must be numeric')
    if amt<=0:raise HTTPException(400,'Amount must be positive')
    with write_db() as c:
        m=c.execute('SELECT * FROM chit_members WHERE id=?',(mid,)).fetchone()
        if not m:raise HTTPException(404,'Member not found')
        if m['status']!='active':raise HTTPException(409,'Only active members can pay')
        c.execute('INSERT INTO chit_payments(member_id,amount_paise,method,paid_on,user_id,created_at) VALUES(?,?,?,?,?,?)',(mid,money_paise(amt),str(p.get('method') or 'cash'),str(p.get('paid_on') or business_date(c)),u['id'],utcnow()))
        c.execute('UPDATE chit_members SET total_paid_paise=total_paid_paise+? WHERE id=?',(money_paise(amt),mid))
        audit(c,u['id'],'create','chit_payment',mid,{'amount':amt});return {'ok':True}
@app.get('/api/gold-loans')
def gold_loans(status:str='',u=Depends(require('contacts'))):
    with read_db() as c:
        if status:return rowsdict(c.execute('SELECT g.*,cu.name customer_name FROM gold_loans g JOIN customers cu ON cu.id=g.customer_id WHERE g.status=? ORDER BY g.id DESC LIMIT 500',(status,)).fetchall())
        return rowsdict(c.execute('SELECT g.*,cu.name customer_name FROM gold_loans g JOIN customers cu ON cu.id=g.customer_id ORDER BY g.id DESC LIMIT 500').fetchall())
@app.post('/api/gold-loans')
def gold_loan_add(p:dict=Body(...),u=Depends(require('contacts'))):
    try:cid=int(p.get('customer_id'));gw=weight(p.get('gross_weight',0));nw=weight(p.get('net_weight',0));amt=money(p.get('loan_amount',0));rate=float(p.get('interest_monthly_percent') or 2.0)
    except Exception:raise HTTPException(400,'Loan fields must be numeric')
    if gw<=0 or nw<=0 or amt<=0:raise HTTPException(400,'Weights and loan amount must be positive')
    if not 0<=rate<=10:raise HTTPException(400,'Monthly interest must be 0-10%')
    with write_db() as c:
        if not c.execute('SELECT id FROM customers WHERE id=?',(cid,)).fetchone():raise HTTPException(400,'Customer not found')
        no=next_sequence(c,'goldloan','GL-',6)
        cur=c.execute('INSERT INTO gold_loans(loan_no,customer_id,gross_weight,net_weight,purity,loan_amount_paise,interest_monthly_percent,status,issued_on,due_on,notes,user_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(no,cid,gw,nw,str(p.get('purity') or '916'),money_paise(amt),rate,'open',str(p.get('issued_on') or business_date(c)),p.get('due_on'),p.get('notes'),u['id'],utcnow()))
        audit(c,u['id'],'create','gold_loan',cur.lastrowid,{'loan_no':no});return {'id':cur.lastrowid,'loan_no':no}
@app.post('/api/gold-loans/{lid}/pay')
def gold_loan_pay(lid:int,p:dict=Body(...),u=Depends(require('contacts'))):
    try:amt=money(p.get('amount',0))
    except Exception:raise HTTPException(400,'Amount must be numeric')
    if amt<=0:raise HTTPException(400,'Amount must be positive')
    kind=str(p.get('kind') or 'interest')
    if kind not in ('interest','principal','closure'):raise HTTPException(400,'Invalid payment kind')
    with write_db() as c:
        g=c.execute('SELECT * FROM gold_loans WHERE id=?',(lid,)).fetchone()
        if not g:raise HTTPException(404,'Loan not found')
        if g['status']!='open':raise HTTPException(409,'Only open loans accept payments')
        c.execute('INSERT INTO gold_loan_payments(loan_id,amount_paise,kind,paid_on,user_id,created_at) VALUES(?,?,?,?,?,?)',(lid,money_paise(amt),kind,str(p.get('paid_on') or business_date(c)),u['id'],utcnow()))
        if kind=='closure':c.execute("UPDATE gold_loans SET status='closed',closed_on=? WHERE id=?",(str(p.get('paid_on') or business_date(c)),lid))
        audit(c,u['id'],'create','gold_loan_payment',lid,{'amount':amt,'kind':kind});return {'ok':True}

def wf_list(table):
    with read_db() as c:
        sql='SELECT r.*,c.name customer_name,k.name karigar_name FROM repairs r LEFT JOIN customers c ON c.id=r.customer_id LEFT JOIN karigars k ON k.id=r.karigar_id ORDER BY r.id DESC LIMIT 500' if table=='repairs' else 'SELECT o.*,c.name customer_name,k.name karigar_name FROM orders o LEFT JOIN customers c ON c.id=o.customer_id LEFT JOIN karigars k ON k.id=o.karigar_id ORDER BY o.id DESC LIMIT 500';return rowsdict(c.execute(sql).fetchall())
@app.get('/api/repairs')
def repairs(u=Depends(require('repairs'))):return wf_list('repairs')
@app.post('/api/repairs')
def repair_add(p:dict=Body(...),u=Depends(require('repairs'))):
    desc=str(p.get('item_description') or '').strip()
    if not desc:raise HTTPException(400,'Repair description is required')
    cid=p.get('customer_id');kid=p.get('karigar_id')
    try:
        gw=weight(p.get('gross_weight',0));est=money(p.get('estimated_amount',0));adv=money(p.get('advance',0))
    except Exception:raise HTTPException(400,'Repair weights and amounts must be numeric')
    if gw<0 or est<0 or adv<0:raise HTTPException(400,'Repair weights and amounts cannot be negative')
    status=str(p.get('status') or 'received')
    if status not in ('received','assigned','in_progress','ready','delivered','cancelled'):raise HTTPException(400,'Invalid repair status')
    promised=p.get('promised_on')
    if promised:
        try:dt.date.fromisoformat(str(promised))
        except ValueError:raise HTTPException(400,'Promised date must be YYYY-MM-DD')
    with write_db() as c:
        if cid and not c.execute('SELECT id FROM customers WHERE id=? AND active=1',(cid,)).fetchone():raise HTTPException(400,'Selected customer does not exist')
        if kid and not c.execute('SELECT id FROM karigars WHERE id=? AND active=1',(kid,)).fetchone():raise HTTPException(400,'Selected karigar does not exist')
        no=next_sequence(c,'repair','REP-',6);now=utcnow();cur=c.execute('INSERT INTO repairs(repair_no,customer_id,item_description,tag_no,gross_weight,received_on,promised_on,status,karigar_id,estimated_amount,advance,final_amount,notes,created_by,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(no,cid,desc,p.get('tag_no'),gw,p.get('received_on') or business_date(c),promised,status,kid,est,adv,0,p.get('notes'),u['id'],now));return {'id':cur.lastrowid,'repair_no':no}
@app.put('/api/repairs/{rid}')
def repair_edit(rid:int,p:dict=Body(...),u=Depends(require('repairs'))):
    with write_db() as c:r=c.execute('SELECT * FROM repairs WHERE id=?',(rid,)).fetchone();
    if not r:raise HTTPException(404,'Repair not found')
    status=str(p.get('status',r['status']))
    if status not in ('received','assigned','in_progress','ready','delivered','cancelled'):raise HTTPException(400,'Invalid repair status')
    kid=p.get('karigar_id',r['karigar_id'])
    if kid and not c.execute('SELECT id FROM karigars WHERE id=? AND active=1',(kid,)).fetchone():raise HTTPException(400,'Selected karigar does not exist')
    with write_db() as c:c.execute('UPDATE repairs SET status=?,karigar_id=?,promised_on=?,estimated_amount=?,advance=?,final_amount=?,notes=?,updated_at=? WHERE id=?',(status,kid,p.get('promised_on',r['promised_on']),money(p.get('estimated_amount',r['estimated_amount'])),money(p.get('advance',r['advance'])),money(p.get('final_amount',r['final_amount'])),p.get('notes',r['notes']),utcnow(),rid));return {'ok':True}
@app.get('/api/orders')
def orders(u=Depends(require('orders'))):return wf_list('orders')
@app.post('/api/orders')
def order_add(p:dict=Body(...),u=Depends(require('orders'))):
    desc=str(p.get('description') or '').strip()
    if not desc:raise HTTPException(400,'Order description is required')
    cid=p.get('customer_id');kid=p.get('karigar_id')
    try:
        tw=weight(p.get('target_weight',0));est=money(p.get('estimated_amount',0));adv=money(p.get('advance',0))
    except Exception:raise HTTPException(400,'Order weights and amounts must be numeric')
    if tw<0 or est<0 or adv<0:raise HTTPException(400,'Order weights and amounts cannot be negative')
    status=str(p.get('status') or 'new')
    if status not in ('new','assigned','in_progress','ready','delivered','cancelled'):raise HTTPException(400,'Invalid order status')
    due=p.get('due_date')
    if due:
        try:dt.date.fromisoformat(str(due))
        except ValueError:raise HTTPException(400,'Due date must be YYYY-MM-DD')
    with write_db() as c:
        if cid and not c.execute('SELECT id FROM customers WHERE id=? AND active=1',(cid,)).fetchone():raise HTTPException(400,'Selected customer does not exist')
        if kid and not c.execute('SELECT id FROM karigars WHERE id=? AND active=1',(kid,)).fetchone():raise HTTPException(400,'Selected karigar does not exist')
        no=next_sequence(c,'order','ORD-',6);now=utcnow();cur=c.execute('INSERT INTO orders(order_no,customer_id,description,metal,purity,target_weight,karigar_id,status,estimated_amount,advance,due_date,notes,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(no,cid,desc,p.get('metal') or 'Gold',p.get('purity') or '916',tw,kid,status,est,adv,due,p.get('notes'),u['id'],now,now));return {'id':cur.lastrowid,'order_no':no}
@app.put('/api/orders/{oid}')
def order_edit(oid:int,p:dict=Body(...),u=Depends(require('orders'))):
    with read_db() as c:r=c.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone()
    if not r:raise HTTPException(404,'Order not found')
    status=str(p.get('status',r['status']))
    if status not in ('new','assigned','in_progress','ready','delivered','cancelled'):raise HTTPException(400,'Invalid order status')
    with write_db() as c:
        kid=p.get('karigar_id',r['karigar_id'])
        if kid and not c.execute('SELECT id FROM karigars WHERE id=? AND active=1',(kid,)).fetchone():raise HTTPException(400,'Selected karigar does not exist')
        c.execute('UPDATE orders SET status=?,karigar_id=?,due_date=?,estimated_amount=?,advance=?,notes=?,updated_at=? WHERE id=?',(status,kid,p.get('due_date',r['due_date']),money(p.get('estimated_amount',r['estimated_amount'])),money(p.get('advance',r['advance'])),p.get('notes',r['notes']),utcnow(),oid));return {'ok':True}

@app.get('/api/karigars/{kid}/ledger')
def kledger(kid:int,u=Depends(require('contacts'))):
    with read_db() as c:return rowsdict(c.execute('SELECT * FROM karigar_ledger WHERE karigar_id=? ORDER BY id DESC LIMIT 500',(kid,)).fetchall())
@app.post('/api/karigars/{kid}/ledger')
def kledger_add(kid:int,p:dict=Body(...),u=Depends(require('contacts'))):
    typ=str(p.get('entry_type') or 'adjustment')
    if typ not in ('metal_issue','metal_receive','cash_debit','cash_credit','making_charge','adjustment'):
        raise HTTPException(400,'Invalid karigar ledger entry type')
    try:wt=weight(p.get('weight',0));amt=money(p.get('amount',0))
    except Exception:raise HTTPException(400,'Karigar weight and amount must be numeric')
    if wt<0 or amt<0:raise HTTPException(400,'Karigar weight and amount cannot be negative')
    with write_db() as c:
        if not c.execute('SELECT id FROM karigars WHERE id=?',(kid,)).fetchone():raise HTTPException(404,'Karigar not found')
        cur=c.execute('INSERT INTO karigar_ledger(karigar_id,entry_type,metal,weight,amount,ref_type,ref_id,note,user_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(kid,typ,p.get('metal'),wt,amt,p.get('ref_type'),p.get('ref_id'),p.get('note'),u['id'],utcnow()));md=wt if typ=='metal_issue' else -wt if typ=='metal_receive' else 0;cd=amt if typ in ('cash_debit','making_charge') else -amt if typ=='cash_credit' else 0;row=c.execute('SELECT metal_balance_mg,cash_balance_paise FROM karigars WHERE id=?',(kid,)).fetchone();newmg=int(row['metal_balance_mg'] or 0)+int(round(md*1000));newp=int(row['cash_balance_paise'] or 0)+money_paise(cd);c.execute('UPDATE karigars SET metal_balance_grams=?,metal_balance_mg=?,cash_balance=?,cash_balance_paise=?,updated_at=? WHERE id=?',(mg_weight(newmg),newmg,paise_money(newp),newp,utcnow(),kid));return {'id':cur.lastrowid}

@app.get('/api/approvals')
def approvals(u=Depends(require('approvals'))):
    with read_db() as c:return rowsdict(c.execute('SELECT a.*,count(ai.id) item_count FROM approvals a LEFT JOIN approval_items ai ON ai.approval_id=a.id GROUP BY a.id ORDER BY a.id DESC LIMIT 500').fetchall())
@app.post('/api/approvals')
def approval_add(p:dict=Body(...),u=Depends(require('approvals'))):
    ids=[int(x) for x in p.get('item_ids') or []]
    if not ids:raise HTTPException(400,'Select at least one item')
    with write_db() as c:
        no=next_sequence(c,'approval','JNG-',6);now=utcnow();aid=c.execute("INSERT INTO approvals(approval_no,party_name,party_phone,issued_at,due_at,status,note,user_id) VALUES(?,?,?,?,?,'open',?,?)",(no,p.get('party_name') or 'Party',p.get('party_phone'),now,p.get('due_at'),p.get('note'),u['id'])).lastrowid
        for iid in ids:
            it=c.execute("SELECT * FROM items WHERE id=? AND status='in_stock'",(iid,)).fetchone()
            if not it:raise HTTPException(409,f'Item {iid} not available')
            c.execute("UPDATE items SET status='approval',version=version+1,updated_at=? WHERE id=?",(now,iid));c.execute("INSERT INTO approval_items(approval_id,item_id,status) VALUES(?,?,'out')",(aid,iid));c.execute('INSERT INTO stock_movements(item_id,movement_type,ref_type,ref_id,from_location,to_location,gross_weight,user_id,note,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(iid,'approval_out','approval',aid,f"branch:{it['branch_id']}",p.get('party_name'),it['gross_weight'],u['id'],no,now))
        return {'id':aid,'approval_no':no}
@app.post('/api/approvals/{aid}/return/{iid}')
def approval_return(aid:int,iid:int,u=Depends(require('approvals'))):
    with write_db() as c:
        ai=c.execute("SELECT * FROM approval_items WHERE approval_id=? AND item_id=? AND status='out'",(aid,iid)).fetchone()
        if not ai:raise HTTPException(409,'Item not outstanding on approval')
        now=utcnow();c.execute("UPDATE approval_items SET status='returned',returned_at=? WHERE id=?",(now,ai['id']));c.execute("UPDATE items SET status='in_stock',version=version+1,updated_at=? WHERE id=?",(now,iid));n=c.execute("SELECT count(*) FROM approval_items WHERE approval_id=? AND status='out'",(aid,)).fetchone()[0];c.execute('UPDATE approvals SET status=? WHERE id=?',('closed' if n==0 else 'partial',aid));return {'ok':True}

@app.post('/api/stock-audits')
def audit_start(p:dict=Body(...),u=Depends(require('audit'))):
    bid=int(p.get('branch_id') or 1);counter=p.get('counter_id') or None;counter=int(counter) if counter is not None else None
    with write_db() as c:
        if not valid_branch_counter(c,bid,counter):raise HTTPException(400,detail={'code':'INVALID_LOCATION','message':'The selected branch and counter are not a valid active pairing'})
        no=next_sequence(c,'audit','AUD-',6);started=utcnow();max_move=int(c.execute("SELECT coalesce(max(sm.id),0) FROM stock_movements sm JOIN items i ON i.id=sm.item_id WHERE i.branch_id=?",(bid,)).fetchone()[0])
        cur=c.execute("INSERT INTO stock_audits(audit_no,branch_id,counter_id,status,started_by,started_at,snapshot_at,snapshot_movement_id) VALUES(?,?,?,'open',?,?,?,?)",(no,bid,counter,u['id'],started,started,max_move));aid=cur.lastrowid
        where="i.status='in_stock' AND i.branch_id=?";params=[bid]
        if counter is not None:where += ' AND i.counter_id=?';params.append(counter)
        rows=c.execute(f"SELECT i.id,i.version,i.status FROM items i WHERE {where}",params).fetchall()
        c.executemany("INSERT INTO stock_audit_expected(audit_id,item_id,version_at_start,status_at_start) VALUES(?,?,?,?)",[(aid,int(r['id']),int(r['version']),str(r['status'])) for r in rows])
        return {'id':aid,'audit_no':no,'expected_count':len(rows),'snapshot_movement_id':max_move}
@app.get('/api/stock-audits')
def audit_list(u=Depends(require('audit'))):
    with read_db() as c:return rowsdict(c.execute('SELECT * FROM stock_audits ORDER BY id DESC LIMIT 100').fetchall())
@app.post('/api/stock-audits/{aid}/scan')
def audit_scan(aid:int,p:dict=Body(...),u=Depends(require('audit'))):
    code=str(p.get('barcode') or '').strip()
    with write_db() as c:
        if not c.execute("SELECT id FROM stock_audits WHERE id=? AND status='open'",(aid,)).fetchone():raise HTTPException(409,'Audit is not open')
        it=c.execute('SELECT * FROM items WHERE barcode=? COLLATE NOCASE OR tag_no=? COLLATE NOCASE OR rfid_epc=?',(code,code,code)).fetchone()
        if not it:raise HTTPException(404,'Tag not found')
        try:c.execute('INSERT INTO stock_audit_scans(audit_id,item_id,scanned_by,scanned_at) VALUES(?,?,?,?)',(aid,it['id'],u['id'],utcnow()));new=True
        except:new=False
        return {'item':dict(it),'new':new}

def _audit_calc_conn(c,aid):
    a=c.execute('SELECT * FROM stock_audits WHERE id=?',(aid,)).fetchone()
    if not a:raise HTTPException(404,'Audit not found')
    exp=rowsdict(c.execute('SELECT i.* FROM stock_audit_expected e JOIN items i ON i.id=e.item_id WHERE e.audit_id=? ORDER BY i.tag_no',(aid,)).fetchall())
    if not exp:
        params=[a['branch_id']];where="i.status='in_stock' AND i.branch_id=?"
        if a['counter_id'] is not None:where+=' AND i.counter_id=?';params.append(a['counter_id'])
        exp=rowsdict(c.execute(f'SELECT i.* FROM items i WHERE {where} ORDER BY i.tag_no',params).fetchall())
    scan=rowsdict(c.execute('SELECT i.* FROM stock_audit_scans s JOIN items i ON i.id=s.item_id WHERE s.audit_id=? ORDER BY s.id',(aid,)).fetchall());ei={x['id'] for x in exp};si={x['id'] for x in scan}
    movement_conflicts=[]
    snap=int(a['snapshot_movement_id'] or 0)
    if snap:
        branch_marker=f"branch:{a['branch_id']}%"
        movement_conflicts=rowsdict(c.execute("""SELECT sm.id,sm.item_id,sm.movement_type,sm.ref_type,sm.ref_id,sm.created_at,i.tag_no
            FROM stock_movements sm LEFT JOIN items i ON i.id=sm.item_id
            WHERE sm.id>? AND (
              EXISTS(SELECT 1 FROM stock_audit_expected e WHERE e.audit_id=? AND e.item_id=sm.item_id)
              OR sm.from_location LIKE ? OR sm.to_location LIKE ?
            ) ORDER BY sm.id LIMIT 200""",(snap,aid,branch_marker,branch_marker)).fetchall())
    version_conflicts=rowsdict(c.execute("""SELECT i.id item_id,i.tag_no,e.version_at_start,i.version current_version,e.status_at_start,i.status current_status,i.branch_id,i.counter_id
        FROM stock_audit_expected e JOIN items i ON i.id=e.item_id
        WHERE e.audit_id=? AND (
          i.version<>e.version_at_start OR i.status<>e.status_at_start OR i.branch_id<>? OR
          (? IS NOT NULL AND coalesce(i.counter_id,-1)<>?)
        ) ORDER BY i.id LIMIT 200""",(aid,a['branch_id'],a['counter_id'],a['counter_id'])).fetchall())
    return {'audit':dict(a),'expected_count':len(exp),'scanned_count':len(scan),'missing':[x for x in exp if x['id'] not in si],'extra':[x for x in scan if x['id'] not in ei],'movement_conflicts':movement_conflicts,'version_conflicts':version_conflicts}

def audit_calc(aid):
    with read_db() as c:return _audit_calc_conn(c,aid)
@app.get('/api/stock-audits/{aid}/result')
def audit_result(aid:int,u=Depends(require('audit'))):return audit_calc(aid)
@app.post('/api/stock-audits/{aid}/close')
def audit_close(aid:int,p:dict=Body(default={}),u=Depends(require('audit'))):
    force=bool(p.get('resolve_movements'))
    if force and u['role'] not in ('admin','manager'):raise HTTPException(403,'Manager permission required to resolve audit movement conflicts')
    if force and len(str(p.get('reason') or '').strip())<3:raise HTTPException(400,'A reason is required to resolve audit movement conflicts')
    with write_db() as c:
        row=c.execute("SELECT id,status FROM stock_audits WHERE id=?",(aid,)).fetchone()
        if not row:raise HTTPException(404,'Audit not found')
        result=_audit_calc_conn(c,aid)
        if row['status']=='closed':return result
        conflicts=(result.get('movement_conflicts') or [])+(result.get('version_conflicts') or [])
        if conflicts and not force:raise HTTPException(409,detail={'code':'AUDIT_MOVEMENT_CONFLICT','message':'Stock changed after this audit snapshot; review or explicitly resolve before closing','conflicts':conflicts})
        c.execute("UPDATE stock_audits SET status='closed',closed_at=? WHERE id=?",(utcnow(),aid));audit(c,u['id'],'close','stock_audit',aid,{'resolve_movements':force,'reason':str(p.get('reason') or ''),'conflict_count':len(conflicts)})
        return _audit_calc_conn(c,aid)

@app.get('/api/tally/status')
def tally_status(u=Depends(require('reports'))):
    with read_db() as c:
        s=get_settings(c);m=get_mappings(c);q={r['status']:r['c'] for r in c.execute("SELECT status,count(*) c FROM tally_sync_queue GROUP BY status").fetchall()}
    out={'enabled':s.get('tally_enabled','0'),'bridge_url':s.get('tally_bridge_url',''),'company':s.get('tally_company',''),'business_state_code':s.get('business_state_code',''),'auto_create_parties':s.get('tally_auto_create_parties','1'),'mappings':m,'queue':q,'bridge':None}
    if str(s.get('tally_enabled','0')).lower() in ('1','true','yes','on'):
        try:out['bridge']=bridge_health(s)
        except Exception as e:out['bridge']={'ok':False,'error':str(e)}
    return out
@app.put('/api/tally/settings')
def tally_settings(p:dict=Body(...),u=Depends(require('*'))):
    allowed={'tally_enabled','tally_bridge_url','tally_bridge_token','tally_company','tally_auto_create_parties','business_state_code'}
    with write_db() as c:
        for k,v in p.items():
            if k in allowed:set_setting(c,k,str(v))
        audit(c,u['id'],'update','tally_settings',None,{k:('***' if k=='tally_bridge_token' else v) for k,v in p.items() if k in allowed})
    if tally_worker:tally_worker.wake()
    return {'ok':True}
@app.get('/api/tally/mappings')
def tally_mappings(u=Depends(require('reports'))):
    with read_db() as c:return get_mappings(c)
@app.put('/api/tally/mappings')
def tally_mappings_save(p:dict=Body(...),u=Depends(require('*'))):
    try:
        with write_db() as c:set_mappings(c,p);audit(c,u['id'],'update','tally_mappings',None,p)
    except ValueError as e:raise HTTPException(400,str(e))
    return {'ok':True}
@app.post('/api/tally/test')
def tally_test(u=Depends(require('reports'))):
    with read_db() as c:s=get_settings(c);m=get_mappings(c)
    return {'bridge':bridge_health(s),'mappings':validate_mappings(s,m)}
@app.get('/api/tally/queue')
def tally_queue(status:str='',limit:int=Query(500,le=2000),u=Depends(require('reports'))):
    with read_db() as c:
        if status:return rowsdict(c.execute('SELECT * FROM tally_sync_queue WHERE status=? ORDER BY id DESC LIMIT ?',(status,limit)).fetchall())
        return rowsdict(c.execute('SELECT * FROM tally_sync_queue ORDER BY id DESC LIMIT ?',(limit,)).fetchall())
@app.post('/api/tally/sync-now')
def tally_sync_now(p:dict=Body(default={}),u=Depends(require('reports'))):
    return process_pending(min(200,max(1,int(p.get('limit',50) or 50))))
@app.post('/api/tally/backfill')
def tally_backfill(u=Depends(require('*'))):
    r=backfill_queue();audit_data={'counts':r}
    with write_db() as c:audit(c,u['id'],'backfill','tally',None,audit_data)
    if tally_worker:tally_worker.wake()
    return r
@app.post('/api/tally/retry/{qid}')
def tally_retry(qid:int,u=Depends(require('reports'))):
    with write_db() as c:
        if not c.execute('SELECT id FROM tally_sync_queue WHERE id=?',(qid,)).fetchone():raise HTTPException(404,'Tally queue item not found')
        c.execute("UPDATE tally_sync_queue SET status='pending',next_attempt_at=NULL,last_error=NULL,updated_at=? WHERE id=?",(utcnow(),qid))
    if tally_worker:tally_worker.wake()
    return {'ok':True}
@app.get('/api/tally/reconcile')
def tally_reconcile(date_from:str='',date_to:str='',u=Depends(require('reports'))):
    with read_db() as c:today=business_date(c)
    date_from=date_from or today[:8]+'01';date_to=date_to or today;return reconcile(date_from,date_to)

@app.get('/api/reports/summary')
def summary(date_from:str='',date_to:str='',u=Depends(require('reports'))):
    with read_db() as c:
        today=business_date(c);date_from=date_from or today[:8]+'01';date_to=date_to or today;s=c.execute("SELECT count(*) invoices,coalesce(sum(taxable_paise),0) taxable,coalesce(sum(gst_paise),0) gst,coalesce(sum(total_paise),0) total FROM sales WHERE status='posted' AND business_date BETWEEN ? AND ?",(date_from,date_to)).fetchone();r=c.execute("SELECT count(*) credit_notes,coalesce(sum(taxable_paise),0) taxable,coalesce(sum(gst_paise),0) gst,coalesce(sum(total_paise),0) total FROM sale_returns WHERE status='posted' AND business_date BETWEEN ? AND ?",(date_from,date_to)).fetchone();stock=c.execute("SELECT count(*) pieces,coalesce(sum(gross_mg),0)/1000.0 gross_weight,coalesce(sum(net_mg),0)/1000.0 net_weight,coalesce(sum(cost_amount_paise),0)/100.0 cost FROM items WHERE status='in_stock'").fetchone();met=rowsdict(c.execute("SELECT metal,purity,count(*) pieces,sum(gross_mg)/1000.0 gross_weight,sum(net_mg)/1000.0 net_weight,sum(cost_amount_paise)/100.0 cost FROM items WHERE status='in_stock' GROUP BY metal,purity ORDER BY metal,purity").fetchall());pay=c.execute("SELECT coalesce(sum(payment_cash_paise),0) cash,coalesce(sum(payment_card_paise),0) card,coalesce(sum(payment_upi_paise),0) upi,coalesce(sum(payment_credit_paise),0) credit,coalesce(sum(old_gold_value_paise),0) old_gold FROM sales WHERE status='posted' AND business_date BETWEEN ? AND ?",(date_from,date_to)).fetchone();refund=c.execute("SELECT coalesce(sum(refund_cash_paise),0) cash,coalesce(sum(refund_card_paise),0) card,coalesce(sum(refund_upi_paise),0) upi,coalesce(sum(refund_credit_paise),0) credit FROM sale_returns WHERE status='posted' AND business_date BETWEEN ? AND ?",(date_from,date_to)).fetchone();gross={'invoices':s['invoices'],'taxable':paise_money(s['taxable']),'gst':paise_money(s['gst']),'total':paise_money(s['total'])};returns={'credit_notes':r['credit_notes'],'taxable':paise_money(r['taxable']),'gst':paise_money(r['gst']),'total':paise_money(r['total'])};net={'invoices':s['invoices'],'taxable':paise_money(int(s['taxable'])-int(r['taxable'])),'gst':paise_money(int(s['gst'])-int(r['gst'])),'total':paise_money(int(s['total'])-int(r['total']))};payments={'cash':paise_money(int(pay['cash'])-int(refund['cash'])),'card':paise_money(int(pay['card'])-int(refund['card'])),'upi':paise_money(int(pay['upi'])-int(refund['upi'])),'credit':paise_money(int(pay['credit'])-int(refund['credit'])),'old_gold':paise_money(pay['old_gold'])};return {'date_from':date_from,'date_to':date_to,'sales':gross,'returns':returns,'net_sales':net,'stock':dict(stock),'stock_by_metal':met,'payments':payments}
@app.get('/api/reports/trial-balance')
def trial(date_to:str='',u=Depends(require('reports'))):
    with read_db() as c:
        date_to=date_to or business_date(c);return rowsdict(c.execute("SELECT a.code,a.name,a.account_type,coalesce(sum(x.debit_paise),0)/100.0 debit,coalesce(sum(x.credit_paise),0)/100.0 credit,coalesce(sum(x.debit_paise-x.credit_paise),0)/100.0 balance FROM accounts a LEFT JOIN (SELECT jl.* FROM journal_lines jl JOIN journal_entries je ON je.id=jl.entry_id WHERE je.entry_date<=?) x ON x.account_code=a.code WHERE a.active=1 GROUP BY a.code,a.name,a.account_type ORDER BY a.code",(date_to,)).fetchall())
@app.get('/api/reports/ledger/{code}')
def ledger(code:str,date_from:str='',date_to:str='',u=Depends(require('reports'))):
    with read_db() as c:return rowsdict(c.execute('SELECT je.entry_no,je.entry_date,je.memo,je.ref_type,je.ref_id,jl.debit_paise/100.0 debit,jl.credit_paise/100.0 credit FROM journal_lines jl JOIN journal_entries je ON je.id=jl.entry_id WHERE jl.account_code=? AND je.entry_date BETWEEN ? AND ? ORDER BY je.entry_date,je.id',(code,date_from or '0001-01-01',date_to or '9999-12-31')).fetchall())
@app.get('/api/reports/profit-loss')
def profit_loss(date_from:str='',date_to:str='',u=Depends(require('reports'))):
    """Offline P&L: sales - returns - COGS. All local, no internet."""
    with read_db() as c:
        today=business_date(c);date_from=date_from or today[:8]+'01';date_to=date_to or today
        s=c.execute("SELECT coalesce(sum(taxable_paise),0) t,coalesce(sum(total_paise),0) tot FROM sales WHERE status='posted' AND business_date BETWEEN ? AND ?",(date_from,date_to)).fetchone()
        r=c.execute("SELECT coalesce(sum(taxable_paise),0) t,coalesce(sum(total_paise),0) tot FROM sale_returns WHERE status='posted' AND business_date BETWEEN ? AND ?",(date_from,date_to)).fetchone()
        cogs=c.execute("SELECT coalesce(sum(si.cost_amount_paise),0) c FROM sale_items si JOIN sales s ON s.id=si.sale_id WHERE s.status='posted' AND s.business_date BETWEEN ? AND ?",(date_from,date_to)).fetchone()[0]
        cogs_ret=c.execute("SELECT coalesce(sum(ri.cost_amount_paise),0) c FROM sale_return_items ri JOIN sale_returns r ON r.id=ri.return_id WHERE r.status='posted' AND r.business_date BETWEEN ? AND ? AND ri.active=1",(date_from,date_to)).fetchone()[0]
        gross_sales=paise_money(s['tot']);returns=paise_money(r['tot']);net_sales=round(gross_sales-returns,2)
        cogs_net=paise_money(int(cogs or 0)-int(cogs_ret or 0));gross_profit=round(paise_money(s['t'])-paise_money(r['t'])-cogs_net,2)
        return {'date_from':date_from,'date_to':date_to,'gross_sales':gross_sales,'returns':returns,'net_sales':net_sales,'cogs':cogs_net,'gross_profit':gross_profit}
@app.get('/api/reports/balance-sheet')
def balance_sheet(date_to:str='',u=Depends(require('reports'))):
    """Offline balance sheet from trial balances. Assets = Liabilities + Equity."""
    with read_db() as c:
        date_to=date_to or business_date(c)
        rows=rowsdict(c.execute("SELECT a.code,a.name,a.account_type,coalesce(sum(x.debit_paise),0)/100.0 debit,coalesce(sum(x.credit_paise),0)/100.0 credit FROM accounts a LEFT JOIN (SELECT jl.* FROM journal_lines jl JOIN journal_entries je ON je.id=jl.entry_id WHERE je.entry_date<=?) x ON x.account_code=a.code WHERE a.active=1 GROUP BY a.code",(date_to,)).fetchall())
        def bal(r):return round(r['debit']-r['credit'],2)
        assets=sum(bal(r) for r in rows if r['account_type']=='asset')
        liabilities=sum(-bal(r) for r in rows if r['account_type']=='liability')
        equity=sum(-bal(r) for r in rows if r['account_type']=='equity')
        income=sum(-(r['debit']-r['credit']) for r in rows if r['account_type']=='income')
        expense=sum((r['debit']-r['credit']) for r in rows if r['account_type']=='expense')
        retained=round(income-expense,2)
        return {'date_to':date_to,'assets':round(assets,2),'liabilities':round(liabilities,2),'equity':round(equity,2),'retained_earnings':retained,'balanced':abs(assets-(liabilities+equity+retained))<0.02,'lines':rows}
@app.get('/api/reports/metal-wise')
def metal_wise(date_from:str='',date_to:str='',u=Depends(require('reports'))):
    with read_db() as c:
        today=business_date(c);date_from=date_from or today[:8]+'01';date_to=date_to or today
        sales=rowsdict(c.execute("SELECT si.metal,si.purity,count(*) pcs,coalesce(sum(si.taxable_paise),0)/100.0 taxable,coalesce(sum(si.gst_amount_paise),0)/100.0 gst,coalesce(sum(si.line_total_paise),0)/100.0 total FROM sale_items si JOIN sales s ON s.id=si.sale_id WHERE s.status='posted' AND s.business_date BETWEEN ? AND ? GROUP BY si.metal,si.purity ORDER BY si.metal,si.purity",(date_from,date_to)).fetchall())
        purch=rowsdict(c.execute("SELECT i.metal,i.purity,count(*) pcs,coalesce(sum(pi.cost_amount_paise),0)/100.0 cost FROM purchase_items pi JOIN items i ON i.id=pi.item_id JOIN purchases p ON p.id=pi.purchase_id WHERE p.business_date BETWEEN ? AND ? GROUP BY i.metal,i.purity",(date_from,date_to)).fetchall())
        stock=rowsdict(c.execute("SELECT metal,purity,count(*) pieces,sum(net_mg)/1000.0 net_weight,sum(cost_amount_paise)/100.0 cost FROM items WHERE status='in_stock' GROUP BY metal,purity").fetchall())
        return {'date_from':date_from,'date_to':date_to,'sales':sales,'purchases':purch,'stock':stock}
@app.get('/api/reports/gstr')
def gstr(date_from:str='',date_to:str='',u=Depends(require('reports'))):
    """Offline GSTR-ready summary: taxable + CGST/SGST/IGST per GST rate. Filing stays online, data is local."""
    with read_db() as c:
        today=business_date(c);date_from=date_from or today[:8]+'01';date_to=date_to or today
        out=rowsdict(c.execute("SELECT si.gst_rate,coalesce(sum(si.taxable_paise),0)/100.0 taxable,coalesce(sum(si.gst_amount_paise),0)/100.0 gst,count(*) lines,coalesce(sum(si.line_total_paise),0)/100.0 total FROM sale_items si JOIN sales s ON s.id=si.sale_id WHERE s.status='posted' AND s.business_date BETWEEN ? AND ? GROUP BY si.gst_rate ORDER BY si.gst_rate",(date_from,date_to)).fetchall())
        tot=c.execute("SELECT coalesce(sum(cgst_paise),0)/100.0 cgst,coalesce(sum(sgst_paise),0)/100.0 sgst,coalesce(sum(igst_paise),0)/100.0 igst FROM sales WHERE status='posted' AND business_date BETWEEN ? AND ?",(date_from,date_to)).fetchone()
        return {'date_from':date_from,'date_to':date_to,'by_rate':out,'cgst':tot['cgst'],'sgst':tot['sgst'],'igst':tot['igst']}
@app.get('/api/reports/stock.pdf')
def stock_pdf(u=Depends(require('reports'))):
    with read_db() as c:data=stock_report_pdf(rowsdict(c.execute("SELECT * FROM items WHERE status='in_stock' ORDER BY category,tag_no").fetchall()),get_settings(c))
    return Response(data,media_type='application/pdf',headers={'Content-Disposition':'inline; filename="stock-report.pdf"'})
@app.get('/api/integrity')
def integrity_report(u=Depends(require('reports'))):
    with read_db() as c:return database_integrity(c)


@app.get('/api/reports/day-close')
def day_close_report(date:str='',branch_id:int=1,u=Depends(require('reports'))):
    with read_db() as c:
        report_date=date or business_date(c)
        try:dt.date.fromisoformat(report_date)
        except ValueError:raise HTTPException(400,'Date must be YYYY-MM-DD')
        if not c.execute('SELECT 1 FROM branches WHERE id=? AND active=1',(branch_id,)).fetchone():raise HTTPException(400,'Branch is not active')
        return day_close(c,report_date,branch_id)


@app.get('/api/day-close/status')
def day_close_status(branch_id:int=1,date:str='',u=Depends(require('reports'))):
    with read_db() as c:
        report_date=date or business_date(c)
        row=c.execute("SELECT * FROM day_closes WHERE branch_id=? AND business_date=?",(branch_id,report_date)).fetchone()
        return {'business_date':report_date,'branch_id':branch_id,'closed':bool(row and row['status']=='closed'),'record':rowdict(row)}


@app.post('/api/day-close')
def day_close_post(p:dict=Body(default={}),u=Depends(require('reports'))):
    branch_id=int(p.get('branch_id') or 1)
    with write_db() as c:
        report_date=str(p.get('business_date') or business_date(c))
        try:dt.date.fromisoformat(report_date)
        except ValueError:raise HTTPException(400,'Business date must be YYYY-MM-DD')
        if not c.execute('SELECT 1 FROM branches WHERE id=? AND active=1',(branch_id,)).fetchone():raise HTTPException(400,'Branch is not active')
        existing=c.execute("SELECT * FROM day_closes WHERE branch_id=? AND business_date=?",(branch_id,report_date)).fetchone()
        if existing and existing['status']=='closed':return {'ok':True,'already_closed':True,'record':dict(existing)}
        report=day_close(c,report_date,branch_id);integrity=database_integrity(c,branch_id=branch_id)
        checks_ok=bool(integrity.get('ok')) and bool(report.get('journal',{}).get('balanced')) and bool(report.get('sales',{}).get('payments_match_sales')) and bool(report.get('returns',{}).get('refunds_match_returns'))
        if not checks_ok:
            raise HTTPException(409,detail={'code':'DAY_CLOSE_BLOCKED','message':'Day close is blocked by reconciliation or data-health failures','report':report,'integrity':integrity})
        evidence={'branch_id':branch_id,'business_date':report_date,'report':report,'integrity':integrity,'closed_by':u['id']}
        evidence_json=json.dumps(evidence,ensure_ascii=False,sort_keys=True,separators=(',',':'));evidence_hash=hashlib.sha256(evidence_json.encode('utf-8')).hexdigest();now=utcnow()
        if existing:
            c.execute("UPDATE day_closes SET status='closed',evidence_json=?,evidence_hash=?,closed_by=?,closed_at=?,reopened_by=NULL,reopened_at=NULL,reopen_reason=NULL WHERE id=?",(evidence_json,evidence_hash,u['id'],now,existing['id']));close_id=existing['id']
        else:
            close_id=c.execute("INSERT INTO day_closes(branch_id,business_date,status,evidence_json,evidence_hash,closed_by,closed_at) VALUES(?,?,'closed',?,?,?,?)",(branch_id,report_date,evidence_json,evidence_hash,u['id'],now)).lastrowid
        audit(c,u['id'],'close','day_close',close_id,{'business_date':report_date,'branch_id':branch_id,'evidence_hash':evidence_hash})
        return {'ok':True,'id':close_id,'business_date':report_date,'branch_id':branch_id,'evidence_hash':evidence_hash,'report':report}


@app.post('/api/day-close/{business_day}/reopen')
def day_close_reopen(business_day:str,branch_id:int=1,p:dict=Body(default={}),u=Depends(require('reports'))):
    if u['role'] not in ('admin','manager'):raise HTTPException(403,'Manager permission required to reopen a closed day')
    reason=str(p.get('reason') or '').strip()
    if len(reason)<3:raise HTTPException(400,'A reason is required to reopen a closed day')
    with write_db() as c:
        row=c.execute("SELECT * FROM day_closes WHERE branch_id=? AND business_date=?",(branch_id,business_day)).fetchone()
        if not row:raise HTTPException(404,'Day close not found')
        if row['status']=='reopened':return {'ok':True,'already_reopened':True}
        now=utcnow();c.execute("UPDATE day_closes SET status='reopened',reopened_by=?,reopened_at=?,reopen_reason=? WHERE id=?",(u['id'],now,reason,row['id']));audit(c,u['id'],'reopen','day_close',row['id'],{'reason':reason})
        return {'ok':True,'business_date':business_day,'branch_id':branch_id}


@app.get('/api/backups')
def backups(u=Depends(require('backup'))):return list_backups()
@app.post('/api/backups')
def backup(p:dict=Body(default={}),u=Depends(require('backup'))):
    f=create_backup(str(p.get('label') or 'manual'));v=verify_backup(f);return {'ok':True,'name':f.name,'size':f.stat().st_size,'sha256':v['sha256'],'verified':v['ok']}
@app.get('/api/audit-log')
def logs(limit:int=Query(200,le=1000),u=Depends(require('*'))):
    with read_db() as c:return rowsdict(c.execute('SELECT l.*,u.username FROM audit_log l LEFT JOIN users u ON u.id=l.user_id ORDER BY l.id DESC LIMIT ?',(limit,)).fetchall())

def lan_addresses(port,scheme='https'):
    try:return sorted({f'{scheme}://{x}:{port}' for x in socket.gethostbyname_ex(socket.gethostname())[2] if not x.startswith('127.')})
    except:return []
def cli():
    p=argparse.ArgumentParser(description='JewelLAN offline jewellery ERP server');p.add_argument('--host',default=os.environ.get('JEWELLAN_HOST','0.0.0.0'));p.add_argument('--port',type=int,default=int(os.environ.get('JEWELLAN_PORT','8765')));p.add_argument('--restore');p.add_argument('--show-fingerprint',action='store_true');p.add_argument('--insecure-http',action='store_true',help='Development only: disable TLS on the private LAN');a=p.parse_args()
    if a.restore:init_db(hash_password);result=restore_backup(a.restore);init_db(hash_password);print('Backup restored and migrated:',result);return
    identity=tls_identity()
    if a.show_fingerprint:print(identity['fingerprint']);return
    os.environ['JEWELLAN_PORT']=str(a.port);scheme='http' if a.insecure_http else 'https'
    if a.insecure_http:os.environ['JEWELLAN_INSECURE_HTTP']='1'
    else:os.environ.pop('JEWELLAN_INSECURE_HTTP',None)
    print('\nJewelLAN Server - OFFLINE PRIVATE LAN MODE');print('Transport:',scheme.upper());print('Certificate SHA-256:',identity['fingerprint']);print('Local:',f'{scheme}://127.0.0.1:{a.port}');[print('LAN:  ',x) for x in lan_addresses(a.port,scheme)];print('Default first login: admin / Jewel@123 (change it immediately; new passwords require 10+ characters)\n')
    kwargs={'host':a.host,'port':a.port,'log_level':'info','access_log':False}
    if not a.insecure_http:kwargs.update(ssl_certfile=identity['cert'],ssl_keyfile=identity['key'],ssl_version=2)
    uvicorn.run(app,**kwargs)
if __name__=='__main__':cli()
