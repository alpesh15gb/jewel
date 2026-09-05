from __future__ import annotations

import datetime as dt
import os
import tempfile
import uuid
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from .api import ApiError
from .config import remove_pending_post, upsert_pending_post
from .ui_theme import PALETTE, card, divider, status_pill


def _utc_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _money(value) -> str:
    try:
        return f"₹{float(value):,.2f}"
    except Exception:
        return "₹0.00"


def _open_pdf(data: bytes, name: str) -> None:
    path = Path(tempfile.gettempdir()) / name
    path.write_bytes(data)
    if os.name == "nt":
        os.startfile(str(path))
    else:
        webbrowser.open(path.as_uri())


class ReturnsPage(ttk.Frame):
    """Manager-facing item-level sales returns and GST credit-note workflow."""

    SALE_COLS = ("invoice_no", "business_date", "customer_name", "total", "status")
    LINE_COLS = ("tag_no", "description", "metal", "purity", "total", "returnable")
    RETURN_COLS = ("return_no", "invoice_no", "business_date", "customer_name", "total", "status")

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.api = app.api
        self.sale_id: int | None = None
        self.quote = None
        self.sale_rows: dict[str, dict] = {}
        self.return_rows: dict[str, dict] = {}
        self.search_var = tk.StringVar()
        self.sale_caption = tk.StringVar(value="Choose an invoice to begin a controlled item return.")
        self.return_total = tk.StringVar(value="₹0.00")
        self.refund_cash = tk.StringVar(value="0.00")
        self.refund_card = tk.StringVar(value="0.00")
        self.refund_upi = tk.StringVar(value="0.00")
        self.refund_credit = tk.StringVar(value="0.00")
        self.reason = tk.StringVar()
        self._build()
        self.refresh_sales()
        self.refresh_returns()

    def _heading(self, title: str, subtitle: str) -> None:
        head = ttk.Frame(self)
        head.pack(fill="x", pady=(0, 14))
        ttk.Label(head, text=title, style="PageTitle.TLabel").pack(anchor="w")
        ttk.Label(head, text=subtitle, style="Muted.TLabel").pack(anchor="w", pady=(3, 0))
        divider(self).pack(fill="x", pady=(0, 12))

    def _tree(self, parent, columns, widths, *, selectmode="browse"):
        tree = ttk.Treeview(parent, columns=columns, show="headings", selectmode=selectmode)
        for col in columns:
            tree.heading(col, text=col.replace("_", " ").title())
            tree.column(col, width=widths.get(col, 115), minwidth=70, anchor="e" if col in {"total"} else "w")
        scroll = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)
        return tree

    def _build(self) -> None:
        self._heading(
            "Returns & Credit Notes",
            "Return individual serialized tags against the original invoice with exact GST, stock and accounting reversal.",
        )

        top = ttk.Frame(self)
        top.pack(fill="both", expand=True)
        left = ttk.Frame(top)
        left.pack(side="left", fill="both", expand=True, padx=(0, 7))
        right = ttk.Frame(top, width=360)
        right.pack(side="left", fill="y", padx=(7, 0))
        right.pack_propagate(False)

        search_card = card(left, 14)
        search_card.pack(fill="x")
        ttk.Label(search_card, text="1  Find original invoice", style="Section.TLabel").pack(anchor="w")
        bar = ttk.Frame(search_card, style="Surface.TFrame")
        bar.pack(fill="x", pady=(10, 8))
        entry = ttk.Entry(bar, textvariable=self.search_var)
        entry.pack(side="left", fill="x", expand=True, ipady=3)
        entry.bind("<Return>", lambda _e: self.refresh_sales())
        ttk.Button(bar, text="Search", style="Secondary.TButton", command=self.refresh_sales).pack(side="left", padx=(8, 0))
        sales_box = ttk.Frame(search_card, style="Surface.TFrame", height=145)
        sales_box.pack(fill="x")
        sales_box.pack_propagate(False)
        self.sales_tree = self._tree(
            sales_box,
            self.SALE_COLS,
            {"invoice_no": 145, "business_date": 95, "customer_name": 170, "total": 100, "status": 80},
        )
        self.sales_tree.bind("<Double-1>", lambda _e: self.load_selected_sale())
        ttk.Button(search_card, text="Use selected invoice", style="Primary.TButton", command=self.load_selected_sale).pack(anchor="e", pady=(8, 0))

        item_card = card(left, 14)
        item_card.pack(fill="both", expand=True, pady=(12, 0))
        ttk.Label(item_card, text="2  Select returned tags", style="Section.TLabel").pack(anchor="w")
        ttk.Label(item_card, textvariable=self.sale_caption, style="SurfaceMuted.TLabel", wraplength=730).pack(anchor="w", pady=(3, 8))
        line_box = ttk.Frame(item_card, style="Surface.TFrame")
        line_box.pack(fill="both", expand=True)
        self.lines_tree = self._tree(
            line_box,
            self.LINE_COLS,
            {"tag_no": 125, "description": 230, "metal": 85, "purity": 70, "total": 105, "returnable": 90},
            selectmode="extended",
        )
        self.lines_tree.bind("<<TreeviewSelect>>", lambda _e: self.clear_quote())
        controls = ttk.Frame(item_card, style="Surface.TFrame")
        controls.pack(fill="x", pady=(10, 0))
        ttk.Button(controls, text="Select all returnable", style="Secondary.TButton", command=self.select_all_returnable).pack(side="left")
        ttk.Button(controls, text="Quote selected", style="Primary.TButton", command=self.quote_selected).pack(side="right")

        summary = card(right, 16)
        summary.pack(fill="x")
        ttk.Label(summary, text="Credit note", style="Section.TLabel").pack(anchor="w")
        ttk.Label(summary, text="RETURN TOTAL", style="SurfaceMuted.TLabel", font=("Segoe UI Semibold", 8)).pack(anchor="w", pady=(16, 2))
        ttk.Label(summary, textvariable=self.return_total, style="Metric.TLabel").pack(anchor="w")
        self.quote_status = ttk.Frame(summary, style="Surface.TFrame")
        self.quote_status.pack(fill="x", pady=(4, 12))
        self._set_quote_status("Select invoice items and quote", "warning")

        ttk.Label(summary, text="3  Refund split", style="Section.TLabel").pack(anchor="w", pady=(4, 8))
        for label, var in (
            ("Cash refund", self.refund_cash),
            ("Card / bank refund", self.refund_card),
            ("UPI refund", self.refund_upi),
            ("Customer account credit", self.refund_credit),
        ):
            ttk.Label(summary, text=label, style="SurfaceMuted.TLabel").pack(anchor="w", pady=(4, 2))
            ttk.Entry(summary, textvariable=var).pack(fill="x", ipady=2)
        ttk.Button(summary, text="Set full refund to cash", style="Secondary.TButton", command=self.full_cash).pack(fill="x", pady=(8, 10))

        ttk.Label(summary, text="Disposition (returned stock)", style="SurfaceMuted.TLabel").pack(anchor="w", pady=(2, 2))
        self.disposition = tk.StringVar(value="in_stock")
        ttk.Combobox(summary, textvariable=self.disposition, values=["in_stock","damaged","scrap"], state="readonly").pack(fill="x", ipady=2)
        ttk.Label(summary, text="in_stock = resaleable, damaged/scrap = quarantine.", style="SurfaceMuted.TLabel", wraplength=300).pack(anchor="w", pady=(2, 6))

        ttk.Label(summary, text="Return reason", style="SurfaceMuted.TLabel").pack(anchor="w", pady=(2, 2))
        ttk.Entry(summary, textvariable=self.reason).pack(fill="x", ipady=2)
        ttk.Label(
            summary,
            text="Posting restores selected tags to stock and creates an immutable credit note plus accounting reversal.",
            style="SurfaceMuted.TLabel",
            wraplength=300,
        ).pack(anchor="w", pady=(8, 10))
        ttk.Button(summary, text="POST CREDIT NOTE", style="Primary.TButton", command=self.post_return).pack(fill="x", ipady=5)

        recent = card(right, 14)
        recent.pack(fill="both", expand=True, pady=(12, 0))
        head = ttk.Frame(recent, style="Surface.TFrame")
        head.pack(fill="x", pady=(0, 7))
        ttk.Label(head, text="Recent credit notes", style="Section.TLabel").pack(side="left")
        ttk.Button(head, text="Refresh", style="Secondary.TButton", command=self.refresh_returns).pack(side="right")
        return_box = ttk.Frame(recent, style="Surface.TFrame")
        return_box.pack(fill="both", expand=True)
        self.returns_tree = self._tree(
            return_box,
            self.RETURN_COLS,
            {"return_no": 120, "invoice_no": 120, "business_date": 90, "customer_name": 150, "total": 95, "status": 75},
        )
        buttons = ttk.Frame(recent, style="Surface.TFrame")
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(buttons, text="Print", style="Secondary.TButton", command=self.print_selected_return).pack(side="left")
        ttk.Button(buttons, text="Cancel credit note", style="Danger.TButton", command=self.cancel_selected_return).pack(side="right")

    def _set_quote_status(self, text: str, kind: str) -> None:
        for widget in self.quote_status.winfo_children():
            widget.destroy()
        status_pill(self.quote_status, text, kind).pack(anchor="w")

    def _show_error(self, exc) -> None:
        self.app.error(exc)

    def refresh_sales(self) -> None:
        try:
            rows = self.api.get("/api/sales", q=self.search_var.get().strip(), limit=150)
        except Exception as exc:
            self._show_error(exc)
            return
        self.sale_rows.clear()
        self.sales_tree.delete(*self.sales_tree.get_children())
        for sale in rows:
            iid = str(sale["id"])
            self.sale_rows[iid] = sale
            self.sales_tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    sale.get("invoice_no", ""),
                    sale.get("business_date", ""),
                    sale.get("customer_name") or "Walk-in",
                    _money(sale.get("total", 0)),
                    sale.get("status", ""),
                ),
            )

    def load_selected_sale(self) -> None:
        selected = self.sales_tree.selection()
        if not selected:
            messagebox.showinfo("Returns", "Select the original invoice first.", parent=self)
            return
        self.sale_id = int(selected[0])
        try:
            quote = self.api.post(f"/api/sales/{self.sale_id}/return-quote", {"sale_item_ids": []})
        except Exception as exc:
            self._show_error(exc)
            return
        self.quote = None
        sale = quote.get("sale", {})
        customer = quote.get("customer") or {}
        self.sale_caption.set(
            f"Invoice {sale.get('invoice_no','')} · {sale.get('business_date','')} · "
            f"{customer.get('name') or 'Walk-in customer'} · Original total {_money(sale.get('total',0))}"
        )
        self.lines_tree.delete(*self.lines_tree.get_children())
        for line in quote.get("lines", []):
            state = "Yes" if line.get("returnable") else ("Already returned" if line.get("already_returned") else "No")
            tags = () if line.get("returnable") else ("disabled",)
            self.lines_tree.insert(
                "",
                "end",
                iid=str(line["sale_item_id"]),
                values=(line.get("tag_no", ""), line.get("description", ""), line.get("metal", ""), line.get("purity", ""), _money(line.get("total", 0)), state),
                tags=tags,
            )
        self.lines_tree.tag_configure("disabled", foreground=PALETTE["muted"])
        self.clear_quote()

    def select_all_returnable(self) -> None:
        eligible = []
        for iid in self.lines_tree.get_children():
            values = self.lines_tree.item(iid, "values")
            if values and values[-1] == "Yes":
                eligible.append(iid)
        self.lines_tree.selection_set(eligible)
        self.clear_quote()

    def selected_line_ids(self) -> list[int]:
        selected = []
        for iid in self.lines_tree.selection():
            values = self.lines_tree.item(iid, "values")
            if values and values[-1] == "Yes":
                selected.append(int(iid))
        return selected

    def clear_quote(self) -> None:
        self.quote = None
        self.return_total.set("₹0.00")
        self._set_quote_status("Quote required", "warning")

    def quote_selected(self) -> None:
        if not self.sale_id:
            messagebox.showinfo("Returns", "Choose an invoice first.", parent=self)
            return
        ids = self.selected_line_ids()
        if not ids:
            messagebox.showinfo("Returns", "Select one or more returnable tags.", parent=self)
            return
        try:
            quote = self.api.post(f"/api/sales/{self.sale_id}/return-quote", {"sale_item_ids": ids})
        except Exception as exc:
            self._show_error(exc)
            return
        self.quote = quote
        self.return_total.set(_money(quote.get("total", 0)))
        self._set_quote_status(f"{quote.get('selected_count', len(ids))} tag(s) · GST {_money(quote.get('gst',0))}", "success")
        try:has_refund = any(self._amount(v) for v in (self.refund_cash, self.refund_card, self.refund_upi, self.refund_credit))
        except ValueError:
            self._show_error(ValueError("Refund amounts must be numeric — reset to 0.00"))
            for v in (self.refund_cash, self.refund_card, self.refund_upi, self.refund_credit):
                try:v.set("0.00")
                except tk.TclError:pass
            has_refund = False
        if not has_refund:
            self.refund_cash.set(f"{float(quote.get('total',0)):.2f}")

    @staticmethod
    def _amount(var: tk.StringVar) -> float:
        try:
            return round(float(var.get().strip() or 0), 2)
        except (ValueError, tk.TclError):
            raise ValueError("Refund amounts must be numeric")

    def full_cash(self) -> None:
        if not self.quote:
            self.quote_selected()
            if not self.quote:
                return
        self.refund_cash.set(f"{float(self.quote.get('total',0)):.2f}")
        self.refund_card.set("0.00")
        self.refund_upi.set("0.00")
        self.refund_credit.set("0.00")

    def post_return(self) -> None:
        if not self.quote:
            self.quote_selected()
            if not self.quote:
                return
        ids = self.selected_line_ids()
        if not ids:
            return
        try:
            cash = self._amount(self.refund_cash)
            card = self._amount(self.refund_card)
            upi = self._amount(self.refund_upi)
            credit = self._amount(self.refund_credit)
        except ValueError as exc:
            self._show_error(exc)
            return
        total = round(float(self.quote.get("total", 0)), 2)
        if round(cash + card + upi + credit, 2) != total:
            messagebox.showerror("Refund split", f"Refunds must total {_money(total)}.", parent=self)
            return
        reason = self.reason.get().strip()
        if len(reason) < 3:
            messagebox.showerror("Return reason", "Enter a return reason of at least 3 characters.", parent=self)
            return
        if not messagebox.askyesno(
            "Post credit note",
            f"Return {len(ids)} serialized tag(s) for {_money(total)}?\n\nThis restores the selected tags to stock and posts the accounting reversal.",
            parent=self,
        ):
            return
        request_id = str(uuid.uuid4())
        payload = {
            "client_request_id": request_id,
            "sale_item_ids": ids,
            "refund_cash": cash,
            "refund_card": card,
            "refund_upi": upi,
            "refund_credit": credit,
            "reason": reason,
            "disposition": self.disposition.get().strip() or "in_stock",
        }
        upsert_pending_post({
            "request_id": request_id,
            "operation": "sale_return",
            "state": "submitting",
            "created_at": _utc_stamp(),
            "payload": {"sale_id": self.sale_id, **payload},
        })
        try:
            result = self.api.post(f"/api/sales/{self.sale_id}/return", payload)
            remove_pending_post(request_id)
        except ApiError as exc:
            if exc.status == 0 or exc.status >= 500 or exc.code == "CONNECTIVITY_UNKNOWN":
                upsert_pending_post({
                    "request_id": request_id,
                    "operation": "sale_return",
                    "state": "outcome_unknown",
                    "created_at": _utc_stamp(),
                    "payload": {"sale_id": self.sale_id, **payload},
                    "error": str(exc),
                })
                messagebox.showwarning("Return outcome unknown", "The server may have posted this credit note. Do not retry with a new request ID. Open Pending Posts and reconcile this request.", parent=self)
                return
            remove_pending_post(request_id)
            self._show_error(exc)
            return
        except Exception as exc:
            remove_pending_post(request_id)
            self._show_error(exc)
            return
        ret = result.get("return", result)
        rid = ret.get("id") or result.get("id")
        number = ret.get("return_no") or result.get("return_no") or "Credit note"
        messagebox.showinfo("Credit note posted", f"{number} posted successfully.", parent=self)
        self.reason.set("")
        for var in (self.refund_cash, self.refund_card, self.refund_upi, self.refund_credit):
            var.set("0.00")
        self.refresh_returns()
        self.refresh_sales()
        self.load_sale_after_return()
        if rid:
            try:
                _open_pdf(self.api.get(f"/api/returns/{rid}/credit-note.pdf"), f"{number}.pdf")
            except Exception:
                pass

    def load_sale_after_return(self) -> None:
        if not self.sale_id:
            return
        try:
            quote = self.api.post(f"/api/sales/{self.sale_id}/return-quote", {"sale_item_ids": []})
        except Exception:
            return
        self.lines_tree.delete(*self.lines_tree.get_children())
        for line in quote.get("lines", []):
            state = "Yes" if line.get("returnable") else ("Already returned" if line.get("already_returned") else "No")
            tags = () if line.get("returnable") else ("disabled",)
            self.lines_tree.insert("", "end", iid=str(line["sale_item_id"]), values=(line.get("tag_no", ""), line.get("description", ""), line.get("metal", ""), line.get("purity", ""), _money(line.get("total", 0)), state), tags=tags)
        self.lines_tree.tag_configure("disabled", foreground=PALETTE["muted"])
        self.clear_quote()

    def refresh_returns(self) -> None:
        try:
            rows = self.api.get("/api/returns", limit=200)
        except Exception as exc:
            self._show_error(exc)
            return
        self.return_rows.clear()
        self.returns_tree.delete(*self.returns_tree.get_children())
        for item in rows:
            iid = str(item["id"])
            self.return_rows[iid] = item
            self.returns_tree.insert("", "end", iid=iid, values=(item.get("return_no", ""), item.get("invoice_no", ""), item.get("business_date", ""), item.get("customer_name") or "Walk-in", _money(item.get("total", 0)), item.get("status", "")))

    def selected_return(self):
        selection = self.returns_tree.selection()
        if not selection:
            messagebox.showinfo("Credit notes", "Select a credit note first.", parent=self)
            return None, None
        iid = selection[0]
        return int(iid), self.return_rows.get(iid, {})

    def print_selected_return(self) -> None:
        rid, row = self.selected_return()
        if not rid:
            return
        try:
            data = self.api.request("GET", f"/api/returns/{rid}/credit-note.pdf")
            if isinstance(data, dict):
                raise ValueError(f"Server returned JSON instead of PDF: {data}")
            _open_pdf(bytes(data), f"{row.get('return_no','credit-note')}.pdf")
        except Exception as exc:
            self._show_error(exc)

    def cancel_selected_return(self) -> None:
        rid, row = self.selected_return()
        if not rid:
            return
        if row.get("status") == "cancelled":
            messagebox.showinfo("Credit notes", "This credit note is already cancelled.", parent=self)
            return
        reason = simpledialog.askstring("Cancel credit note", "Reason for cancelling this credit note:", parent=self)
        if not reason:
            return
        if len(reason.strip()) < 3:
            messagebox.showerror("Cancel credit note", "Cancellation reason must be at least 3 characters.", parent=self)
            return
        if not messagebox.askyesno("Cancel credit note", f"Cancel {row.get('return_no','this credit note')} and reverse its stock/accounting effects?", parent=self):
            return
        try:
            self.api.post(f"/api/returns/{rid}/cancel", {"reason": reason.strip()})
            messagebox.showinfo("Credit note", "Credit note cancelled and reversed.", parent=self)
            self.refresh_returns()
            if self.sale_id:
                self.load_sale_after_return()
        except Exception as exc:
            self._show_error(exc)
