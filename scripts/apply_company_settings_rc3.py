from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        if new in text:
            return text
        raise RuntimeError(f"Expected fragment not found: {label}")
    if text.count(old) != 1:
        raise RuntimeError(f"Expected exactly one fragment for {label}, found {text.count(old)}")
    return text.replace(old, new, 1)


def patch_db() -> None:
    path = ROOT / "jewel_server" / "db.py"
    text = path.read_text("utf-8")
    text = replace_once(text, 'LATEST_SCHEMA_VERSION = 5', 'LATEST_SCHEMA_VERSION = 6', 'schema version')

    old_seed_migration = '''        conn.execute("UPDATE branches SET name='Bijoria Main Showroom' WHERE id=? AND name='Main Showroom'",(bid,))
    conn.execute("UPDATE settings SET value='Bijoria',updated_at=? WHERE key='business_name' AND value='My Jewellery Store'",(utcnow(),))
    conn.execute("UPDATE settings SET value='36',updated_at=? WHERE key='business_state_code' AND trim(value)=''",(utcnow(),))
'''
    text = replace_once(text, old_seed_migration, '', 'remove deployment-specific migration defaults')

    migration_marker = "\n\nMIGRATIONS = ((1, _migration_1), (2, _migration_2), (3, _migration_3), (4, _migration_4), (5, _migration_5))"
    migration6 = r'''


def _migration_6(conn) -> None:
    """Remove the RC1/RC2 demo-shop seed and introduce generic company setup state.

    Existing real stores are never renamed.  The old deployment-specific values are
    cleared only when the database has no business data and still exactly matches the
    obsolete seed shipped in the release candidates.
    """
    counts = 0
    for table in ("items", "sales", "purchases", "customers", "suppliers", "karigars", "repairs", "orders", "approvals"):
        counts += int(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
    business = conn.execute("SELECT value FROM settings WHERE key='business_name'").fetchone()
    branch = conn.execute("SELECT id,name FROM branches WHERE code='MAIN'").fetchone()
    old_seed = bool(
        counts == 0
        and business
        and business[0] == "Bijoria"
        and branch
        and branch["name"] == "Bijoria Main Showroom"
    )
    if old_seed:
        now = utcnow()
        conn.execute("UPDATE settings SET value='',updated_at=? WHERE key='business_name'", (now,))
        conn.execute("UPDATE settings SET value='',updated_at=? WHERE key='business_state_code'", (now,))
        conn.execute("UPDATE branches SET name='Main Showroom',gstin='',address='',phone='' WHERE id=?", (branch["id"],))

    now = utcnow()
    defaults = {
        "company_setup_complete": "0",
        "business_email": "",
        "business_state_name": "",
        "business_pincode": "",
    }
    for key, value in defaults.items():
        conn.execute("INSERT OR IGNORE INTO settings(key,value,updated_at) VALUES(?,?,?)", (key, value, now))

    if not old_seed:
        configured = conn.execute("SELECT value FROM settings WHERE key='business_name'").fetchone()
        current = str(configured[0] if configured else '').strip()
        if current and current not in ("My Jewellery Store", "Bijoria"):
            conn.execute("UPDATE settings SET value='1',updated_at=? WHERE key='company_setup_complete'", (now,))


MIGRATIONS = ((1, _migration_1), (2, _migration_2), (3, _migration_3), (4, _migration_4), (5, _migration_5), (6, _migration_6))'''
    text = replace_once(text, migration_marker, migration6, 'migration 6')

    old_init = '''        conn.executescript(SCHEMA); _migrate_schema(conn); _ensure_optional_indexes(conn); now=utcnow(); conn.execute("INSERT OR IGNORE INTO branches(code,name,gstin,address,phone,active) VALUES('MAIN','Bijoria Main Showroom','','','',1)"); branch_id=conn.execute("SELECT id FROM branches WHERE code='MAIN'").fetchone()[0]; conn.execute("INSERT OR IGNORE INTO counters(branch_id,name,active) VALUES(?,'Counter 1',1)",(branch_id,)); conn.execute("INSERT OR IGNORE INTO counters(branch_id,name,active) VALUES(?,'Counter 2',1)",(branch_id,)); conn.execute("INSERT OR IGNORE INTO counters(branch_id,name,active) VALUES(?,'Counter 3',1)",(branch_id,))
'''
    new_init = '''        conn.executescript(SCHEMA); _migrate_schema(conn); _ensure_optional_indexes(conn); now=utcnow(); conn.execute("INSERT OR IGNORE INTO branches(code,name,gstin,address,phone,active) VALUES('MAIN','Main Showroom','','','',1)"); branch_id=conn.execute("SELECT id FROM branches WHERE code='MAIN'").fetchone()[0]; conn.execute("INSERT OR IGNORE INTO counters(branch_id,name,active) VALUES(?,'Counter 1',1)",(branch_id,))
'''
    text = replace_once(text, old_init, new_init, 'generic main branch')

    old_defaults = '''        defaults={"business_name":"Bijoria","business_address":"","business_phone":"","business_gstin":"","business_timezone_offset_minutes":"330","currency":"INR","invoice_prefix":"INV","tag_prefix":"TAG","gst_default":"3","label_width_mm":"60","label_height_mm":"25","backup_interval_hours":"6","backup_retention_days":"30","business_state_code":"36","tally_enabled":"0","tally_bridge_url":"http://127.0.0.1:8767","tally_bridge_token":"","tally_company":"","tally_auto_create_parties":"1"}
'''
    new_defaults = '''        defaults={"business_name":"","business_address":"","business_phone":"","business_email":"","business_gstin":"","business_state_code":"","business_state_name":"","business_pincode":"","company_setup_complete":"0","business_timezone_offset_minutes":"330","currency":"INR","invoice_prefix":"INV","tag_prefix":"TAG","gst_default":"3","label_width_mm":"60","label_height_mm":"25","backup_interval_hours":"6","backup_retention_days":"30","tally_enabled":"0","tally_bridge_url":"http://127.0.0.1:8767","tally_bridge_token":"","tally_company":"","tally_auto_create_parties":"1"}
'''
    text = replace_once(text, old_defaults, new_defaults, 'generic company defaults')
    path.write_text(text, "utf-8")


def write_company_module() -> None:
    path = ROOT / "jewel_server" / "company.py"
    path.write_text(r'''from __future__ import annotations

import re

from .db import audit, get_settings, set_setting

GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
PREFIX_RE = re.compile(r"^[A-Z0-9/-]{1,12}$")


def get_company(conn) -> dict:
    settings = get_settings(conn)
    branch = conn.execute("SELECT * FROM branches WHERE code='MAIN'").fetchone()
    counters = conn.execute("SELECT * FROM counters WHERE branch_id=? AND active=1 ORDER BY id", (branch['id'],)).fetchall() if branch else []
    return {
        "configured": str(settings.get("company_setup_complete", "0")).lower() in ("1", "true", "yes", "on"),
        "settings": settings,
        "branch": dict(branch) if branch else None,
        "counters": [dict(x) for x in counters],
        "counter_count": len(counters),
    }


def _prefix(value, field: str) -> str:
    out = str(value or '').strip().upper()
    if not PREFIX_RE.fullmatch(out):
        raise ValueError(f"{field} must be 1-12 letters/numbers and may contain / or -")
    return out


def save_company(conn, payload: dict, user_id: int) -> dict:
    name = str(payload.get("business_name") or '').strip()
    if not name or len(name) > 120:
        raise ValueError("Company name is required and must be 120 characters or fewer")
    branch_name = str(payload.get("branch_name") or "Main Showroom").strip()
    if not branch_name or len(branch_name) > 120:
        raise ValueError("Main branch/showroom name is required")

    state_code = str(payload.get("business_state_code") or '').strip()
    if not re.fullmatch(r"[0-9]{2}", state_code):
        raise ValueError("GST state code must be exactly two digits")
    gstin = str(payload.get("business_gstin") or '').strip().upper()
    if gstin and not GSTIN_RE.fullmatch(gstin):
        raise ValueError("GSTIN must be a valid 15-character GSTIN")
    if gstin and gstin[:2] != state_code:
        raise ValueError("GSTIN state code does not match the company state code")

    pincode = str(payload.get("business_pincode") or '').strip()
    if pincode and not re.fullmatch(r"[0-9]{6}", pincode):
        raise ValueError("PIN code must be six digits")
    try:
        counter_count = int(payload.get("counter_count") or 1)
        timezone = int(payload.get("business_timezone_offset_minutes") or 330)
        gst_default = float(payload.get("gst_default") or 0)
    except (TypeError, ValueError):
        raise ValueError("Counter count, timezone and GST rate must be numeric")
    if not 1 <= counter_count <= 20:
        raise ValueError("Counter count must be between 1 and 20")
    if not -720 <= timezone <= 840:
        raise ValueError("Timezone offset is outside the supported range")
    if not 0 <= gst_default <= 100:
        raise ValueError("Default GST rate must be between 0 and 100")

    invoice_prefix = _prefix(payload.get("invoice_prefix") or "INV", "Invoice prefix")
    tag_prefix = _prefix(payload.get("tag_prefix") or "TAG", "Tag prefix")
    fields = {
        "business_name": name,
        "business_address": str(payload.get("business_address") or '').strip(),
        "business_phone": str(payload.get("business_phone") or '').strip(),
        "business_email": str(payload.get("business_email") or '').strip(),
        "business_gstin": gstin,
        "business_state_code": state_code,
        "business_state_name": str(payload.get("business_state_name") or '').strip(),
        "business_pincode": pincode,
        "business_timezone_offset_minutes": str(timezone),
        "invoice_prefix": invoice_prefix,
        "tag_prefix": tag_prefix,
        "gst_default": (f"{gst_default:g}"),
        "company_setup_complete": "1",
    }
    for key, value in fields.items():
        set_setting(conn, key, value)

    branch = conn.execute("SELECT * FROM branches WHERE code='MAIN'").fetchone()
    if not branch:
        cur = conn.execute(
            "INSERT INTO branches(code,name,gstin,address,phone,active) VALUES('MAIN',?,?,?,?,1)",
            (branch_name, gstin, fields['business_address'], fields['business_phone']),
        )
        branch_id = int(cur.lastrowid)
    else:
        branch_id = int(branch['id'])
        conn.execute(
            "UPDATE branches SET name=?,gstin=?,address=?,phone=?,active=1 WHERE id=?",
            (branch_name, gstin, fields['business_address'], fields['business_phone'], branch_id),
        )

    for number in range(1, counter_count + 1):
        counter_name = f"Counter {number}"
        conn.execute(
            "INSERT INTO counters(branch_id,name,active) VALUES(?,?,1) ON CONFLICT(branch_id,name) DO UPDATE SET active=1",
            (branch_id, counter_name),
        )

    # Reduce unused generic counters when an administrator lowers the configured
    # count.  Referenced counters are deliberately retained for audit/history.
    for row in conn.execute("SELECT id,name FROM counters WHERE branch_id=? AND active=1", (branch_id,)).fetchall():
        match = re.fullmatch(r"Counter ([0-9]+)", str(row['name']))
        if not match or int(match.group(1)) <= counter_count:
            continue
        cid = int(row['id'])
        used = any(
            conn.execute(f"SELECT 1 FROM {table} WHERE counter_id=? LIMIT 1", (cid,)).fetchone()
            for table in ("items", "sales", "stock_audits")
        )
        if not used:
            conn.execute("UPDATE counters SET active=0 WHERE id=?", (cid,))

    audit(conn, user_id, "update", "company_settings", branch_id, {**fields, "branch_name": branch_name, "counter_count": counter_count})
    return get_company(conn)
''', "utf-8")


def patch_server_main() -> None:
    path = ROOT / "jewel_server" / "main.py"
    text = path.read_text("utf-8")
    text = replace_once(text, "from .backup import BackupWorker,backup_status,create_backup,list_backups,restore_backup,verify_backup\n", "from .backup import BackupWorker,backup_status,create_backup,list_backups,restore_backup,verify_backup\nfrom .company import get_company,save_company\n", "company import")
    text = replace_once(text, "APP_VERSION='1.2.0-rc1'", "APP_VERSION='1.2.0-rc3'", "server version")
    old_allowed = "allowed={'business_name','business_address','business_phone','business_gstin','business_state_code','business_timezone_offset_minutes','currency','invoice_prefix','tag_prefix','gst_default','label_width_mm','label_height_mm','backup_interval_hours','backup_retention_days','tally_enabled','tally_bridge_url','tally_bridge_token','tally_company','tally_auto_create_parties'}"
    new_allowed = "allowed={'business_name','business_address','business_phone','business_email','business_gstin','business_state_code','business_state_name','business_pincode','business_timezone_offset_minutes','currency','invoice_prefix','tag_prefix','gst_default','label_width_mm','label_height_mm','backup_interval_hours','backup_retention_days','tally_enabled','tally_bridge_url','tally_bridge_token','tally_company','tally_auto_create_parties'}"
    text = replace_once(text, old_allowed, new_allowed, "settings allowlist")
    marker = "    return {'ok':True}\n@app.get('/api/users')"
    company_routes = '''    return {'ok':True}\n\n@app.get('/api/company')\ndef company_settings(u=Depends(current_user)):\n    with read_db() as c:return get_company(c)\n\n@app.put('/api/company')\ndef company_settings_save(p:dict=Body(...),u=Depends(require('*'))):\n    try:\n        with write_db() as c:return save_company(c,p,u['id'])\n    except ValueError as e:raise HTTPException(400,str(e))\n\n@app.get('/api/users')'''
    text = replace_once(text, marker, company_routes, "company routes")
    path.write_text(text, "utf-8")


def patch_client_main() -> None:
    path = ROOT / "jewel_client" / "main.py"
    text = path.read_text("utf-8")
    password_marker = "    return True\n\n\n\n\nclass LoginDialog"
    setup_code = '''    return True\n\n\ndef ensure_company_setup(root,api):\n    try:data=api.get('/api/company')\n    except Exception as e:\n        messagebox.showerror('Company setup',str(e),parent=root);return False\n    if data.get('configured'):return True\n    settings=data.get('settings',{});branch=data.get('branch') or {}\n    defaults={**settings,'branch_name':branch.get('name','Main Showroom'),'counter_count':str(data.get('counter_count') or 1)}\n    fields=[('business_name','Company name'),('branch_name','Main branch / showroom name'),('business_state_code','GST state code (2 digits)'),('business_state_name','State name'),('business_gstin','GSTIN (optional)'),('business_address','Address'),('business_pincode','PIN code'),('business_phone','Phone'),('business_email','Email'),('counter_count','Number of counters'),('invoice_prefix','Invoice prefix'),('tag_prefix','Tag prefix'),('gst_default','Default GST %'),('business_timezone_offset_minutes','Timezone offset minutes')]\n    while True:\n        values=form_dialog(root,'Company setup',fields,defaults)\n        if not values:return False\n        try:\n            values['counter_count']=int(values.get('counter_count') or 1);api.put('/api/company',values);messagebox.showinfo('Company setup','Company settings saved. JewelLAN is ready for shop configuration.',parent=root);return True\n        except Exception as e:\n            messagebox.showerror('Company setup',str(e),parent=root);defaults.update(values)\n\n\nclass LoginDialog'''
    text = replace_once(text, password_marker, setup_code, "first-run company setup")

    old_label = '        ttk.Label(nav, text=self.settings.get("business_name", "Jewellery Store"), style="NavMuted.TLabel", wraplength=180).pack(anchor="w", padx=18, pady=(0, 18))'
    new_label = '        self.company_label=ttk.Label(nav, text=self.settings.get("business_name") or "Company not configured", style="NavMuted.TLabel", wraplength=180);self.company_label.pack(anchor="w", padx=18, pady=(0, 18))'
    text = replace_once(text, old_label, new_label, "navigation company label")

    pattern = re.compile(r"    def make_business\(self\):\n.*?    def save_business\(self\):\n.*?(?=\n\n\ndef main\(\):)", re.S)
    if not pattern.search(text):
        raise RuntimeError("Business settings methods not found")
    replacement = '''    def make_business(self):\n        f=ttk.Frame(self.nb,padding=12);self.nb.add(f,text="Company settings");self.bv={}\n        try:d=self.api.get('/api/company')\n        except Exception as e:d={'settings':self.app.settings,'branch':{},'counter_count':len(self.app.counters)};self.app.error(e)\n        s=d.get('settings',{});branch=d.get('branch') or {}\n        fields=[('business_name','Company name',s.get('business_name','')),('branch_name','Main branch / showroom',branch.get('name','Main Showroom')),('business_state_code','GST state code',s.get('business_state_code','')),('business_state_name','State name',s.get('business_state_name','')),('business_gstin','GSTIN',s.get('business_gstin','')),('business_address','Address',s.get('business_address','')),('business_pincode','PIN code',s.get('business_pincode','')),('business_phone','Phone',s.get('business_phone','')),('business_email','Email',s.get('business_email','')),('counter_count','Number of counters',str(d.get('counter_count') or 1)),('invoice_prefix','Invoice prefix',s.get('invoice_prefix','INV')),('tag_prefix','Tag prefix',s.get('tag_prefix','TAG')),('gst_default','Default GST %',s.get('gst_default','3')),('business_timezone_offset_minutes','Timezone offset minutes',s.get('business_timezone_offset_minutes','330'))]\n        ttk.Label(f,text='These values belong to the company database and appear on invoices/reports. They are not hard-coded into JewelLAN.',style='SurfaceMuted.TLabel',wraplength=900).grid(row=0,column=0,columnspan=2,sticky='w',pady=(0,10))\n        for i,(k,label,value) in enumerate(fields,1):self.bv[k]=tk.StringVar(value=str(value));ttk.Label(f,text=label).grid(row=i,column=0,sticky='w',pady=3);ttk.Entry(f,textvariable=self.bv[k]).grid(row=i,column=1,sticky='ew',padx=8)\n        f.columnconfigure(1,weight=1);ttk.Button(f,text="Save company settings",style='Primary.TButton',command=self.save_business).grid(row=len(fields)+2,column=0,columnspan=2,sticky="ew",pady=12)\n    def save_business(self):\n        try:\n            p={k:v.get() for k,v in self.bv.items()};p['counter_count']=int(p.get('counter_count') or 1);r=self.api.put('/api/company',p);self.app.load_settings();self.app.company_label.configure(text=self.app.settings.get('business_name') or 'Company not configured');messagebox.showinfo('Company settings','Saved',parent=self)\n        except Exception as e:self.app.error(e)\n'''
    text = pattern.sub(replacement.rstrip(), text, count=1)

    main_marker = "    if login.user.get(\"must_change_password\") and not force_initial_password_change(root,api,login.user):return\n    root.deiconify();App(root,api,cfg,login.user);root.mainloop()"
    main_new = "    if login.user.get(\"must_change_password\") and not force_initial_password_change(root,api,login.user):return\n    if not ensure_company_setup(root,api):return\n    root.deiconify();App(root,api,cfg,login.user);root.mainloop()"
    text = replace_once(text, main_marker, main_new, "main company setup gate")
    path.write_text(text, "utf-8")


def patch_tests() -> None:
    path = ROOT / "tests" / "test_core.py"
    text = path.read_text("utf-8")
    if "def test_company_settings_are_generic_and_configurable" in text:
        return
    text += r'''


def test_company_settings_are_generic_and_configurable():
    with TestClient(app) as c:
        h = auth_headers(c)
        before = c.get("/api/company", headers=h)
        assert before.status_code == 200, before.text
        company = before.json()
        assert company["settings"].get("business_name", "") != "Bijoria"
        assert (company.get("branch") or {}).get("name", "") != "Bijoria Main Showroom"

        saved = c.put("/api/company", headers=h, json={
            "business_name": "Test Jewellers",
            "branch_name": "Main Showroom",
            "business_state_code": "36",
            "business_state_name": "Telangana",
            "business_gstin": "",
            "business_address": "Test Address",
            "business_pincode": "500001",
            "business_phone": "0400000000",
            "business_email": "accounts@example.test",
            "counter_count": 3,
            "invoice_prefix": "INV",
            "tag_prefix": "TAG",
            "gst_default": "3",
            "business_timezone_offset_minutes": "330",
        })
        assert saved.status_code == 200, saved.text
        result = saved.json()
        assert result["configured"] is True
        assert result["settings"]["business_name"] == "Test Jewellers"
        assert result["settings"]["business_state_code"] == "36"
        assert result["branch"]["name"] == "Main Showroom"
        assert len(result["counters"]) == 3
'''
    path.write_text(text, "utf-8")


def patch_installer() -> None:
    path = ROOT / "installer" / "JewelLAN.iss"
    text = path.read_text("utf-8")
    text = replace_once(text, '#define MyAppVersion "1.2.0-rc2"', '#define MyAppVersion "1.2.0-rc3"', 'installer rc3')
    text = replace_once(text, '#define MyFileVersion "1.2.0.1"', '#define MyFileVersion "1.2.0.2"', 'installer file version')
    path.write_text(text, "utf-8")


def write_docs() -> None:
    path = ROOT / "docs" / "COMPANY_SETTINGS.md"
    path.write_text('''# Company settings\n\nJewelLAN installers are company-neutral. A fresh database contains no shop name, GSTIN or GST state code. After the administrator changes the initial password, the desktop client requires Company Setup before the normal application opens.\n\nCompany Setup stores the company name, main branch/showroom, GST state code, optional GSTIN, address, PIN, phone, email, counter count, invoice/tag prefixes, GST default and business timezone in the server database. These values are editable later under **Administration > Company settings**.\n\nThe RC1/RC2 Bijoria seed was a release-candidate mistake. Schema migration 6 removes it only from untouched databases that still exactly match that obsolete seed; databases containing business data or a customized company name are never renamed.\n''', 'utf-8')


def main() -> None:
    patch_db()
    write_company_module()
    patch_server_main()
    patch_client_main()
    patch_tests()
    patch_installer()
    write_docs()


if __name__ == '__main__':
    main()
