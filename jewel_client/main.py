from __future__ import annotations

import datetime as dt
import os
import uuid
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from .api import Api, ApiError, discover_servers, format_fingerprint, probe_server_fingerprint, secure_url
from .config import load_config, load_pending_posts, remove_pending_post, save_config, save_pending_posts
from .scale import read_scale
from .ui_theme import PALETTE, apply_theme, card, divider, status_pill
from .returns_page import ReturnsPage
# Single shared implementation (breaks the old main<->billing_page cycle).
from .ui_common import Page, center, form_dialog, money, open_pdf

APP_TITLE = "JewelLAN Jewellery ERP"
PRODUCTION_HARDENED_V1 = True

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
            msg=str(e)
            if "403" in msg or "Permission" in msg or "FORBIDDEN" in msg:
                msg="Company setup needs Administrator. Sign in as admin for first setup.\n\nDetails: "+msg
            messagebox.showerror('Company setup',msg,parent=root);defaults.update(values)


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
        self.entries = {}
        for r, (label, var) in enumerate((("Server", self.server), ("Username", self.username), ("Password", self.password))):
            ttk.Label(frm, text=label, style="SurfaceMuted.TLabel").grid(row=r*2, column=0, columnspan=2, sticky="w", pady=(6, 4))
            e = ttk.Entry(frm, textvariable=var, show="●" if label == "Password" else "", font=("Segoe UI", 10))
            e.grid(row=r*2+1, column=0, sticky="ew", ipady=6)
            e.bind("<Return>", lambda _e: self.login())
            self.entries[label] = e
            if label == "Server": ttk.Button(frm, text="Discover", style="Secondary.TButton", command=self.discover).grid(row=r*2+1, column=1, padx=(8,0))
            if label == "Password":
                self._pw_entry = e
        # Show password toggle + keyboard order Server→Username→Password→Sign in.
        self.show_pw = tk.BooleanVar(value=False)
        ttk.Checkbutton(right, text="Show password", variable=self.show_pw, command=self._toggle_pw).pack(anchor="w", pady=(6,0))
        try:self.entries["Server"].focus_set()
        except Exception:pass
        frm.columnconfigure(0, weight=1)
        self.status = tk.StringVar(value="Server discovery is available on the private LAN.")
        ttk.Label(right, textvariable=self.status, style="SurfaceMuted.TLabel", wraplength=390).pack(anchor="w", pady=(12, 12))
        self.sign_btn = ttk.Button(right, text="Sign in", style="Primary.TButton", command=self.login)
        self.sign_btn.pack(fill="x", ipady=6)

    def _toggle_pw(self):
        try:self._pw_entry.configure(show="" if self.show_pw.get() else "●")
        except Exception:pass

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
        try:self.sign_btn.configure(state="disabled", text="Signing in…")
        except Exception:pass
        self.status.set("Verifying server identity and signing in…");self.update_idletasks()
        try:
            url=secure_url(self.server.get().strip());self._trust_live_server(url,self.discovered_fingerprint);self.user = self.api.login(self.username.get().strip(), self.password.get());self.destroy()
        except ApiError as e:
            messagebox.showerror("Login failed", str(e), parent=self)
            self.status.set("Sign-in failed. Check server, username and password.")
        finally:
            try:self.sign_btn.configure(state="normal", text="Sign in")
            except Exception:pass

# Page is imported from ui_common (single source of truth).


class PendingPostsPage(Page):
    """Reconcile financial writes whose network outcome was unknown."""

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.heading("Pending Posts", "Reconcile timed-out financial writes before retrying. Never create a second request for the same operation.")
        bar=ttk.Frame(self);bar.pack(fill="x",pady=(0,10))
        ttk.Button(bar,text="Refresh",style="Secondary.TButton",command=self.refresh).pack(side="left")
        ttk.Button(bar,text="Reconcile selected",style="Primary.TButton",command=self.reconcile).pack(side="left",padx=6)
        self.status=tk.StringVar(value="")
        ttk.Label(bar,textvariable=self.status,style="Muted.TLabel").pack(side="left",padx=10)
        box=ttk.Frame(self);box.pack(fill="both",expand=True)
        self.t=self.tree(box,("request_id","operation","state","created_at","error"),{"request_id":260,"operation":100,"state":150,"created_at":160,"error":430})
        self.refresh()

    def refresh(self):
        self.t.delete(*self.t.get_children())
        posts=load_pending_posts()
        for row in posts:
            self.t.insert("","end",iid=str(row.get("request_id") or ""),values=(row.get("request_id",""),row.get("operation",""),row.get("state",""),row.get("created_at",""),row.get("error","") or ""))
        self.status.set(f"{len(posts)} pending operation" + ("" if len(posts)==1 else "s"))

    def reconcile(self):
        selection=self.t.selection()
        if not selection:return
        request_id=selection[0]
        row=next((x for x in load_pending_posts() if str(x.get("request_id"))==request_id),None)
        if not row:return self.refresh()
        operation=str(row.get("operation") or "")
        try:
            result=self.api.get(f"/api/operations/reconcile/{operation}/{request_id}")
            if result.get("state")=="confirmed":
                remove_pending_post(request_id)
                messagebox.showinfo("Operation confirmed",f"The server already confirmed {operation}: {result.get('reference') or result.get('id')}",parent=self)
            elif result.get("safe_to_retry"):
                row["state"]="pending";row["error"]="Server found no matching operation; retry the original request when ready.";save_pending_posts([row if str(x.get("request_id"))==request_id else x for x in load_pending_posts()])
                messagebox.showinfo("Safe to retry","No matching server record was found. The original request is preserved and may be retried.",parent=self)
            else:
                messagebox.showwarning("Reconciliation pending",str(result),parent=self)
            self.refresh()
        except Exception as exc:self.app.error(exc)

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
        from .ui_theme import ICONS, hero_card
        body = tk.Frame(self, bg=PALETTE["bg"]); body.pack(fill="both", expand=True)
        nav = ttk.Frame(body, style="Nav.TFrame", width=236); nav.pack(side="left", fill="y"); nav.pack_propagate(False)
        brand = ttk.Frame(nav, style="Nav.TFrame"); brand.pack(fill="x", padx=18, pady=(20, 4))
        tk.Label(brand, text="◈", bg=PALETTE["nav"], fg=PALETTE["gold"], font=("Segoe UI Semibold", 20)).pack(side="left")
        ttk.Label(brand, text="JewelLAN", style="NavBrand.TLabel").pack(side="left", padx=(8, 0))
        self.company_label=ttk.Label(nav, text=self.settings.get("business_name") or "Company not configured", style="NavMuted.TLabel", wraplength=190);self.company_label.pack(anchor="w", padx=18, pady=(0, 10))

        # Scrollable nav — 17 items overflow 720p otherwise (Administration hidden).
        nav_scroll = tk.Canvas(nav, bg=PALETTE["nav"], highlightthickness=0, borderwidth=0)
        nav_bar = ttk.Scrollbar(nav, orient="vertical", command=nav_scroll.yview)
        nav_scroll.configure(yscrollcommand=nav_bar.set)
        nav_bar.pack(side="right", fill="y")
        nav_scroll.pack(side="left", fill="both", expand=True)
        nav_inner = ttk.Frame(nav_scroll, style="Nav.TFrame")
        nav_win = nav_scroll.create_window((0,0), window=nav_inner, anchor="nw")
        def _nav_conf(_e=None):
            nav_scroll.configure(scrollregion=nav_scroll.bbox("all"))
            try:nav_scroll.itemconfigure(nav_win, width=nav_scroll.winfo_width())
            except Exception:pass
        nav_inner.bind("<Configure>", _nav_conf)
        nav_scroll.bind("<Configure>", _nav_conf)
        def _nav_wheel(ev):
            try:nav_scroll.yview_scroll(-1 if getattr(ev,"delta",0)>0 else 1, "units")
            except Exception:pass
            return "break"
        nav_scroll.bind("<MouseWheel>", _nav_wheel)
        nav_inner.bind("<MouseWheel>", _nav_wheel)

        role = self.user.get("role", "cashier")
        base_pages = [("Overview", DashboardPage), ("Pending Posts", PendingPostsPage), ("Inventory", InventoryPage), ("Parties", PartiesPage)]
        if role in ("admin","manager","cashier"): base_pages.insert(1, ("Billing", POSPage))
        if role in ("admin","manager","cashier"): base_pages.insert(2, ("Estimation", EstimationPage))
        if role in ("admin","manager"): base_pages.insert(3, ("Returns & Credit Notes", ReturnsPage))
        if role in ("admin","manager"): base_pages.insert(4, ("Exchange", ExchangePage))
        if role in ("admin","manager","inventory"): base_pages.append(("Purchases", PurchasesPage))
        if role in ("admin","manager","cashier"): base_pages.append(("Repairs & Orders", JobsPage))
        if role in ("admin","manager","inventory"): base_pages.append(("Approvals", ApprovalsPage))
        if role in ("admin","manager","inventory","accounts"): base_pages.append(("Karigar Ledger", KarigarLedgerPage))
        if role in ("admin","manager","cashier","inventory","accounts"): base_pages.append(("Schemes & Loans", SchemesLoansPage))
        if role in ("admin","manager","inventory"): base_pages.append(("Stock Audit", StockAuditPage))
        if role in ("admin","manager","accounts"): base_pages.append(("Reports", ReportsPage))
        if role in ("admin","manager"):
            base_pages.append(("TallyPrime", TallyPage))
        if role in ("admin","manager","inventory","accounts"):
            base_pages.append(("Administration", AdminPage))
        from .ui_theme import ICONS as _ICONS
        def _icon(name):
            key = {"Overview":"overview","Billing":"billing","Estimation":"estimation","Returns & Credit Notes":"returns","Exchange":"exchange","Pending Posts":"pending","Inventory":"inventory","Parties":"parties","Purchases":"purchases","Repairs & Orders":"jobs","Approvals":"approvals","Karigar Ledger":"karigar","Schemes & Loans":"schemes","Stock Audit":"audit","Reports":"reports","TallyPrime":"tally","Administration":"admin"}.get(name, "overview")
            return _ICONS.get(key, "•")
        sections = [("SELL", {"Billing","Estimation","Returns & Credit Notes","Exchange"}), ("STOCK", {"Inventory","Purchases","Approvals","Stock Audit"}), ("PEOPLE", {"Parties","Repairs & Orders","Karigar Ledger","Schemes & Loans"}), ("INSIGHT", {"Overview","Pending Posts","Reports","TallyPrime","Administration"})]
        shown_sections = set()
        pages = base_pages
        for name, cls in pages:
            for sec, members in sections:
                if name in members and sec not in shown_sections:
                    ttk.Label(nav_inner, text=sec, style="NavSection.TLabel").pack(anchor="w", padx=18, pady=(10, 2))
                    shown_sections.add(sec)
                    break
            b = ttk.Button(nav_inner, text=f"{_icon(name)}  {name}", style="Nav.TButton", command=lambda c=cls,n=name: self.show(c,n)); b.pack(fill="x", padx=10, pady=1); self.nav_buttons[name] = b
            b.bind("<MouseWheel>", _nav_wheel)

        bottom = ttk.Frame(nav, style="Nav.TFrame"); bottom.pack(side="bottom", fill="x", padx=10, pady=12)
        divider(bottom).pack(fill="x", pady=(0, 10))
        ttk.Label(bottom, text=self.user.get("full_name","User"), style="NavUser.TLabel").pack(anchor="w", padx=8)
        ttk.Label(bottom, text=self.user.get("role","" ).title(), style="NavMuted.TLabel").pack(anchor="w", padx=8, pady=(0,6))
        ttk.Button(bottom, text="Change password", style="Nav.TButton", command=self.change_password).pack(fill="x")
        ttk.Button(bottom, text="Exit", style="Nav.TButton", command=self.root.destroy).pack(fill="x")

        work = ttk.Frame(body); work.pack(side="left", fill="both", expand=True)
        top = ttk.Frame(work, style="Surface.TFrame", padding=(20, 10)); top.pack(fill="x")
        self.top_title = ttk.Label(top, text="Overview", style="Surface.TLabel", font=("Segoe UI Semibold", 13)); self.top_title.pack(side="left")
        ttk.Label(top, text="  •  Ctrl+K quick tag  •  F9 post sale", style="SurfaceMuted.TLabel", font=("Segoe UI", 8)).pack(side="left", padx=(10, 0))
        status_pill(top, f"LAN  {self.api.base_url.replace('http://','')}", "success").pack(side="right")
        self.content = ttk.Frame(work, padding=(22, 14)); self.content.pack(fill="both", expand=True)
        # Status bar: branch/counter/user/date always visible.
        self.status_var = tk.StringVar(value="")
        statusbar = ttk.Frame(work, style="Surface.TFrame", padding=(20, 6)); statusbar.pack(fill="x", side="bottom")
        ttk.Label(statusbar, textvariable=self.status_var, style="SurfaceMuted.TLabel", font=("Segoe UI", 8)).pack(side="left")
        self._refresh_statusbar()
        self.show(DashboardPage, "Overview")
        try:self.root.bind_all("<Control-k>", lambda _e: self.quick_tag(), add="+")
        except Exception:pass

    def _refresh_statusbar(self):
        try:
            br = next((b.get("name","") for b in self.branches if str(b.get("id"))==str(self.cfg.get("branch_id",1))), "")
            self.status_var.set(f"Branch: {br or self.cfg.get('branch_id',1)}  •  Counter: {self.cfg.get('counter_id',1)}  •  {self.user.get('full_name','')} ({self.user.get('role','')})  •  Offline-first — internet never blocks billing")
        except Exception:pass

    def quick_tag(self):
        """Ctrl+K: jump to inventory search from anywhere."""
        try:self.show(InventoryPage, "Inventory")
        except Exception:pass

    def show(self, cls, name=None):
        for w in self.content.winfo_children(): w.destroy()
        for b in self.nav_buttons.values(): b.configure(style="Nav.TButton")
        if name and name in self.nav_buttons: self.nav_buttons[name].configure(style="NavActive.TButton")
        if name: self.top_title.configure(text=name)
        self.current_page = cls(self.content, self); self.current_page.pack(fill="both", expand=True)

    def error(self, e):
        from .api import ApiError as _ApiError
        msg = str(e)
        if isinstance(e, _ApiError) and e.details:
            # Prefer server-provided structured message over raw repr.
            msg = str(e)
        # Map common technical errors to operator-friendly guidance.
        friendly = {
            "QUOTE_STALE": "Prices changed before posting. The quote was refreshed — review and try again.",
            "STOCK_CHANGED": "That tag was just sold or moved on another counter. Remove it and re-scan.",
            "ITEM_LOCATION_CONFLICT": "That tag belongs to another branch/counter.",
            "DAY_CLOSED": "This business date is closed for this branch.",
            "VERSION_CONFLICT": "This record changed on another PC. Refresh and retry.",
            "DISCOUNT_EXCEEDS_SUBTOTAL": "Discount exceeds subtotal. Reduce discount/loyalty.",
            "OLD_GOLD_VALUE_MISMATCH": "Old-gold value differs from net×rate. Correct it or use a manager override.",
            "IDEMPOTENCY_CONFLICT": "This request was already used with different data. Use a new request (re-enter) instead of retrying.",
        }
        code = getattr(e, "code", "") or ""
        if code in friendly:
            msg = f"{friendly[code]}\n\nDetails: {msg}"
        messagebox.showerror("JewelLAN", msg, parent=self.root)

    def change_password(self, forced=False):
        data=password_change_dialog(self.root,"Change password",forced)
        if not data:return
        if len(data["new_password"])<10:self.error("New password must be at least 10 characters");return
        if data["new_password"]!=data["again"]:self.error("New passwords do not match");return
        try:self.api.post("/api/auth/change-password",{"old_password":data["old_password"],"new_password":data["new_password"]});self.user["must_change_password"]=0;messagebox.showinfo("Password","Password changed.",parent=self.root)
        except Exception as e:self.error(e)

class DashboardPage(Page):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        from .ui_theme import hero_card, kpi_card
        hero = hero_card(self); hero.pack(fill="x", pady=(0,12))
        hinner = tk.Frame(hero, bg=PALETTE["nav"]); hinner.pack(fill="x", padx=22, pady=16)
        self.hero_title = tk.Label(hinner, text="Shop overview", bg=PALETTE["nav"], fg="#FFFFFF", font=("Segoe UI Semibold", 20)); self.hero_title.pack(side="left")
        self.date_var=tk.StringVar(value="");tk.Label(hinner, textvariable=self.date_var, bg=PALETTE["nav"], fg="#C9CDD6", font=("Segoe UI", 10)).pack(side="left", padx=(12, 0))
        ttk.Button(hinner, text="↻ Refresh", style="Secondary.TButton", command=self.refresh).pack(side="right")
        ttk.Label(self,text="Today's billing, stock position, rates and operational health — 100% offline.",style="Muted.TLabel").pack(anchor="w",pady=(0,8))
        self.metrics = ttk.Frame(self); self.metrics.pack(fill="x")
        # Quick actions: one-tap entry to money workflows.
        qa = ttk.Frame(self); qa.pack(fill="x", pady=(12, 0))
        ttk.Label(qa, text="Quick actions", style="Muted.TLabel", font=("Segoe UI Semibold", 8)).pack(side="left", padx=(0,10))
        for label, dest in (("＋ New bill","Billing"),("◈ Estimation","Estimation"),("↩ Return","Returns & Credit Notes"),("⇄ Exchange","Exchange"),("▦ Stock","Inventory")):
            ttk.Button(qa, text=label, style="Secondary.TButton", command=lambda d=dest: self._goto(d)).pack(side="left", padx=(0,6))
        lower = ttk.Frame(self); lower.pack(fill="both",expand=True,pady=(14,0))
        self.rates_card = card(lower, 18); self.rates_card.pack(side="left", fill="both", expand=True, padx=(0,7))
        self.stock_card = card(lower, 18); self.stock_card.pack(side="left", fill="both", expand=True, padx=7)
        self.health_card = card(lower, 18); self.health_card.pack(side="left", fill="both", expand=True, padx=(7,0))
        self._kpi = {}
        self.refresh()

    def _goto(self, dest):
        try:
            cls = {"Billing":POSPage,"Estimation":EstimationPage,"Returns & Credit Notes":ReturnsPage,"Exchange":ExchangePage,"Inventory":InventoryPage}[dest]
            self.app.show(cls, dest)
        except Exception as e:self.app.error(e)

    def metric(self, key, icon, label, value, note=""):
        from .ui_theme import kpi_card
        if key not in self._kpi:
            f, val, notevar = kpi_card(self.metrics, icon, label)
            f.pack(side="left", fill="x", expand=True, padx=(0,10))
            self._kpi[key] = (val, notevar)
        val, notevar = self._kpi[key]
        val.set(str(value)); notevar.set(note)

    def refresh(self):
        try: d = self.api.get("/api/dashboard")
        except Exception as e: self.app.error(e); return
        try:
            ts = d.get("today_sales", {}); st = d.get("stock", {})
            sales_total = ts.get("total", 0); sales_c = ts.get("c", 0)
            ret_total = d.get("today_returns", {}).get("total", 0)
            pieces = st.get("c", 0)
            try:nw = float(st.get("nw", 0))
            except Exception:nw = 0.0
            pending = int(d.get("pending_repairs", 0)) + int(d.get("pending_orders", 0))
        except Exception as e:self.app.error(f"Dashboard data invalid: {e}");return
        self.date_var.set(f"Business date {d.get('business_date','')}  •  {self.app.settings.get('business_name','')}")
        for parent in (self.rates_card,self.stock_card,self.health_card):
            for w in parent.winfo_children(): w.destroy()
        self.metric("sales", "₹", "Today's sales", money(sales_total), f"{sales_c} bills • returns {money(ret_total)}")
        self.metric("pieces", "▦", "Stock pieces", pieces, "Serialized tags")
        self.metric("net", "⚖", "Net stock", f"{nw:.3f} g", "All metals")
        self.metric("pending", "◷", "Pending work", pending, "Repairs + orders")

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
    FIELDS = [("name","Item name *"),("category","Category"),("metal","Metal",["Gold","Silver","Platinum","Other"]),("purity","Purity",["999","995","958","925","916","875","833","750","585","417"]),("gross_weight","Gross weight (g) *"),("stone_weight","Stone weight (g)"),("net_weight","Net weight (auto = gross - stone)"),("stone_value","Stone value"),("cost_amount","Cost amount"),("making_type","Making type",["per_gram","percent","fixed"]),("making_value","Making value"),("wastage_percent","Wastage %"),("huid","HUID (6 alphanumeric, optional)"),("certificate_no","Certificate"),("barcode","Barcode (blank=tag)"),("rfid_epc","RFID EPC (optional)")]
    def __init__(self,parent,app):
        super().__init__(parent,app); self.heading("Inventory & Tagging", "Serialized jewellery with barcode, HUID, weights and movement-safe status.")
        self.can_write = app.user.get("role") in ("admin","manager","inventory")
        bar=ttk.Frame(self);bar.pack(fill="x")
        self.q=tk.StringVar()
        e=ttk.Entry(bar,textvariable=self.q,width=30);e.pack(side="left",fill="x",expand=True);e.bind("<Return>",lambda _:self.refresh())
        ttk.Button(bar,text="Search",command=self.refresh).pack(side="left",padx=4)
        if self.can_write:
            ttk.Button(bar,text="Add",style="Primary.TButton",command=self.add).pack(side="left")
            ttk.Button(bar,text="Edit",command=self.edit).pack(side="left",padx=4)
        else:
            ttk.Label(bar,text="View only for this role",style="Muted.TLabel").pack(side="left",padx=6)
        ttk.Button(bar,text="Print tag",command=self.print_tag).pack(side="left")
        ttk.Button(bar,text="Bulk labels",command=self.print_bulk).pack(side="left",padx=4)
        ttk.Button(bar,text="Movements",command=self.movements).pack(side="left",padx=4)
        if app.user.get("role") in ("admin", "manager","inventory"):
            ttk.Button(bar,text="Transfer",command=self.transfer).pack(side="left",padx=4)
        if app.user.get("role") in ("admin", "manager"):
            ttk.Button(bar,text="Opening stock",style="Secondary.TButton",command=self.opening_stock).pack(side="left",padx=(8,0))
            ttk.Button(bar,text="Bulk CSV",command=self.bulk_import).pack(side="left",padx=4)
        ttk.Button(bar,text="Read scale",command=self.read_scale_show).pack(side="right")
        h=ttk.Frame(self);h.pack(fill="both",expand=True,pady=8);self.t=self.tree(h,self.COLS,{"name":180,"tag_no":120});self.refresh()
        if not self.can_write:
            ttk.Label(self,text="Your role can search, print and view movements. Add/Edit needs Inventory permission.",style="Muted.TLabel",wraplength=900).pack(anchor="w",pady=(6,0))
    def read_scale_show(self):
        try:
            w=read_scale(self.app.cfg.get("scale_port",""),int(self.app.cfg.get("scale_baud") or 9600))
            messagebox.showinfo("Scale",f"{w:.3f} g — will prefill next Add.",parent=self)
        except Exception as e:self.app.error(e)
    def refresh(self):
        try:r=self.api.get("/api/items",q=self.q.get(),limit=1000)
        except Exception as e:self.app.error(e);return
        self.t.delete(*self.t.get_children());[self.t.insert("","end",iid=str(x["id"]),values=tuple(x.get(c,"") for c in self.COLS)) for x in r]
        if not self.t.get_children():
            # Empty state is shown via status, tree stays blank but explained.
            pass
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
        d["branch_id"]=int(self.app.cfg.get("branch_id",1));d["counter_id"]=self.app.cfg.get("counter_id") or None
        if original.get("version") is not None:d["expected_version"]=int(original["version"])
        return d

    def add(self):
        try:
            # Offline scale auto-capture: prefill gross weight if scale configured.
            defaults={"metal":"Gold","purity":"916","making_type":"per_gram","category":"Ring"}
            try:
                cfg=self.app.cfg
                if cfg.get("scale_port"):
                    w=read_scale(cfg.get("scale_port",""),int(cfg.get("scale_baud") or 9600))
                    if w>0:defaults["gross_weight"]=f"{w:.3f}"
            except Exception:pass
            d=self.values(defaults);
            if d:r=self.api.post("/api/items",d);self.refresh();messagebox.showinfo("Inventory",f"Created {r['tag_no']}",parent=self)
        except Exception as e:self.app.error(e)
    def bulk_import(self):
        """Offline CSV bulk import with preview. Columns: name,category,metal,purity,gross_weight,stone_weight,making_type,making_value,stone_value,cost_amount,wastage_percent,huid,certificate_no,barcode,rfid_epc"""
        from tkinter import filedialog
        import csv
        path=filedialog.askopenfilename(parent=self,title="Select CSV for bulk import",filetypes=[("CSV","*.csv")])
        if not path:return
        try:
            with open(path,newline='',encoding='utf-8-sig') as fh:
                rows=list(csv.DictReader(fh))
        except Exception as e:self.app.error(f"Cannot read CSV: {e}");return
        if not rows:self.app.error("CSV is empty");return
        # Preview first 10 + validate all
        errors=[];items=[]
        for n,r in enumerate(rows,2):
            try:
                it={k:(r.get(k) or '').strip() for k in ("name","category","metal","purity","making_type","huid","certificate_no","barcode","rfid_epc")}
                for k in ("gross_weight","stone_weight","stone_value","cost_amount","making_value","wastage_percent"):
                    it[k]=float((r.get(k) or 0) or 0)
                if not it["name"]:raise ValueError("name required")
                if it["stone_weight"]>it["gross_weight"]+0.0005:raise ValueError("stone> gross")
                it["net_weight"]=round(it["gross_weight"]-it["stone_weight"],3)
                huid=it.get("huid","").upper()
                if huid and (len(huid)!=6 or not huid.isalnum()):raise ValueError("HUID must be 6 alnum")
                it["huid"]=huid
                items.append(it)
            except Exception as e:errors.append(f"Row {n}: {e}")
        if errors:
            messagebox.showerror("Bulk import validation",f"{len(errors)} row(s) invalid:\n"+"\n".join(errors[:15]),parent=self);return
        if not messagebox.askyesno("Bulk import",f"{len(items)} item(s) valid. Preview:\n"+", ".join(i['name'][:20] for i in items[:5])+(f" ... +{len(items)-5} more" if len(items)>5 else "")+"\n\nPost as opening stock?",parent=self):return
        ref=simpledialog.askstring("Bulk import","Reference/batch name:",initialvalue="Bulk import",parent=self)
        if not ref:return
        try:
            r=self.api.post("/api/opening-stock",{"branch_id":int(self.app.cfg.get("branch_id",1)),"counter_id":self.app.cfg.get("counter_id") or None,"reference":ref,"items":items})
            self.refresh();messagebox.showinfo("Bulk import",f"Recorded {r['item_count']} item(s).",parent=self)
        except Exception as e:self.app.error(e)
    def opening_stock(self):
        try:
            d=self.values()
            if not d:return
            reference=simpledialog.askstring("Opening stock","Reference or opening-stock batch name:",initialvalue="Opening stock",parent=self)
            if not reference:return
            r=self.api.post("/api/opening-stock",{"branch_id":d.pop("branch_id"),"counter_id":d.pop("counter_id"),"reference":reference,"items":[d]})
            self.refresh();messagebox.showinfo("Opening stock",f"Recorded {r['item_count']} item(s) with journal {r['journal_id']}.",parent=self)
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
        if not iid:
            messagebox.showinfo("Inventory","Select an item first.",parent=self);return
        d=form_dialog(self,"Print tag",[("format","Format",["PDF (Windows printer)","ZPL (Zebra direct)","TSPL (TSC direct)"])],{"format":"PDF (Windows printer)"})
        if not d:return
        fmt=str(d.get("format",""))
        try:
            if fmt.startswith("ZPL"):
                data=self.api.request("GET",f"/api/items/{iid}/label.zpl")
                self._send_thermal(data, f"tag-{iid}.zpl")
            elif fmt.startswith("TSPL"):
                data=self.api.request("GET",f"/api/items/{iid}/label.tspl")
                self._send_thermal(data, f"tag-{iid}.tspl")
            else:open_pdf(self.api.request("GET",f"/api/items/{iid}/label.pdf"),f"tag-{iid}.pdf")
        except Exception as e:self.app.error(e)
    def _send_thermal(self, data, filename):
        from tkinter import filedialog
        from .label_send import save_file, send_serial, send_tcp
        if isinstance(data, (bytes, bytearray)):text=bytes(data).decode("utf-8", errors="ignore")
        else:text=str(data)
        d=form_dialog(self,"Thermal send",[("target","Send to",["Save .zpl/.tspl file","Serial COM (USB)","TCP 9100 (LAN printer)"]),("port","COM port / IP (e.g. COM3 or 192.168.1.50)"),("baud","Baud (serial only)")],{"target":"Save .zpl/.tspl file","baud":"9600"})
        if not d:return
        try:
            if d["target"].startswith("Save"):
                p=filedialog.asksaveasfilename(parent=self,initialfile=filename,defaultextension=filename.rsplit(".",1)[-1]);
                if not p:return
                save_file(text,p);messagebox.showinfo("Labels",f"Saved {p}\nCopy to printer via USB/driver.",parent=self)
            elif d["target"].startswith("Serial"):
                send_serial(text,d.get("port",""),int(d.get("baud") or 9600));messagebox.showinfo("Labels","Sent to printer.",parent=self)
            else:
                host=d.get("port","").split(":")[0];prt=d.get("port","").split(":")[1] if ":" in d.get("port","") else 9100
                send_tcp(text,host,int(prt));messagebox.showinfo("Labels","Sent to printer.",parent=self)
        except Exception as e:self.app.error(e)
    def print_bulk(self):
        # Bulk re-print current search (first 50) or entered IDs. PDF/ZPL/TSPL.
        d=form_dialog(self,"Bulk labels",[("format","Format",["PDF (Windows printer)","ZPL (Zebra direct)","TSPL (TSC direct)"]),("ids","Item IDs comma (blank = current search first 50)"),("note","PDF prints at 100%. ZPL/TSPL sends raw.")],{"format":"PDF (Windows printer)"})
        if d is None:return
        fmt=str(d.get("format",""));
        try:
            if str(d.get("ids") or "").strip():
                ids=[int(x.strip()) for x in str(d["ids"]).split(",") if x.strip()][:100]
            else:
                ids=[int(x) for x in self.t.get_children()[:50]]
            if not ids:self.app.error("No tags to print");return
            if fmt.startswith("ZPL"):
                data=self.api.request("POST","/api/items/labels.zpl",json_body={"item_ids":ids})
                self._send_thermal(data,f"tags-{len(ids)}.zpl")
            elif fmt.startswith("TSPL"):
                data=self.api.request("POST","/api/items/labels.tspl",json_body={"item_ids":ids})
                self._send_thermal(data,f"tags-{len(ids)}.tspl")
            else:
                data=self.api.request("POST","/api/items/labels.pdf",json_body={"item_ids":ids})
                open_pdf(data,f"tags-{len(ids)}.pdf")
                messagebox.showinfo("Labels",f"Opened {len(ids)} tag(s). Print at 100% scale, no fit-to-page.",parent=self)
        except ValueError:self.app.error("IDs must be numeric")
        except Exception as e:self.app.error(e)
    def movements(self):
        iid=self.selected()
        if not iid:
            messagebox.showinfo("Inventory","Select an item to see its stock movements.",parent=self);return
        try:data=self.api.get(f"/api/items/{iid}")
        except Exception as e:self.app.error(e);return
        rows=data.get("movements",[])
        if not rows:
            messagebox.showinfo("Movements","No movements recorded for this tag.",parent=self);return
        lines="\n".join(f"{m.get('created_at','')[:16]}  {m.get('movement_type','')}  {m.get('from_location','')} → {m.get('to_location','')}  {m.get('note','') or ''}" for m in rows[:30])
        messagebox.showinfo(f"Movements — {data['item'].get('tag_no','')}",lines,parent=self)
    def transfer(self):
        iid=self.selected()
        if not iid:
            messagebox.showinfo("Inventory","Select an in-stock item to transfer.",parent=self);return
        try:branches=self.app.branches
        except Exception:branches=[]
        if not branches:
            self.app.error("No branches loaded");return
        names=[f"{b['id']}: {b.get('name','')}" for b in branches]
        d=form_dialog(self,"Transfer item",[("branch","Branch",names),("counter_id","Counter ID (blank = none)"),("note","Note")],{"branch":names[0]})
        if not d:return
        try:
            bid=int(str(d.get("branch","")).split(":")[0])
            cid=d.get("counter_id","").strip()
            cid=int(cid) if cid else None
            r=self.api.post(f"/api/items/{iid}/transfer",{"branch_id":bid,"counter_id":cid,"note":d.get("note","")})
            messagebox.showinfo("Transfer",f"{r.get('tag_no','Item')} moved.",parent=self);self.refresh()
        except ValueError:self.app.error("Counter ID must be numeric or blank")
        except Exception as e:self.app.error(e)


class PartiesPage(Page):
    def __init__(self,parent,app):
        super().__init__(parent,app);self.heading("Customers / Suppliers / Karigars","Party masters, search, balances and karigar ledger shortcut.");self.nb=ttk.Notebook(self);self.nb.pack(fill="both",expand=True);self.tables={};self._rows={};self.search_vars={}
        for typ in ("customers","suppliers","karigars"):
            f=ttk.Frame(self.nb,padding=8);self.nb.add(f,text=typ.title())
            bar=ttk.Frame(f);bar.pack(fill="x")
            sv=tk.StringVar();self.search_vars[typ]=sv
            e=ttk.Entry(bar,textvariable=sv,width=28);e.pack(side="left");e.bind("<Return>",lambda _e,t=typ:self.refresh(t))
            ttk.Button(bar,text="Search",command=lambda t=typ:self.refresh(t)).pack(side="left",padx=4)
            ttk.Button(bar,text="Add",command=lambda t=typ:self.add(t)).pack(side="left")
            ttk.Button(bar,text="Edit",command=lambda t=typ:self.edit(t)).pack(side="left",padx=4)
            ttk.Button(bar,text="Refresh",command=lambda t=typ:self.refresh(t)).pack(side="left")
            h=ttk.Frame(f);h.pack(fill="both",expand=True,pady=8);cols=("code","name","phone","balance") if typ!="karigars" else ("code","name","phone","metal_balance_grams","cash_balance");self.tables[typ]=self.tree(h,cols,{"name":220});self.refresh(typ)
    def refresh(self,t):
        try:r=self.api.get(f"/api/{t}",q=self.search_vars[t].get().strip())
        except Exception as e:self.app.error(e);return
        self._rows[t]={str(x["id"]):x for x in r}
        tr=self.tables[t];tr.delete(*tr.get_children());[tr.insert("","end",iid=str(x["id"]),values=tuple(x.get(c,"") for c in tr["columns"])) for x in r]
    def add(self,t):
        fields=[("name","Name *"),("phone","Phone"),("address","Address"),("notes","Notes")];
        if t=="customers":fields += [("email","Email"),("gstin","GSTIN (15 chars, optional)"),("birthday","Birthday YYYY-MM-DD"),("anniversary","Anniversary YYYY-MM-DD")]
        elif t=="suppliers":fields += [("email","Email"),("gstin","GSTIN (15 chars, optional)")]
        d=form_dialog(self,f"Add {t[:-1]}",fields)
        if not d:return
        if not d.get("name","").strip():
            self.app.error("Name is required");return
        if d.get("gstin","").strip() and len(d["gstin"].strip())!=15:
            self.app.error("GSTIN must be 15 characters or left blank");return
        for dk in ("birthday","anniversary"):
            if d.get(dk,"").strip():
                try:dt.date.fromisoformat(d[dk].strip())
                except ValueError:self.app.error(f"{dk} must be YYYY-MM-DD or blank");return
        try:self.api.post(f"/api/{t}",d);self.refresh(t)
        except Exception as e:self.app.error(e)
    def edit(self,t):
        sel=self.tables[t].selection()
        if not sel:messagebox.showinfo("Parties","Select a row first.",parent=self);return
        pid=sel[0];cur=self._rows[t].get(pid,{})
        if t=="customers":fields=[("name","Name *"),("phone","Phone"),("email","Email"),("address","Address"),("gstin","GSTIN"),("birthday","Birthday YYYY-MM-DD"),("anniversary","Anniversary YYYY-MM-DD"),("notes","Notes")]
        elif t=="suppliers":fields=[("name","Name *"),("phone","Phone"),("email","Email"),("address","Address"),("gstin","GSTIN"),("notes","Notes")]
        else:fields=[("name","Name *"),("phone","Phone"),("address","Address"),("notes","Notes")]
        d=form_dialog(self,f"Edit {t[:-1]}",fields,{k:str(cur.get(k) or '') for k,_ in fields})
        if not d:return
        try:self.api.put(f"/api/{t}/{int(pid)}",d);self.refresh(t)
        except Exception as e:self.app.error(e)


class PurchasesPage(Page):
    def __init__(self,parent,app):
        super().__init__(parent,app);self.heading("Purchases / Stock In","Receive a tagged jewellery piece from a supplier in one transaction.")
        bar=ttk.Frame(self);bar.pack(fill="x",pady=(0,8))
        ttk.Button(bar,text="Receive tagged item",style="Primary.TButton",command=self.receive).pack(side="left")
        ttk.Button(bar,text="Refresh",style="Secondary.TButton",command=self.refresh).pack(side="left",padx=6)
        ttk.Label(bar,text="Select a supplier by name (not ID), enter GST paid and cost.",style="Muted.TLabel").pack(side="left",padx=10)
        h=ttk.Frame(self);h.pack(fill="both",expand=True);self.t=self.tree(h,("purchase_no","supplier_name","subtotal","gst","total","paid","created_at"),{"supplier_name":200});self.refresh()
    def refresh(self):
        try:r=self.api.get("/api/purchases")
        except Exception as e:self.app.error(e);return
        self.t.delete(*self.t.get_children());[self.t.insert("","end",values=tuple(x.get(c,"") for c in self.t["columns"])) for x in r]
    def _pick_supplier(self):
        try:sups=self.api.get("/api/suppliers")
        except Exception as e:self.app.error(e);return None
        if not sups:self.app.error("Add a supplier first (Parties → Suppliers → Add)");return None
        d=tk.Toplevel(self);d.title("Select supplier");d.transient(self);d.grab_set();d.geometry("460x320")
        ttk.Label(d,text="Choose supplier",font=("Segoe UI Semibold",11)).pack(anchor="w",padx=12,pady=(12,6))
        lb=tk.Listbox(d,height=10);lb.pack(fill="both",expand=True,padx=12)
        for s in sups:lb.insert("end",f"{s['id']}: {s['name']} ({s.get('phone') or 'no phone'})")
        lb.selection_set(0)
        out={"id":None}
        def ok():
            sel=lb.curselection()
            if sel:out["id"]=sups[sel[0]]["id"]
            d.destroy()
        ttk.Button(d,text="Select",command=ok).pack(pady=10)
        self.wait_window(d)
        return out["id"]
    def receive(self):
        sid=self._pick_supplier()
        if not sid:return
        d=form_dialog(self,"Purchased jewellery",InventoryPage.FIELDS,{"metal":"Gold","purity":"916","making_type":"per_gram","category":"Ring"})
        if not d:return
        try:
            for k in ("gross_weight","stone_weight","net_weight","stone_value","cost_amount","making_value","wastage_percent"):d[k]=float(d.get(k) or 0)
            if d["cost_amount"]<=0:
                self.app.error("Cost amount must be positive");return
            pay=form_dialog(self,"Purchase payment",[("paid","Paid now *"),("gst","GST paid")],{"paid":str(d["cost_amount"]),"gst":"0"})
            if not pay:return
            paid=float(pay.get("paid") or 0);gst=float(pay.get("gst") or 0)
            if paid<0 or gst<0:
                self.app.error("Paid and GST cannot be negative");return
            req=str(uuid.uuid4())
            body={"client_request_id":req,"supplier_id":sid,"branch_id":int(self.app.cfg.get("branch_id",1)),"counter_id":self.app.cfg.get("counter_id") or None,"paid":paid,"gst":gst,"items":[d]}
            try:
                from .config import upsert_pending_post, remove_pending_post
                upsert_pending_post({"request_id":req,"operation":"purchase","state":"submitting","created_at":req,"payload":body})
            except Exception:pass
            try:
                r=self.api.post("/api/purchases",body)
                try:
                    from .config import remove_pending_post as _rm;_rm(req)
                except Exception:pass
                messagebox.showinfo("Purchase",r["purchase_no"],parent=self);self.refresh()
            except Exception as e:
                from .api import ApiError as _AE
                if isinstance(e,_AE) and (e.status==0 or e.status>=500):
                    messagebox.showwarning("Purchase outcome unknown","Server may have posted. Check Pending Posts → Reconcile before retrying.",parent=self)
                else:self.app.error(e)
        except ValueError:self.app.error("Purchase weights and amounts must be numeric")
        except Exception as e:self.app.error(e)


class JobsPage(Page):
    REPAIR_STATUS=["received","assigned","in_progress","ready","delivered","cancelled"]
    ORDER_STATUS=["new","assigned","in_progress","ready","delivered","cancelled"]
    def __init__(self,parent,app):
        super().__init__(parent,app);self.heading("Repairs & Custom Orders","Track customer jobs through karigar assignment and delivery.");self.nb=ttk.Notebook(self);self.nb.pack(fill="both",expand=True);self.tabs={}
        for typ in ("repairs","orders"):
            f=ttk.Frame(self.nb,padding=8);self.nb.add(f,text=typ.title());bar=ttk.Frame(f);bar.pack(fill="x");ttk.Button(bar,text="Add",command=lambda t=typ:self.add(t)).pack(side="left");ttk.Button(bar,text="Change status",command=lambda t=typ:self.status(t)).pack(side="left",padx=4);ttk.Button(bar,text="Refresh",command=lambda t=typ:self.refresh(t)).pack(side="left",padx=4);h=ttk.Frame(f);h.pack(fill="both",expand=True,pady=8);cols=("repair_no","customer_name","item_description","gross_weight","status","karigar_name","promised_on","estimated_amount") if typ=="repairs" else ("order_no","customer_name","description","metal","purity","target_weight","status","karigar_name","due_date");self.tabs[typ]=self.tree(h,cols,{"item_description":220,"description":220});self.refresh(typ)
    def _choices(self, kind):
        try:rows=self.api.get(f"/api/{kind}")
        except Exception:rows=[]
        return rows
    def refresh(self,t):
        try:r=self.api.get(f"/api/{t}")
        except Exception as e:self.app.error(e);return
        tr=self.tabs[t];tr.delete(*tr.get_children());[tr.insert("","end",iid=str(x["id"]),values=tuple(x.get(c,"") for c in tr["columns"])) for x in r]
    def add(self,t):
        customers=self._choices("customers");karigars=self._choices("karigars")
        if not customers:
            self.app.error("Add a customer first (Parties → Customers → Add)");return
        c_names=[f"{x['id']}: {x['name']}" for x in customers];k_names=["(none)"]+[f"{x['id']}: {x['name']}" for x in karigars]
        base=[("customer_choice","Customer",[""]) ]  # placeholder replaced below
        if t=="repairs":
            fields=[("customer_choice","Customer",c_names),("karigar_choice","Karigar",k_names),("item_description","Description *"),("gross_weight","Gross weight"),("promised_on","Promised date (YYYY-MM-DD)"),("estimated_amount","Estimate"),("advance","Advance"),("notes","Notes")]
            defaults={"customer_choice":c_names[0],"karigar_choice":k_names[0],"promised_on":dt.date.today().isoformat(),"gross_weight":"0","estimated_amount":"0","advance":"0"}
        else:
            fields=[("customer_choice","Customer",c_names),("karigar_choice","Karigar",k_names),("description","Description *"),("metal","Metal",["Gold","Silver","Platinum","Other"]),("purity","Purity"),("target_weight","Target weight"),("due_date","Due date (YYYY-MM-DD)"),("estimated_amount","Estimate"),("advance","Advance"),("notes","Notes")]
            defaults={"customer_choice":c_names[0],"karigar_choice":k_names[0],"metal":"Gold","purity":"916","due_date":dt.date.today().isoformat(),"estimated_amount":"0","advance":"0","target_weight":"0"}
        d=form_dialog(self,f"Add {t[:-1]}",fields,defaults)
        if not d:return
        try:
            def _id(choice):
                if not choice or choice=="(none)":return None
                return int(str(choice).split(":")[0])
            body={"customer_id":_id(d.get("customer_choice")),"karigar_id":_id(d.get("karigar_choice")),"notes":d.get("notes","")}
            if t=="repairs":
                if not d.get("item_description","").strip():
                    self.app.error("Description is required");return
                body.update({"item_description":d["item_description"].strip(),"gross_weight":float(d.get("gross_weight") or 0),"promised_on":d.get("promised_on") or dt.date.today().isoformat(),"estimated_amount":float(d.get("estimated_amount") or 0),"advance":float(d.get("advance") or 0)})
                dt.date.fromisoformat(body["promised_on"])
            else:
                if not d.get("description","").strip():
                    self.app.error("Description is required");return
                body.update({"description":d["description"].strip(),"metal":d.get("metal") or "Gold","purity":d.get("purity") or "916","target_weight":float(d.get("target_weight") or 0),"due_date":d.get("due_date") or dt.date.today().isoformat(),"estimated_amount":float(d.get("estimated_amount") or 0),"advance":float(d.get("advance") or 0)})
                dt.date.fromisoformat(body["due_date"])
            if body["gross_weight" if t=="repairs" else "target_weight"]<0 or body["estimated_amount"]<0 or body["advance"]<0:
                self.app.error("Weights and amounts cannot be negative");return
            self.api.post(f"/api/{t}",body);self.refresh(t)
        except ValueError:self.app.error("Dates must be YYYY-MM-DD and numbers must be numeric")
        except Exception as e:self.app.error(e)
    def status(self,t):
        if not self.tabs[t].selection():
            messagebox.showinfo("Jobs","Select a row first.",parent=self);return
        values=self.REPAIR_STATUS if t=="repairs" else self.ORDER_STATUS
        d=form_dialog(self,"Change status",[("status","Status",values)],{"status":values[0]})
        if d and d.get("status") in values:
            try:self.api.put(f"/api/{t}/{int(self.tabs[t].selection()[0])}",{"status":d["status"]});self.refresh(t)
            except Exception as e:self.app.error(e)


class EstimationPage(Page):
    """Offline estimation/quotation — no stock movement, printable, convertible."""
    def __init__(self,parent,app):
        super().__init__(parent,app);self.heading("Estimation / Quotation","Scan barcode/tag, save a price quote (NOT a tax invoice), print and convert later.");bar=ttk.Frame(self);bar.pack(fill="x",pady=(0,8))
        ttk.Button(bar,text="New estimation",style="Primary.TButton",command=self.create).pack(side="left")
        ttk.Button(bar,text="Print",command=self.print_sel).pack(side="left",padx=6)
        ttk.Button(bar,text="Convert to sale",command=self.convert).pack(side="left")
        ttk.Button(bar,text="Refresh",command=self.refresh).pack(side="left",padx=6)
        ttk.Label(bar,text="Estimations never move stock.",style="Muted.TLabel").pack(side="left",padx=10)
        h=ttk.Frame(self);h.pack(fill="both",expand=True,pady=8);self.t=self.tree(h,("est_no","customer_name","total","status","created_at"),{"customer_name":200});self.refresh()
    def refresh(self):
        try:r=self.api.get("/api/estimations")
        except Exception as e:self.app.error(e);return
        self.t.delete(*self.t.get_children())
        for x in r:
            tot=float(x.get('total_paise',0))/100.0
            self.t.insert("","end",iid=str(x["id"]),values=(x.get("est_no",""),x.get("customer_name") or "Walk-in",f"Rs {tot:,.2f}",x.get("status",""),str(x.get("created_at",""))[:16]))
    def create(self):
        # Barcode-first + customer picker (no raw IDs).
        try:customers=self.api.get("/api/customers")
        except Exception:customers=[]
        c_names=["Walk-in"]+[f"{x['id']}: {str(x['name'])[:24]}" for x in customers]
        d=form_dialog(self,"New estimation",[("customer","Customer",c_names),("barcodes","Scan barcodes/tags (comma or new lines) *"),("discount","Discount"),("notes","Notes")],{"customer":"Walk-in","discount":"0"})
        if not d:return
        codes=[x.strip() for x in d.get("barcodes","").replace("\n",",").split(",") if x.strip()]
        if not codes:self.app.error("Scan at least one tag");return
        lines=[]
        for code in codes:
            try:it=self.api.get(f"/api/items/barcode/{code}",branch_id=int(self.app.cfg.get("branch_id",1)),counter_id=self.app.cfg.get("counter_id") or None)
            except Exception:
                # fallback: numeric inventory ID
                try:it=self.api.get(f"/api/items/{int(code)}")["item"]
                except Exception as e:self.app.error(f"{code}: {e}");return
            if it["status"]!="in_stock":self.app.error(f"{it['tag_no']} is {it['status']}");return
            if any(x["item_id"]==it["id"] for x in lines):self.app.error(f"{it['tag_no']} scanned twice");return
            lines.append({"item_id":it["id"],"item_version":it["version"]})
        try:
            choice=str(d.get("customer","Walk-in"));cid=int(choice.split(":")[0]) if ":" in choice else None
            r=self.api.post("/api/estimations",{"customer_id":cid,"branch_id":int(self.app.cfg.get("branch_id",1)),"counter_id":self.app.cfg.get("counter_id") or None,"lines":lines,"discount":float(d.get("discount") or 0),"notes":d.get("notes","")})
            messagebox.showinfo("Estimation",f"Saved {r['est_no']} Rs {r['total']:,.2f}",parent=self);self.refresh()
        except Exception as e:self.app.error(e)
    def print_sel(self):
        if not self.t.selection():messagebox.showinfo("Estimation","Select a row first.",parent=self);return
        try:open_pdf(self.api.request("GET",f"/api/estimations/{self.t.selection()[0]}/estimation.pdf"),f"EST-{self.t.selection()[0]}.pdf")
        except Exception as e:self.app.error(e)
    def convert(self):
        if not self.t.selection():messagebox.showinfo("Estimation","Select an estimation first.",parent=self);return
        if not messagebox.askyesno("Convert","Open Billing and re-scan these tags for a tax invoice? Stock is checked live.",parent=self):return
        try:det=self.api.get(f"/api/estimations/{self.t.selection()[0]}")
        except Exception as e:self.app.error(e);return
        tags=", ".join(x.get("tag_no","?") for x in det.get("items",[])[:10])
        messagebox.showinfo("Convert",f"Re-scan in Billing:\n{tags}\n\nEstimation stays as quote history.",parent=self)
        try:self.app.show(POSPage,"Billing")
        except Exception as e:self.app.error(e)


class ExchangePage(Page):
    """Offline exchange wizard: old return credit + new sale = net payable. Original invoice immutable."""
    def __init__(self,parent,app):
        super().__init__(parent,app);self.heading("Exchange","1) Pick original invoice → 2) Return tags → 3) Sell new tags → net balance.");bar=ttk.Frame(self);bar.pack(fill="x",pady=(0,8))
        ttk.Button(bar,text="Start exchange",style="Primary.TButton",command=self.run).pack(side="left")
        ttk.Label(bar,text="Posts return first, then new sale. Both references shown.",style="Muted.TLabel").pack(side="left",padx=10)
        self.txt=tk.Text(self,height=20,font=("Consolas",9),wrap="word");self.txt.pack(fill="both",expand=True)
        self.txt.insert("1.0","Exchange keeps audit trail:\n- Credit note against original invoice (stock restored)\n- New tax invoice for replacement (stock sold)\n- Net cash = new total − return credit\n")
    def run(self):
        # Step 1: original invoice
        sid=simpledialog.askinteger("Exchange","Original sale/invoice ID:",parent=self)
        if not sid:return
        try:detail=self.api.get(f"/api/sales/{sid}")
        except Exception as e:self.app.error(e);return
        lines=detail.get("lines",[])
        if not lines:self.app.error("Original invoice has no lines");return
        # Step 2: return tags (sale_item ids)
        opts="\n".join(f"{l['id']}: {l['tag_no']} Rs {l['line_total']}" for l in lines)
        d=form_dialog(self,"Exchange — return",[("sale_item_ids",f"Return sale_item IDs (comma)\n{opts}"),("reason","Reason")],{"reason":"Exchange"})
        if not d:return
        try:rids=[int(x.strip()) for x in d["sale_item_ids"].split(",") if x.strip()]
        except ValueError:self.app.error("IDs must be numeric");return
        try:rq=self.api.post(f"/api/sales/{sid}/return-quote",{"sale_item_ids":rids})
        except Exception as e:self.app.error(e);return
        ret_total=float(rq.get("total",0))
        if not messagebox.askyesno("Exchange",f"Return credit Rs {ret_total:,.2f} for {len(rids)} tag(s). Continue to new sale?",parent=self):return
        # Step 3: new tags
        d2=form_dialog(self,"Exchange — new sale",[("tag_ids","New item IDs (inventory IDs, comma)"),("discount","Discount on new sale")],{"discount":"0"})
        if not d2:return
        try:new_ids=[int(x.strip()) for x in d2.get("tag_ids","").split(",") if x.strip()]
        except ValueError:self.app.error("IDs must be numeric");return
        new_lines=[]
        for iid in new_ids:
            try:it=self.api.get(f"/api/items/{iid}")["item"]
            except Exception as e:self.app.error(str(e));return
            new_lines.append({"item_id":it["id"],"item_version":it["version"]})
        try:q=self.api.post("/api/sales/quote",{"lines":new_lines,"discount":float(d2.get("discount") or 0),"old_gold":[],"branch_id":int(self.app.cfg.get("branch_id",1)),"counter_id":self.app.cfg.get("counter_id") or None})
        except Exception as e:self.app.error(e);return
        new_total=float(q.get("total",0));net=round(new_total-ret_total,2)
        if net<0:
            messagebox.showwarning("Exchange","Return credit exceeds new total. Refund the balance separately; exchange posts only when net >= 0.",parent=self);return
        if not messagebox.askyesno("Exchange confirm",f"New total Rs {new_total:,.2f}\nReturn credit Rs {ret_total:,.2f}\nNet payable Rs {net:,.2f}\n\nPost return + sale now?",parent=self):return
        import uuid as _uuid
        try:
            qhash=q.get("quote_hash") or q.get("quote_id")
            if not qhash:self.app.error("Quote expired — re-run exchange");return
            ret=self.api.post(f"/api/sales/{sid}/return",{"client_request_id":str(_uuid.uuid4()),"sale_item_ids":rids,"refund_cash":ret_total,"refund_card":0,"refund_upi":0,"refund_credit":0,"reason":d.get("reason","Exchange"),"disposition":"in_stock"})
            sale=self.api.post("/api/sales",{"client_request_id":str(_uuid.uuid4()),"branch_id":int(self.app.cfg.get("branch_id",1)),"counter_id":self.app.cfg.get("counter_id") or None,"customer_id":detail["sale"].get("customer_id"),"lines":new_lines,"discount":float(d2.get("discount") or 0),"old_gold":[],"payment_cash":net,"payment_card":0,"payment_upi":0,"payment_credit":0,"quote_hash":qhash})
            self.txt.delete("1.0","end");self.txt.insert("1.0",f"Exchange done.\nCredit note: {ret.get('return',{}).get('return_no')} Rs {ret_total:,.2f}\nNew invoice: {sale.get('invoice_no')} Rs {new_total:,.2f}\nNet collected: Rs {max(0,net):,.2f}\n")
            messagebox.showinfo("Exchange",f"Return {ret.get('return',{}).get('return_no')}\nSale {sale.get('invoice_no')}",parent=self)
        except Exception as e:self.app.error(e)


class SchemesLoansPage(Page):
    """Offline chit schemes + gold loans — local ledgers, no internet."""
    def __init__(self,parent,app):
        super().__init__(parent,app);self.heading("Schemes & Gold Loans","Chit/saving schemes and Girvi loans — fully offline.");self.nb=ttk.Notebook(self);self.nb.pack(fill="both",expand=True)
        self._schemes_tab();self._loans_tab()
    def _schemes_tab(self):
        f=ttk.Frame(self.nb,padding=8);self.nb.add(f,text="Schemes");bar=ttk.Frame(f);bar.pack(fill="x")
        ttk.Button(bar,text="New scheme",command=self.scheme_add).pack(side="left");ttk.Button(bar,text="Enroll",command=self.member_add).pack(side="left",padx=4);ttk.Button(bar,text="Collect",command=self.member_pay).pack(side="left");ttk.Button(bar,text="Refresh",command=self.scheme_refresh).pack(side="left",padx=4)
        h=ttk.Frame(f);h.pack(fill="both",expand=True,pady=8);self.st=self.tree(h,("code","name","metal","tenure_months","monthly_amount","active"),{"name":200});self.mt=self.tree(ttk.Frame(f),("id","scheme_name","customer_name","status","total_paid"),{"customer_name":180})
        # second tree packed below
        for w in f.winfo_children():
            pass
        self.mt.master.pack(fill="both",expand=True);self.scheme_refresh()
    def scheme_refresh(self):
        try:s=self.api.get("/api/chit-schemes");m=self.api.get("/api/chit-members")
        except Exception as e:self.app.error(e);return
        def _f(x,d=0.0):
            try:return float(x)
            except Exception:return d
        self.st.delete(*self.st.get_children())
        for x in s:self.st.insert("","end",iid=str(x["id"]),values=(x.get("code",""),x.get("name",""),x.get("metal",""),x.get("tenure_months",""),_f(x.get("monthly_amount_paise",0))/100.0,x.get("active","")))
        self.mt.delete(*self.mt.get_children())
        for x in m:self.mt.insert("","end",iid=str(x["id"]),values=(x.get("id",""),x.get("scheme_name",""),x.get("customer_name",""),x.get("status",""),_f(x.get("total_paid_paise",0))/100.0))
    def scheme_add(self):
        d=form_dialog(self,"New scheme",[("name","Name *"),("metal","Metal",["Gold","Silver"]),("tenure_months","Tenure months"),("monthly_amount","Monthly amount"),("target_weight","Target weight g"),("making_discount_percent","Making discount %")],{"metal":"Gold","tenure_months":"11","monthly_amount":"5000"})
        if not d:return
        try:self.api.post("/api/chit-schemes",d);self.scheme_refresh()
        except Exception as e:self.app.error(e)
    def member_add(self):
        d=form_dialog(self,"Enroll member",[("scheme_id","Scheme ID"),("customer_id","Customer ID"),("start_date","Start YYYY-MM-DD")],{"start_date":dt.date.today().isoformat()})
        if not d:return
        try:self.api.post("/api/chit-members",d);self.scheme_refresh()
        except Exception as e:self.app.error(e)
    def member_pay(self):
        if not self.mt.selection():messagebox.showinfo("Schemes","Select a member first.",parent=self);return
        d=form_dialog(self,"Collect installment",[("amount","Amount *"),("method","Method",["cash","card","upi"]),("paid_on","Date")],{"method":"cash","paid_on":dt.date.today().isoformat()})
        if not d:return
        try:self.api.post(f"/api/chit-members/{self.mt.selection()[0]}/pay",d);self.scheme_refresh()
        except Exception as e:self.app.error(e)
    def _loans_tab(self):
        f=ttk.Frame(self.nb,padding=8);self.nb.add(f,text="Gold loans");bar=ttk.Frame(f);bar.pack(fill="x")
        ttk.Button(bar,text="New loan",style="Primary.TButton",command=self.loan_add).pack(side="left");ttk.Button(bar,text="Collect",command=self.loan_pay).pack(side="left",padx=4);ttk.Button(bar,text="Refresh",command=self.loan_refresh).pack(side="left",padx=4)
        h=ttk.Frame(f);h.pack(fill="both",expand=True,pady=8);self.lt=self.tree(h,("loan_no","customer_name","net_weight","loan_amount","interest","status"),{"customer_name":180});self.loan_refresh()
    def loan_refresh(self):
        try:r=self.api.get("/api/gold-loans")
        except Exception as e:self.app.error(e);return
        def _f(x,d=0.0):
            try:return float(x)
            except Exception:return d
        self.lt.delete(*self.lt.get_children())
        for x in r:self.lt.insert("","end",iid=str(x["id"]),values=(x.get("loan_no",""),x.get("customer_name",""),x.get("net_weight",""),_f(x.get("loan_amount_paise",0))/100.0,x.get("interest_monthly_percent",""),x.get("status","")))
    def loan_add(self):
        d=form_dialog(self,"New gold loan",[("customer_id","Customer ID *"),("gross_weight","Gross g *"),("net_weight","Net g *"),("purity","Purity"),("loan_amount","Loan Rs *"),("interest_monthly_percent","Interest %/mo"),("issued_on","Issued YYYY-MM-DD"),("notes","Notes")],{"purity":"916","interest_monthly_percent":"2","issued_on":dt.date.today().isoformat()})
        if not d:return
        try:r=self.api.post("/api/gold-loans",d);messagebox.showinfo("Gold loan",r["loan_no"],parent=self);self.loan_refresh()
        except Exception as e:self.app.error(e)
    def loan_pay(self):
        if not self.lt.selection():messagebox.showinfo("Loans","Select a loan first.",parent=self);return
        d=form_dialog(self,"Loan collection",[("amount","Amount *"),("kind","Kind",["interest","principal","closure"]),("paid_on","Date")],{"kind":"interest","paid_on":dt.date.today().isoformat()})
        if not d:return
        try:self.api.post(f"/api/gold-loans/{self.lt.selection()[0]}/pay",d);self.loan_refresh()
        except Exception as e:self.app.error(e)


class ApprovalsPage(Page):
    """Jangad / approval issue and return (was backend-only, now visible)."""
    def __init__(self,parent,app):
        super().__init__(parent,app);self.heading("Approvals / Jangad","Issue serialized tags on approval and record returns.");bar=ttk.Frame(self);bar.pack(fill="x",pady=(0,8));ttk.Button(bar,text="New approval",style="Primary.TButton",command=self.create).pack(side="left");ttk.Button(bar,text="Return item",style="Secondary.TButton",command=self.return_item).pack(side="left",padx=6);ttk.Button(bar,text="Refresh",style="Secondary.TButton",command=self.refresh).pack(side="left");h=ttk.Frame(self);h.pack(fill="both",expand=True,pady=8);self.t=self.tree(h,("approval_no","party_name","party_phone","status","item_count","issued_at"),{"party_name":180});self.refresh()
    def refresh(self):
        try:r=self.api.get("/api/approvals")
        except Exception as e:self.app.error(e);return
        self.t.delete(*self.t.get_children());[self.t.insert("","end",iid=str(x["id"]),values=(x.get("approval_no",""),x.get("party_name",""),x.get("party_phone",""),x.get("status",""),x.get("item_count",""),str(x.get("issued_at",""))[:16])) for x in r]
    def create(self):
        d=form_dialog(self,"New approval",[("party_name","Party name *"),("party_phone","Party phone"),("item_ids","Tag IDs (comma separated) *"),("due_at","Due date (optional)"),("note","Note")])
        if not d:return
        if not d.get("party_name","").strip() or not d.get("item_ids","").strip():
            self.app.error("Party name and at least one tag ID are required");return
        try:ids=[int(x.strip()) for x in d["item_ids"].split(",") if x.strip()]
        except ValueError:self.app.error("Tag IDs must be comma-separated numbers");return
        try:r=self.api.post("/api/approvals",{"party_name":d["party_name"].strip(),"party_phone":d.get("party_phone","").strip(),"item_ids":ids,"due_at":d.get("due_at") or None,"note":d.get("note","")});messagebox.showinfo("Approval",f"Created {r['approval_no']}",parent=self);self.refresh()
        except Exception as e:self.app.error(e)
    def return_item(self):
        if not self.t.selection():
            messagebox.showinfo("Approvals","Select an approval first.",parent=self);return
        aid=self.t.selection()[0]
        d=form_dialog(self,"Return approval item",[("item_id","Tag ID *")])
        if not d or not d.get("item_id"):return
        try:self.api.post(f"/api/approvals/{int(aid)}/return/{int(d['item_id'])}",{});messagebox.showinfo("Approvals","Item returned to stock.",parent=self);self.refresh()
        except Exception as e:self.app.error(e)


class KarigarLedgerPage(Page):
    TYPES=["metal_issue","metal_receive","cash_debit","cash_credit","making_charge","adjustment"]
    def __init__(self,parent,app):
        super().__init__(parent,app);self.heading("Karigar Ledger","Metal and cash balances per karigar.");bar=ttk.Frame(self);bar.pack(fill="x",pady=(0,8));ttk.Label(bar,text="Karigar:").pack(side="left");self.kvar=tk.StringVar();self.kbox=ttk.Combobox(bar,textvariable=self.kvar,state="readonly",width=36);self.kbox.pack(side="left",padx=6);ttk.Button(bar,text="Load",command=self.refresh).pack(side="left");ttk.Button(bar,text="Add entry",style="Primary.TButton",command=self.add).pack(side="left",padx=6);self.kids=[];self.load_karigars();h=ttk.Frame(self);h.pack(fill="both",expand=True,pady=8);self.t=self.tree(h,("id","entry_type","metal","weight","amount","note","created_at"),{"note":220})
    def load_karigars(self):
        try:rows=self.api.get("/api/karigars")
        except Exception:rows=[]
        self.kids=rows;self.kbox["values"]=[f"{x['id']}: {x['name']} (metal {x.get('metal_balance_grams',0)}g, cash ₹{x.get('cash_balance',0)})" for x in rows]
        if rows:self.kbox.current(0)
    def _kid(self):
        if not self.kids:return None
        try:
            idx=self.kbox.current()
            if idx<0 or idx>=len(self.kids):return None
            return self.kids[idx]["id"]
        except Exception:return None
    def refresh(self):
        kid=self._kid()
        if not kid:
            self.app.error("Add a karigar first");return
        try:r=self.api.get(f"/api/karigars/{kid}/ledger")
        except Exception as e:self.app.error(e);return
        self.t.delete(*self.t.get_children());[self.t.insert("","end",values=(x.get("id",""),x.get("entry_type",""),x.get("metal",""),x.get("weight",""),x.get("amount",""),(x.get("note") or "")[:60],str(x.get("created_at",""))[:16])) for x in r]
    def add(self):
        kid=self._kid()
        if not kid:return
        d=form_dialog(self,"Karigar entry",[("entry_type","Type",self.TYPES),("metal","Metal"),("weight","Weight (g)"),("amount","Amount"),("note","Note")],{"entry_type":"metal_issue","metal":"Gold","weight":"0","amount":"0"})
        if not d:return
        try:d["weight"]=float(d.get("weight") or 0);d["amount"]=float(d.get("amount") or 0)
        except ValueError:self.app.error("Weight and amount must be numeric");return
        try:self.api.post(f"/api/karigars/{kid}/ledger",d);self.load_karigars();self.refresh()
        except Exception as e:self.app.error(e)


class StockAuditPage(Page):
    def __init__(self,parent,app):
        super().__init__(parent,app);self.audit_id=None;self.heading("Physical Stock Audit","Open an audit and scan every tag/RFID EPC. Reconcile missing and misplaced stock.");bar=ttk.Frame(self);bar.pack(fill="x");ttk.Button(bar,text="Start audit",style="Primary.TButton",command=self.start).pack(side="left");ttk.Button(bar,text="Close & reconcile",command=self.close).pack(side="left",padx=4);ttk.Button(bar,text="View result",command=self.view).pack(side="left");self.state=tk.StringVar(value="No audit open");ttk.Label(bar,textvariable=self.state).pack(side="left",padx=10);self.count=tk.StringVar(value="Scanned 0");ttk.Label(bar,textvariable=self.count,style="Muted.TLabel").pack(side="right");self.scan=tk.StringVar();e=ttk.Entry(self,textvariable=self.scan,font=("Consolas",13));e.pack(fill="x",pady=8);e.bind("<Return>",self.do_scan);self.scan_entry=e;h=ttk.Frame(self);h.pack(fill="both",expand=True);self.t=self.tree(h,("tag_no","name","metal","purity","gross_weight","status"),{"name":220});e.focus_set()
    def start(self):
        try:r=self.api.post("/api/stock-audits",{"branch_id":int(self.app.cfg.get("branch_id",1)),"counter_id":self.app.cfg.get("counter_id") or None});self.audit_id=r["id"];self.state.set("Open: "+r["audit_no"]);self.t.delete(*self.t.get_children());self.count.set("Scanned 0");self.scan_entry.focus_set()
        except Exception as e:self.app.error(e)
    def do_scan(self,event):
        code=self.scan.get().strip();self.scan.set("")
        if not code:return
        if not self.audit_id:
            self.app.error("Start an audit first");return
        # Duplicate feedback: already in current list → inform, don't silently ignore.
        try:r=self.api.post(f"/api/stock-audits/{self.audit_id}/scan",{"barcode":code});i=r.get("item") or {};is_new=bool(r.get("new"))
        except Exception as e:self.app.error(e);self.scan_entry.focus_set();return
        if not i:self.app.error("Scan returned no item");self.scan_entry.focus_set();return
        if is_new:
            try:self.t.insert("","end",iid=str(i["id"]),values=tuple(i.get(c,"") for c in self.t["columns"]))
            except tk.TclError:pass
            self.count.set(f"Scanned {len(self.t.get_children())}")
        else:
            self.count.set(f"Scanned {len(self.t.get_children())} — {i.get('tag_no','tag')} already scanned")
        self.scan_entry.focus_set()
    def close(self):
        if not self.audit_id:
            messagebox.showinfo("Stock audit","Start an audit first.",parent=self);return
        try:r=self.api.post(f"/api/stock-audits/{self.audit_id}/close",{})
        except Exception as e:self.app.error(e);return
        missing=[m.get("tag_no","?") for m in r.get("missing",[])[:20]]
        extra=[x.get("tag_no","?") for x in r.get("extra",[])[:20]]
        msg=f"Expected {r['expected_count']}\nScanned {r['scanned_count']}\nMissing {len(r['missing'])}\nExtra/misplaced {len(r['extra'])}"
        if missing:msg+=f"\n\nMissing e.g.: {', '.join(missing)}"
        if extra:msg+=f"\nExtra e.g.: {', '.join(extra)}"
        messagebox.showinfo("Audit result",msg,parent=self);self.audit_id=None;self.state.set("Audit closed")
    def view(self):
        if not self.audit_id:
            messagebox.showinfo("Stock audit","Start an audit first, or close it to see the final result.",parent=self);return
        try:r=self.api.get(f"/api/stock-audits/{self.audit_id}/result")
        except Exception as e:self.app.error(e);return
        messagebox.showinfo("Audit progress",f"Expected {r.get('expected_count',0)}\nScanned {r.get('scanned_count',0)}\nMissing {len(r.get('missing',[]))}\nExtra {len(r.get('extra',[]))}",parent=self)


class ReportsPage(Page):
    def __init__(self,parent,app):
        super().__init__(parent,app);self.heading("Reports & Accounting","Offline P&L, balance sheet, metal-wise, GSTR-ready, trial balance.");bar=ttk.Frame(self);bar.pack(fill="x");ttk.Label(bar,text="From").pack(side="left");self.df=tk.StringVar(value=dt.date.today().replace(day=1).isoformat());self.to=tk.StringVar(value=dt.date.today().isoformat());ttk.Entry(bar,textvariable=self.df,width=12).pack(side="left",padx=4);ttk.Label(bar,text="To").pack(side="left");ttk.Entry(bar,textvariable=self.to,width=12).pack(side="left",padx=4);ttk.Button(bar,text="Refresh",style="Primary.TButton",command=self.refresh).pack(side="left",padx=4);ttk.Button(bar,text="Stock PDF",command=self.pdf).pack(side="right")
        self.nb=ttk.Notebook(self);self.nb.pack(fill="both",expand=True,pady=8)
        self.txt=tk.Text(self.nb,height=10,font=("Consolas",9),wrap="word");self.nb.add(self.txt,text="Summary")
        f2=ttk.Frame(self.nb);self.nb.add(f2,text="P&L / Balance");self.pl_text=tk.Text(f2,height=12,font=("Consolas",9),wrap="word");self.pl_text.pack(fill="both",expand=True)
        f3=ttk.Frame(self.nb);self.nb.add(f3,text="Metal / GSTR");self.mg_text=tk.Text(f3,height=12,font=("Consolas",9),wrap="word");self.mg_text.pack(fill="both",expand=True)
        h=ttk.Frame(self);h.pack(fill="both",expand=True);self.t=self.tree(h,("code","name","account_type","debit","credit","balance"),{"name":220});self.refresh()
    def refresh(self):
        try:dt.date.fromisoformat(self.df.get().strip());dt.date.fromisoformat(self.to.get().strip())
        except ValueError:self.app.error("Report dates must be YYYY-MM-DD");return
        df=self.df.get().strip();to=self.to.get().strip()
        # Partial render: one failing report must not blank all others.
        try:s=self.api.get("/api/reports/summary",date_from=df,date_to=to)
        except Exception as e:self.app.error(f"Summary failed: {e}");s=None
        try:tb=self.api.get("/api/reports/trial-balance",date_to=to)
        except Exception as e:self.app.error(f"Trial balance failed: {e}");tb=[]
        try:pl=self.api.get("/api/reports/profit-loss",date_from=df,date_to=to)
        except Exception:pl=None
        try:bs=self.api.get("/api/reports/balance-sheet",date_to=to)
        except Exception:bs=None
        try:mw=self.api.get("/api/reports/metal-wise",date_from=df,date_to=to)
        except Exception:mw=None
        try:gs=self.api.get("/api/reports/gstr",date_from=df,date_to=to)
        except Exception:gs=None
        if s is None:return
        txt=f"Period {s['date_from']} to {s['date_to']}\nInvoices {s['sales']['invoices']} | Sales {money(s['sales']['total'])} | GST {money(s['sales']['gst'])}  |  Returns {s.get('returns',{}).get('credit_notes',0)} / {money(s.get('returns',{}).get('total',0))}\nStock {s['stock']['pieces']} pcs | Gross {s['stock']['gross_weight']:.3f} g | Net {s['stock']['net_weight']:.3f} g | Cost {money(s['stock']['cost'])}\nPayments: Cash {money(s['payments']['cash'])}, Card {money(s['payments']['card'])}, UPI {money(s['payments']['upi'])}, Credit {money(s['payments']['credit'])}, Old gold {money(s['payments']['old_gold'])}\n\n"+"\n".join(f"{x['metal']} {x['purity']}: {x['pieces']} pcs / {x['net_weight']:.3f} g" for x in s['stock_by_metal']);self.txt.delete("1.0","end");self.txt.insert("1.0",txt)
        try:
            pl_txt=f"P&L {pl['date_from']} to {pl['date_to']}\nGross sales {money(pl['gross_sales'])}\nReturns {money(pl['returns'])}\nNet sales {money(pl['net_sales'])}\nCOGS {money(pl['cogs'])}\nGross profit {money(pl['gross_profit'])}\n\nBalance {bs['date_to']}\nAssets {money(bs['assets'])}\nLiabilities {money(bs['liabilities'])}\nEquity {money(bs['equity'])}\nRetained {money(bs['retained_earnings'])}\nBalanced: {bs['balanced']}" if pl and bs else "P&L/Balance unavailable for this period."
        except Exception:pl_txt="P&L/Balance unavailable."
        self.pl_text.delete("1.0","end");self.pl_text.insert("1.0",pl_txt)
        try:
            mg_txt="Metal-wise sales:\n"+"\n".join(f"{x['metal']} {x['purity']}: {x['pcs']} pcs Rs {x['total']:,.2f}" for x in (mw['sales'] if mw else []))+"\n\nGSTR by rate:\n"+"\n".join(f"{x['gst_rate']}%: taxable Rs {x['taxable']:,.2f} GST Rs {x['gst']:,.2f}" for x in (gs['by_rate'] if gs else []))+f"\nCGST Rs {gs['cgst']:,.2f} SGST Rs {gs['sgst']:,.2f} IGST Rs {gs['igst']:,.2f} (generate offline, file online later)" if gs else "Metal/GSTR unavailable."
        except Exception:mg_txt="Metal/GSTR unavailable."
        self.mg_text.delete("1.0","end");self.mg_text.insert("1.0",mg_txt)
        self.t.delete(*self.t.get_children());[self.t.insert("","end",values=tuple(x.get(c,"") for c in self.t["columns"])) for x in tb]
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
        fields=[('tally_enabled','Enabled',['0','1'],str(d.get('enabled','0'))),('tally_bridge_url','Bridge URL',None,str(d.get('bridge_url','http://127.0.0.1:8767'))),('tally_bridge_token','Bridge token (leave blank to keep)',None,''),('tally_company','Tally company',None,str(d.get('company',''))),('business_state_code','Business state code (2 digits)',None,str(d.get('business_state_code',''))),('tally_auto_create_parties','Auto-create party ledgers',['0','1'],str(d.get('auto_create_parties','1')))]
        form=ttk.Frame(left,style="Surface.TFrame"); form.pack(fill="x")
        for r,(k,l,choices,val) in enumerate(fields):
            self.tv[k]=tk.StringVar(value=str(val)); ttk.Label(form,text=l,style="SurfaceMuted.TLabel").grid(row=r,column=0,sticky='w',pady=5)
            if choices:
                ttk.Combobox(form,textvariable=self.tv[k],values=choices,state="readonly",width=10).grid(row=r,column=1,sticky='w',padx=(12,0),pady=5)
            else:
                ttk.Entry(form,textvariable=self.tv[k],show='●' if k=='tally_bridge_token' else '').grid(row=r,column=1,sticky='ew',padx=(12,0),pady=5)
        form.columnconfigure(1,weight=1)
        self._is_admin = self.app.user.get("role")=="admin"
        controls=ttk.Frame(left,style="Surface.TFrame"); controls.pack(fill="x",pady=(14,0)); ttk.Button(controls,text='Save settings',style="Primary.TButton",command=self.save,state="normal" if self._is_admin else "disabled").pack(side='left'); ttk.Button(controls,text='Test connection',style="Secondary.TButton",command=self.test).pack(side='left',padx=5); ttk.Button(controls,text='Sync now',style="Secondary.TButton",command=self.sync).pack(side='left')
        if not self._is_admin:
            ttk.Label(left,text="Save needs Administrator.",style="SurfaceMuted.TLabel").pack(anchor="w",pady=(6,0))

        ttk.Label(right,text="Ledger mappings",style="Section.TLabel").pack(anchor="w"); ttk.Label(right,text="Map JewelLAN accounting roles to exact Tally ledger names.",style="SurfaceMuted.TLabel",wraplength=430).pack(anchor="w",pady=(3,10))
        maps=ttk.Frame(right,style="Surface.TFrame"); maps.pack(fill="both",expand=True)
        for r,(k,val) in enumerate(d.get('mappings',{}).items()):
            self.tm[k]=tk.StringVar(value=str(val)); ttk.Label(maps,text=k.replace('_',' ').title(),style="SurfaceMuted.TLabel").grid(row=r,column=0,sticky='w',pady=3); ttk.Entry(maps,textvariable=self.tm[k]).grid(row=r,column=1,sticky='ew',padx=(10,0),pady=3)
        maps.columnconfigure(1,weight=1)
        bottom=ttk.Frame(right,style="Surface.TFrame"); bottom.pack(fill="x",pady=(12,0))
        self._is_admin = self.app.user.get("role")=="admin"
        ttk.Button(bottom,text='Save mappings',style="Primary.TButton",command=self.save_mappings,state="normal" if self._is_admin else "disabled").pack(side='left')
        ttk.Button(bottom,text='Reconcile month',style="Secondary.TButton",command=self.reconcile).pack(side='left',padx=5)
        ttk.Button(bottom,text='Backfill history',style="Secondary.TButton",command=self.backfill,state="normal" if self._is_admin else "disabled").pack(side='left')
        if not self._is_admin:
            ttk.Label(right,text="Settings/mappings/backfill need Administrator. You can test, sync and reconcile.",style="SurfaceMuted.TLabel",wraplength=430).pack(anchor="w",pady=(8,0))
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
        super().__init__(parent,app);self.heading("Administration","Metal rates, users, backups, integrity, business settings and this workstation.");self.nb=ttk.Notebook(self);self.nb.pack(fill="both",expand=True)
        role=app.user.get("role","")
        # rates/backup visible to roles with matching server permission; users/company admin-only.
        if role in ("admin","manager","inventory","accounts"):self.make_rates()
        self.make_labels();self.make_health();self.make_backup();self.make_pc();
        if app.user.get("role")=="admin":self.make_users();self.make_business()
    def make_rates(self):
        f=ttk.Frame(self.nb,padding=8);self.nb.add(f,text="Metal rates")
        bar=ttk.Frame(f);bar.pack(fill="x")
        ttk.Button(bar,text="Set new rate",style="Primary.TButton",command=self.rate).pack(side="left")
        ttk.Button(bar,text="Refresh",command=self.refresh_rates).pack(side="left",padx=6)
        ttk.Label(bar,text="Rates are effective-dated. New rates apply to new quotes only; old invoices never change.",style="Muted.TLabel").pack(side="left",padx=10)
        h=ttk.Frame(f);h.pack(fill="both",expand=True,pady=8);self.rt=self.tree(h,("metal","purity","rate_per_gram","effective_at"));self.refresh_rates()
    def refresh_rates(self):
        try:r=self.api.get("/api/rates")
        except Exception as e:self.app.error(e);return
        self.rt.delete(*self.rt.get_children());[self.rt.insert("","end",values=tuple(x.get(c,"") for c in self.rt["columns"])) for x in r]
    def rate(self):
        d=form_dialog(self,"Set new metal rate",[("metal","Metal",["Gold","Silver","Platinum"]),("purity","Purity",["999","995","958","925","916","875","750","585"]),("rate_per_gram","Rate per gram *"),("effective_at","Effective at (blank = now)")],{"metal":"Gold","purity":"916"})
        if not d:return
        if not d.get("metal","").strip() or not d.get("purity","").strip():
            self.app.error("Metal and purity are required");return
        try:
            rate=float(d.get("rate_per_gram") or 0)
            if rate<=0:
                self.app.error("Rate must be positive");return
            d["rate_per_gram"]=rate
            if d.get("effective_at","").strip():
                dt.datetime.fromisoformat(d["effective_at"].strip())
            else:d.pop("effective_at",None)
            self.api.post("/api/rates",d);self.refresh_rates();messagebox.showinfo("Metal rates","New rate saved. It applies to new quotes only.",parent=self)
        except ValueError:self.app.error("Rate must be numeric and date must be ISO format")
        except Exception as e:self.app.error(e)
    def make_labels(self):
        f=ttk.Frame(self.nb,padding=12);self.nb.add(f,text="Labels")
        ttk.Label(f,text="Tag stock size (mm). PDF prints at 100% — no fit-to-page. ZPL/TSPL use same size. QR appears on 28mm+ tall stock.",style="Muted.TLabel",wraplength=800).pack(anchor="w",pady=(0,10))
        self.lab_w=tk.StringVar(value=self.app.settings.get("label_width_mm","60"));self.lab_h=tk.StringVar(value=self.app.settings.get("label_height_mm","25"))
        row=ttk.Frame(f);row.pack(fill="x")
        ttk.Label(row,text="Width mm (30-100)").pack(side="left");ttk.Entry(row,textvariable=self.lab_w,width=10).pack(side="left",padx=6)
        ttk.Label(row,text="Height mm (15-60)").pack(side="left",padx=(12,0));ttk.Entry(row,textvariable=self.lab_h,width=10).pack(side="left",padx=6)
        ttk.Button(row,text="Save",style="Primary.TButton",command=self.save_labels,state="normal" if self.app.user.get("role")=="admin" else "disabled").pack(side="left",padx=12)
        ttk.Button(row,text="Test print (first in-stock)",command=self.test_label).pack(side="left")
        ttk.Label(f,text="Formats: PDF via Windows printer, ZPL for Zebra, TSPL for TSC — all offline. Verify barcode scan + margins on exact tag stock before go-live.",style="Muted.TLabel",wraplength=800).pack(anchor="w",pady=(12,0))
    def save_labels(self):
        try:
            w=float(self.lab_w.get());h=float(self.lab_h.get())
            if not 30<=w<=100 or not 15<=h<=60:self.app.error("Width 30-100, height 15-60");return
            self.api.put("/api/settings",{"label_width_mm":str(w),"label_height_mm":str(h)});self.app.load_settings()
            messagebox.showinfo("Labels",f"Saved {w} x {h} mm.",parent=self)
        except ValueError:self.app.error("Sizes must be numeric")
        except Exception as e:self.app.error(e)
    def test_label(self):
        try:rows=self.api.get("/api/items",q="",limit=1)
        except Exception as e:self.app.error(e);return
        if not rows:self.app.error("No in-stock item to test with");return
        try:open_pdf(self.api.request("GET",f"/api/items/{rows[0]['id']}/label.pdf"),f"test-{rows[0]['tag_no']}.pdf")
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
        f=ttk.Frame(self.nb,padding=8);self.nb.add(f,text="Backups");ttk.Button(f,text="Create backup now",command=self.do_backup).pack(anchor="w");ttk.Label(f,text="Backups stay on the server PC. Restore is a server-admin operation while JewelLAN is stopped.",foreground="#666").pack(anchor="w",pady=10)
    def do_backup(self):
        try:r=self.api.post("/api/backups",{"label":"manual"});messagebox.showinfo("Backup",f"Created {r.get('name','backup')}",parent=self)
        except Exception as e:self.app.error(e)
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
        f=ttk.Frame(self.nb,padding=12);self.nb.add(f,text="Company settings");self.bv={}
        s=self.app.settings;branch=self.app.branches[0] if self.app.branches else {};branch_id=branch.get('id');counter_count=sum(1 for x in self.app.counters if branch_id is None or x.get('branch_id')==branch_id) or 1
        fields=[('business_name','Company name',s.get('business_name','')),('branch_name','Main branch / showroom',branch.get('name','Main Showroom')),('business_state_code','GST state code',s.get('business_state_code','')),('business_state_name','State name',s.get('business_state_name','')),('business_gstin','GSTIN',s.get('business_gstin','')),('business_address','Address',s.get('business_address','')),('business_pincode','PIN code',s.get('business_pincode','')),('business_phone','Phone',s.get('business_phone','')),('business_email','Email',s.get('business_email','')),('counter_count','Number of counters',str(counter_count)),('invoice_prefix','Invoice prefix',s.get('invoice_prefix','INV')),('tag_prefix','Tag prefix',s.get('tag_prefix','TAG')),('gst_default','Default GST %',s.get('gst_default','3')),('business_timezone_offset_minutes','Timezone offset minutes',s.get('business_timezone_offset_minutes','330'))]
        ttk.Label(f,text='These values belong to the company database and appear on invoices/reports. They are not hard-coded into JewelLAN.',style='SurfaceMuted.TLabel',wraplength=900).grid(row=0,column=0,columnspan=2,sticky='w',pady=(0,10))
        for i,(k,label,value) in enumerate(fields,1):self.bv[k]=tk.StringVar(value=str(value));ttk.Label(f,text=label).grid(row=i,column=0,sticky='w',pady=3);ttk.Entry(f,textvariable=self.bv[k]).grid(row=i,column=1,sticky='ew',padx=8)
        f.columnconfigure(1,weight=1);ttk.Button(f,text="Save company settings",style='Primary.TButton',command=self.save_business).grid(row=len(fields)+2,column=0,columnspan=2,sticky="ew",pady=12)
    def save_business(self):
        try:
            p={k:v.get() for k,v in self.bv.items()};p['counter_count']=int(p.get('counter_count') or 1);r=self.api.put('/api/company',p);self.app.load_settings();self.app.company_label.configure(text=self.app.settings.get('business_name') or 'Company not configured');messagebox.showinfo('Company settings','Saved',parent=self)
        except Exception as e:self.app.error(e)


# Unified billing screen: single implementation lives in billing_page.py.
# Imported here (after Page etc. are defined) so App navigation and older
# imports (from jewel_client.main import POSPage) keep working without the
# fragile run_client monkey-patch.
try:
    from .billing_page import POSPage  # noqa: E402,F401
except Exception:  # pragma: no cover
    class POSPage(Page):  # type: ignore[no-redef]
        def __init__(self, parent, app):
            super().__init__(parent, app)
            self.heading("Billing counter", "Billing module failed to load. Restart JewelPOS.")


def main():
    root=tk.Tk();root.withdraw();cfg=load_config();api=Api(cfg.get("server_url",""),cfg.get("server_fingerprint",""));login=LoginDialog(root,api,cfg);root.wait_window(login)
    if not login.user:return
    if login.user.get("must_change_password") and not force_initial_password_change(root,api,login.user):return
    if not ensure_company_setup(root,api):return
    root.deiconify();App(root,api,cfg,login.user);root.mainloop()


if __name__ == "__main__":
    main()
