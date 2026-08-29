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

from .api import Api, ApiError, discover_servers
from .config import load_config, save_config
from .scale import read_scale

APP_TITLE = "JewelLAN Jewellery ERP"


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
    d = tk.Toplevel(parent); d.title(title); center(d, 520, min(650, 120 + len(fields) * 42)); d.transient(parent); d.grab_set()
    f = ttk.Frame(d, padding=16); f.pack(fill="both", expand=True); vars_ = {}; result = {"value": None}
    for i, spec in enumerate(fields):
        key, label = spec[0], spec[1]; values = spec[2] if len(spec) > 2 else None
        v = tk.StringVar(value=str(defaults.get(key, "") if defaults.get(key) is not None else "")); vars_[key] = v
        ttk.Label(f, text=label).grid(row=i, column=0, sticky="w", pady=4)
        w = ttk.Combobox(f, textvariable=v, values=values, state="readonly") if values else ttk.Entry(f, textvariable=v)
        w.grid(row=i, column=1, sticky="ew", padx=8, pady=4)
        if values and not v.get() and values: v.set(values[0])
    f.columnconfigure(1, weight=1)
    def save():
        result["value"] = {k: v.get().strip() for k, v in vars_.items()}; d.destroy()
    b = ttk.Frame(f); b.grid(row=len(fields)+1, column=0, columnspan=2, sticky="ew", pady=12)
    ttk.Button(b, text="Cancel", command=d.destroy).pack(side="right")
    ttk.Button(b, text="Save", command=save).pack(side="right", padx=8)
    parent.wait_window(d)
    return result["value"]


class LoginDialog(tk.Toplevel):
    def __init__(self, master, api: Api, cfg: dict):
        super().__init__(master); self.api = api; self.cfg = cfg; self.user = None
        self.title("JewelLAN Login"); self.resizable(False, False); center(self, 520, 350); self.protocol("WM_DELETE_WINDOW", master.destroy)
        f = ttk.Frame(self, padding=24); f.pack(fill="both", expand=True)
        ttk.Label(f, text="JewelLAN", font=("Segoe UI", 22, "bold")).pack(anchor="w")
        ttk.Label(f, text="Offline jewellery ERP • private LAN", foreground="#555").pack(anchor="w", pady=(0, 18))
        frm = ttk.Frame(f); frm.pack(fill="x")
        self.server = tk.StringVar(value=cfg.get("server_url") or "http://127.0.0.1:8765")
        self.username = tk.StringVar(value="admin"); self.password = tk.StringVar()
        for r, (label, var) in enumerate((("Server", self.server), ("Username", self.username), ("Password", self.password))):
            ttk.Label(frm, text=label).grid(row=r, column=0, sticky="w", pady=6)
            e = ttk.Entry(frm, textvariable=var, show="●" if label == "Password" else ""); e.grid(row=r, column=1, sticky="ew", padx=8)
            if label == "Password": e.bind("<Return>", lambda _: self.login()); e.focus_set()
        ttk.Button(frm, text="Discover", command=self.discover).grid(row=0, column=2); frm.columnconfigure(1, weight=1)
        self.status = tk.StringVar(value="Start JewelServer.exe on one PC. Internet is not required.")
        ttk.Label(f, textvariable=self.status, foreground="#555").pack(anchor="w", pady=12)
        ttk.Button(f, text="Sign in", command=self.login).pack(fill="x", ipady=4)

    def discover(self):
        self.status.set("Searching private LAN…"); self.update_idletasks(); servers = discover_servers()
        if servers:
            self.server.set(servers[0]["url"]); self.status.set(f"Found {servers[0].get('name','JewelLAN')} at {servers[0]['url']}")
        else:
            self.status.set("No server found automatically. Enter its LAN address manually.")

    def login(self):
        try:
            self.api.set_url(self.server.get().strip()); self.user = self.api.login(self.username.get().strip(), self.password.get())
            self.cfg["server_url"] = self.api.base_url; save_config(self.cfg); self.destroy()
        except ApiError as e:
            messagebox.showerror("Login failed", str(e), parent=self)


class Page(ttk.Frame):
    def __init__(self, parent, app): super().__init__(parent); self.app = app; self.api = app.api
    def heading(self, title, sub=""):
        ttk.Label(self, text=title, font=("Segoe UI", 18, "bold")).pack(anchor="w")
        if sub: ttk.Label(self, text=sub, foreground="#666").pack(anchor="w", pady=(0, 10))
    def tree(self, parent, cols, widths=None):
        widths = widths or {}; t = ttk.Treeview(parent, columns=cols, show="headings", selectmode="browse")
        for c in cols:
            t.heading(c, text=c.replace("_", " ").title()); t.column(c, width=widths.get(c, 110), anchor="e" if any(x in c for x in ("weight","amount","total","rate","gst","cost")) else "w")
        s = ttk.Scrollbar(parent, orient="vertical", command=t.yview); t.configure(yscrollcommand=s.set); s.pack(side="right", fill="y"); t.pack(side="left", fill="both", expand=True); return t


class App(ttk.Frame):
    def __init__(self, root, api, cfg, user):
        super().__init__(root); self.root = root; self.api = api; self.cfg = cfg; self.user = user; self.settings = {}; self.branches = []; self.counters = []
        self.pack(fill="both", expand=True); root.title(f"{APP_TITLE} — {user['full_name']}"); root.minsize(1120, 700)
        if os.name == "nt": root.state("zoomed")
        else: root.geometry("1280x800")
        style = ttk.Style()
        try: style.theme_use("vista" if os.name == "nt" else "clam")
        except Exception: pass
        style.configure("Nav.TButton", font=("Segoe UI", 10), padding=(12, 10), anchor="w"); style.configure("Treeview", rowheight=27)
        self.load_settings(); self.build()
        if user.get("must_change_password"): root.after(400, lambda: self.change_password(True))

    def load_settings(self):
        d = self.api.get("/api/settings"); self.settings, self.branches, self.counters = d["settings"], d["branches"], d["counters"]

    def build(self):
        top = ttk.Frame(self, padding=(14,8)); top.pack(fill="x")
        ttk.Label(top, text=self.settings.get("business_name", "JewelLAN"), font=("Segoe UI", 15, "bold")).pack(side="left")
        ttk.Label(top, text=f"LAN: {self.api.base_url}", foreground="#666").pack(side="right")
        body = ttk.Frame(self); body.pack(fill="both", expand=True); nav = ttk.Frame(body, padding=8); nav.pack(side="left", fill="y"); ttk.Separator(body, orient="vertical").pack(side="left", fill="y"); self.content = ttk.Frame(body, padding=14); self.content.pack(side="left", fill="both", expand=True)
        role = self.user.get("role", "cashier")
        pages = [("Dashboard", DashboardPage), ("Inventory & Tags", InventoryPage), ("Customers / Parties", PartiesPage)]
        if role in ("admin","manager","cashier"): pages.insert(1, ("POS / Billing", POSPage))
        if role in ("admin","manager","inventory"): pages.append(("Purchases", PurchasesPage))
        if role in ("admin","manager","cashier"): pages.append(("Repairs & Orders", JobsPage))
        if role in ("admin","manager","inventory"): pages.append(("Stock Audit", StockAuditPage))
        if role in ("admin","manager","accounts"): pages.append(("Reports", ReportsPage))
        if role in ("admin","manager"): pages.append(("Administration", AdminPage))
        for name, cls in pages: ttk.Button(nav, text=name, style="Nav.TButton", command=lambda c=cls: self.show(c)).pack(fill="x", pady=2)
        ttk.Separator(nav).pack(fill="x", pady=10); ttk.Button(nav, text="Change Password", style="Nav.TButton", command=self.change_password).pack(fill="x"); ttk.Button(nav, text="Exit", style="Nav.TButton", command=self.root.destroy).pack(fill="x", pady=2)
        self.show(DashboardPage)

    def show(self, cls):
        for w in self.content.winfo_children(): w.destroy()
        cls(self.content, self).pack(fill="both", expand=True)

    def error(self, e): messagebox.showerror("JewelLAN", str(e), parent=self.root)

    def change_password(self, forced=False):
        data = form_dialog(self.root, "Change password", [("old_password","Current password"),("new_password","New password"),("again","Repeat new password")])
        if not data:
            if forced: self.root.after(300, lambda: self.change_password(True))
            return
        if data["new_password"] != data["again"]: self.error("New passwords do not match"); return
        try: self.api.post("/api/auth/change-password", {"old_password": data["old_password"], "new_password": data["new_password"]}); self.user["must_change_password"] = 0
        except Exception as e: self.error(e); self.root.after(300, lambda: self.change_password(True)) if forced else None


class DashboardPage(Page):
    def __init__(self, parent, app):
        super().__init__(parent, app); self.heading("Dashboard", "Live figures from the local shop server."); self.box = ttk.Frame(self); self.box.pack(fill="x"); self.txt = tk.Text(self, height=24, font=("Consolas", 10)); self.txt.pack(fill="both", expand=True, pady=10); self.refresh()
    def refresh(self):
        try: d = self.api.get("/api/dashboard")
        except Exception as e: self.app.error(e); return
        for w in self.box.winfo_children(): w.destroy()
        for label, value in (("Stock pieces", d["stock"]["c"]),("Net stock", f"{d['stock']['nw']:.3f} g"),("Today's sales", money(d["today_sales"]["total"])),("Pending work", d["pending_repairs"] + d["pending_orders"])):
            f = ttk.LabelFrame(self.box, text=label, padding=12); f.pack(side="left", fill="x", expand=True, padx=(0,8)); ttk.Label(f, text=str(value), font=("Segoe UI", 18, "bold")).pack(anchor="w")
        text = "METAL RATES\n" + "\n".join(f"{x['metal']} {x['purity']}: {money(x['rate_per_gram'])}/g" for x in d["rates"]) + "\n\nSTOCK CATEGORIES\n" + "\n".join(f"{x['category']}: {x['c']} pieces" for x in d["categories"])
        self.txt.delete("1.0","end"); self.txt.insert("1.0", text)


class InventoryPage(Page):
    COLS = ("tag_no","name","metal","purity","gross_weight","net_weight","huid","status","cost_amount")
    FIELDS = [("name","Item name"),("category","Category"),("metal","Metal",["Gold","Silver","Platinum","Other"]),("purity","Purity",["999","995","958","925","916","875","833","750","585","417"]),("gross_weight","Gross weight"),("stone_weight","Stone weight"),("net_weight","Net weight"),("stone_value","Stone value"),("cost_amount","Cost amount"),("making_type","Making type",["per_gram","percent","fixed"]),("making_value","Making value"),("wastage_percent","Wastage %"),("huid","HUID"),("certificate_no","Certificate"),("barcode","Barcode (blank=tag)"),("rfid_epc","RFID EPC")]
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
        d=form_dialog(self,"Jewellery item",self.FIELDS,defaults or {"metal":"Gold","purity":"916","making_type":"per_gram","category":"Ring"})
        if not d:return None
        for k in ("gross_weight","stone_weight","net_weight","stone_value","cost_amount","making_value","wastage_percent"):
            try:d[k]=float(d.get(k) or 0)
            except ValueError:raise RuntimeError(f"{k} must be numeric")
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
        super().__init__(parent,app);self.lines=[];self.old=[];self.quote={};self.heading("POS / Billing","Scan tags, price centrally, split payment, and post an atomic GST invoice.")
        top=ttk.Frame(self);top.pack(fill="x");ttk.Label(top,text="Scan barcode/tag").pack(side="left");self.scan=tk.StringVar();e=ttk.Entry(top,textvariable=self.scan,font=("Consolas",13));e.pack(side="left",fill="x",expand=True,padx=8);e.bind("<Return>",self.add_scan);ttk.Button(top,text="Add",command=lambda:self.add_scan(None)).pack(side="left")
        pan=ttk.Panedwindow(self,orient="horizontal");pan.pack(fill="both",expand=True,pady=8);left=ttk.Frame(pan);right=ttk.Frame(pan,padding=10);pan.add(left,weight=4);pan.add(right,weight=2);h=ttk.Frame(left);h.pack(fill="both",expand=True);self.t=self.tree(h,self.COLS,{"description":160});ttk.Button(left,text="Remove selected",command=self.remove).pack(anchor="w",pady=5)
        self.customers=[];self.customer=ttk.Combobox(right,state="readonly");self.customer.pack(fill="x");ttk.Button(right,text="Refresh customers",command=self.load_customers).pack(fill="x",pady=(4,8));self.load_customers();self.discount=tk.StringVar(value="0");ttk.Label(right,text="Invoice discount").pack(anchor="w");ttk.Entry(right,textvariable=self.discount).pack(fill="x");ttk.Button(right,text="Add old-gold exchange",command=self.old_gold).pack(fill="x",pady=6);self.old_label=tk.StringVar(value="Old gold: ₹0.00");ttk.Label(right,textvariable=self.old_label).pack(anchor="w")
        self.totals={}
        for k,l in (("subtotal","Subtotal"),("gst","GST"),("total","Grand total"),("payable","Balance")):
            row=ttk.Frame(right);row.pack(fill="x",pady=2);ttk.Label(row,text=l).pack(side="left");v=tk.StringVar(value="₹0.00");self.totals[k]=v;ttk.Label(row,textvariable=v,font=("Segoe UI",11,"bold") if k in ("total","payable") else None).pack(side="right")
        self.pay={}
        for k,l in (("cash","Cash"),("card","Card"),("upi","UPI"),("credit","Credit")):
            row=ttk.Frame(right);row.pack(fill="x",pady=2);ttk.Label(row,text=l,width=8).pack(side="left");v=tk.StringVar(value="0");self.pay[k]=v;ttk.Entry(row,textvariable=v,width=14).pack(side="right")
        ttk.Button(right,text="Recalculate",command=self.requote).pack(fill="x",pady=5);ttk.Button(right,text="Set balance to cash",command=self.cash).pack(fill="x");ttk.Button(right,text="POST SALE & PRINT",command=self.checkout).pack(fill="x",ipady=8,pady=10);e.focus_set()
    def load_customers(self):
        try:self.customers=self.api.get("/api/customers");self.customer["values"]=["Walk-in Customer"]+[f"{x['name']} — {x.get('phone') or ''} [#{x['id']}]" for x in self.customers];self.customer.current(0)
        except Exception:pass
    def add_scan(self,event):
        code=self.scan.get().strip();self.scan.set("")
        if not code:return
        try:i=self.api.get(f"/api/items/barcode/{code}");
        except Exception as e:self.app.error(e);return
        if i["status"]!="in_stock":self.app.error(f"{i['tag_no']} is {i['status']}");return
        if not any(x["item_id"]==i["id"] for x in self.lines):self.lines.append({"item_id":i["id"]});self.requote()
    def requote(self):
        try:self.quote=self.api.post("/api/sales/quote",{"lines":self.lines,"discount":float(self.discount.get() or 0),"old_gold":self.old});self.render()
        except Exception as e:
            if self.lines:self.app.error(e)
    def render(self):
        self.t.delete(*self.t.get_children());[self.t.insert("","end",iid=str(r["item_id"]),values=tuple(r.get(c,"") for c in self.COLS)) for r in self.quote.get("lines",[])]
        for k,v in self.totals.items():v.set(money(self.quote.get(k,0)))
        self.old_label.set("Old gold: "+money(sum(float(x.get("value",0)) for x in self.old)))
    def remove(self):
        if self.t.selection():self.lines=[x for x in self.lines if x["item_id"]!=int(self.t.selection()[0])];self.requote()
    def old_gold(self):
        d=form_dialog(self,"Old gold",[("metal","Metal",["Gold","Silver"]),("purity","Purity"),("gross_weight","Gross weight"),("deduction_percent","Deduction %"),("rate","Rate / g"),("value","Exchange value"),("notes","Notes")],{"metal":"Gold","purity":"916","gross_weight":"0","deduction_percent":"0","rate":"0","value":"0"})
        if not d:return
        try:
            for k in ("gross_weight","deduction_percent","rate","value"):d[k]=float(d[k] or 0)
            if not d["value"]:d["value"]=d["gross_weight"]*(1-d["deduction_percent"]/100)*d["rate"]
            self.old.append(d);self.requote()
        except ValueError:self.app.error("Old-gold values must be numeric")
    def cash(self):
        self.pay["cash"].set(f"{self.quote.get('payable',0):.2f}");[self.pay[k].set("0") for k in ("card","upi","credit")]
    def checkout(self):
        if not self.lines:return
        try:
            idx=self.customer.current();cid=self.customers[idx-1]["id"] if idx>0 else None;p={k:float(v.get() or 0) for k,v in self.pay.items()};body={"client_request_id":str(uuid.uuid4()),"branch_id":int(self.app.cfg.get("branch_id",1)),"counter_id":self.app.cfg.get("counter_id") or None,"customer_id":cid,"lines":self.lines,"discount":float(self.discount.get() or 0),"old_gold":self.old,"payment_cash":p["cash"],"payment_card":p["card"],"payment_upi":p["upi"],"payment_credit":p["credit"]};r=self.api.post("/api/sales",body);open_pdf(self.api.request("GET",f"/api/sales/{r['id']}/invoice.pdf"),f"{r['invoice_no']}.pdf");messagebox.showinfo("Sale posted",f"{r['invoice_no']}\n{money(r['total'])}",parent=self);self.lines=[];self.old=[];self.quote={};self.discount.set("0");self.render()
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


class AdminPage(Page):
    def __init__(self,parent,app):
        super().__init__(parent,app);self.heading("Administration","Metal rates, users, backups, business settings and this workstation.");self.nb=ttk.Notebook(self);self.nb.pack(fill="both",expand=True);self.make_rates();self.make_backup();self.make_pc();
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
        f=ttk.Frame(self.nb,padding=8);self.nb.add(f,text="Business");keys=("business_name","business_address","business_phone","business_gstin","invoice_prefix","tag_prefix","gst_default","label_width_mm","label_height_mm","backup_interval_hours","backup_retention_days");self.bv={}
        for i,k in enumerate(keys):self.bv[k]=tk.StringVar(value=self.app.settings.get(k,""));ttk.Label(f,text=k.replace("_"," ").title()).grid(row=i,column=0,sticky="w",pady=3);ttk.Entry(f,textvariable=self.bv[k]).grid(row=i,column=1,sticky="ew",padx=8)
        f.columnconfigure(1,weight=1);ttk.Button(f,text="Save",command=self.save_business).grid(row=len(keys)+1,column=0,columnspan=2,sticky="ew",pady=10)
    def save_business(self):
        try:self.api.put("/api/settings",{k:v.get() for k,v in self.bv.items()});self.app.load_settings();messagebox.showinfo("Settings","Saved",parent=self)
        except Exception as e:self.app.error(e)


def main():
    root=tk.Tk();root.withdraw();cfg=load_config();api=Api(cfg.get("server_url",""));login=LoginDialog(root,api,cfg);root.wait_window(login)
    if not login.user:return
    root.deiconify();App(root,api,cfg,login.user);root.mainloop()


if __name__ == "__main__":
    main()
