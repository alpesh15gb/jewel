from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .ui_theme import card, divider, status_pill


COMMON_RATES = (
    ("Gold", "999"),
    ("Gold", "995"),
    ("Gold", "916"),
    ("Gold", "750"),
    ("Gold", "585"),
    ("Silver", "999"),
    ("Platinum", "999"),
)


def _money(value) -> str:
    try:
        return f"₹{float(value):,.2f}"
    except Exception:
        return "₹0.00"


def _fmt_effective(value) -> str:
    text = str(value or "")
    return text.replace("T", " ")[:19]


class RateBoardFrame(ttk.Frame):
    """Operator-facing daily rate board.

    JewelLAN rates are deliberately append-only. "Change rate" creates a new
    effective rate and leaves historical invoices/rate history untouched.
    """

    def __init__(self, parent, admin_page):
        super().__init__(parent)
        self.page = admin_page
        self.app = admin_page.app
        self.api = admin_page.api
        self.data: dict = {}
        self.current_rows: list[dict] = []
        self._build()
        self.refresh()

    def _build(self):
        intro = card(self, 12)
        intro.pack(fill="x", pady=(0, 8))
        top = ttk.Frame(intro, style="Surface.TFrame")
        top.pack(fill="x")
        ttk.Label(top, text="Daily metal rate board", style="Section.TLabel").pack(side="left")
        self.fresh_status = ttk.Frame(top, style="Surface.TFrame")
        self.fresh_status.pack(side="right")
        ttk.Label(
            intro,
            text=(
                "Set a new shop rate whenever Gold, Silver or Platinum changes. "
                "Previous rates are never edited, so old invoices keep their original price basis."
            ),
            style="SurfaceMuted.TLabel",
            wraplength=1040,
        ).pack(anchor="w", pady=(3, 8))

        actions = ttk.Frame(intro, style="Surface.TFrame")
        actions.pack(fill="x")
        ttk.Button(actions, text="Set / change rate", style="Primary.TButton", command=self.change_selected).pack(side="left")
        ttk.Button(actions, text="Set daily board", style="Secondary.TButton", command=self.set_daily_board).pack(side="left", padx=5)
        ttk.Button(actions, text="Refresh", style="Secondary.TButton", command=self.refresh).pack(side="left")
        ttk.Button(actions, text="Sync IBJA reference", style="Secondary.TButton", command=self.sync_reference).pack(side="right")
        ttk.Button(actions, text="Apply synced reference", style="Secondary.TButton", command=self.apply_reference).pack(side="right", padx=5)
        if self.app.user.get("role") == "admin":
            ttk.Button(actions, text="Rate source settings", style="Secondary.TButton", command=self.provider_settings).pack(side="right")

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body)
        right = ttk.Frame(body)
        body.add(left, weight=7)
        body.add(right, weight=3)

        current_card = card(left, 12)
        current_card.pack(fill="both", expand=True, padx=(0, 5))
        ttk.Label(current_card, text="Current shop rates", style="Section.TLabel").pack(anchor="w")
        ttk.Label(
            current_card,
            text="Double-click any row to post a new effective rate. A stale marker means no rate was set on this business date.",
            style="SurfaceMuted.TLabel",
            wraplength=780,
        ).pack(anchor="w", pady=(2, 7))
        tree_host = ttk.Frame(current_card, style="Surface.TFrame")
        tree_host.pack(fill="both", expand=True)
        cols = ("metal", "purity", "rate", "effective", "status")
        self.current = ttk.Treeview(tree_host, columns=cols, show="headings", selectmode="browse", height=9)
        labels = {"metal": "Metal", "purity": "Purity", "rate": "Shop rate / g", "effective": "Effective at", "status": "Today"}
        widths = {"metal": 100, "purity": 80, "rate": 145, "effective": 180, "status": 100}
        for col in cols:
            self.current.heading(col, text=labels[col])
            self.current.column(col, width=widths[col], minwidth=70, anchor="e" if col in {"rate"} else "w")
        y = ttk.Scrollbar(tree_host, orient="vertical", command=self.current.yview)
        self.current.configure(yscrollcommand=y.set)
        y.pack(side="right", fill="y")
        self.current.pack(side="left", fill="both", expand=True)
        self.current.bind("<Double-1>", lambda _e: self.change_selected())

        ref_card = card(right, 12)
        ref_card.pack(fill="both", expand=True, padx=(5, 0))
        ttk.Label(ref_card, text="Market reference", style="Section.TLabel").pack(anchor="w")
        self.provider_label = tk.StringVar(value="Manual rates only")
        ttk.Label(ref_card, textvariable=self.provider_label, style="SurfaceMuted.TLabel", wraplength=330).pack(anchor="w", pady=(2, 7))
        self.reference_text = tk.Text(ref_card, height=14, wrap="word", font=("Consolas", 9), relief="flat", borderwidth=0)
        self.reference_text.pack(fill="both", expand=True)
        self.reference_text.configure(state="disabled")

        divider(self).pack(fill="x", pady=8)
        history_card = card(self, 10)
        history_card.pack(fill="both", expand=True)
        ttk.Label(history_card, text="Rate history", style="Section.TLabel").pack(anchor="w")
        ttk.Label(
            history_card,
            text="Audit history is append-only. Setting a new rate never rewrites an older rate.",
            style="SurfaceMuted.TLabel",
        ).pack(anchor="w", pady=(2, 6))
        hh = ttk.Frame(history_card, style="Surface.TFrame")
        hh.pack(fill="both", expand=True)
        hcols = ("metal", "purity", "rate", "effective")
        self.history = ttk.Treeview(hh, columns=hcols, show="headings", height=8)
        for col, label, width in (
            ("metal", "Metal", 100),
            ("purity", "Purity", 80),
            ("rate", "Rate / g", 150),
            ("effective", "Effective at", 220),
        ):
            self.history.heading(col, text=label)
            self.history.column(col, width=width, anchor="e" if col == "rate" else "w")
        hy = ttk.Scrollbar(hh, orient="vertical", command=self.history.yview)
        self.history.configure(yscrollcommand=hy.set)
        hy.pack(side="right", fill="y")
        self.history.pack(side="left", fill="both", expand=True)

    def refresh(self):
        try:
            self.data = self.api.get("/api/rate-board")
        except Exception as exc:
            self.app.error(exc)
            return
        self.current_rows = list(self.data.get("current") or [])
        self.current.delete(*self.current.get_children())
        stale = 0
        for row in self.current_rows:
            fresh = bool(row.get("fresh_today"))
            if not fresh:
                stale += 1
            iid = str(row.get("id"))
            self.current.insert(
                "",
                "end",
                iid=iid,
                values=(
                    row.get("metal", ""),
                    row.get("purity", ""),
                    _money(row.get("rate_per_gram")),
                    _fmt_effective(row.get("effective_at")),
                    "TODAY" if fresh else "STALE",
                ),
            )
        self.history.delete(*self.history.get_children())
        for row in self.data.get("history") or []:
            self.history.insert(
                "",
                "end",
                values=(row.get("metal", ""), row.get("purity", ""), _money(row.get("rate_per_gram")), _fmt_effective(row.get("effective_at"))),
            )
        for child in self.fresh_status.winfo_children():
            child.destroy()
        if not self.current_rows:
            status_pill(self.fresh_status, "No shop rates", "warning").pack()
        elif stale:
            status_pill(self.fresh_status, f"{stale} stale", "warning").pack()
        else:
            status_pill(self.fresh_status, "Rates set today", "success").pack()
        self._render_reference()

    def _current_map(self) -> dict[tuple[str, str], dict]:
        return {(str(x.get("metal")), str(x.get("purity"))): x for x in self.current_rows}

    def change_selected(self):
        selected = self.current.selection()
        row = None
        if selected:
            row = next((x for x in self.current_rows if str(x.get("id")) == selected[0]), None)
        defaults = {
            "metal": (row or {}).get("metal", "Gold"),
            "purity": (row or {}).get("purity", "916"),
            "rate_per_gram": str((row or {}).get("rate_per_gram", "")),
            "note": "",
        }
        data = self.page.app.current_page and self.page.app.current_page
        form = self.page.__class__.__mro__[1] if False else None
        # Use the shared, scroll-safe JewelLAN form dialog from the legacy shell.
        import jewel_client.main as main_module

        result = main_module.form_dialog(
            self,
            "Set new metal rate",
            [
                ("metal", "Metal", ["Gold", "Silver", "Platinum"]),
                ("purity", "Purity / fineness"),
                ("rate_per_gram", "New shop rate per gram"),
                ("note", "Reason / rate-board note"),
            ],
            defaults,
        )
        if not result:
            return
        try:
            rate = float(result.get("rate_per_gram") or 0)
            self.api.post(
                "/api/rate-board/batch",
                {"rates": [{"metal": result.get("metal"), "purity": result.get("purity"), "rate_per_gram": rate}], "note": result.get("note", "")},
            )
            self.refresh()
        except Exception as exc:
            self.app.error(exc)

    def set_daily_board(self):
        import jewel_client.main as main_module

        current = self._current_map()
        fields = []
        defaults = {"note": "Daily rate board"}
        for metal, purity in COMMON_RATES:
            key = f"{metal.lower()}_{purity}"
            fields.append((key, f"{metal} {purity} rate / g (blank = unchanged)"))
            value = current.get((metal, purity), {}).get("rate_per_gram")
            defaults[key] = str(value if value is not None else "")
        fields.append(("note", "Rate-board note"))
        result = main_module.form_dialog(self, "Set daily rate board", fields, defaults)
        if not result:
            return
        rates = []
        try:
            for metal, purity in COMMON_RATES:
                key = f"{metal.lower()}_{purity}"
                raw = str(result.get(key) or "").strip()
                if not raw:
                    continue
                rates.append({"metal": metal, "purity": purity, "rate_per_gram": float(raw)})
            if not rates:
                raise RuntimeError("Enter at least one rate")
            self.api.post("/api/rate-board/batch", {"rates": rates, "note": result.get("note", "")})
            self.refresh()
        except Exception as exc:
            self.app.error(exc)

    def provider_settings(self):
        import jewel_client.main as main_module

        provider = self.data.get("provider") or {}
        result = main_module.form_dialog(
            self,
            "Market-rate source",
            [
                ("provider", "Provider", ["manual", "ibja"]),
                ("environment", "IBJA environment", ["production", "uat"]),
                ("access_token", "IBJA access token (blank keeps existing)"),
            ],
            {
                "provider": provider.get("provider", "manual"),
                "environment": provider.get("environment", "production"),
                "access_token": "",
            },
        )
        if not result:
            return
        try:
            self.api.put(
                "/api/rate-board/provider",
                {
                    "provider": result.get("provider"),
                    "environment": result.get("environment"),
                    "access_token": result.get("access_token"),
                    "keep_existing_token": True,
                },
            )
            self.refresh()
        except Exception as exc:
            self.app.error(exc)

    def sync_reference(self):
        provider = self.data.get("provider") or {}
        if provider.get("provider") != "ibja":
            messagebox.showinfo(
                "Market reference",
                "IBJA sync is not configured. An administrator can configure it under Rate source settings. Manual shop rates continue to work offline.",
                parent=self,
            )
            return
        try:
            result = self.api.post("/api/rate-board/sync", {})
            reference = result.get("reference") or {}
            self.data["reference"] = reference
            self._render_reference()
            messagebox.showinfo(
                "IBJA reference synced",
                "Reference rates were fetched but NOT applied to billing. Review them, then use Apply synced reference if desired.",
                parent=self,
            )
        except Exception as exc:
            self.app.error(exc)

    def apply_reference(self):
        reference = self.data.get("reference") or {}
        if not reference.get("rates"):
            try:
                found = self.api.get("/api/rate-board/reference")
                reference = (found or {}).get("reference") or {}
            except Exception as exc:
                self.app.error(exc)
                return
        if not reference.get("rates"):
            messagebox.showinfo("Market reference", "Sync a reference first.", parent=self)
            return
        import jewel_client.main as main_module

        result = main_module.form_dialog(
            self,
            "Apply synced reference as shop rates",
            [
                ("gold_premium_per_gram", "Gold premium / adjustment per gram"),
                ("silver_premium_per_gram", "Silver premium / adjustment per gram"),
                ("round_to", "Round final rate to nearest (0 = no rounding)"),
            ],
            {"gold_premium_per_gram": "0", "silver_premium_per_gram": "0", "round_to": "0"},
        )
        if not result:
            return
        summary = "\n".join(f"{x.get('metal')} {x.get('purity')}: {_money(x.get('rate_per_gram'))}/g" for x in reference.get("rates", []))
        if not messagebox.askyesno(
            "Apply reference rates?",
            "This will POST new shop rates. Existing invoices/history will not change.\n\n" + summary[:1200],
            parent=self,
        ):
            return
        try:
            self.api.post(
                "/api/rate-board/apply-reference",
                {
                    "gold_premium_per_gram": float(result.get("gold_premium_per_gram") or 0),
                    "silver_premium_per_gram": float(result.get("silver_premium_per_gram") or 0),
                    "round_to": float(result.get("round_to") or 0),
                },
            )
            self.refresh()
        except Exception as exc:
            self.app.error(exc)

    def _render_reference(self):
        provider = self.data.get("provider") or {}
        reference = self.data.get("reference") or {}
        label = provider.get("provider", "manual").upper()
        if provider.get("provider") == "ibja":
            label += " configured" if provider.get("configured") else " token missing"
        self.provider_label.set(label + " · reference only; billing remains offline")
        lines = []
        if reference.get("rates"):
            lines.append(f"Provider: {reference.get('provider','')}  Session: {reference.get('session','')}")
            lines.append(f"Rate date: {reference.get('rate_date','')}  Fetched: {_fmt_effective(reference.get('fetched_at'))}")
            lines.append("")
            for row in reference.get("rates") or []:
                lines.append(f"{row.get('metal',''):8} {row.get('purity',''):>3}  {_money(row.get('rate_per_gram'))}/g")
            lines.append("")
            lines.append("Reference is not a shop rate until explicitly applied.")
        else:
            lines = [
                "No market reference cached.",
                "",
                "Manual shop-rate entry is always available and does not need internet.",
                "IBJA sync is optional and requires a subscribed API token.",
            ]
        self.reference_text.configure(state="normal")
        self.reference_text.delete("1.0", "end")
        self.reference_text.insert("1.0", "\n".join(lines))
        self.reference_text.configure(state="disabled")


def install_rate_management(main_module) -> None:
    """Replace only Administration.make_rates while legacy main.py is decomposed."""

    def make_rates(admin_page):
        host = ttk.Frame(admin_page.nb, padding=8)
        admin_page.nb.add(host, text="Metal rates")
        panel = RateBoardFrame(host, admin_page)
        panel.pack(fill="both", expand=True)
        admin_page.rate_board_panel = panel

    main_module.AdminPage.make_rates = make_rates
