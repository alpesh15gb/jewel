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

def patch_main() -> None:
    path = "jewel_server/main.py"
    text = Path(path).read_text(encoding="utf-8")
    if "from .tally import" not in text:
        anchor = 'from .services import cancel_sale,create_item,latest_rate,money,post_sale,purity_fraction,quote_sale,transfer_item,update_item,weight\n'
        imp = anchor + "from .tally import TallySyncWorker,backfill_queue,bridge_health,enqueue_tally,get_mappings,process_pending,reconcile,set_mappings,validate_mappings\n"
        text = must_replace(text, anchor, imp, "Tally main import")
    text = text.replace('backup_worker=None;discovery=None\n', 'backup_worker=None;discovery=None;tally_worker=None\n', 1)
    text = text.replace('global backup_worker,discovery\n    init_db(hash_password);backup_worker=BackupWorker();backup_worker.start();port=', 'global backup_worker,discovery,tally_worker\n    init_db(hash_password);backup_worker=BackupWorker();backup_worker.start();tally_worker=TallySyncWorker();tally_worker.start();port=', 1)
    text = text.replace('if backup_worker:backup_worker.stop()\n    if discovery:discovery.stop()', 'if backup_worker:backup_worker.stop()\n    if tally_worker:tally_worker.stop()\n    if discovery:discovery.stop()', 1)
    old_allowed = "allowed={'business_name','business_address','business_phone','business_gstin','currency','invoice_prefix','tag_prefix','gst_default','label_width_mm','label_height_mm','backup_interval_hours','backup_retention_days'}"
    if old_allowed in text:
        new_allowed = "allowed={'business_name','business_address','business_phone','business_gstin','business_state_code','currency','invoice_prefix','tag_prefix','gst_default','label_width_mm','label_height_mm','backup_interval_hours','backup_retention_days','tally_enabled','tally_bridge_url','tally_bridge_token','tally_company','tally_auto_create_parties'}"
        text = text.replace(old_allowed, new_allowed, 1)
    old_purchase_end = "audit(c,u['id'],'create','purchase',pid,{'purchase_no':no,'total':total});return {'id':pid,'purchase_no':no,'total':total}"
    if old_purchase_end in text:
        text = text.replace(old_purchase_end, "audit(c,u['id'],'create','purchase',pid,{'purchase_no':no,'total':total});enqueue_tally(c,'purchase',pid,'create');return {'id':pid,'purchase_no':no,'total':total}", 1)
    if "@app.get('/api/tally/status')" not in text:
        marker = "@app.get('/api/reports/summary')\n"
        endpoints = '''@app.get('/api/tally/status')\ndef tally_status(u=Depends(require('reports'))):\n    with read_db() as c:\n        s=get_settings(c);m=get_mappings(c);q={r['status']:r['c'] for r in c.execute("SELECT status,count(*) c FROM tally_sync_queue GROUP BY status").fetchall()}\n    out={'enabled':s.get('tally_enabled','0'),'bridge_url':s.get('tally_bridge_url',''),'company':s.get('tally_company',''),'business_state_code':s.get('business_state_code',''),'auto_create_parties':s.get('tally_auto_create_parties','1'),'mappings':m,'queue':q,'bridge':None}\n    if str(s.get('tally_enabled','0')).lower() in ('1','true','yes','on'):\n        try:out['bridge']=bridge_health(s)\n        except Exception as e:out['bridge']={'ok':False,'error':str(e)}\n    return out\n@app.put('/api/tally/settings')\ndef tally_settings(p:dict=Body(...),u=Depends(require('*'))):\n    allowed={'tally_enabled','tally_bridge_url','tally_bridge_token','tally_company','tally_auto_create_parties','business_state_code'}\n    with write_db() as c:\n        for k,v in p.items():\n            if k in allowed:set_setting(c,k,str(v))\n        audit(c,u['id'],'update','tally_settings',None,{k:('***' if k=='tally_bridge_token' else v) for k,v in p.items() if k in allowed})\n    if tally_worker:tally_worker.wake()\n    return {'ok':True}\n@app.get('/api/tally/mappings')\ndef tally_mappings(u=Depends(require('reports'))):\n    with read_db() as c:return get_mappings(c)\n@app.put('/api/tally/mappings')\ndef tally_mappings_save(p:dict=Body(...),u=Depends(require('*'))):\n    try:\n        with write_db() as c:set_mappings(c,p);audit(c,u['id'],'update','tally_mappings',None,p)\n    except ValueError as e:raise HTTPException(400,str(e))\n    return {'ok':True}\n@app.post('/api/tally/test')\ndef tally_test(u=Depends(require('reports'))):\n    with read_db() as c:s=get_settings(c);m=get_mappings(c)\n    return {'bridge':bridge_health(s),'mappings':validate_mappings(s,m)}\n@app.get('/api/tally/queue')\ndef tally_queue(status:str='',limit:int=Query(500,le=2000),u=Depends(require('reports'))):\n    with read_db() as c:\n        if status:return rowsdict(c.execute('SELECT * FROM tally_sync_queue WHERE status=? ORDER BY id DESC LIMIT ?',(status,limit)).fetchall())\n        return rowsdict(c.execute('SELECT * FROM tally_sync_queue ORDER BY id DESC LIMIT ?',(limit,)).fetchall())\n@app.post('/api/tally/sync-now')\ndef tally_sync_now(p:dict=Body(default={}),u=Depends(require('reports'))):\n    return process_pending(min(200,max(1,int(p.get('limit',50) or 50))))\n@app.post('/api/tally/backfill')\ndef tally_backfill(u=Depends(require('*'))):\n    r=backfill_queue();audit_data={'counts':r}\n    with write_db() as c:audit(c,u['id'],'backfill','tally',None,audit_data)\n    if tally_worker:tally_worker.wake()\n    return r\n@app.post('/api/tally/retry/{qid}')\ndef tally_retry(qid:int,u=Depends(require('reports'))):\n    with write_db() as c:\n        if not c.execute('SELECT id FROM tally_sync_queue WHERE id=?',(qid,)).fetchone():raise HTTPException(404,'Tally queue item not found')\n        c.execute("UPDATE tally_sync_queue SET status='pending',next_attempt_at=NULL,last_error=NULL,updated_at=? WHERE id=?",(utcnow(),qid))\n    if tally_worker:tally_worker.wake()\n    return {'ok':True}\n@app.get('/api/tally/reconcile')\ndef tally_reconcile(date_from:str='',date_to:str='',u=Depends(require('reports'))):\n    date_from=date_from or dt.date.today().replace(day=1).isoformat();date_to=date_to or dt.date.today().isoformat();return reconcile(date_from,date_to)\n\n'''
        text = must_replace(text, marker, endpoints + marker, "Tally API endpoints")
    write_if_changed(path, text)

if __name__ == "__main__":
    patch_main()
