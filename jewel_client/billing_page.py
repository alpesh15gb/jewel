from __future__ import annotations

import datetime as dt
import uuid
import tkinter as tk
from tkinter import messagebox, ttk

from .api import ApiError
from .config import remove_pending_post, upsert_pending_post
from .ui_common import Page, form_dialog, money, open_pdf
from .ui_theme import card, divider, status_pill


def _utc_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


MONEY_COLUMNS = {
    "metal_rate",
    "metal_value",
    "wastage_value",
    "making_charge",
    "stone_value",
    "discount",
    "taxable",
    "gst_amount",
    "line_total",
}


def _number(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _signed_money(value) -> str:
    amount = _number(value)
    if abs(amount) < 0.005:
        return "₹0.00"
    sign = "−" if amount < 0 else "+"
    return f"{sign}₹{abs(amount):,.2f}"


def format_invoice_cell(column: str, value) -> str:
    if column in MONEY_COLUMNS:
        return money(value)
    if column in ("gross_weight", "net_weight"):
        return f"{_number(value):.3f}"
    if column in ("wastage_percent", "gst_rate"):
        return f"{_number(value):.2f}%"
    return str(value if value is not None else "")


def line_formula(line: dict) -> str:
    tag = str(line.get("tag_no") or "Item")
    net = _number(line.get("net_weight"))
    rate = _number(line.get("metal_rate"))
    metal_value = _number(line.get("metal_value"))
    wastage_percent = _number(line.get("wastage_percent"))
    wastage_value = _number(line.get("wastage_value"))
    making = _number(line.get("making_charge"))
    stone = _number(line.get("stone_value"))
    discount = _number(line.get("discount"))
    taxable = _number(line.get("taxable"))
    gst_rate = _number(line.get("gst_rate"))
    gst = _number(line.get("gst_amount"))
    total = _number(line.get("line_total"))
    return (
        f"{tag}  •  {net:.3f} g × {money(rate)}/g = {money(metal_value)} metal\n"
        f"Wastage {wastage_percent:.2f}% = {money(wastage_value)}   +   "
        f"Making {money(making)}   +   Stones {money(stone)}   −   Discount {money(discount)}\n"
        f"Taxable {money(taxable)}   +   GST {gst_rate:.2f}% {money(gst)}   =   {money(total)}"
    )


class POSPage(Page):
    """Billing screen with an auditable jewellery-price breakdown.

    The server remains the pricing authority. This page only makes every component
    returned by /api/sales/quote visible and keeps the quote current while the
    operator edits invoice discount or payment tenders.
    """

    COLS = (
        "tag_no",
        "description",
        "metal",
        "purity",
        "net_weight",
        "metal_rate",
        "metal_value",
        "wastage_percent",
        "wastage_value",
        "making_charge",
        "stone_value",
        "discount",
        "taxable",
        "gst_amount",
        "line_total",
    )
    HEADINGS = {
        "tag_no": "Tag No",
        "description": "Description",
        "metal": "Metal",
        "purity": "Purity",
        "net_weight": "Net Wt (g)",
        "metal_rate": "Rate / g",
        "metal_value": "Metal Value",
        "wastage_percent": "Wastage %",
        "wastage_value": "Wastage Value",
        "making_charge": "Making",
        "stone_value": "Stone",
        "discount": "Discount",
        "taxable": "Taxable",
        "gst_amount": "GST",
        "line_total": "Line Total",
    }
    WIDTHS = {
        "tag_no": 105,
        "description": 140,
        "metal": 65,
        "purity": 60,
        "net_weight": 80,
        "metal_rate": 90,
        "metal_value": 95,
        "wastage_percent": 75,
        "wastage_value": 95,
        "making_charge": 85,
        "stone_value": 80,
        "discount": 80,
        "taxable": 95,
        "gst_amount": 80,
        "line_total": 100,
    }

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.lines: list[dict] = []
        self.old: list[dict] = []
        self.quote: dict = {}
        self.customers: list[dict] = []
        self._discount_after = None

        self.heading(
            "Billing counter",
            "Scan → Review → Pay → Post. One atomic invoice, fully offline.",
        )
        from .ui_theme import stepper as _stepper
        self._steps = _stepper(self, [("▣", "Scan"), ("◈", "Review"), ("₹", "Pay"), ("✔", "Post")], 0)

        scan_card = card(self, 14)
        scan_card.pack(fill="x", pady=(0, 10))
        top = ttk.Frame(scan_card, style="Surface.TFrame")
        top.pack(fill="x")
        ttk.Label(
            top,
            text="◉  SCAN BARCODE / TAG  —  F2 refocus  •  Enter adds  •  F9 posts",
            style="SurfaceMuted.TLabel",
            font=("Segoe UI Semibold", 8),
        ).pack(side="left")
        self.scan_pill = status_pill(top, "● Ready for scanner", "success")
        self.scan_pill.pack(side="right")
        self.scan = tk.StringVar()
        self.scan_entry = ttk.Entry(scan_card, textvariable=self.scan, font=("Segoe UI Semibold", 16))
        self.scan_entry.pack(fill="x", pady=(6, 0), ipady=8)
        self.scan_entry.bind("<Return>", self.add_scan)
        self.scan_entry.bind("<FocusIn>", lambda _e: self._scan_focus(True))
        self.scan_entry.bind("<FocusOut>", lambda _e: self._scan_focus(False))
        self.scan_entry.bind("<FocusIn>", lambda _e: self._scan_focus(True))
        self.scan_entry.bind("<FocusOut>", lambda _e: self._scan_focus(False))

        pan = ttk.Panedwindow(self, orient="horizontal")
        pan.pack(fill="both", expand=True)
        left = ttk.Frame(pan)
        right = ttk.Frame(pan, width=360)
        pan.add(left, weight=5)
        pan.add(right, weight=4)
        # Keep right panel usable on 1366px screens + force sash so totals never clip.
        try:pan.paneconfigure(right, minsize=340)
        except Exception:pass
        try:pan.paneconfigure(left, minsize=520)
        except Exception:pass
        self._pan = pan
        self._pan_left = left
        self._pan_right = right
        def _place_sash():
            try:
                total = pan.winfo_width()
                if total and total > 900:
                    pan.sashpos(0, total - 370)
            except Exception:pass
        try:self.after(100, _place_sash)
        except Exception:pass
        try:self.bind("<Configure>", lambda _e: _place_sash(), add="+")
        except Exception:pass

        line_card = card(left, 12)
        line_card.pack(fill="both", expand=True, padx=(0, 6))
        lh = ttk.Frame(line_card, style="Surface.TFrame")
        lh.pack(fill="x", pady=(0, 7))
        ttk.Label(lh, text="Invoice items", style="Section.TLabel").pack(side="left")
        self.item_count = tk.StringVar(value="0 items")
        ttk.Label(lh, textvariable=self.item_count, style="SurfaceMuted.TLabel").pack(side="left", padx=(10, 0))
        ttk.Button(
            lh,
            text="Remove selected",
            style="Secondary.TButton",
            command=self.remove,
        ).pack(side="right")

        tree_host = ttk.Frame(line_card, style="Surface.TFrame")
        tree_host.pack(fill="both", expand=True)
        self.t = self._invoice_tree(tree_host)
        self.t.bind("<Delete>", lambda _e: self.remove())
        self.t.bind("<<TreeviewSelect>>", lambda _e: self._render_selected_formula())

        divider(line_card).pack(fill="x", pady=(8, 7))
        ttk.Label(
            line_card,
            text="SELECTED ITEM CALCULATION",
            style="SurfaceMuted.TLabel",
            font=("Segoe UI Semibold", 8),
        ).pack(anchor="w")
        self.calc_text = tk.StringVar(value="Scan an item to see its complete metal, wastage, making, stone and GST calculation.")
        self.calc_box = tk.Text(line_card, height=3, wrap="word", font=("Segoe UI", 9), relief="flat", bg="#FFFFFF", fg="#1C2430", padx=2, pady=2)
        self.calc_box.pack(fill="x", anchor="w", pady=(4, 0))
        self.calc_box.insert("1.0", self.calc_text.get())
        self.calc_box.configure(state="disabled")
        def _sync_calc(*_a):
            try:
                self.calc_box.configure(state="normal");self.calc_box.delete("1.0","end");self.calc_box.insert("1.0", self.calc_text.get());self.calc_box.configure(state="disabled")
            except Exception:pass
        try:self.calc_text.trace_add("write", _sync_calc)
        except Exception:pass

        summary_outer = card(right, 10)
        summary_outer.pack(fill="both", expand=True, padx=(6, 0))
        # Vertical scroll so totals/COMPLETE SALE never clip on short screens.
        summary_canvas = tk.Canvas(summary_outer, bg="#FFFFFF", highlightthickness=0, borderwidth=0)
        summary_bar = ttk.Scrollbar(summary_outer, orient="vertical", command=summary_canvas.yview)
        summary_canvas.configure(yscrollcommand=summary_bar.set)
        summary_bar.pack(side="right", fill="y")
        summary_canvas.pack(side="left", fill="both", expand=True)
        summary = ttk.Frame(summary_canvas, style="Surface.TFrame", padding=6)
        summary_win = summary_canvas.create_window((0,0), window=summary, anchor="nw")
        def _sum_conf(_e=None):
            try:
                summary_canvas.configure(scrollregion=summary_canvas.bbox("all"))
                summary_canvas.itemconfigure(summary_win, width=summary_canvas.winfo_width())
            except Exception:pass
        summary.bind("<Configure>", _sum_conf)
        summary_canvas.bind("<Configure>", _sum_conf)
        def _sum_wheel(ev):
            try:
                if summary_canvas.bbox("all") and summary_canvas.winfo_height() < summary.winfo_reqheight():
                    summary_canvas.yview_scroll(-1 if getattr(ev,"delta",0)>0 else 1, "units")
                    return "break"
            except Exception:pass
        summary_canvas.bind("<MouseWheel>", _sum_wheel)
        summary.bind("<MouseWheel>", _sum_wheel)
        ttk.Label(summary, text="Customer & payment", style="Section.TLabel", wraplength=300, justify="left").pack(anchor="w")

        ttk.Label(
            summary,
            text="CUSTOMER",
            style="SurfaceMuted.TLabel",
            font=("Segoe UI Semibold", 8),
        ).pack(anchor="w", pady=(9, 3))
        customer_row = ttk.Frame(summary, style="Surface.TFrame")
        customer_row.pack(fill="x")
        self.customer = ttk.Combobox(customer_row, state="readonly")
        self.customer.pack(side="left", fill="x", expand=True)
        ttk.Button(
            customer_row,
            text="↻",
            width=3,
            style="Secondary.TButton",
            command=self.load_customers,
        ).pack(side="left", padx=(5, 0))
        self.load_customers()

        ttk.Label(
            summary,
            text="INVOICE DISCOUNT",
            style="SurfaceMuted.TLabel",
            font=("Segoe UI Semibold", 8),
        ).pack(anchor="w", pady=(8, 3))
        self.discount = tk.StringVar(value="0")
        discount_entry = ttk.Entry(summary, textvariable=self.discount)
        discount_entry.pack(fill="x")
        discount_entry.bind("<Return>", lambda _e: self.requote())
        discount_entry.bind("<FocusOut>", lambda _e: self.requote(show_error=False))
        self.discount_hint = tk.StringVar(value="Discount recalculates automatically.")
        ttk.Label(summary, textvariable=self.discount_hint, style="SurfaceMuted.TLabel", wraplength=300, justify="left").pack(anchor="w", pady=(2, 0))
        self.discount.trace_add("write", self._schedule_discount_requote)

        # Offline loyalty: 1 pt = Rs 1, earn 1 pt per Rs 1000.
        loyrow = ttk.Frame(summary, style="Surface.TFrame")
        loyrow.pack(fill="x", pady=(6, 0))
        ttk.Label(loyrow, text="LOYALTY PTS", style="SurfaceMuted.TLabel", font=("Segoe UI Semibold", 8)).pack(side="left")
        self.loyalty_info = tk.StringVar(value="")
        ttk.Label(loyrow, textvariable=self.loyalty_info, style="SurfaceMuted.TLabel", wraplength=150, justify="right").pack(side="right")
        self.loyalty_redeem = tk.StringVar(value="0")
        loyentry = ttk.Entry(summary, textvariable=self.loyalty_redeem)
        loyentry.pack(fill="x")
        loyentry.bind("<Return>", lambda _e: self.requote())
        loyentry.bind("<FocusOut>", lambda _e: self.requote(show_error=False))
        self.loyalty_redeem.trace_add("write", self._schedule_discount_requote)

        oldrow = ttk.Frame(summary, style="Surface.TFrame")
        oldrow.pack(fill="x", pady=(7, 4))
        oldrow.columnconfigure(0, weight=1)
        oldrow.columnconfigure(1, weight=1)
        ttk.Button(oldrow, text="Add old gold", style="Secondary.TButton", command=self.old_gold).grid(row=0, column=0, sticky="ew", padx=(0,3))
        ttk.Button(oldrow, text="Bhav-cut", style="Secondary.TButton", command=self.bhav_cut).grid(row=0, column=1, sticky="ew", padx=(3,0))
        self.old_label = tk.StringVar(value="₹0.00")
        ttk.Label(oldrow, textvariable=self.old_label, style="Surface.TLabel", font=("Segoe UI Semibold", 9), anchor="e").grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4,0))

        divider(summary).pack(fill="x", pady=7)
        self.totals: dict[str, tk.StringVar] = {}
        self._summary_row(summary, "subtotal", "Subtotal")
        self._summary_row(summary, "discount", "Discount")
        self._summary_row(summary, "taxable", "Taxable")
        self._summary_row(summary, "gst", "GST")
        self._summary_row(summary, "round_off", "Round-off")
        self._summary_row(summary, "total", "Total", emphasis=True)
        self._summary_row(summary, "payable", "Due", emphasis=True)

        divider(summary).pack(fill="x", pady=7)
        ttk.Label(
            summary,
            text="PAYMENT SPLIT",
            style="SurfaceMuted.TLabel",
            font=("Segoe UI Semibold", 8),
        ).pack(anchor="w", pady=(0, 4))
        pay_grid = ttk.Frame(summary, style="Surface.TFrame")
        pay_grid.pack(fill="x")
        self.pay: dict[str, tk.StringVar] = {}
        self._pay_entries = {}
        for n, (key, label) in enumerate((("cash", "Cash"), ("card", "Card"), ("upi", "UPI"), ("credit", "Credit"))):
            row, col = divmod(n, 2)
            cell = ttk.Frame(pay_grid, style="Surface.TFrame")
            cell.grid(row=row, column=col, sticky="ew", padx=(0 if col == 0 else 5, 5 if col == 0 else 0), pady=2)
            ttk.Label(cell, text=label, style="SurfaceMuted.TLabel").pack(anchor="w")
            var = tk.StringVar(value="0")
            self.pay[key] = var
            ent = ttk.Entry(cell, textvariable=var)
            ent.pack(fill="x")
            ent.bind("<Return>", lambda _e: self.checkout())
            ent.bind("<F9>", lambda _e: self.checkout())
            self._pay_entries[key] = ent
            var.trace_add("write", self._payment_changed)
        pay_grid.columnconfigure(0, weight=1)
        pay_grid.columnconfigure(1, weight=1)

        payment_line = ttk.Frame(summary, style="Surface.TFrame")
        payment_line.pack(fill="x", pady=(6, 2))
        ttk.Label(payment_line, text="Tendered", style="SurfaceMuted.TLabel").pack(side="left")
        self.tendered = tk.StringVar(value="₹0.00")
        ttk.Label(payment_line, textvariable=self.tendered, style="Surface.TLabel").pack(side="right")
        remaining_line = ttk.Frame(summary, style="Surface.TFrame")
        remaining_line.pack(fill="x", pady=2)
        ttk.Label(remaining_line, text="Payment remaining", style="SurfaceMuted.TLabel").pack(side="left")
        self.remaining = tk.StringVar(value="₹0.00")
        ttk.Label(remaining_line, textvariable=self.remaining, style="Surface.TLabel", font=("Segoe UI Semibold", 10)).pack(side="right")

        quick = ttk.Frame(summary, style="Surface.TFrame")
        quick.pack(fill="x", pady=(7, 3))
        ttk.Button(quick, text="Recalculate", style="Secondary.TButton", command=self.requote).pack(side="left", fill="x", expand=True)
        ttk.Button(quick, text="Balance → Cash", style="Secondary.TButton", command=self.cash).pack(side="left", fill="x", expand=True, padx=(5, 0))
        self.checkout_btn = ttk.Button(
            summary,
            text="✔  COMPLETE SALE & PRINT  (F9)",
            style="Primary.TButton",
            command=self.checkout,
        )
        self.checkout_btn.pack(fill="x", ipady=10, pady=(5, 0))
        ttk.Label(
            summary,
            text="Scanner + Enter adds a tag. Delete removes the selected line.",
            style="SurfaceMuted.TLabel",
            wraplength=340,
        ).pack(anchor="w", pady=(6, 0))

        self.render()
        try:self.scan_entry.focus_set()
        except tk.TclError:pass
        # Keyboard: F9 posts from scan/pay entries, F2 refocuses scanner.
        try:
            self.scan_entry.bind("<F9>", lambda _e: self.checkout())
            self.scan_entry.bind("<F2>", lambda _e: self.scan_entry.focus_set())
        except Exception:pass

    def _scan_focus(self, focused: bool):
        try:self.scan_pill.configure(text=("● Scanning…" if focused else "● Ready for scanner"))
        except Exception:pass

    def _invoice_tree(self, parent):
        tree = ttk.Treeview(parent, columns=self.COLS, show="headings", selectmode="browse")
        for column in self.COLS:
            tree.heading(column, text=self.HEADINGS[column])
            numeric = column in MONEY_COLUMNS or column in ("net_weight", "wastage_percent")
            tree.column(
                column,
                width=self.WIDTHS.get(column, 105),
                minwidth=65,
                stretch=False,
                anchor="e" if numeric else "w",
            )
        ybar = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        xbar = ttk.Scrollbar(parent, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        ybar.pack(side="right", fill="y")
        xbar.pack(side="bottom", fill="x")
        tree.pack(side="left", fill="both", expand=True)
        return tree

    def _summary_row(self, parent, key, label, emphasis=False):
        row = ttk.Frame(parent, style="Surface.TFrame")
        row.pack(fill="x", pady=2)
        row.columnconfigure(0, weight=1)
        row.columnconfigure(1, weight=0)
        # Short labels + wraplength so money never clips on narrow panels.
        ttk.Label(row, text=label, style="SurfaceMuted.TLabel", wraplength=150, justify="left").grid(row=0, column=0, sticky="w")
        var = tk.StringVar(value="₹0.00")
        self.totals[key] = var
        ttk.Label(
            row,
            textvariable=var,
            style="Money.TLabel" if emphasis else "Surface.TLabel",
            font=("Segoe UI Semibold", 11) if emphasis else ("Segoe UI Semibold", 9),
            anchor="e",
            justify="right",
        ).grid(row=0, column=1, sticky="e", padx=(8, 0))

    def load_customers(self, reset=True):
        try:
            self.customers = self.api.get("/api/customers")
            self.customer["values"] = ["Walk-in Customer"] + [
                f"{str(x['name'])[:22]} [#{x['id']}]" for x in self.customers
            ]
            if reset:self.customer.current(0)
            self._update_loyalty_info()
            if not getattr(self, "_loyalty_bound", False):
                try:self.customer.bind("<<ComboboxSelected>>", lambda _e: self._update_loyalty_info(), add="+")
                except Exception:pass
                self._loyalty_bound = True
        except Exception:
            pass

    def _update_loyalty_info(self):
        try:
            idx=self.customer.current()
            if idx>0:
                pts=int(float(self.customers[idx-1].get('loyalty_points') or 0))
                self.loyalty_info.set(f"{pts} pts avail (Rs {pts})")
            else:self.loyalty_info.set("")
        except Exception:self.loyalty_info.set("")

    def add_scan(self, event=None):
        code = self.scan.get().strip()
        self.scan.set("")
        if not code:
            return
        try:
            item = self.api.get(
                f"/api/items/barcode/{code}",
                branch_id=int(self.app.cfg.get("branch_id", 1)),
                counter_id=self.app.cfg.get("counter_id") or None,
            )
        except Exception as exc:
            self.app.error(exc)
            return
        if item["status"] != "in_stock":
            self.app.error(f"{item['tag_no']} is {item['status']}")
            return
        if any(x["item_id"] == item["id"] for x in self.lines):
            self.app.error(f"{item['tag_no']} is already on this invoice")
            return
        self.lines.append({"item_id": item["id"], "item_version": item.get("version")})
        self.requote()
        self.scan_entry.focus_set()

    def _schedule_discount_requote(self, *_):
        if self._discount_after is not None:
            try:
                self.after_cancel(self._discount_after)
            except tk.TclError:
                pass
        try:
            self._discount_after = self.after(300, self._discount_requote)
        except tk.TclError:
            self._discount_after = None

    def _discount_requote(self):
        self._discount_after = None
        try:
            raw = self.discount.get().strip()
            lraw = self.loyalty_redeem.get().strip()
        except tk.TclError:return
        try:
            value = float(raw or 0)
            if value < 0:
                raise ValueError
            loy = int(float(lraw or 0))
            if loy < 0:raise ValueError
        except ValueError:
            try:self.discount_hint.set("Enter non-negative discount and loyalty points.")
            except tk.TclError:pass
            return
        try:self.discount_hint.set("Discount applied to the live quote.")
        except tk.TclError:pass
        try:
            if self.lines and self.winfo_exists():
                self.requote(show_error=False)
        except tk.TclError:pass

    def requote(self, show_error=True):
        if not self.lines:
            self.quote = {}
            self.render()
            return
        try:
            discount = float(self.discount.get().strip() or 0)
            if discount < 0:
                raise ValueError("Invoice discount cannot be negative")
            loy = int(float(self.loyalty_redeem.get().strip() or 0))
            if loy < 0:raise ValueError("Loyalty cannot be negative")
        except ValueError as exc:
            if show_error:
                self.app.error(exc)
            return
        try:
            self.quote = self.api.post(
                "/api/sales/quote",
                {
                    "lines": self.lines,
                    "discount": discount,
                    "loyalty_redeem_points": loy,
                    "old_gold": self.old,
                    "branch_id": int(self.app.cfg.get("branch_id", 1)),
                    "counter_id": self.app.cfg.get("counter_id") or None,
                },
            )
            self.discount_hint.set("Discount applied to the live quote.")
            self.render()
        except Exception as exc:
            if show_error:
                self.app.error(exc)

    def render(self):
        selected = self.t.selection()[0] if self.t.selection() else None
        self.t.delete(*self.t.get_children())
        rows = self.quote.get("lines", [])
        for row in rows:
            values = tuple(format_invoice_cell(column, row.get(column, "")) for column in self.COLS)
            self.t.insert("", "end", iid=str(row["item_id"]), values=values)
        self.item_count.set(f"{len(rows)} item" + ("" if len(rows) == 1 else "s"))
        if selected and self.t.exists(selected):
            self.t.selection_set(selected)
        elif rows:
            first = str(rows[0]["item_id"])
            self.t.selection_set(first)
            self.t.focus(first)
        self._render_selected_formula()

        self.totals["subtotal"].set(money(self.quote.get("subtotal", 0)))
        discount = _number(self.quote.get("discount", 0))
        self.totals["discount"].set("−" + money(discount) if discount else money(0))
        self.totals["taxable"].set(money(self.quote.get("taxable", 0)))
        self.totals["gst"].set(money(self.quote.get("gst", 0)))
        self.totals["round_off"].set(_signed_money(self.quote.get("round_off", 0)))
        self.totals["total"].set(money(self.quote.get("total", 0)))
        self.totals["payable"].set(money(self.quote.get("payable", 0)))
        old_value = sum(_number(x.get("value", 0)) for x in self.old)
        self.old_label.set("Old gold  " + ("−" + money(old_value) if old_value else money(0)))
        self._payment_changed()

    def _render_selected_formula(self):
        selection = self.t.selection()
        if not selection:
            self.calc_text.set("Scan an item to see its complete metal, wastage, making, stone and GST calculation.")
            return
        item_id = int(selection[0])
        row = next((x for x in self.quote.get("lines", []) if int(x.get("item_id", 0)) == item_id), None)
        if row:
            self.calc_text.set(line_formula(row))

    def remove(self):
        if self.t.selection():
            item_id = int(self.t.selection()[0])
            self.lines = [x for x in self.lines if x["item_id"] != item_id]
            self.requote()
            self.scan_entry.focus_set()

    def old_gold(self):
        data = form_dialog(
            self,
            "Old gold exchange",
            [
                ("metal", "Metal", ["Gold", "Silver"]),
                ("purity", "Purity"),
                ("gross_weight", "Gross weight (g)"),
                ("deduction_percent", "Deduction % (0-100)"),
                ("rate", "Rate / g"),
                ("value", "Exchange value (0 = auto)"),
                ("notes", "Notes"),
            ],
            {
                "metal": "Gold",
                "purity": "916",
                "gross_weight": "0",
                "deduction_percent": "0",
                "rate": "0",
                "value": "0",
            },
        )
        if not data:
            return
        data["mode"]="cash"
        try:
            for key in ("gross_weight", "deduction_percent", "rate", "value"):
                data[key] = float(data[key] or 0)
            if data["gross_weight"] <= 0:
                self.app.error("Old-gold gross weight must be positive")
                return
            if not 0 <= data["deduction_percent"] <= 100:
                self.app.error("Deduction % must be between 0 and 100")
                return
            if data["rate"] < 0 or data["value"] < 0:
                self.app.error("Old-gold rate and value cannot be negative")
                return
            if not data["value"]:
                data["value"] = round(data["gross_weight"] * (1 - data["deduction_percent"] / 100) * data["rate"], 2)
            if data["value"] <= 0:
                self.app.error("Old-gold exchange value must be positive (enter rate or value)")
                return
            self.old.append(data)
            self.requote()
        except ValueError:
            self.app.error("Old-gold values must be numeric")

    def bhav_cut(self):
        """Offline bhav-cut: old gold valued at live shop rate, metal-for-metal."""
        try:rates=self.api.get("/api/rates")
        except Exception as e:self.app.error(e);return
        if not rates:self.app.error("Set a metal rate first (Administration → Metal rates)");return
        # pick latest Gold 916 or first
        live=None
        for r in rates:
            if str(r.get('metal','')).lower()=='gold' and str(r.get('purity'))=='916':live=r;break
        live=live or rates[0]
        data=form_dialog(self,"Bhav-cut exchange",[("metal","Metal",["Gold","Silver"]),("purity","Purity"),("gross_weight","Old gross weight (g)"),("deduction_percent","Deduction %"),("notes","Notes")],{"metal":live.get('metal','Gold'),"purity":live.get('purity','916'),"gross_weight":"0","deduction_percent":"2"})
        if not data:return
        try:
            gw=float(data.get("gross_weight") or 0);ded=float(data.get("deduction_percent") or 0)
            if gw<=0:self.app.error("Gross weight must be positive");return
            if not 0<=ded<=100:self.app.error("Deduction must be 0-100");return
            # find matching live rate
            rate=float(live.get('rate_per_gram',0))
            for r in rates:
                if str(r.get('metal'))==data.get('metal') and str(r.get('purity'))==data.get('purity'):rate=float(r.get('rate_per_gram',rate));break
            val=round(gw*(1-ded/100)*rate,2)
            self.old.append({"metal":data.get('metal'),"purity":data.get('purity'),"gross_weight":gw,"deduction_percent":ded,"rate":rate,"value":val,"notes":f"BHAV-CUT @ {rate}: {data.get('notes','')}".strip(),"mode":"bhav_cut"})
            self.requote();messagebox.showinfo("Bhav-cut",f"Valued {gw:.3f}g @ Rs {rate:,.2f} = Rs {val:,.2f}",parent=self)
        except ValueError:self.app.error("Weights must be numeric")

    def _payment_changed(self, *_):
        tendered = 0.0
        for var in self.pay.values():
            try:
                tendered += float(var.get().strip() or 0)
            except ValueError:
                pass
        payable = _number(self.quote.get("payable", 0))
        remaining = payable - tendered
        self.tendered.set(money(tendered))
        if remaining > 0.004:
            self.remaining.set(money(remaining) + " due")
        elif remaining < -0.004:
            self.remaining.set(money(abs(remaining)) + " over")
        else:
            self.remaining.set("₹0.00 — paid")

    def cash(self):
        self.pay["cash"].set(f"{_number(self.quote.get('payable', 0)):.2f}")
        for key in ("card", "upi", "credit"):
            self.pay[key].set("0")

    def checkout(self):
        if not self.lines:
            messagebox.showinfo("Billing", "Scan at least one tag before completing the sale.", parent=self)
            return
        self.requote()
        if not self.quote or not self.quote.get("quote_hash"):
            self.app.error("Quote failed — fix discount/loyalty and retry before posting.")
            return
        body = {}
        posted = False
        try:
            index = self.customer.current()
            customer_id = self.customers[index - 1]["id"] if index > 0 else None
            try:
                payments = {key: float(var.get().strip() or 0) for key, var in self.pay.items()}
            except ValueError:
                self.app.error("Payment amounts must be numeric")
                return
            if any(v < 0 for v in payments.values()):
                self.app.error("Payment amounts cannot be negative")
                return
            if payments.get("credit", 0) > 0 and not customer_id:
                self.app.error("Credit payment requires a customer (not Walk-in)")
                return
            payable = _number(self.quote.get("payable", 0))
            tendered = sum(payments.values())
            if abs(tendered - payable) > 0.005:
                self.app.error(f"Payments (₹{tendered:,.2f}) must equal amount due (₹{payable:,.2f}). Use Balance → Cash.")
                return
            request_id = str(uuid.uuid4())
            try:loy_pts=int(float(self.loyalty_redeem.get().strip() or 0))
            except ValueError:self.app.error("Loyalty points must be numeric");return
            body = {
                "client_request_id": request_id,
                "branch_id": int(self.app.cfg.get("branch_id", 1)),
                "counter_id": self.app.cfg.get("counter_id") or None,
                "customer_id": customer_id,
                "lines": self.lines,
                "discount": float(self.discount.get() or 0),
                "loyalty_redeem_points": loy_pts,
                "old_gold": self.old,
                "payment_cash": payments["cash"],
                "payment_card": payments["card"],
                "payment_upi": payments["upi"],
                "payment_credit": payments["credit"],
                "quote_id": self.quote.get("quote_id"),
                "quote_version": self.quote.get("quote_version"),
                "quote_hash": self.quote.get("quote_hash"),
            }
            upsert_pending_post({
                "request_id": request_id,
                "operation": "sale",
                "state": "submitting",
                "created_at": _utc_stamp(),
                "payload": body,
            })
            result = self.api.post("/api/sales", body)
            posted = True
            remove_pending_post(request_id)
            open_pdf(
                self.api.request("GET", f"/api/sales/{result['id']}/invoice.pdf"),
                f"{result['invoice_no']}.pdf",
            )
            messagebox.showinfo(
                "Sale completed",
                f"{result['invoice_no']}\n{money(result['total'])}",
                parent=self,
            )
            self.lines = []
            self.old = []
            self.quote = {}
            self.discount.set("0")
            self.loyalty_redeem.set("0")
            for value in self.pay.values():
                value.set("0")
            self.render()
            self.load_customers(reset=False)
            self.scan_entry.focus_set()
        except ApiError as exc:
            if exc.code == "OLD_GOLD_VALUE_MISMATCH" and self.app.user.get("role") in ("admin", "manager"):
                from tkinter import simpledialog as _sd
                remove_pending_post(body.get("client_request_id", ""))
                reason = _sd.askstring("Old-gold override", f"{exc}\n\nEnter override reason (min 3 chars):", parent=self)
                if reason and len(reason.strip()) >= 3:
                    body["allow_old_gold_override"] = True
                    body["old_gold_override_reason"] = reason.strip()
                    # Same request_id is safe: override fields are excluded from fingerprint.
                    try:
                        upsert_pending_post({"request_id": body["client_request_id"], "operation": "sale", "state": "submitting", "created_at": _utc_stamp(), "payload": body})
                        result = self.api.post("/api/sales", body)
                        posted = True
                        remove_pending_post(body["client_request_id"])
                        open_pdf(self.api.request("GET", f"/api/sales/{result['id']}/invoice.pdf"), f"{result['invoice_no']}.pdf")
                        messagebox.showinfo("Sale completed", f"{result['invoice_no']}\n{money(result['total'])}", parent=self)
                        self.lines = []; self.old = []; self.quote = {}; self.discount.set("0"); self.loyalty_redeem.set("0")
                        for value in self.pay.values(): value.set("0")
                        self.render(); self.load_customers(reset=False); self.scan_entry.focus_set()
                        return
                    except Exception as e2:self.app.error(e2);return
                self.app.error(exc);return
            if exc.code == "DISCOUNT_EXCEEDS_SUBTOTAL":
                remove_pending_post(body.get("client_request_id", ""))
                self.app.error(f"{exc}\n\nReduce discount/loyalty to within subtotal.");return
            if not posted and (exc.status == 0 or exc.status >= 500 or exc.code == "CONNECTIVITY_UNKNOWN"):
                upsert_pending_post({
                    "request_id": body.get("client_request_id", ""),
                    "operation": "sale",
                    "state": "outcome_unknown",
                    "created_at": _utc_stamp(),
                    "payload": body,
                    "error": str(exc),
                })
                messagebox.showwarning("Sale outcome unknown", "The server may have posted this invoice. Do not create a new sale. Open Pending Posts and reconcile this request.", parent=self)
            else:
                remove_pending_post(body.get("client_request_id", ""))
                self.app.error(exc)
        except Exception as exc:
            self.app.error(exc)
