from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .main import form_dialog, money
from .ui_theme import card, status_pill


RATE_FIELDS = (
    ("gold_999", "Gold 999 base (₹ / 10 g)", "Gold", "999", 10.0),
    ("gold_995", "Gold 995 override (optional; blank = derive)", "Gold", "995", 10.0),
    ("gold_916", "Gold 916 / 22K override (optional; blank = derive)", "Gold", "916", 10.0),
    ("gold_750", "Gold 750 / 18K override (optional; blank = derive)", "Gold", "750", 10.0),
    ("gold_585", "Gold 585 / 14K override (optional; blank = derive)", "Gold", "585", 10.0),
    ("silver_999", "Silver 999 base (₹ / kg)", "Silver", "999", 1000.0),
    ("silver_925", "Silver 925 override (optional; blank = derive)", "Silver", "925", 1000.0),
)


def _n(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def market_rate_text(metal: str, per_gram) -> str:
    value = _n(per_gram)
    if str(metal).lower() == "silver":
        return f"₹{value * 1000:,.2f} / kg"
    return f"₹{value * 10:,.2f} / 10 g"


def _current_lookup(snapshot: dict) -> dict[tuple[str, str], dict]:
    return {(str(x.get("metal")), str(x.get("purity"))): x for x in snapshot.get("rates", [])}


class RateManagerPanel(ttk.Frame):
    def __init__(self, parent, admin_page):
        super().__init__(parent)
        self.admin = admin_page
        self.api = admin_page.api
        self.snapshot: dict = {}
        self.provider: dict = {}

        hero = card(self, 14)
        hero.pack(fill="x", pady=(0, 10))
        top = ttk.Frame(hero, style="Surface.TFrame")
        top.pack(fill="x")
        ttk.Label(top, text="Daily shop metal rates", style="Section.TLabel").pack(side="left")
        self.status_host = ttk.Frame(top, style="Surface.TFrame")
        self.status_host.pack(side="right")
        self.status = tk.StringVar(value="Loading rate status…")
        ttk.Label(hero, textvariable=self.status, style="SurfaceMuted.TLabel", wraplength=950).pack(anchor="w", pady=(4, 8))

        actions = ttk.Frame(hero, style="Surface.TFrame")
        actions.pack(fill="x")
        ttk.Button(actions, text="Set / update shop rates", style="Primary.TButton", command=self.manual_update).pack(side="left")
        ttk.Button(actions, text="Confirm current unchanged", style="Secondary.TButton", command=self.confirm_unchanged).pack(side="left", padx=5)
        ttk.Button(actions, text="Sync reference", style="Secondary.TButton", command=self.sync_reference).pack(side="left")
        ttk.Button(actions, text="Provider settings", style="Secondary.TButton", command=self.provider_settings).pack(side="left", padx=5)
        ttk.Button(actions, text="Refresh", style="Secondary.TButton", command=self.refresh).pack(side="right")

        ttk.Label(
            hero,
            text="Rate history is append-only. Set the 999 base rate and JewelLAN derives other purities unless you deliberately enter a purity-specific override. External feeds are reference-only until you approve them.",
            style="SurfaceMuted.TLabel",
            wraplength=1050,
        ).pack(anchor="w", pady=(9, 0))

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True)
        current_card = card(body, 12)
        history_card = card(body, 12)
        body.add(current_card, weight=3)
        body.add(history_card, weight=2)

        ttk.Label(current_card, text="Active shop rates", style="Section.TLabel").pack(anchor="w")
        ttk.Label(current_card, text="These are the rates the pricing engine resolves for new bills.", style="SurfaceMuted.TLabel").pack(anchor="w", pady=(2, 6))
        current_host = ttk.Frame(current_card, style="Surface.TFrame")
        current_host.pack(fill="both", expand=True)
        self.current_tree = self._tree(
            current_host,
            ("metal", "purity", "market_rate", "per_gram", "updated", "resolution"),
            {"market_rate": 170, "per_gram": 120, "updated": 165, "resolution": 160},
        )

        ttk.Label(history_card, text="Rate change history", style="Section.TLabel").pack(anchor="w")
        ttk.Label(history_card, text="Newest first. Historical rows are preserved for auditability.", style="SurfaceMuted.TLabel").pack(anchor="w", pady=(2, 6))
        history_host = ttk.Frame(history_card, style="Surface.TFrame")
        history_host.pack(fill="both", expand=True)
        self.history_tree = self._tree(
            history_host,
            ("metal", "purity", "market_rate", "effective_at"),
            {"market_rate": 180, "effective_at": 185},
        )
        self.refresh()

    def _tree(self, parent, columns, widths):
        tree = ttk.Treeview(parent, columns=columns, show="headings", selectmode="browse")
        names = {
            "metal": "Metal", "purity": "Purity", "market_rate": "Market unit",
            "per_gram": "Stored / g", "updated": "Effective", "resolution": "Pricing source",
            "effective_at": "Effective",
        }
        for col in columns:
            tree.heading(col, text=names.get(col, col.replace("_", " ").title()))
            tree.column(col, width=widths.get(col, 100), minwidth=75, anchor="e" if col in {"market_rate", "per_gram"} else "w")
        y = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=y.set)
        y.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)
        return tree

    def refresh(self):
        try:
            self.snapshot = self.api.get("/api/rate-management/current")
            self.provider = self.api.get("/api/rate-management/settings")
            history = self.api.get("/api/rates")
        except Exception as exc:
            self.status.set(str(exc))
            return

        for child in self.status_host.winfo_children():
            child.destroy()
        if not self.snapshot.get("rates"):
            status_pill(self.status_host, "NO RATES", "warning").pack()
            self.status.set("No shop rates are configured. Set Gold/Silver rates before billing jewellery.")
        elif self.snapshot.get("updated_today"):
            status_pill(self.status_host, "TODAY CONFIRMED", "success").pack()
            self.status.set(
                f"Shop rates were confirmed for business date {self.snapshot.get('business_date')}. Provider: {self.provider.get('provider','manual').upper()}."
            )
        else:
            status_pill(self.status_host, "CONFIRM TODAY", "warning").pack()
            last = self.snapshot.get("last_rate_business_date") or "unknown"
            self.status.set(
                f"No rate update/confirmation has been recorded for business date {self.snapshot.get('business_date')}. Last effective shop-rate date: {last}. Confirm or update rates before the day's first billing session."
            )

        self.current_tree.delete(*self.current_tree.get_children())
        for row in self.snapshot.get("rates", []):
            resolution = "Direct " + str(row.get("purity"))
            if row.get("derived"):
                resolution = "Derived from " + str(row.get("source_purity"))
            self.current_tree.insert(
                "", "end",
                values=(
                    row.get("metal"), row.get("purity"), market_rate_text(row.get("metal"), row.get("rate_per_gram")),
                    money(row.get("rate_per_gram")), row.get("effective_at"), resolution,
                ),
            )

        self.history_tree.delete(*self.history_tree.get_children())
        for row in history:
            self.history_tree.insert(
                "", "end",
                values=(row.get("metal"), row.get("purity"), market_rate_text(row.get("metal"), row.get("rate_per_gram")), row.get("effective_at")),
            )

    def manual_update(self):
        lookup = _current_lookup(self.snapshot)
        defaults = {"note": "Daily shop rate confirmation"}
        fields = []
        for key, label, metal, purity, divisor in RATE_FIELDS:
            row = lookup.get((metal, purity))
            # Only base rates are prefilled. Purity overrides stay blank on purpose;
            # otherwise yesterday's direct 916/925 rate could be copied into today's
            # batch and silently defeat a newly entered 999 base rate.
            defaults[key] = f"{_n(row.get('rate_per_gram')) * divisor:.2f}" if row and purity == "999" else ""
            fields.append((key, label))
        fields.append(("note", "Reason / note"))
        data = form_dialog(self, "Set current shop metal rates", fields, defaults)
        if not data:
            return
        rates = []
        try:
            for key, _label, metal, purity, divisor in RATE_FIELDS:
                raw = str(data.get(key) or "").strip()
                if not raw:
                    continue
                market_value = float(raw.replace(",", ""))
                if market_value <= 0:
                    raise ValueError(f"{metal} {purity} rate must be positive")
                rates.append({"metal": metal, "purity": purity, "rate_per_gram": market_value / divisor})
            if not rates:
                raise ValueError("Enter at least one Gold or Silver rate")
            self.api.post("/api/rate-management/apply", {"source": "manual", "note": data.get("note", ""), "rates": rates})
            messagebox.showinfo("Metal rates", "New shop rates are active. Previous rate history was preserved.", parent=self)
            self.refresh()
        except Exception as exc:
            self.admin.app.error(exc)

    def confirm_unchanged(self):
        base_rows = []
        seen = set()
        for row in self.snapshot.get("rates", []):
            metal = str(row.get("metal") or "")
            purity = str(row.get("purity") or "")
            if purity != "999" or metal in seen:
                continue
            value = _n(row.get("rate_per_gram"))
            if value > 0:
                base_rows.append({"metal": metal, "purity": "999", "rate_per_gram": value})
                seen.add(metal)
        if not base_rows:
            self.admin.app.error("No current base rate is available to confirm. Set the shop rate first.")
            return
        if not messagebox.askyesno(
            "Confirm unchanged rates",
            "Confirm the currently resolved base rates for today's business date?\n\nThis creates a new dated rate record; it does not rewrite earlier rate history.",
            parent=self,
        ):
            return
        try:
            self.api.post("/api/rate-management/apply", {"source": "manual", "note": "Confirmed current rates unchanged", "rates": base_rows})
            self.refresh()
            messagebox.showinfo("Metal rates", "Today's shop rates are confirmed.", parent=self)
        except Exception as exc:
            self.admin.app.error(exc)

    def sync_reference(self):
        try:
            provider = self.provider.get("provider", "manual")
            if provider == "manual":
                messagebox.showinfo(
                    "Rate sync",
                    "The provider is set to Manual. Choose IBJA or GoldAPI in Provider settings first. Manual rate entry remains available without internet.",
                    parent=self,
                )
                return
            preview = self.api.post("/api/rate-management/sync-preview", {"provider": provider})
            lines = [f"{x['metal']} {x['purity']}: {market_rate_text(x['metal'], x['rate_per_gram'])}" for x in preview.get("rates", [])]
            text = (
                f"Reference provider: {str(preview.get('provider','')).upper()}\n"
                f"Provider date: {preview.get('provider_date') or 'live'}  Session: {preview.get('session','')}\n\n"
                + "\n".join(lines)
                + "\n\n"
                + str(preview.get("note") or "")
                + "\n\nApply these reference values as the active shop rates?"
            )
            if not messagebox.askyesno("Review synced reference", text, parent=self):
                return
            self.api.post(
                "/api/rate-management/apply",
                {
                    "source": str(preview.get("provider") or provider),
                    "note": f"Approved synced {preview.get('provider')} reference {preview.get('provider_date','')} {preview.get('session','')}",
                    "rates": preview.get("rates", []),
                },
            )
            messagebox.showinfo("Metal rates", "Reference rates were approved and are now active shop rates.", parent=self)
            self.refresh()
        except Exception as exc:
            self.admin.app.error(exc)

    def provider_settings(self):
        current = self.provider or {}
        data = form_dialog(
            self,
            "Metal rate provider",
            [
                ("provider", "Provider", ["manual", "ibja", "goldapi"]),
                ("ibja_access_token", "IBJA access token (blank = keep existing)"),
                ("goldapi_access_token", "GoldAPI token (blank = keep existing)"),
            ],
            {"provider": current.get("provider", "manual")},
        )
        if not data:
            return
        try:
            payload = {"provider": data.get("provider") or "manual"}
            if str(data.get("ibja_access_token") or "").strip():
                payload["ibja_access_token"] = str(data["ibja_access_token"]).strip()
            if str(data.get("goldapi_access_token") or "").strip():
                payload["goldapi_access_token"] = str(data["goldapi_access_token"]).strip()
            self.api.put("/api/rate-management/settings", payload)
            self.refresh()
            messagebox.showinfo("Rate provider", "Provider settings saved. API tokens are not shown back in the UI.", parent=self)
        except Exception as exc:
            self.admin.app.error(exc)


def install_rate_ui(main_module) -> None:
    if getattr(main_module, "_rate_ui_installed", False):
        return

    def make_rates(admin_page):
        tab = ttk.Frame(admin_page.nb, padding=8)
        admin_page.nb.add(tab, text="Metal rates")
        panel = RateManagerPanel(tab, admin_page)
        panel.pack(fill="both", expand=True)
        admin_page.rate_panel = panel

    main_module.AdminPage.make_rates = make_rates

    original_app_init = main_module.App.__init__

    def app_init_with_rate_check(self, *args, **kwargs):
        original_app_init(self, *args, **kwargs)
        if self.user.get("role") in ("admin", "manager"):
            self.after(900, lambda: _day_start_rate_check(self, main_module))

    main_module.App.__init__ = app_init_with_rate_check
    main_module._rate_ui_installed = True


def _day_start_rate_check(app, main_module) -> None:
    try:
        snapshot = app.api.get("/api/rate-management/current")
    except Exception:
        return
    if not snapshot.get("rates"):
        messagebox.showwarning(
            "Metal rates required",
            "No Gold/Silver shop rate is configured. Set the current shop rate before billing jewellery.",
            parent=app.root,
        )
        return
    if snapshot.get("updated_today"):
        return
    last = snapshot.get("last_rate_business_date") or "unknown"
    if messagebox.askyesno(
        "Confirm today's metal rate",
        f"Today's shop rate has not been confirmed.\n\nBusiness date: {snapshot.get('business_date')}\nLast effective rate date: {last}\n\nOpen Administration → Metal rates now?",
        parent=app.root,
    ):
        app.show(main_module.AdminPage, "Administration")
