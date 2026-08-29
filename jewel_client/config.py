from __future__ import annotations
import json,os
from pathlib import Path
APP_NAME='JewelLAN'
def config_dir():
    base=Path(os.environ.get('APPDATA',Path.home())) if os.name=='nt' else Path.home()/'.config';p=base/APP_NAME;p.mkdir(parents=True,exist_ok=True);return p
def config_path():return config_dir()/'client.json'
def load_config():
    d={'server_url':'','branch_id':1,'counter_id':1,'scale_port':'','scale_baud':9600,'print_after_sale':True}
    try:d.update(json.loads(config_path().read_text('utf-8')))
    except:pass
    return d
def save_config(cfg):config_path().write_text(json.dumps(cfg,indent=2),'utf-8')
