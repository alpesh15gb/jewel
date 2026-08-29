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

def patch_client() -> None:
    path = "jewel_client/main.py"
    text = Path(path).read_text(encoding="utf-8")
    text = text.replace('self.make_rates();self.make_backup();self.make_pc();\n        if app.user.get("role")=="admin":self.make_users();self.make_business()', 'self.make_rates();self.make_backup();self.make_pc();self.make_tally();\n        if app.user.get("role")=="admin":self.make_users();self.make_business()', 1)
    if "def make_tally(self):" not in text:
        marker = '    def make_users(self):\n'
        methods = '''    def make_tally(self):\n        f=ttk.Frame(self.nb,padding=10);self.nb.add(f,text="TallyPrime");self.tv={};self.tm={};self.tally_status=tk.StringVar(value="Loading Tally integration status…");ttk.Label(f,textvariable=self.tally_status,foreground="#555").grid(row=0,column=0,columnspan=2,sticky="w",pady=(0,8))\n        try:d=self.api.get('/api/tally/status')\n        except Exception as e:d={'mappings':{}};self.tally_status.set(str(e))\n        fields=[('tally_enabled','Enabled (0/1)',d.get('enabled','0')),('tally_bridge_url','Bridge URL',d.get('bridge_url','http://127.0.0.1:8767')),('tally_bridge_token','Bridge token',''),('tally_company','Tally company',d.get('company','')),('business_state_code','Business state code',d.get('business_state_code','')),('tally_auto_create_parties','Auto-create party ledgers (0/1)',d.get('auto_create_parties','1'))]\n        r=1\n        for k,l,val in fields:self.tv[k]=tk.StringVar(value=str(val));ttk.Label(f,text=l).grid(row=r,column=0,sticky='w',pady=3);ttk.Entry(f,textvariable=self.tv[k],show='●' if k=='tally_bridge_token' else '').grid(row=r,column=1,sticky='ew',padx=8);r+=1\n        ttk.Separator(f).grid(row=r,column=0,columnspan=2,sticky='ew',pady=8);r+=1;ttk.Label(f,text='Ledger mappings',font=('Segoe UI',11,'bold')).grid(row=r,column=0,columnspan=2,sticky='w');r+=1\n        for k,val in d.get('mappings',{}).items():self.tm[k]=tk.StringVar(value=str(val));ttk.Label(f,text=k.replace('_',' ').title()).grid(row=r,column=0,sticky='w',pady=2);ttk.Entry(f,textvariable=self.tm[k]).grid(row=r,column=1,sticky='ew',padx=8);r+=1\n        b=ttk.Frame(f);b.grid(row=r,column=0,columnspan=2,sticky='ew',pady=10);ttk.Button(b,text='Save',command=self.save_tally).pack(side='left');ttk.Button(b,text='Test',command=self.test_tally).pack(side='left',padx=4);ttk.Button(b,text='Sync now',command=self.sync_tally).pack(side='left');ttk.Button(b,text='Reconcile',command=self.reconcile_tally).pack(side='left',padx=4);ttk.Button(b,text='Backfill',command=self.backfill_tally).pack(side='left');f.columnconfigure(1,weight=1)\n        bridge=d.get('bridge');q=d.get('queue',{});self.tally_status.set(('Connected' if bridge and bridge.get('ok') else 'Not connected')+f" | pending {q.get('pending',0)} failed {q.get('failed',0)} synced {q.get('synced',0)}")\n    def save_tally(self):\n        try:\n            p={k:v.get() for k,v in self.tv.items() if k!='tally_bridge_token' or v.get().strip()};self.api.put('/api/tally/settings',p);self.api.put('/api/tally/mappings',{k:v.get() for k,v in self.tm.items()});messagebox.showinfo('TallyPrime','Settings saved. Use Test before enabling live sync.',parent=self)\n        except Exception as e:self.app.error(e)\n    def test_tally(self):\n        try:r=self.api.post('/api/tally/test',{});missing=r.get('mappings',{}).get('missing',[]);messagebox.showinfo('TallyPrime',f"Bridge connected. Missing mapped ledgers: {', '.join(missing) if missing else 'none'}",parent=self)\n        except Exception as e:self.app.error(e)\n    def sync_tally(self):\n        try:r=self.api.post('/api/tally/sync-now',{'limit':100});messagebox.showinfo('TallyPrime',f"Processed {r['processed']} | Synced {r['synced']} | Failed {r['failed']}",parent=self)\n        except Exception as e:self.app.error(e)\n    def reconcile_tally(self):\n        try:r=self.api.get('/api/tally/reconcile',date_from=dt.date.today().replace(day=1).isoformat(),date_to=dt.date.today().isoformat());messagebox.showinfo('Tally reconciliation',f"Expected {r['expected_count']}\\nFound {r['found_count']}\\nMissing {len(r['missing'])}\\nAmount mismatches {len(r['amount_mismatches'])}",parent=self)\n        except Exception as e:self.app.error(e)\n    def backfill_tally(self):\n        if not messagebox.askyesno('TallyPrime','Queue historical JewelLAN sales and purchases for Tally sync?',parent=self):return\n        try:r=self.api.post('/api/tally/backfill',{});messagebox.showinfo('TallyPrime',str(r),parent=self)\n        except Exception as e:self.app.error(e)\n\n'''
        text = must_replace(text, marker, methods + marker, "Tally admin UI")
    write_if_changed(path, text)

if __name__ == "__main__":
    patch_client()
