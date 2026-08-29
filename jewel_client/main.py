from __future__ import annotations

import datetime as dt
import os
import tempfile
import uuid
import webbrowser
from pathlib import Path
from typing import Any
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from .api import Api, ApiError, discover_servers, format_fingerprint, probe_server_fingerprint, secure_url
from .config import load_config, save_config
from .scale import read_scale
from .ui_theme import PALETTE, apply_theme, card, divider, status_pill
from .returns_page import ReturnsPage

APP_TITLE = "JewelLAN Jewellery ERP"
PRODUCTION_HARDENED_V1 = True


def money(v: Any) -> str:
    try:
        return f"₹{float(v):,.2f}"
    except Exception:
        return "₹0.00"


def open_pdf(data: bytes, name: str):
    p = Path(tempfile.gettempdir()) / name
    p.write_bytes(data)
    if os.name == "nt":
        os.startfile(str(p))
    else:
        webbrowser.open(p.as_uri())


def center(win, w=520, h=400):
    win.update_idletasks()
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    win.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")


def form_dialog(parent, title, fields, defaults=None):
    defaults = defaults or {}
    d = tk.Toplevel(parent)
    d.title(title)
    d.configure(bg=PALETTE["bg"])
    screen_h = max(480, d.winfo_screenheight())
    desired_h = 190 + len(fields) * 44
    dialog_h = min(max(460, desired_h), max(460, screen_h - 120), 760)
    center(d, 620, dialog_h)
    d.minsize(520, min(460, dialog_h)); d.transient(parent); d.grab_set(); d.resizable(True, True)

    shell = ttk.Frame(d, style="Surface.TFrame", padding=22)
    shell.pack(fill="both", expand=True, padx=18, pady=18)
    ttk.Label(shell, text=title, style="Section.TLabel", font=("Segoe UI Semibold", 15)).pack(anchor="w", pady=(0, 12))

    body = ttk.Frame(shell, style="Surface.TFrame")
    body.pack(fill="both", expand=True)
    canvas = tk.Canvas(body, bg=PALETTE["surface"], highlightthickness=0, borderwidth=0)
    scroll = ttk.Scrollbar(body, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=scroll.set)
    scroll.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    form = ttk.Frame(canvas, style="Surface.TFrame", padding=(0, 2, 8, 2))
    window_id = canvas.create_window((0, 0), window=form, anchor="nw")
    form.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window_id, width=e.width))

    vars_ = {}; result = {"value": None}; first_widget = None
    for i, spec in enumerate(fields):
        key, label = spec[0], spec[1]; values = spec[2] if len(spec) > 2 else None
        v = tk.StringVar(value=str(defaults.get(key, "") if defaults.get(key) is not None else "")); vars_[key] = v
        ttk.Label(form, text=label, style="SurfaceMuted.TLabel").grid(row=i, column=0, sticky="w", pady=5)
        widget = ttk.Combobox(form, textvariable=v, values=values, state="readonly") if values else ttk.Entry(form, textvariable=v)
        widget.grid(row=i, column=1, sticky="ew", padx=(16, 0), pady=5)
        if values and not v.get() and values: v.set(values[0])
        if first_widget is None: first_widget = widget
    form.columnconfigure(1, weight=1)

    def save():
        result["value"] = {k: v.get().strip() for k, v in vars_.items()}; d.destroy()

    divider(shell).pack(fill="x", pady=(12, 10))
    buttons = ttk.Frame(shell, style="Surface.TFrame")
    buttons.pack(fill="x")
    ttk.Label(buttons, text="Ctrl+Enter saves", style="SurfaceMuted.TLabel").pack(side="left")
    cancel_button = ttk.Button(buttons, text="Cancel", style="Secondary.TButton", command=d.destroy)
    cancel_button.pack(side="right")
    save_button = ttk.Button(buttons, text="Save", style="Primary.TButton", command=save)
    save_button.pack(side="right", padx=(0, 8))
    d.save_button = save_button
    d.cancel_button = cancel_button
    d.form_canvas = canvas

    def on_wheel(event):
        if canvas.bbox("all") and canvas.winfo_height() < form.winfo_reqheight():
            canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    d.bind("<MouseWheel>", on_wheel)
    d.bind("<Escape>", lambda _e: d.destroy())
    d.bind("<Control-Return>", lambda _e: save())
    if first_widget is not None: first_widget.focus_set()
    parent.wait_window(d)
    return result["value"]

def password_change_dialog(parent, title="Change password", forced=False):
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


def ensure_company_setup(root,api):
    try:data=api.get('/api/company')
    except Exception as e:
        messagebox.showerror('Company setup',str(e),parent=root);return False
    if data.get('configured'):return True
    settings=data.get('settings',{});branch=data.get('branch') or {}
    defaults={**settings,'branch_name':branch.get('name','Main Showroom'),'counter_count':str(data.get('counter_count') or 1)}
    fields=[('business_name','Company name'),('branch_name','Main branch / showroom name'),('business_state_code','GST state code (2 digits)'),('business_state_name','State name'),('business_gstin','GSTIN (optional)'),('business_address','Address'),('business_pincode','PIN code'),('business_phone','Phone'),('business_email','Email'),('counter_count','Number of counters'),('invoice_prefix','Invoice prefix'),('tag_prefix','Tag prefix'),('gst_default','Default GST %'),('business_timezone_offset_minutes','Timezone offset minutes')]
    while True:
        values=form_dialog(root,'Company setup',fields,defaults)
        if not values:return False
        try:
            values['counter_count']=int(values.get('counter_count') or 1);api.put('/api/company',values);messagebox.showinfo('Company setup','Company settings saved. JewelLAN is ready for shop configuration.',parent=root);return True
        except Exception as e:
            messagebox.showerror('Company setup',str(e),parent=root);defaults.update(values)


class LoginDialog(tk.Toplevel):
    def __init__(self, master, api: Api, cfg: dict):
        super().__init__(master); self.api = api; self.cfg = cfg; self.user = None
        apply_theme(self)
        self.title("JewelLAN — Sign in")
        self.resizable(False, False); center(self, 760, 470); self.protocol("WM_DELETE_WINDOW", master.destroy)

        shell = tk.Frame(self, bg=PALETTE["bg"]); shell.pack(fill="both", expand=True)
        brand = tk.Frame(shell, bg=PALETTE["nav"], width=285); brand.pack(side="left", fill="y"); brand.pack_propagate(False)
        tk.Label(brand, text="JEWELLAN", bg=PALETTE["nav"], fg="#FFFFFF", font=("Segoe UI Semibold", 23)).pack(anchor="w", padx=28, pady=(46, 4))
        tk.Label(brand, text="Jewellery operations,\nwithout the cloud.", justify="left", bg=PALETTE["nav"], fg="#D7DAE0", font=("Segoe UI", 13)).pack(anchor="w", padx=28, pady=(0, 26))
        tk.Label(brand, text="• Billing and barcode tagging\n• Local LAN multi-counter\n• TallyPrime bridge\n• Offline backups", justify="left", bg=PALETTE["nav"], fg="#9EA4AF", font=("Segoe UI", 10), pady=4).pack(anchor="w", padx=28)
        tk.Label(brand, text="No internet required", bg="#26352F", fg="#BCE3CD", font=("Segoe UI Semibold", 9), padx=10, pady=5).pack(anchor="w", padx=28, pady=(38, 0))

        right = ttk.Frame(shell, style="Surface.TFrame", padding=32); right.pack(side="left", fill="both", expand=True, padx=(22, 26), pady=28)
        ttk.Label(right, text="Welcome back", style="Section.TLabel", font=("Segoe UI Semibold", 19)).pack(anchor="w")
        ttk.Label(right, text="Sign in to this shop's private LAN.", style="SurfaceMuted.TLabel").pack(anchor="w", pady=(3, 20))
        self.server = tk.StringVar(value=secure_url(cfg.get("server_url") or "https://127.0.0.1:8765")); self.discovered_fingerprint = ""
        self.username = tk.StringVar(value="admin"); self.password = tk.StringVar()
        frm = ttk.Frame(right, style="Surface.TFrame"); frm.pack(fill="x")
        for r, (label, var) in enumerate((("Server", self.server), ("Username", self.username), ("Password", self.password))):
            ttk.Label(frm, text=label, style="SurfaceMuted.TLabel").grid(row=r*2, column=0, columnspan=2, sticky="w", pady=(6, 4))
            e = ttk.Entry(frm, textvariable=var, show="●" if label == "Password" else "", font=("Segoe UI", 10))
            e.grid(row=r*2+1, column=0, sticky="ew", ipady=3)
            if label == "Server": ttk.Button(frm, text="Discover", style="Secondary.TButton", command=self.discover).grid(row=r*2+1, column=1, padx=(8,0))
            if label == "Password": e.bind("<Return>", lambda _e: self.login()); e.focus_set()
        frm.columnconfigure(0, weight=1)
        self.status = tk.StringVar(value="Server discovery is available on the private LAN.")
        ttk.Label(right, textvariable=self.status, style="SurfaceMuted.TLabel", wraplength=390).pack(anchor="w", pady=(12, 12))
        ttk.Button(right, text="Sign in", style="Primary.TButton", command=self.login).pack(fill="x", ipady=3)

    def _trust_live_server(self, url, advertised_fingerprint=""):
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

class Page(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent); self.app = app; self.api = app.api
    def heading(self, title, sub=""):
        head = ttk.Frame(self); head.pack(fill="x", pady=(0, 14))
        ttk.Label(head, text=title, style="PageTitle.TLabel").pack(anchor="w")
        if sub: ttk.Label(head, text=sub, style="Muted.TLabel").pack(anchor="w", pady=(3, 0))
        divider(self).pack(fill="x", pady=(0, 12))
    def tree(self, parent, cols, widths=None):
        widths = widths or {}; t = ttk.Treeview(parent, columns=cols, show="headings", selectmode="browse")
        for c in cols:
            t.heading(c, text=c.replace("_", " ").title())
            t.column(c, width=widths.get(c, 115), minwidth=70, anchor="e" if any(x in c for x in ("weight","amount","total","rate","gst","cost","paid")) else "w")
        s = ttk.Scrollbar(parent, orient="vertical", command=t.yview); t.configure(yscrollcommand=s.set)
        s.pack(side="right", fill="y"); t.pack(side="left", fill="both", expand=True); return t
    def toolbar(self):
        f = ttk.Frame(self); f.pack(fill="x", pady=(0, 10)); return f

class App(ttk.Frame):
    def __init__(self, root, api, cfg, user):
        apply_theme(root)
        super().__init__(root); self.root = root; self.api = api; self.cfg = cfg; self.user = user; self.settings = {}; self.branches = []; self.counters = []; self.nav_buttons = {}; self.current_page = None
        self.pack(fill="both", expand=True); root.title(f"{APP_TITLE} — {user['full_name']}"); root.minsize(1180, 720)
        if os.name == "nt": root.state("zoomed")
        else: root.geometry("1360x850")
        self.load_settings(); self.build()

    def load_settings(self):
        d = self.api.get("/api/settings"); self.settings, self.branches, self.counters = d["settings"], d["branches"], d["counters"]

    def build(self):
        body = tk.Frame(self, bg=PALETTE["bg"]); body.pack(fill="both", expand=True)
        nav = ttk.Frame(body, style="Nav.TFrame", width=220); nav.pack(side="left", fill="y"); nav.pack_propagate(False)
        ttk.Label(nav, text="JewelLAN", style="NavBrand.TLabel").pack(anchor="w", padx=18, pady=(22, 2))
        self.company_label=ttk.Label(nav, text=self.settings.get("business_name") or "Company not configured", style="NavMuted.TLabel", wraplength=180);self.company_label.pack(anchor="w", padx=18, pady=(0, 18))

        role = self.user.get("role", "cashier")
        pages = [("Overview", DashboardPage), ("Inventory", InventoryPage), ("Parties", PartiesPage)]
        if role in ("admin","manager","cashier"): pages.insert(1, ("Billing", POSPage))
        if role in ("admin","manager"): pages.insert(2, ("Returns & Credit Notes", ReturnsPage))
        if role in ("admin","manager","inventory"): pages.append(("Purchases", PurchasesPage))
        if role in ("admin","manager","cashier"): pages.append(("Repairs & Orders", JobsPage))
        if role in ("admin","manager","inventory"): pages.append(("Stock Audit", StockAuditPage))
        if role in ("admin","manager","accounts"): pages.append(("Reports", ReportsPage))
        if role in ("admin","manager"): pages.append(("TallyPrime", TallyPage)); pages.append(("Administration", AdminPage))
        for name, cls in pages:
            b = ttk.Button(nav, text=name, style="Nav.TButton", command=lambda c=cls,n=name: self.show(c,n)); b.pack(fill="x", padx=10, pady=1); self.nav_buttons[name] = b

        bottom = ttk.Frame(nav, style="Nav.TFrame"); bottom.pack(side="bottom", fill="x", padx=10, pady=12)
        divider(bottom).pack(fill="x", pady=(0, 10))
        ttk.Label(bottom, text=self.user.get("full_name","User"), style="NavUser.TLabel").pack(anchor="w", padx=8)
        ttk.Label(bottom, text=self.user.get("role","" ).title(), style="NavMuted.TLabel").pack(anchor="w", padx=8, pady=(0,6))
        ttk.Button(bottom, text="Change password", style="Nav.TButton", command=self.change_password).pack(fill="x")
        ttk.Button(bottom, text="Exit", style="Nav.TButton", command=self.root.destroy).pack(fill="x")

        work = ttk.Frame(body); work.pack(side="left", fill="both", expand=True)
        top = ttk.Frame(work, style="Surface.TFrame", padding=(20, 10)); top.pack(fill="x")
        self.top_title = ttk.Label(top, text="Overview", style="Surface.TLabel", font=("Segoe UI Semibold", 12)); self.top_title.pack(side="left")
        status_pill(top, f"LAN  {self.api.base_url.replace('http://','')}", "success").pack(side="right")
        self.content = ttk.Frame(work, padding=(22, 18)); self.content.pack(fill="both", expand=True)
        self.show(DashboardPage, "Overview")

    def show(self, cls, name=None):
        for w in self.content.winfo_children(): w.destroy()
        for b in self.nav_buttons.values(): b.configure(style="Nav.TButton")
        if name and name in self.nav_buttons: self.nav_buttons[name].configure(style="NavActive.TButton")
        if name: self.top_title.configure(text=name)
        self.current_page = cls(self.content, self); self.current_page.pack(fill="both", expand=True)

    def error(self, e): messagebox.showerror("JewelLAN", str(e), parent=self.root)

    def change_password(self, forced=False):
        data=password_change_dialog(self.root,"Change password",forced)
        if not data:return
        if len(data["new_password"])<10:self.error("New password must be at least 10 characters");return
        if data["new_password"]!=data["again"]:self.error("New passwords do not match");return
        try:self.api.post("/api/auth/change-password",{"old_password":data["old_password"],"new_password":data["new_password"]});self.user["must_change_password"]=0;messagebox.showinfo("Password","Password changed.",parent=self.root)
        except Exception as e:self.error(e)

class DashboardPage(Page):
    def __init__(self, parent, app):
        super().__init__(parent, app); self.heading("Shop overview", "Today's billing, stock position, rates and operational health from the local server.")
        self.metrics = ttk.Frame(self); self.metrics.pack(fill="x")
        lower = ttk.Frame(self); lower.pack(fill="both", expand=True, pady=(14,0))
        self.rates_card = card(lower, 18); self.rates_card.pack(side="left", fill="both", expand=True, padx=(0,7))
        self.stock_card = card(lower, 18); self.stock_card.pack(side="left", fill="both", expand=True, padx=7)
        self.health_card = card(lower, 18); self.health_card.pack(side="left", fill="both", expand=True, padx=(7,0))
        self.refresh()

    def metric(self, label, value, note=""):
        f = card(self.metrics, 16); f.pack(side="left", fill="x", expand=True, padx=(0,10))
        ttk.Label(f, text=label.upper(), style="SurfaceMuted.TLabel", font=("Segoe UI Semibold", 8)).pack(anchor="w")
        ttk.Label(f, text=str(value), style="Metric.TLabel").pack(anchor="w", pady=(7,2))
        if note: ttk.Label(f, text=note, style="SurfaceMuted.TLabel", font=("Segoe UI", 8)).pack(anchor="w")

    def refresh(self):
        try: d = self.api.get("/api/dashboard")
        except Exception as e: self.app.error(e); return
        for parent in (self.metrics,self.rates_card,self.stock_card,self.health_card):
            for w in parent.winfo_children(): w.destroy()
        self.metric("Today's sales", money(d["today_sales"]["total"]), f"{d['today_sales'].get('c',0)} invoices")
        self.metric("Stock pieces", d["stock"]["c"], "Serialized tags in stock")
        self.metric("Net stock", f"{d['stock']['nw']:.3f} g", "Across all metals")
        self.metric("Pending work", d["pending_repairs"] + d["pending_orders"], "Repairs + custom orders")

        ttk.Label(self.rates_card, text="Metal rates", style="Section.TLabel").pack(anchor="w")
        ttk.Label(self.rates_card, text="Current shop pricing rates", style="SurfaceMuted.TLabel").pack(anchor="w", pady=(2,10))
        if not d["rates"]: ttk.Label(self.rates_card, text="No metal rates configured", style="SurfaceMuted.TLabel").pack(anchor="w")
        for x in d["rates"][:8]:
            row=ttk.Frame(self.rates_card, style="Surface.TFrame"); row.pack(fill="x", pady=4)
            ttk.Label(row, text=f"{x['metal']} {x['purity']}", style="Surface.TLabel").pack(side="left")
            ttk.Label(row, text=money(x['rate_per_gram'])+" / g", style="Surface.TLabel", font=("Segoe UI Semibold",10)).pack(side="right")

        ttk.Label(self.stock_card, text="Stock mix", style="Section.TLabel").pack(anchor="w")
        ttk.Label(self.stock_card, text="Top inventory categories", style="SurfaceMuted.TLabel").pack(anchor="w", pady=(2,10))
        if not d["categories"]: ttk.Label(self.stock_card, text="No stock yet", style="SurfaceMuted.TLabel").pack(anchor="w")
        for x in d["categories"][:8]:
            row=ttk.Frame(self.stock_card, style="Surface.TFrame"); row.pack(fill="x", pady=4)
            ttk.Label(row, text=x['category'], style="Surface.TLabel").pack(side="left")
            status_pill(row, f"{x['c']} pcs", "accent").pack(side="right")

        ttk.Label(self.health_card, text="Operations", style="Section.TLabel").pack(anchor="w")
        ttk.Label(self.health_card, text="Local services and shortcuts", style="SurfaceMuted.TLabel").pack(anchor="w", pady=(2,10))
        status_pill(self.health_card, "LAN server connected", "success").pack(anchor="w", pady=3)
        try:
            ts=self.api.get('/api/tally/status'); bridge=ts.get('bridge'); q=ts.get('queue',{})
            status_pill(self.health_card, "Tally bridge connected" if bridge and bridge.get('ok') else "Tally bridge offline", "success" if bridge and bridge.get('ok') else "warning").pack(anchor="w", pady=3)
            ttk.Label(self.health_card, text=f"Tally queue: {q.get('pending',0)} pending · {q.get('failed',0)} failed", style="SurfaceMuted.TLabel").pack(anchor="w", pady=(2,10))
        except Exception:
            ttk.Label(self.health_card, text="Tally status unavailable for this role", style="SurfaceMuted.TLabel").pack(anchor="w", pady=(2,10))
        if self.app.user.get('role') in ('admin','manager','cashier'):
            ttk.Button(self.health_card, text="Open billing", style="Primary.TButton", command=lambda:self.app.show(POSPage,"Billing")).pack(fill="x", pady=(4,5))
        ttk.Button(self.health_card, text="Open inventory", style="Secondary.TButton", command=lambda:self.app.show(InventoryPage,"Inventory")).pack(fill="x")

class InventoryPage(Page):
    COLS = ("tag_no","name","metal","purity","gross_weight","net_weight","huid","status","cost_amount")
    FIELDS = [("name","Item name"),("category","Category"),("metal","Metal",["Gold","Silver","Platinum","Other"]),("purity","Purity",["999","995","958","925","916","875","833","750","585","417"]),("gross_weight","Gross weight (g)"),("stone_weight","Stone weight (g)"),("net_weight","Net weight (auto = gross - stone)"),("stone_value","Stone value"),("cost_amount","Cost amount"),("making_type","Making type",["per_gram","percent","fixed"]),("making_value","Making value"),("wastage_percent","Wastage %"),("huid","HUID (6 alphanumeric)"),("certificate_no","Certificate"),("barcode","Barcode (blank=tag)"),("rfid_epc","RFID EPC")]
    def __init__(self,parent,app):
        super().__init__(parent,app); self.heading("Inventory & Tagging", "Serialized jewellery with barcode, HUID, weights and movement-safe status.")
        bar=ttk.Frame(self);bar.pack(fill="x");self.q=tk.StringVar();e=ttk.Entry(bar,textvariable=self.q);e.pack(side="left",fill="x",expand=True);e.bind("<Return>",lambda _:self.refresh());ttk.Button(bar,text="Search",command=self.refresh).pack(side="left",padx=4);ttk.Button(bar,text="Add",command=self.add).pack(side="left");ttk.Button(bar,text="Edit",command=self.edit).pack(side="left",padx=4);ttk.Button(bar,text="Print tag",command=self.print_tag).pack(side="left")
        h=ttk.Frame(self);h.pack(fill="both",expand=True,pady=8);self.t=self.tree(h,self.COLS,{"name":180,"tag_no":120});self.refresh()
    def refresh(self):
        try:r=self.api.get("/api/items",q=self.q.get(),limit=1000)
        except Exception as e:self.app.error(e);return
        self.t.delete(*self.t.get_children());[self.t.insert("","end",iid=str(x["id"]),values=tuple(x.get(c,"") for c in self.COLS)) for x in r]
    def selected(self): return int(self.t.selection()[0]) if self.t.selection() else None
    def values(self, defaults=None):
        original=defaults or {}
        d=form_dialog(self,"Jewellery item",self.FIELDS,original or {"metal":"Gold","purity":"916","making_type":"per_gram","category":"Ring"})
        if not d:return None
        for k in ("gross_weight","stone_weight","net_weight","stone_value","cost_amount","making_value","wastage_percent"):
            try:d[k]=float(d.get(k) or 0)
            except ValueError:raise RuntimeError(f"{k} must be numeric")
        if d['stone_weight']>d['gross_weight']+0.0005:raise RuntimeError('Stone weight cannot exceed gross weight')
        expected=round(d['gross_weight']-d['stone_weight']+1e-12,3);entered=round(d['net_weight'],3)
        unchanged_existing_override=bool(original.get('net_weight_override_reason')) and all(abs(float(d.get(k) or 0)-float(original.get(k) or 0))<=0.001 for k in ('gross_weight','stone_weight','net_weight')) and str(d.get('purity'))==str(original.get('purity'))
        if unchanged_existing_override:
            d['net_weight_override_reason']=original.get('net_weight_override_reason')
        elif abs(entered-expected)>0.001:
            if self.app.user.get('role') in ('admin','manager'):
                use_override=messagebox.askyesno('Net weight differs',f'Gross − stone is {expected:.3f} g but you entered {entered:.3f} g.\n\nUse a manager override instead of auto-correcting?',parent=self)
                if use_override:
                    reason=simpledialog.askstring('Net weight override','Enter the reason for overriding calculated net weight:',parent=self)
                    if not reason or len(reason.strip())<3:raise RuntimeError('A reason is required for a net-weight override')
                    d['allow_net_weight_override']=True;d['net_weight_override_reason']=reason.strip();d['net_weight']=entered
                else:d['net_weight']=expected
            else:
                messagebox.showwarning('Net weight corrected',f'Net weight has been set to Gross − Stone = {expected:.3f} g.',parent=self);d['net_weight']=expected
        else:d['net_weight']=expected
        huid=str(d.get('huid') or '').strip().upper();d['huid']=huid
        if huid and (len(huid)!=6 or not huid.isalnum()):raise RuntimeError('HUID must be exactly six letters/numbers, for example ABC123')
        d["branch_id"]=int(self.app.cfg.get("branch_id",1));d["counter_id"]=self.app.cfg.get("counter_id") or None;return d

    def add(self):
        try:
            d=self.values();
            if d:r=self.api.post("/api/items",d);self.refresh();messagebox.showinfo("Inventory",f"Created {r['tag_no']}",parent=self)
        except Exception as e:self.app.error(e)
    def edit(self):
        iid=self.selected();
        if not iid:return
        try:
            old=self.api.get(f"/api/items/{iid}")["item"];d=self.values(old)
            if d:self.api.put(f"/api/items/{iid}",d);self.refresh()
        except Exception as e:self.app.error(e)
    def print_tag(self):
        iid=self.selected();
        if iid:
            try:open_pdf(self.api.request("GET",f"/api/items/{iid}/label.pdf"),f"tag-{iid}.pdf")
            except Exception as e:self.app.error(e)


class POSPage(Page):
    COLS=("tag_no","description","metal","purity","net_weight","metal_rate","making_charge","stone_value","gst_amount","line_total")
    def __init__(self,parent,app):
        super().__init__(parent,app); self.lines=[]; self.old=[]; self.quote={}; self.customers=[]
        self.heading("Billing counter", "Scan a tag, review the jewellery calculation, accept payment and post one atomic invoice.")

        scan_card = card(self, 14); scan_card.pack(fill="x", pady=(0,12))
        top=ttk.Frame(scan_card, style="Surface.TFrame"); top.pack(fill="x")
        ttk.Label(top,text="SCAN BARCODE / TAG",style="SurfaceMuted.TLabel",font=("Segoe UI Semibold",8)).pack(side="left")
        status_pill(top,"Ready for scanner","success").pack(side="right")
        self.scan=tk.StringVar(); self.scan_entry=ttk.Entry(scan_card,textvariable=self.scan,font=("Segoe UI Semibold",15)); self.scan_entry.pack(fill="x", pady=(8,0), ipady=5); self.scan_entry.bind("<Return>",self.add_scan)

        pan=ttk.Panedwindow(self,orient="horizontal"); pan.pack(fill="both",expand=True)
        left=ttk.Frame(pan); right=ttk.Frame(pan); pan.add(left,weight=5); pan.add(right,weight=2)
        line_card=card(left,14); line_card.pack(fill="both",expand=True,padx=(0,7))
        lh=ttk.Frame(line_card,style="Surface.TFrame"); lh.pack(fill="x",pady=(0,8)); ttk.Label(lh,text="Invoice items",style="Section.TLabel").pack(side="left"); ttk.Button(lh,text="Remove selected",style="Secondary.TButton",command=self.remove).pack(side="right")
        h=ttk.Frame(line_card,style="Surface.TFrame"); h.pack(fill="both",expand=True); self.t=self.tree(h,self.COLS,{"description":180,"tag_no":110,"line_total":110}); self.t.bind("<Delete>",lambda _e:self.remove())

        summary=card(right,16); summary.pack(fill="both",expand=True,padx=(7,0))
        ttk.Label(summary,text="Customer & payment",style="Section.TLabel").pack(anchor="w")
        ttk.Label(summary,text="CUSTOMER",style="SurfaceMuted.TLabel",font=("Segoe UI Semibold",8)).pack(anchor="w",pady=(12,4))
        self.customer=ttk.Combobox(summary,state="readonly"); self.customer.pack(fill="x"); self.load_customers()
        ttk.Button(summary,text="Refresh customers",style="Secondary.TButton",command=self.load_customers).pack(fill="x",pady=(5,10))
        self.discount=tk.StringVar(value="0")
        ttk.Label(summary,text="INVOICE DISCOUNT",style="SurfaceMuted.TLabel",font=("Segoe UI Semibold",8)).pack(anchor="w",pady=(2,4)); ttk.Entry(summary,textvariable=self.discount).pack(fill="x")
        oldrow=ttk.Frame(summary,style="Surface.TFrame"); oldrow.pack(fill="x",pady=(10,6)); ttk.Button(oldrow,text="Add old gold",style="Secondary.TButton",command=self.old_gold).pack(side="left"); self.old_label=tk.StringVar(value="₹0.00"); ttk.Label(oldrow,textvariable=self.old_label,style="Surface.TLabel",font=("Segoe UI Semibold",10)).pack(side="right")
        divider(summary).pack(fill="x",pady=10)

        self.totals={}
        for k,l in (("subtotal","Subtotal"),("gst","GST"),("total","Grand total"),("payable","Balance due")):
            row=ttk.Frame(summary,style="Surface.TFrame"); row.pack(fill="x",pady=3); ttk.Label(row,text=l,style="SurfaceMuted.TLabel").pack(side="left"); v=tk.StringVar(value="₹0.00"); self.totals[k]=v; ttk.Label(row,textvariable=v,style="Money.TLabel" if k in ("total","payable") else "Surface.TLabel",font=("Segoe UI Semibold",10) if k not in ("total","payable") else None).pack(side="right")
        divider(summary).pack(fill="x",pady=10)
        ttk.Label(summary,text="PAYMENT SPLIT",style="SurfaceMuted.TLabel",font=("Segoe UI Semibold",8)).pack(anchor="w",pady=(0,5))
        self.pay={}
        for k,l in (("cash","Cash"),("card","Card"),("upi","UPI"),("credit","Credit")):
            row=ttk.Frame(summary,style="Surface.TFrame"); row.pack(fill="x",pady=3); ttk.Label(row,text=l,style="Surface.TLabel",width=8).pack(side="left"); v=tk.StringVar(value="0"); self.pay[k]=v; ttk.Entry(row,textvariable=v,width=16).pack(side="right")
        quick=ttk.Frame(summary,style="Surface.TFrame"); quick.pack(fill="x",pady=(10,5)); ttk.Button(quick,text="Recalculate",style="Secondary.TButton",command=self.requote).pack(side="left",fill="x",expand=True); ttk.Button(quick,text="Balance → Cash",style="Secondary.TButton",command=self.cash).pack(side="left",fill="x",expand=True,padx=(5,0))
        ttk.Button(summary,text="COMPLETE SALE & PRINT",style="Primary.TButton",command=self.checkout).pack(fill="x",ipady=7,pady=(8,0))
        ttk.Label(summary,text="Tip: scanner + Enter adds a tag. Delete removes the selected line.",style="SurfaceMuted.TLabel",wraplength=280).pack(anchor="w",pady=(9,0))
        self.scan_entry.focus_set()

    def load_customers(self):
        try:
            self.customers=self.api.get("/api/customers"); self.customer["values"]=["Walk-in Customer"]+[f"{x['name']} — {x.get('phone') or ''} [#{x['id']}]" for x in self.customers]; self.customer.current(0)
        except Exception: pass
    def add_scan(self,event=None):
        code=self.scan.get().strip(); self.scan.set("")
        if not code:return
        try:i=self.api.get(f"/api/items/barcode/{code}")
        except Exception as e:self.app.error(e);return
        if i["status"]!="in_stock":self.app.error(f"{i['tag_no']} is {i['status']}");return
        if any(x["item_id"]==i["id"] for x in self.lines): self.app.error(f"{i['tag_no']} is already on this invoice"); return
        self.lines.append({"item_id":i["id"]}); self.requote(); self.scan_entry.focus_set()
    def requote(self):
        try:self.quote=self.api.post("/api/sales/quote",{"lines":self.lines,"discount":float(self.discount.get() or 0),"old_gold":self.old});self.render()
        except Exception as e:
            if self.lines:self.app.error(e)
    def render(self):
        self.t.delete(*self.t.get_children()); [self.t.insert("","end",iid=str(r["item_id"]),values=tuple(r.get(c,"") for c in self.COLS)) for r in self.quote.get("lines",[])]
        for k,v in self.totals.items():v.set(money(self.quote.get(k,0)))
        self.old_label.set("Old gold  "+money(sum(float(x.get("value",0)) for x in self.old)))
    def remove(self):
        if self.t.selection():self.lines=[x for x in self.lines if x["item_id"]!=int(self.t.selection()[0])];self.requote();self.scan_entry.focus_set()
    def old_gold(self):
        d=form_dialog(self,"Old gold exchange",[("metal","Metal",["Gold","Silver"]),("purity","Purity"),("gross_weight","Gross weight"),("deduction_percent","Deduction %"),("rate","Rate / g"),("value","Exchange value"),("notes","Notes")],{"metal":"Gold","purity":"916","gross_weight":"0","deduction_percent":"0","rate":"0","value":"0"})
        if not d:return
        try:
            for k in ("gross_weight","deduction_percent","rate","value"):d[k]=float(d[k] or 0)
            if not d["value"]:d["value"]=d["gross_weight"]*(1-d["deduction_percent"]/100)*d["rate"]
            self.old.append(d);self.requote()
        except ValueError:self.app.error("Old-gold values must be numeric")
    def cash(self):
        self.pay["cash"].set(f"{self.quote.get('payable',0):.2f}"); [self.pay[k].set("0") for k in ("card","upi","credit")]
    def checkout(self):
        if not self.lines:return
        try:
            idx=self.customer.current(); cid=self.customers[idx-1]["id"] if idx>0 else None; p={k:float(v.get() or 0) for k,v in self.pay.items()}
            body={"client_request_id":str(uuid.uuid4()),"branch_id":int(self.app.cfg.get("branch_id",1)),"counter_id":self.app.cfg.get("counter_id") or None,"customer_id":cid,"lines":self.lines,"discount":float(self.discount.get() or 0),"old_gold":self.old,"payment_cash":p["cash"],"payment_card":p["card"],"payment_upi":p["upi"],"payment_credit":p["credit"]}
            r=self.api.post("/api/sales",body); open_pdf(self.api.request("GET",f"/api/sales/{r['id']}/invoice.pdf"),f"{r['invoice_no']}.pdf")
            messagebox.showinfo("Sale completed",f"{r['invoice_no']}\n{money(r['total'])}",parent=self); self.lines=[]; self.old=[]; self.quote={}; self.discount.set("0"); [v.set("0") for v in self.pay.values()]; self.render(); self.scan_entry.focus_set()
        except Exception as e:self.app.error(e)

class PartiesPage(Page):
    def __init__(self,parent,app):
        super().__init__(parent,app);self.heading("Customers / Suppliers / Karigars","Party masters and balances.");self.nb=ttk.Notebook(self);self.nb.pack(fill="both",expand=True);self.tables={}
        for typ in ("customers","suppliers","karigars"):
            f=ttk.Frame(self.nb,padding=8);self.nb.add(f,text=typ.title());bar=ttk.Frame(f);bar.pack(fill="x");ttk.Button(bar,text="Add",command=lambda t=typ:self.add(t)).pack(side="left");ttk.Button(bar,text="Refresh",command=lambda t=typ:self.refresh(t)).pack(side="left",padx=4);h=ttk.Frame(f);h.pack(fill="both",expand=True,pady=8);cols=("code","name","phone","balance") if typ!="karigars" else ("code","name","phone","metal_balance_grams","cash_balance");self.tables[typ]=self.tree(h,cols,{"name":220});self.refresh(typ)
    def refresh(self,t):
        try:r=self.api.get(f"/api/{t}")
        except:return
        tr=self.tables[t];tr.delete(*tr.get_children());[tr.insert("","end",iid=str(x["id"]),values=tuple(x.get(c,"") for c in tr["columns"])) for x in r]
    def add(self,t):
        fields=[("name","Name"),("phone","Phone"),("address","Address"),("notes","Notes")];
        if t!="karigars":fields += [("email","Email"),("gstin","GSTIN")]
        d=form_dialog(self,f"Add {t[:-1]}",fields)
        if d:
            try:self.api.post(f"/api/{t}",d);self.refresh(t)
            except Exception as e:self.app.error(e)


class PurchasesPage(Page):
    def __init__(self,parent,app):
        super().__init__(parent,app);self.heading("Purchases / Stock In","Receive a tagged jewellery piece from a supplier in one transaction.");ttk.Button(self,text="Receive tagged item",command=self.receive).pack(anchor="w");h=ttk.Frame(self);h.pack(fill="both",expand=True,pady=8);self.t=self.tree(h,("purchase_no","supplier_name","subtotal","gst","total","paid","created_at"),{"supplier_name":200});self.refresh()
    def refresh(self):
        try:r=self.api.get("/api/purchases")
        except:return
        self.t.delete(*self.t.get_children());[self.t.insert("","end",values=tuple(x.get(c,"") for c in self.t["columns"])) for x in r]
    def receive(self):
        try:sups=self.api.get("/api/suppliers")
        except Exception as e:self.app.error(e);return
        if not sups:self.app.error("Add a supplier first");return
        sid=simpledialog.askinteger("Supplier","Supplier ID\n"+"\n".join(f"{x['id']}: {x['name']}" for x in sups[:15]),initialvalue=sups[0]["id"],parent=self)
        d=form_dialog(self,"Purchased jewellery",InventoryPage.FIELDS,{"metal":"Gold","purity":"916","making_type":"per_gram","category":"Ring"})
        if not d:return
        try:
            for k in ("gross_weight","stone_weight","net_weight","stone_value","cost_amount","making_value","wastage_percent"):d[k]=float(d.get(k) or 0)
            paid=simpledialog.askfloat("Purchase","Paid now",initialvalue=d["cost_amount"],parent=self) or 0;r=self.api.post("/api/purchases",{"client_request_id":str(uuid.uuid4()),"supplier_id":sid,"branch_id":int(self.app.cfg.get("branch_id",1)),"paid":paid,"gst":0,"items":[d]});messagebox.showinfo("Purchase",r["purchase_no"],parent=self);self.refresh()
        except Exception as e:self.app.error(e)


class JobsPage(Page):
    def __init__(self,parent,app):
        super().__init__(parent,app);self.heading("Repairs & Custom Orders","Track customer jobs through karigar assignment and delivery.");self.nb=ttk.Notebook(self);self.nb.pack(fill="both",expand=True);self.tabs={}
        for typ in ("repairs","orders"):
            f=ttk.Frame(self.nb,padding=8);self.nb.add(f,text=typ.title());bar=ttk.Frame(f);bar.pack(fill="x");ttk.Button(bar,text="Add",command=lambda t=typ:self.add(t)).pack(side="left");ttk.Button(bar,text="Change status",command=lambda t=typ:self.status(t)).pack(side="left",padx=4);h=ttk.Frame(f);h.pack(fill="both",expand=True,pady=8);cols=("repair_no","customer_name","item_description","gross_weight","status","karigar_name","promised_on","estimated_amount") if typ=="repairs" else ("order_no","customer_name","description","metal","purity","target_weight","status","karigar_name","due_date");self.tabs[typ]=self.tree(h,cols,{"item_description":220,"description":220});self.refresh(typ)
    def refresh(self,t):
        try:r=self.api.get(f"/api/{t}")
        except:return
        tr=self.tabs[t];tr.delete(*tr.get_children());[tr.insert("","end",iid=str(x["id"]),values=tuple(x.get(c,"") for c in tr["columns"])) for x in r]
    def add(self,t):
        fields=[("customer_id","Customer ID"),("karigar_id","Karigar ID"),("notes","Notes")]
        fields=( [("item_description","Description"),("gross_weight","Gross weight"),("promised_on","Promised date"),("estimated_amount","Estimate"),("advance","Advance")]+fields if t=="repairs" else [("description","Description"),("metal","Metal"),("purity","Purity"),("target_weight","Target weight"),("due_date","Due date"),("estimated_amount","Estimate"),("advance","Advance")]+fields )
        d=form_dialog(self,f"Add {t[:-1]}",fields,{"metal":"Gold","purity":"916","promised_on":dt.date.today().isoformat(),"due_date":dt.date.today().isoformat()})
        if d:
            try:
                for k in ("gross_weight","target_weight","estimated_amount","advance"):
                    if k in d:d[k]=float(d[k] or 0)
                for k in ("customer_id","karigar_id"):
                    if k in d:d[k]=int(d[k]) if d[k] else None
                self.api.post(f"/api/{t}",d);self.refresh(t)
            except Exception as e:self.app.error(e)
    def status(self,t):
        if not self.tabs[t].selection():return
        values=["received","assigned","in_progress","ready","delivered","cancelled"] if t=="repairs" else ["new","assigned","in_progress","ready","delivered","cancelled"]
        st=simpledialog.askstring("Status","Choose: "+", ".join(values),parent=self)
        if st in values:
            try:self.api.put(f"/api/{t}/{int(self.tabs[t].selection()[0])}",{"status":st});self.refresh(t)
            except Exception as e:self.app.error(e)


class StockAuditPage(Page):
    def __init__(self,parent,app):
        super().__init__(parent,app);self.audit_id=None;self.heading("Physical Stock Audit","Open an audit and scan every tag/RFID EPC. Reconcile missing and misplaced stock.");bar=ttk.Frame(self);bar.pack(fill="x");ttk.Button(bar,text="Start audit",command=self.start).pack(side="left");ttk.Button(bar,text="Close & reconcile",command=self.close).pack(side="left",padx=4);self.state=tk.StringVar(value="No audit open");ttk.Label(bar,textvariable=self.state).pack(side="left",padx=10);self.scan=tk.StringVar();e=ttk.Entry(self,textvariable=self.scan,font=("Consolas",13));e.pack(fill="x",pady=8);e.bind("<Return>",self.do_scan);h=ttk.Frame(self);h.pack(fill="both",expand=True);self.t=self.tree(h,("tag_no","name","metal","purity","gross_weight","status"),{"name":220});e.focus_set()
    def start(self):
        try:r=self.api.post("/api/stock-audits",{"branch_id":int(self.app.cfg.get("branch_id",1)),"counter_id":self.app.cfg.get("counter_id") or None});self.audit_id=r["id"];self.state.set("Open: "+r["audit_no"]);self.t.delete(*self.t.get_children())
        except Exception as e:self.app.error(e)
    def do_scan(self,event):
        code=self.scan.get().strip();self.scan.set("")
        if not self.audit_id or not code:return
        try:r=self.api.post(f"/api/stock-audits/{self.audit_id}/scan",{"barcode":code});i=r["item"];
        except Exception as e:self.app.error(e);return
        if r["new"]:self.t.insert("","end",iid=str(i["id"]),values=tuple(i.get(c,"") for c in self.t["columns"]))
    def close(self):
        if not self.audit_id:return
        try:r=self.api.post(f"/api/stock-audits/{self.audit_id}/close",{});messagebox.showinfo("Audit result",f"Expected {r['expected_count']}\nScanned {r['scanned_count']}\nMissing {len(r['missing'])}\nExtra/misplaced {len(r['extra'])}",parent=self);self.audit_id=None;self.state.set("Audit closed")
        except Exception as e:self.app.error(e)


class ReportsPage(Page):
    def __init__(self,parent,app):
        super().__init__(parent,app);self.heading("Reports & Accounting","Sales/stock summaries and double-entry trial balance.");bar=ttk.Frame(self);bar.pack(fill="x");self.df=tk.StringVar(value=dt.date.today().replace(day=1).isoformat());self.to=tk.StringVar(value=dt.date.today().isoformat());ttk.Entry(bar,textvariable=self.df,width=12).pack(side="left");ttk.Entry(bar,textvariable=self.to,width=12).pack(side="left",padx=4);ttk.Button(bar,text="Refresh",command=self.refresh).pack(side="left");ttk.Button(bar,text="Stock PDF",command=self.pdf).pack(side="right");self.txt=tk.Text(self,height=9,font=("Consolas",10));self.txt.pack(fill="x",pady=8);h=ttk.Frame(self);h.pack(fill="both",expand=True);self.t=self.tree(h,("code","name","account_type","debit","credit","balance"),{"name":220});self.refresh()
    def refresh(self):
        try:s=self.api.get("/api/reports/summary",date_from=self.df.get(),date_to=self.to.get());tb=self.api.get("/api/reports/trial-balance",date_to=self.to.get())
        except Exception as e:self.app.error(e);return
        txt=f"Period {s['date_from']} to {s['date_to']}\nInvoices {s['sales']['invoices']} | Sales {money(s['sales']['total'])} | GST {money(s['sales']['gst'])}\nStock {s['stock']['pieces']} pcs | Gross {s['stock']['gross_weight']:.3f} g | Net {s['stock']['net_weight']:.3f} g | Cost {money(s['stock']['cost'])}\nPayments: Cash {money(s['payments']['cash'])}, Card {money(s['payments']['card'])}, UPI {money(s['payments']['upi'])}, Credit {money(s['payments']['credit'])}, Old gold {money(s['payments']['old_gold'])}\n\n"+"\n".join(f"{x['metal']} {x['purity']}: {x['pieces']} pcs / {x['net_weight']:.3f} g" for x in s['stock_by_metal']);self.txt.delete("1.0","end");self.txt.insert("1.0",txt);self.t.delete(*self.t.get_children());[self.t.insert("","end",values=tuple(x.get(c,"") for c in self.t["columns"])) for x in tb]
    def pdf(self):
        try:open_pdf(self.api.request("GET","/api/reports/stock.pdf"),"jewellan-stock.pdf")
        except Exception as e:self.app.error(e)


class TallyPage(Page):
    def __init__(self,parent,app):
        super().__init__(parent,app); self.heading("TallyPrime", "Offline accounting bridge, queue health, ledger mappings and reconciliation.")
        outer=ttk.Frame(self); outer.pack(fill="both",expand=True)
        left=card(outer,18); left.pack(side="left",fill="both",expand=True,padx=(0,7)); right=card(outer,18); right.pack(side="left",fill="both",expand=True,padx=(7,0))
        self.tv={}; self.tm={}; self.status=tk.StringVar(value="Loading…")
        ttk.Label(left,text="Connection",style="Section.TLabel").pack(anchor="w"); ttk.Label(left,textvariable=self.status,style="SurfaceMuted.TLabel",wraplength=460).pack(anchor="w",pady=(3,12))
        try:d=self.api.get('/api/tally/status')
        except Exception as e:d={'mappings':{}};self.status.set(str(e))
        fields=[('tally_enabled','Enabled (0/1)',d.get('enabled','0')),('tally_bridge_url','Bridge URL',d.get('bridge_url','http://127.0.0.1:8767')),('tally_bridge_token','Bridge token',''),('tally_company','Tally company',d.get('company','')),('business_state_code','Business state code',d.get('business_state_code','')),('tally_auto_create_parties','Auto-create party ledgers (0/1)',d.get('auto_create_parties','1'))]
        form=ttk.Frame(left,style="Surface.TFrame"); form.pack(fill="x")
        for r,(k,l,val) in enumerate(fields):
            self.tv[k]=tk.StringVar(value=str(val)); ttk.Label(form,text=l,style="SurfaceMuted.TLabel").grid(row=r,column=0,sticky='w',pady=5); ttk.Entry(form,textvariable=self.tv[k],show='●' if k=='tally_bridge_token' else '').grid(row=r,column=1,sticky='ew',padx=(12,0),pady=5)
        form.columnconfigure(1,weight=1)
        controls=ttk.Frame(left,style="Surface.TFrame"); controls.pack(fill="x",pady=(14,0)); ttk.Button(controls,text='Save settings',style="Primary.TButton",command=self.save).pack(side='left'); ttk.Button(controls,text='Test connection',style="Secondary.TButton",command=self.test).pack(side='left',padx=5); ttk.Button(controls,text='Sync now',style="Secondary.TButton",command=self.sync).pack(side='left')

        ttk.Label(right,text="Ledger mappings",style="Section.TLabel").pack(anchor="w"); ttk.Label(right,text="Map JewelLAN accounting roles to exact Tally ledger names.",style="SurfaceMuted.TLabel",wraplength=430).pack(anchor="w",pady=(3,10))
        maps=ttk.Frame(right,style="Surface.TFrame"); maps.pack(fill="both",expand=True)
        for r,(k,val) in enumerate(d.get('mappings',{}).items()):
            self.tm[k]=tk.StringVar(value=str(val)); ttk.Label(maps,text=k.replace('_',' ').title(),style="SurfaceMuted.TLabel").grid(row=r,column=0,sticky='w',pady=3); ttk.Entry(maps,textvariable=self.tm[k]).grid(row=r,column=1,sticky='ew',padx=(10,0),pady=3)
        maps.columnconfigure(1,weight=1)
        bottom=ttk.Frame(right,style="Surface.TFrame"); bottom.pack(fill="x",pady=(12,0)); ttk.Button(bottom,text='Save mappings',style="Primary.TButton",command=self.save_mappings).pack(side='left'); ttk.Button(bottom,text='Reconcile month',style="Secondary.TButton",command=self.reconcile).pack(side='left',padx=5); ttk.Button(bottom,text='Backfill history',style="Secondary.TButton",command=self.backfill).pack(side='left')
        bridge=d.get('bridge'); q=d.get('queue',{}); self.status.set(('Connected to bridge' if bridge and bridge.get('ok') else 'Bridge not connected')+f" · {q.get('pending',0)} pending · {q.get('failed',0)} failed · {q.get('synced',0)} synced")
    def save(self):
        try:
            p={k:v.get() for k,v in self.tv.items() if k!='tally_bridge_token' or v.get().strip()}; self.api.put('/api/tally/settings',p); messagebox.showinfo('TallyPrime','Connection settings saved.',parent=self)
        except Exception as e:self.app.error(e)
    def save_mappings(self):
        try:self.api.put('/api/tally/mappings',{k:v.get() for k,v in self.tm.items()});messagebox.showinfo('TallyPrime','Ledger mappings saved.',parent=self)
        except Exception as e:self.app.error(e)
    def test(self):
        try:r=self.api.post('/api/tally/test',{});missing=r.get('mappings',{}).get('missing',[]);messagebox.showinfo('TallyPrime',f"Bridge connected. Missing mapped ledgers: {', '.join(missing) if missing else 'none'}",parent=self)
        except Exception as e:self.app.error(e)
    def sync(self):
        try:r=self.api.post('/api/tally/sync-now',{'limit':100});messagebox.showinfo('TallyPrime',f"Processed {r['processed']} · Synced {r['synced']} · Failed {r['failed']}",parent=self)
        except Exception as e:self.app.error(e)
    def reconcile(self):
        try:r=self.api.get('/api/tally/reconcile',date_from=dt.date.today().replace(day=1).isoformat(),date_to=dt.date.today().isoformat());messagebox.showinfo('Tally reconciliation',f"Expected {r['expected_count']}\nFound {r['found_count']}\nMissing {len(r['missing'])}\nAmount mismatches {len(r['amount_mismatches'])}",parent=self)
        except Exception as e:self.app.error(e)
    def backfill(self):
        if not messagebox.askyesno('TallyPrime','Queue historical JewelLAN sales and purchases for Tally sync?',parent=self):return
        try:r=self.api.post('/api/tally/backfill',{});messagebox.showinfo('TallyPrime',str(r),parent=self)
        except Exception as e:self.app.error(e)


class AdminPage(Page):
    def __init__(self,parent,app):
        super().__init__(parent,app);self.heading("Administration","Metal rates, users, backups, integrity, business settings and this workstation.");self.nb=ttk.Notebook(self);self.nb.pack(fill="both",expand=True);self.make_rates();self.make_health();self.make_backup();self.make_pc();
        if app.user.get("role")=="admin":self.make_users();self.make_business()
    def make_rates(self):
        f=ttk.Frame(self.nb,padding=8);self.nb.add(f,text="Metal rates");ttk.Button(f,text="Add rate",command=self.rate).pack(anchor="w");h=ttk.Frame(f);h.pack(fill="both",expand=True,pady=8);self.rt=self.tree(h,("metal","purity","rate_per_gram","effective_at"));self.refresh_rates()
    def refresh_rates(self):
        try:r=self.api.get("/api/rates")
        except:return
        self.rt.delete(*self.rt.get_children());[self.rt.insert("","end",values=tuple(x.get(c,"") for c in self.rt["columns"])) for x in r]
    def rate(self):
        d=form_dialog(self,"Metal rate",[("metal","Metal"),("purity","Purity"),("rate_per_gram","Rate per gram")],{"metal":"Gold","purity":"916"})
        if d:
            try:d["rate_per_gram"]=float(d["rate_per_gram"]);self.api.post("/api/rates",d);self.refresh_rates()
            except Exception as e:self.app.error(e)
    def make_health(self):
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

    def make_backup(self):
        f=ttk.Frame(self.nb,padding=8);self.nb.add(f,text="Backups");ttk.Button(f,text="Create backup now",command=lambda:self.api.post("/api/backups",{"label":"manual"})).pack(anchor="w");ttk.Label(f,text="Backups stay on the server PC. Restore is a server-admin operation while JewelLAN is stopped.",foreground="#666").pack(anchor="w",pady=10)
    def make_pc(self):
        f=ttk.Frame(self.nb,padding=12);self.nb.add(f,text="This PC");fields=[("server_url","Server URL"),("branch_id","Branch ID"),("counter_id","Counter ID"),("scale_port","Scale COM port"),("scale_baud","Scale baud")];self.pcv={}
        for i,(k,l) in enumerate(fields):self.pcv[k]=tk.StringVar(value=str(self.app.cfg.get(k,"")));ttk.Label(f,text=l).grid(row=i,column=0,sticky="w",pady=5);ttk.Entry(f,textvariable=self.pcv[k]).grid(row=i,column=1,sticky="ew",padx=8)
        f.columnconfigure(1,weight=1);ttk.Button(f,text="Read scale now",command=self.test_scale).grid(row=6,column=0,sticky="ew",pady=10);ttk.Button(f,text="Save",command=self.save_pc).grid(row=6,column=1,sticky="ew",pady=10)
    def test_scale(self):
        try:messagebox.showinfo("Scale",f"{read_scale(self.pcv['scale_port'].get(),int(self.pcv['scale_baud'].get() or 9600)):.3f} g",parent=self)
        except Exception as e:self.app.error(e)
    def save_pc(self):
        try:self.app.cfg.update({"server_url":self.pcv["server_url"].get(),"branch_id":int(self.pcv["branch_id"].get() or 1),"counter_id":int(self.pcv["counter_id"].get() or 1),"scale_port":self.pcv["scale_port"].get(),"scale_baud":int(self.pcv["scale_baud"].get() or 9600)});save_config(self.app.cfg);messagebox.showinfo("Workstation","Saved",parent=self)
        except Exception as e:self.app.error(e)
    def make_tally(self):
        f=ttk.Frame(self.nb,padding=10);self.nb.add(f,text="TallyPrime");self.tv={};self.tm={};self.tally_status=tk.StringVar(value="Loading Tally integration status…");ttk.Label(f,textvariable=self.tally_status,foreground="#555").grid(row=0,column=0,columnspan=2,sticky="w",pady=(0,8))
        try:d=self.api.get('/api/tally/status')
        except Exception as e:d={'mappings':{}};self.tally_status.set(str(e))
        fields=[('tally_enabled','Enabled (0/1)',d.get('enabled','0')),('tally_bridge_url','Bridge URL',d.get('bridge_url','http://127.0.0.1:8767')),('tally_bridge_token','Bridge token',''),('tally_company','Tally company',d.get('company','')),('business_state_code','Business state code',d.get('business_state_code','')),('tally_auto_create_parties','Auto-create party ledgers (0/1)',d.get('auto_create_parties','1'))]
        r=1
        for k,l,val in fields:self.tv[k]=tk.StringVar(value=str(val));ttk.Label(f,text=l).grid(row=r,column=0,sticky='w',pady=3);ttk.Entry(f,textvariable=self.tv[k],show='●' if k=='tally_bridge_token' else '').grid(row=r,column=1,sticky='ew',padx=8);r+=1
        ttk.Separator(f).grid(row=r,column=0,columnspan=2,sticky='ew',pady=8);r+=1;ttk.Label(f,text='Ledger mappings',font=('Segoe UI',11,'bold')).grid(row=r,column=0,columnspan=2,sticky='w');r+=1
        for k,val in d.get('mappings',{}).items():self.tm[k]=tk.StringVar(value=str(val));ttk.Label(f,text=k.replace('_',' ').title()).grid(row=r,column=0,sticky='w',pady=2);ttk.Entry(f,textvariable=self.tm[k]).grid(row=r,column=1,sticky='ew',padx=8);r+=1
        b=ttk.Frame(f);b.grid(row=r,column=0,columnspan=2,sticky='ew',pady=10);ttk.Button(b,text='Save',command=self.save_tally).pack(side='left');ttk.Button(b,text='Test',command=self.test_tally).pack(side='left',padx=4);ttk.Button(b,text='Sync now',command=self.sync_tally).pack(side='left');ttk.Button(b,text='Reconcile',command=self.reconcile_tally).pack(side='left',padx=4);ttk.Button(b,text='Backfill',command=self.backfill_tally).pack(side='left');f.columnconfigure(1,weight=1)
        bridge=d.get('bridge');q=d.get('queue',{});self.tally_status.set(('Connected' if bridge and bridge.get('ok') else 'Not connected')+f" | pending {q.get('pending',0)} failed {q.get('failed',0)} synced {q.get('synced',0)}")
    def save_tally(self):
        try:
            p={k:v.get() for k,v in self.tv.items() if k!='tally_bridge_token' or v.get().strip()};self.api.put('/api/tally/settings',p);self.api.put('/api/tally/mappings',{k:v.get() for k,v in self.tm.items()});messagebox.showinfo('TallyPrime','Settings saved. Use Test before enabling live sync.',parent=self)
        except Exception as e:self.app.error(e)
    def test_tally(self):
        try:r=self.api.post('/api/tally/test',{});missing=r.get('mappings',{}).get('missing',[]);messagebox.showinfo('TallyPrime',f"Bridge connected. Missing mapped ledgers: {', '.join(missing) if missing else 'none'}",parent=self)
        except Exception as e:self.app.error(e)
    def sync_tally(self):
        try:r=self.api.post('/api/tally/sync-now',{'limit':100});messagebox.showinfo('TallyPrime',f"Processed {r['processed']} | Synced {r['synced']} | Failed {r['failed']}",parent=self)
        except Exception as e:self.app.error(e)
    def reconcile_tally(self):
        try:r=self.api.get('/api/tally/reconcile',date_from=dt.date.today().replace(day=1).isoformat(),date_to=dt.date.today().isoformat());messagebox.showinfo('Tally reconciliation',f"Expected {r['expected_count']}\nFound {r['found_count']}\nMissing {len(r['missing'])}\nAmount mismatches {len(r['amount_mismatches'])}",parent=self)
        except Exception as e:self.app.error(e)
    def backfill_tally(self):
        if not messagebox.askyesno('TallyPrime','Queue historical JewelLAN sales and purchases for Tally sync?',parent=self):return
        try:r=self.api.post('/api/tally/backfill',{});messagebox.showinfo('TallyPrime',str(r),parent=self)
        except Exception as e:self.app.error(e)

    def make_users(self):
        f=ttk.Frame(self.nb,padding=8);self.nb.add(f,text="Users");ttk.Button(f,text="Add user",command=self.add_user).pack(anchor="w");h=ttk.Frame(f);h.pack(fill="both",expand=True,pady=8);self.ut=self.tree(h,("username","full_name","role","active","must_change_password"));self.refresh_users()
    def refresh_users(self):
        try:r=self.api.get("/api/users")
        except:return
        self.ut.delete(*self.ut.get_children());[self.ut.insert("","end",values=tuple(x.get(c,"") for c in self.ut["columns"])) for x in r]
    def add_user(self):
        d=form_dialog(self,"Add user",[("username","Username"),("full_name","Full name"),("role","Role",["cashier","inventory","accounts","manager","admin"]),("password","Temporary password")])
        if d:
            try:self.api.post("/api/users",d);self.refresh_users()
            except Exception as e:self.app.error(e)
    def make_business(self):
        f=ttk.Frame(self.nb,padding=12);self.nb.add(f,text="Company settings");self.bv={}
        try:d=self.api.get('/api/company')
        except Exception as e:d={'settings':self.app.settings,'branch':{},'counter_count':len(self.app.counters)};self.app.error(e)
        s=d.get('settings',{});branch=d.get('branch') or {}
        fields=[('business_name','Company name',s.get('business_name','')),('branch_name','Main branch / showroom',branch.get('name','Main Showroom')),('business_state_code','GST state code',s.get('business_state_code','')),('business_state_name','State name',s.get('business_state_name','')),('business_gstin','GSTIN',s.get('business_gstin','')),('business_address','Address',s.get('business_address','')),('business_pincode','PIN code',s.get('business_pincode','')),('business_phone','Phone',s.get('business_phone','')),('business_email','Email',s.get('business_email','')),('counter_count','Number of counters',str(d.get('counter_count') or 1)),('invoice_prefix','Invoice prefix',s.get('invoice_prefix','INV')),('tag_prefix','Tag prefix',s.get('tag_prefix','TAG')),('gst_default','Default GST %',s.get('gst_default','3')),('business_timezone_offset_minutes','Timezone offset minutes',s.get('business_timezone_offset_minutes','330'))]
        ttk.Label(f,text='These values belong to the company database and appear on invoices/reports. They are not hard-coded into JewelLAN.',style='SurfaceMuted.TLabel',wraplength=900).grid(row=0,column=0,columnspan=2,sticky='w',pady=(0,10))
        for i,(k,label,value) in enumerate(fields,1):self.bv[k]=tk.StringVar(value=str(value));ttk.Label(f,text=label).grid(row=i,column=0,sticky='w',pady=3);ttk.Entry(f,textvariable=self.bv[k]).grid(row=i,column=1,sticky='ew',padx=8)
        f.columnconfigure(1,weight=1);ttk.Button(f,text="Save company settings",style='Primary.TButton',command=self.save_business).grid(row=len(fields)+2,column=0,columnspan=2,sticky="ew",pady=12)
    def save_business(self):
        try:
            p={k:v.get() for k,v in self.bv.items()};p['counter_count']=int(p.get('counter_count') or 1);r=self.api.put('/api/company',p);self.app.load_settings();self.app.company_label.configure(text=self.app.settings.get('business_name') or 'Company not configured');messagebox.showinfo('Company settings','Saved',parent=self)
        except Exception as e:self.app.error(e)


def main():
    root=tk.Tk();root.withdraw();cfg=load_config();api=Api(cfg.get("server_url",""),cfg.get("server_fingerprint",""));login=LoginDialog(root,api,cfg);root.wait_window(login)
    if not login.user:return
    if login.user.get("must_change_password") and not force_initial_password_change(root,api,login.user):return
    if not ensure_company_setup(root,api):return
    root.deiconify();App(root,api,cfg,login.user);root.mainloop()


if __name__ == "__main__":
    main()
