from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"security v3 anchor not found: {label}")
    return text.replace(old, new, 1)


def patch_client() -> None:
    p=Path('jewel_client/main.py');t=p.read_text(encoding='utf-8')
    t=replace_once(t,'from .api import Api, ApiError, discover_servers','from .api import Api, ApiError, discover_servers, format_fingerprint, probe_server_fingerprint, secure_url','client TLS imports')
    t=replace_once(t,'self.server = tk.StringVar(value=cfg.get("server_url") or "http://127.0.0.1:8765")','self.server = tk.StringVar(value=secure_url(cfg.get("server_url") or "https://127.0.0.1:8765")); self.discovered_fingerprint = ""','secure login default')
    old='''    def discover(self):
        self.status.set("Searching the private LAN…"); self.update_idletasks(); servers = discover_servers()
        if servers:
            self.server.set(servers[0]["url"]); self.status.set(f"Found {servers[0].get('name','JewelLAN')} at {servers[0]['url']}")
        else:
            self.status.set("No server was discovered. Enter its LAN address manually.")

    def login(self):
        try:
            self.api.set_url(self.server.get().strip()); self.user = self.api.login(self.username.get().strip(), self.password.get())
            self.cfg["server_url"] = self.api.base_url; save_config(self.cfg); self.destroy()
        except ApiError as e:
            messagebox.showerror("Login failed", str(e), parent=self)
'''
    new='''    def _trust_live_server(self, url, advertised_fingerprint=""):
        url=secure_url(url);live=probe_server_fingerprint(url);advertised="".join(ch for ch in str(advertised_fingerprint or "") if ch.isalnum()).upper()
        if advertised and advertised!=live:
            raise ApiError("LAN discovery fingerprint does not match the server TLS certificate. Do not sign in.")
        saved_url=secure_url(self.cfg.get("server_url") or "");saved="".join(ch for ch in str(self.cfg.get("server_fingerprint") or "") if ch.isalnum()).upper()
        if saved_url==url and saved:
            if saved!=live:raise ApiError("The JewelLAN server certificate changed. Verify the server PC before trusting the new identity.")
        else:
            pretty=format_fingerprint(live)
            message=f"""Secure server found at:
{url}

SHA-256 certificate fingerprint:
{pretty}

Verify this fingerprint on the server PC with 'JewelServer.exe --show-fingerprint'. Trust this server?"""
            ok=messagebox.askyesno("Trust JewelLAN server?",message,parent=self)
            if not ok:raise ApiError("Server identity was not trusted")
        self.api.trust_server(url,live);self.cfg["server_url"]=url;self.cfg["server_fingerprint"]=live;save_config(self.cfg);return live

    def discover(self):
        self.status.set("Searching the private LAN securely…"); self.update_idletasks(); servers = discover_servers()
        if servers:
            server=servers[0];self.server.set(server["url"]);self.discovered_fingerprint=server.get("fingerprint_sha256","");self.status.set(f"Found {server.get('name','JewelLAN')} over HTTPS. Identity verification is required before sign-in.")
        else:
            self.status.set("No secure server was discovered. Enter its LAN address manually; HTTPS identity will be verified before sign-in.")

    def login(self):
        try:
            url=secure_url(self.server.get().strip());self._trust_live_server(url,self.discovered_fingerprint);self.user = self.api.login(self.username.get().strip(), self.password.get());self.destroy()
        except ApiError as e:
            messagebox.showerror("Login failed", str(e), parent=self)
'''
    t=replace_once(t,old,new,'client trust workflow')
    t=replace_once(t,'root=tk.Tk();root.withdraw();cfg=load_config();api=Api(cfg.get("server_url",""));login=LoginDialog(root,api,cfg);root.wait_window(login)','root=tk.Tk();root.withdraw();cfg=load_config();api=Api(cfg.get("server_url",""),cfg.get("server_fingerprint",""));login=LoginDialog(root,api,cfg);root.wait_window(login)','client pinned API startup')
    p.write_text(t,encoding='utf-8')


def patch_server() -> None:
    p=Path('jewel_server/main.py');t=p.read_text(encoding='utf-8')
    t=replace_once(t,'from .tally import TallySyncWorker,backfill_queue,bridge_health,enqueue_tally,get_mappings,process_pending,reconcile,set_mappings,validate_mappings','from .tally import TallySyncWorker,backfill_queue,bridge_health,enqueue_tally,get_mappings,process_pending,reconcile,set_mappings,validate_mappings\nfrom .tls import tls_identity','server TLS import')
    old='''def lan_addresses(port):
    try:return sorted({f'http://{x}:{port}' for x in socket.gethostbyname_ex(socket.gethostname())[2] if not x.startswith('127.')})
    except:return []
def cli():
    p=argparse.ArgumentParser(description='JewelLAN offline jewellery ERP server');p.add_argument('--host',default=os.environ.get('JEWELLAN_HOST','0.0.0.0'));p.add_argument('--port',type=int,default=int(os.environ.get('JEWELLAN_PORT','8765')));p.add_argument('--restore');a=p.parse_args()
    if a.restore:init_db(hash_password);result=restore_backup(a.restore);init_db(hash_password);print('Backup restored and migrated:',result);return
    os.environ['JEWELLAN_PORT']=str(a.port);print('\\nJewelLAN Server - OFFLINE LAN MODE');print('Local:',f'http://127.0.0.1:{a.port}');[print('LAN:  ',x) for x in lan_addresses(a.port)];print('Default first login: admin / Jewel@123 (change it immediately; new passwords require 10+ characters)\\n');uvicorn.run(app,host=a.host,port=a.port,log_level='info',access_log=False)
'''
    new='''def lan_addresses(port,scheme='https'):
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
    print('\\nJewelLAN Server - OFFLINE PRIVATE LAN MODE');print('Transport:',scheme.upper());print('Certificate SHA-256:',identity['fingerprint']);print('Local:',f'{scheme}://127.0.0.1:{a.port}');[print('LAN:  ',x) for x in lan_addresses(a.port,scheme)];print('Default first login: admin / Jewel@123 (change it immediately; new passwords require 10+ characters)\\n')
    kwargs={'host':a.host,'port':a.port,'log_level':'info','access_log':False}
    if not a.insecure_http:kwargs.update(ssl_certfile=identity['cert'],ssl_keyfile=identity['key'],ssl_version=2)
    uvicorn.run(app,**kwargs)
'''
    t=replace_once(t,old,new,'secure server CLI')
    p.write_text(t,encoding='utf-8')


def patch_installer() -> None:
    p=Path('installer/JewelLAN.iss');t=p.read_text(encoding='utf-8')
    t=t.replace('; Tally Bridge is exposed only to the Private LAN; TallyPrime itself remains localhost-only.','; Tally Bridge remains loopback-only by default so its bearer token never crosses the LAN in clear text.')
    t=t.replace('Filename: "{sys}\\netsh.exe"; Parameters: "advfirewall firewall add rule name=""JewelLAN Tally Bridge TCP"" dir=in action=allow protocol=TCP localport=8767 profile=private enable=yes"; Flags: runhidden; Components: tallybridge\n','')
    t=t.replace('--host 0.0.0.0 --port 8767 --tally-url http://127.0.0.1:9000','--host 127.0.0.1 --port 8767 --tally-url http://127.0.0.1:9000')
    t=t.replace('VersionInfoProductVersion={#MyAppVersion}','VersionInfoProductVersion={#MyFileVersion}')
    p.write_text(t,encoding='utf-8')


if __name__=='__main__':
    patch_client();patch_server();patch_installer();print('production security v3 applied')
