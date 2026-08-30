from __future__ import annotations

import uuid
import tkinter as tk
from tkinter import ttk

from .main import Page, form_dialog, money, open_pdf
from .ui_theme import card, divider, status_pill


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
        "tag_no": 120,
        "description": 180,
        "metal": 80,
        "purity": 70,
        "net_weight": 92,
        "metal_rate": 105,
        "metal_value": 115,
        "wastage_percent": 92,
        "wastage_value": 115,
        "making_charge": 105,
        "stone_value": 95,
        "discount": 95,
        "taxable": 110,
        "gst_amount": 95,
        "line_total": 115,
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
            "Scan a tag, verify the complete jewellery calculation, accept payment and post one atomic invoice.",
        )

        scan_card = card(self, 12)
        scan_card.pack(fill="x", pady=(0, 10))
        top = ttk.Frame(scan_card, style="Surface.TFrame")
        top.pack(fill="x")
        ttk.Label(
            top,
            text="SCAN BARCODE / TAG",
            style="SurfaceMuted.TLabel",
            font=("Segoe UI Semibold", 8),
        ).pack(side="left")
        status_pill(top, "Ready for scanner", "success").pack(side="right")
        self.scan = tk.StringVar()
        self.scan_entry = ttk.Entry(scan_card, textvariable=self.scan, font=("Segoe UI Semibold", 14))
        self.scan_entry.pack(fill="x", pady=(6, 0), ipady=4)
        self.scan_entry.bind("<Return>", self.add_scan)

        pan = ttk.Panedwindow(self, orient="horizontal")
        pan.pack(fill="both", expand=True)
        left = ttk.Frame(pan)
        right = ttk.Frame(pan)
        pan.add(left, weight=7)
        pan.add(right, weight=3)

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
        ttk.Label(
            line_card,
            textvariable=self.calc_text,
            style="Surface.TLabel",
            justify="left",
            wraplength=980,
        ).pack(fill="x", anchor="w", pady=(4, 0))

        summary = card(right, 14)
        summary.pack(fill="both", expand=True, padx=(6, 0))
        ttk.Label(summary, text="Customer & payment", style="Section.TLabel").pack(anchor="w")

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
        ttk.Label(summary, textvariable=self.discount_hint, style="SurfaceMuted.TLabel").pack(anchor="w", pady=(2, 0))
        self.discount.trace_add("write", self._schedule_discount_requote)

        oldrow = ttk.Frame(summary, style="Surface.TFrame")
        oldrow.pack(fill="x", pady=(7, 4))
        ttk.Button(oldrow, text="Add old gold", style="Secondary.TButton", command=self.old_gold).pack(side="left")
        self.old_label = tk.StringVar(value="₹0.00")
        ttk.Label(oldrow, textvariable=self.old_label, style="Surface.TLabel", font=("Segoe UI Semibold", 10)).pack(side="right")

        divider(summary).pack(fill="x", pady=7)
        self.totals: dict[str, tk.StringVar] = {}
        self._summary_row(summary, "subtotal", "Subtotal")
        self._summary_row(summary, "discount", "Invoice discount")
        self._summary_row(summary, "taxable", "Taxable value")
        self._summary_row(summary, "gst", "GST")
        self._summary_row(summary, "round_off", "Round-off")
        self._summary_row(summary, "total", "Invoice total", emphasis=True)
        self._summary_row(summary, "payable", "Amount due", emphasis=True)

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
        for n, (key, label) in enumerate((("cash", "Cash"), ("card", "Card"), ("upi", "UPI"), ("credit", "Credit"))):
            row, col = divmod(n, 2)
            cell = ttk.Frame(pay_grid, style="Surface.TFrame")
            cell.grid(row=row, column=col, sticky="ew", padx=(0 if col == 0 else 5, 5 if col == 0 else 0), pady=2)
            ttk.Label(cell, text=label, style="SurfaceMuted.TLabel").pack(anchor="w")
            var = tk.StringVar(value="0")
            self.pay[key] = var
            ttk.Entry(cell, textvariable=var).pack(fill="x")
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
        ttk.Button(
            summary,
            text="COMPLETE SALE & PRINT",
            style="Primary.TButton",
            command=self.checkout,
        ).pack(fill="x", ipady=6, pady=(5, 0))
        ttk.Label(
            summary,
            text="Scanner + Enter adds a tag. Delete removes the selected line.",
            style="SurfaceMuted.TLabel",
            wraplength=340,
        ).pack(anchor="w", pady=(6, 0))

        self.render()
        self.scan_entry.focus_set()

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
        ttk.Label(row, text=label, style="SurfaceMuted.TLabel").pack(side="left")
        var = tk.StringVar(value="₹0.00")
        self.totals[key] = var
        ttk.Label(
            row,
            textvariable=var,
            style="Money.TLabel" if emphasis else "Surface.TLabel",
            font=None if emphasis else ("Segoe UI Semibold", 10),
        ).pack(side="right")

    def load_customers(self):
        try:
            self.customers = self.api.get("/api/customers")
            self.customer["values"] = ["Walk-in Customer"] + [
                f"{x['name']} — {x.get('phone') or ''} [#{x['id']}]" for x in self.customers
            ]
            self.customer.current(0)
        except Exception:
            pass

    def add_scan(self, event=None):
        code = self.scan.get().strip()
        self.scan.set("")
        if not code:
            return
        try:
            item = self.api.get(f"/api/items/barcode/{code}")
        except Exception as exc:
            self.app.error(exc)
            return
        if item["status"] != "in_stock":
            self.app.error(f"{item['tag_no']} is {item['status']}")
            return
        if any(x["item_id"] == item["id"] for x in self.lines):
            self.app.error(f"{item['tag_no']} is already on this invoice")
            return
        self.lines.append({"item_id": item["id"]})
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
        raw = self.discount.get().strip()
        try:
            value = float(raw or 0)
            if value < 0:
                raise ValueError
        except ValueError:
            self.discount_hint.set("Enter a non-negative numeric discount.")
            return
        self.discount_hint.set("Discount applied to the live quote.")
        if self.lines:
            self.requote(show_error=False)

    def requote(self, show_error=True):
        if not self.lines:
            self.quote = {}
            self.render()
            return
        try:
            discount = float(self.discount.get().strip() or 0)
            if discount < 0:
                raise ValueError("Invoice discount cannot be negative")
        except ValueError as exc:
            if show_error:
                self.app.error(exc)
            return
        try:
            self.quote = self.api.post(
                "/api/sales/quote",
                {"lines": self.lines, "discount": discount, "old_gold": self.old},
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
                ("gross_weight", "Gross weight"),
                ("deduction_percent", "Deduction %"),
                ("rate", "Rate / g"),
                ("value", "Exchange value"),
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
        try:
            for key in ("gross_weight", "deduction_percent", "rate", "value"):
                data[key] = float(data[key] or 0)
            if not data["value"]:
                data["value"] = data["gross_weight"] * (1 - data["deduction_percent"] / 100) * data["rate"]
            self.old.append(data)
            self.requote()
        except ValueError:
            self.app.error("Old-gold values must be numeric")

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
            return
        self.requote()
        if not self.quote:
            return
        try:
            index = self.customer.current()
            customer_id = self.customers[index - 1]["id"] if index > 0 else None
            payments = {key: float(var.get() or 0) for key, var in self.pay.items()}
            body = {
                "client_request_id": str(uuid.uuid4()),
                "branch_id": int(self.app.cfg.get("branch_id", 1)),
                "counter_id": self.app.cfg.get("counter_id") or None,
                "customer_id": customer_id,
                "lines": self.lines,
                "discount": float(self.discount.get() or 0),
                "old_gold": self.old,
                "payment_cash": payments["cash"],
                "payment_card": payments["card"],
                "payment_upi": payments["upi"],
                "payment_credit": payments["credit"],
            }
            result = self.api.post("/api/sales", body)
            open_pdf(
                self.api.request("GET", f"/api/sales/{result['id']}/invoice.pdf"),
                f"{result['invoice_no']}.pdf",
            )
            from tkinter import messagebox

            messagebox.showinfo(
                "Sale completed",
                f"{result['invoice_no']}\n{money(result['total'])}",
                parent=self,
            )
            self.lines = []
            self.old = []
            self.quote = {}
            self.discount.set("0")
            for value in self.pay.values():
                value.set("0")
            self.render()
            self.scan_entry.focus_set()
        except Exception as exc:
            self.app.error(exc)
