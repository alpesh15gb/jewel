from __future__ import annotations

from pathlib import Path

PATH = Path("jewel_client/main.py")
text = PATH.read_text(encoding="utf-8")


def between(src: str, start: str, end: str, replacement: str) -> str:
    a = src.find(start)
    if a < 0:
        raise RuntimeError(f"UI upgrade start marker not found: {start!r}")
    b = src.find(end, a)
    if b < 0:
        raise RuntimeError(f"UI upgrade end marker not found: {end!r}")
    return src[:a] + replacement.rstrip() + "\n\n" + src[b:]


imp = "from .scale import read_scale\n"
ui_imp = "from .scale import read_scale\nfrom .ui_theme import PALETTE, apply_theme, card, divider, status_pill\n"
if "from .ui_theme import" not in text:
    if imp not in text:
        raise RuntimeError("Could not insert ui_theme import")
    text = text.replace(imp, ui_imp, 1)

FORM_DIALOG = r'''def form_dialog(parent, title, fields, defaults=None):
    defaults = defaults or {}
    d = tk.Toplevel(parent)
    d.title(title)
    d.configure(bg=PALETTE["bg"])
    center(d, 590, min(720, 150 + len(fields) * 44))
    d.transient(parent); d.grab_set(); d.resizable(True, True)
    shell = ttk.Frame(d, style="Surface.TFrame", padding=22)
    shell.pack(fill="both", expand=True, padx=18, pady=18)
    ttk.Label(shell, text=title, style="Section.TLabel", font=("Segoe UI Semibold", 15)).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 14))
    vars_ = {}; result = {"value": None}
    for i, spec in enumerate(fields, start=1):
        key, label = spec[0], spec[1]; values = spec[2] if len(spec) > 2 else None
        v = tk.StringVar(value=str(defaults.get(key, "") if defaults.get(key) is not None else "")); vars_[key] = v
        ttk.Label(shell, text=label, style="SurfaceMuted.TLabel").grid(row=i, column=0, sticky="w", pady=5)
        widget = ttk.Combobox(shell, textvariable=v, values=values, state="readonly") if values else ttk.Entry(shell, textvariable=v)
        widget.grid(row=i, column=1, sticky="ew", padx=(16, 0), pady=5)
        if values and not v.get() and values: v.set(values[0])
    shell.columnconfigure(1, weight=1)
    def save():
        result["value"] = {k: v.get().strip() for k, v in vars_.items()}; d.destroy()
    buttons = ttk.Frame(shell, style="Surface.TFrame")
    buttons.grid(row=len(fields)+2, column=0, columnspan=2, sticky="e", pady=(18, 0))
    ttk.Button(buttons, text="Cancel", style="Secondary.TButton", command=d.destroy).pack(side="right")
    ttk.Button(buttons, text="Save", style="Primary.TButton", command=save).pack(side="right", padx=(0, 8))
    d.bind("<Escape>", lambda _e: d.destroy())
    d.bind("<Control-Return>", lambda _e: save())
    parent.wait_window(d)
    return result["value"]
'''
text = between(text, "def form_dialog(parent, title, fields, defaults=None):", "class LoginDialog", FORM_DIALOG)

LOGIN = r'''class LoginDialog(tk.Toplevel):
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
        self.server = tk.StringVar(value=cfg.get("server_url") or "http://127.0.0.1:8765")
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

    def discover(self):
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
text = between(text, "class LoginDialog", "class Page", LOGIN)

PAGE = r'''class Page(ttk.Frame):
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
'''
text = between(text, "class Page", "class App", PAGE)

APP = r'''class App(ttk.Frame):
    def __init__(self, root, api, cfg, user):
        apply_theme(root)
        super().__init__(root); self.root = root; self.api = api; self.cfg = cfg; self.user = user; self.settings = {}; self.branches = []; self.counters = []; self.nav_buttons = {}; self.current_page = None
        self.pack(fill="both", expand=True); root.title(f"{APP_TITLE} — {user['full_name']}"); root.minsize(1180, 720)
        if os.name == "nt": root.state("zoomed")
        else: root.geometry("1360x850")
        self.load_settings(); self.build()
        if user.get("must_change_password"): root.after(400, lambda: self.change_password(True))

    def load_settings(self):
        d = self.api.get("/api/settings"); self.settings, self.branches, self.counters = d["settings"], d["branches"], d["counters"]

    def build(self):
        body = tk.Frame(self, bg=PALETTE["bg"]); body.pack(fill="both", expand=True)
        nav = ttk.Frame(body, style="Nav.TFrame", width=220); nav.pack(side="left", fill="y"); nav.pack_propagate(False)
        ttk.Label(nav, text="JewelLAN", style="NavBrand.TLabel").pack(anchor="w", padx=18, pady=(22, 2))
        ttk.Label(nav, text=self.settings.get("business_name", "Jewellery Store"), style="NavMuted.TLabel", wraplength=180).pack(anchor="w", padx=18, pady=(0, 18))

        role = self.user.get("role", "cashier")
        pages = [("Overview", DashboardPage), ("Inventory", InventoryPage), ("Parties", PartiesPage)]
        if role in ("admin","manager","cashier"): pages.insert(1, ("Billing", POSPage))
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
        data = form_dialog(self.root, "Change password", [("old_password","Current password"),("new_password","New password"),("again","Repeat new password")])
        if not data:
            if forced: self.root.after(300, lambda: self.change_password(True))
            return
        if data["new_password"] != data["again"]: self.error("New passwords do not match"); return
        try:
            self.api.post("/api/auth/change-password", {"old_password": data["old_password"], "new_password": data["new_password"]}); self.user["must_change_password"] = 0
            messagebox.showinfo("Password", "Password changed.", parent=self.root)
        except Exception as e:
            self.error(e); self.root.after(300, lambda: self.change_password(True)) if forced else None
'''
text = between(text, "class App", "class DashboardPage", APP)

DASH = r'''class DashboardPage(Page):
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
'''
text = between(text, "class DashboardPage", "class InventoryPage", DASH)

POS = r'''class POSPage(Page):
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
'''
text = between(text, "class POSPage", "class PartiesPage", POS)

# Put TallyPrime in its own first-class navigation page instead of hiding it inside Administration.
text = text.replace("self.make_rates();self.make_backup();self.make_pc();self.make_tally();", "self.make_rates();self.make_backup();self.make_pc();", 1)

TALLY = r'''class TallyPage(Page):
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
'''
marker = "class AdminPage(Page):"
if "class TallyPage(Page):" not in text:
    pos = text.find(marker)
    if pos < 0: raise RuntimeError("Could not insert TallyPage")
    text = text[:pos] + TALLY.rstrip() + "\n\n\n" + text[pos:]

PATH.write_text(text, encoding="utf-8")
print("Professional JewelLAN UI redesign applied.")
