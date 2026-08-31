from __future__ import annotations
import json,os,tempfile
from pathlib import Path
APP_NAME='JewelLAN'
def config_dir():
    base=Path(os.environ.get('APPDATA',Path.home())) if os.name=='nt' else Path.home()/'.config';p=base/APP_NAME;p.mkdir(parents=True,exist_ok=True);return p
def config_path():return config_dir()/'client.json'
def pending_posts_path():return config_dir()/'pending_posts.json'
def load_config():
    d={'server_url':'','server_fingerprint':'','branch_id':1,'counter_id':1,'scale_port':'','scale_baud':9600,'print_after_sale':True}
    try:d.update(json.loads(config_path().read_text('utf-8')))
    except:pass
    return d
def save_config(cfg):config_path().write_text(json.dumps(cfg,indent=2),'utf-8')


def load_pending_posts():
    try:
        value=json.loads(pending_posts_path().read_text('utf-8'))
        return value if isinstance(value,list) else []
    except Exception:
        return []


def save_pending_posts(posts):
    path=pending_posts_path();path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='pending-',suffix='.tmp',dir=str(path.parent))
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as fh:
            json.dump(posts,fh,ensure_ascii=False,indent=2,sort_keys=True)
            fh.flush();os.fsync(fh.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):
            try:os.unlink(tmp)
            except OSError:pass


def upsert_pending_post(record):
    posts=load_pending_posts();request_id=str(record.get('request_id') or '')
    posts=[x for x in posts if str(x.get('request_id') or '')!=request_id]
    posts.append(dict(record));save_pending_posts(posts)


def remove_pending_post(request_id):
    posts=[x for x in load_pending_posts() if str(x.get('request_id') or '')!=str(request_id)]
    save_pending_posts(posts)
