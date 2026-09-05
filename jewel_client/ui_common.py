"""Shared Tk helpers used by all JewelPOS pages.

Extracted from jewel_client.main so billing_page and main no longer import
from each other (which caused a circular import when unifying the billing
screen). main.py re-exports these names for backwards compatibility.
"""
from __future__ import annotations

import os
import tempfile
import webbrowser
from pathlib import Path
from typing import Any
import tkinter as tk
from tkinter import ttk

from .ui_theme import PALETTE, divider


def money(v: Any) -> str:
    try:
        return f"₹{float(v):,.2f}"
    except Exception:
        return "₹0.00"


def open_pdf(data: bytes, name: str):
    p = Path(tempfile.gettempdir()) / name
    p.write_bytes(data)
    if os.name == "nt":
        os.startfile(str(p))  # type: ignore[attr-defined]
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
    try:
        screen_h = max(480, d.winfo_screenheight())
    except Exception:
        screen_h = 800
    desired_h = 190 + len(fields) * 44
    dialog_h = min(max(460, desired_h), max(460, screen_h - 120), 760)
    center(d, 620, dialog_h)
    d.minsize(520, min(460, dialog_h))
    d.transient(parent)
    d.grab_set()
    d.resizable(True, True)

    shell = ttk.Frame(d, style="Surface.TFrame", padding=22)
    shell.pack(fill="both", expand=True, padx=18, pady=18)
    ttk.Label(shell, text=title, style="Section.TLabel", font=("Segoe UI Semibold", 15)).pack(anchor="w", pady=(0, 4))
    ttk.Label(shell, text="Fields marked * are required. Tab moves forward, Shift+Tab moves back.", style="SurfaceMuted.TLabel", wraplength=540, justify="left").pack(anchor="w", pady=(0, 10))

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

    vars_ = {}
    result = {"value": None}
    first_widget = None
    for i, spec in enumerate(fields):
        key, label = spec[0], spec[1]
        values = spec[2] if len(spec) > 2 else None
        v = tk.StringVar(value=str(defaults.get(key, "") if defaults.get(key) is not None else ""))
        vars_[key] = v
        # Required indicator: red asterisk, label stays readable (not color-only).
        lab_frame = ttk.Frame(form, style="Surface.TFrame")
        lab_frame.grid(row=i, column=0, sticky="w", pady=6)
        base_label = label[:-1].rstrip() if label.rstrip().endswith("*") else label
        ttk.Label(lab_frame, text=base_label, style="SurfaceMuted.TLabel").pack(side="left")
        if label.rstrip().endswith("*"):
            tk.Label(lab_frame, text=" *", bg=PALETTE["surface"], fg=PALETTE["danger"], font=("Segoe UI Semibold", 10)).pack(side="left")
        widget = ttk.Combobox(form, textvariable=v, values=values, state="readonly") if values else ttk.Entry(form, textvariable=v)
        widget.grid(row=i, column=1, sticky="ew", padx=(16, 0), pady=6, ipady=2)
        # Only apply a silent default when the caller did not supply one AND
        # the field explicitly provides choices. Callers should still pass
        # explicit defaults for Metal/Purity/Making so the choice is deliberate.
        if values and not v.get():
            v.set(values[0])
        if first_widget is None:
            first_widget = widget
    form.columnconfigure(1, weight=1)

    def save():
        result["value"] = {k: v.get().strip() for k, v in vars_.items()}
        d.destroy()

    divider(shell).pack(fill="x", pady=(12, 10))
    buttons = ttk.Frame(shell, style="Surface.TFrame")
    buttons.pack(fill="x")
    ttk.Label(buttons, text="Ctrl+Enter saves  •  Esc cancels", style="SurfaceMuted.TLabel").pack(side="left")
    cancel_button = ttk.Button(buttons, text="Cancel", style="Secondary.TButton", command=d.destroy)
    cancel_button.pack(side="right")
    save_button = ttk.Button(buttons, text="Save", style="Primary.TButton", command=save)
    save_button.pack(side="right", padx=(0, 8))
    d.save_button = save_button  # type: ignore[attr-defined]
    d.cancel_button = cancel_button  # type: ignore[attr-defined]
    d.form_canvas = canvas  # type: ignore[attr-defined]

    def on_wheel(event):
        try:
            if canvas.bbox("all") and canvas.winfo_height() < form.winfo_reqheight():
                canvas.yview_scroll(-1 if getattr(event, "delta", 0) > 0 else 1, "units")
        except Exception:
            pass
        return "break"

    d.bind("<MouseWheel>", on_wheel)
    # Linux: Button-4/5 are wheel up/down
    d.bind("<Button-4>", lambda _e: (canvas.yview_scroll(-1, "units"), "break")[1] if canvas.bbox("all") else None)
    d.bind("<Button-5>", lambda _e: (canvas.yview_scroll(1, "units"), "break")[1] if canvas.bbox("all") else None)
    d.bind("<Escape>", lambda _e: d.destroy())
    d.bind("<Control-Return>", lambda _e: save())
    if first_widget is not None:
        first_widget.focus_set()
    parent.wait_window(d)
    return result["value"]


class Page(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.api = app.api

    def heading(self, title, sub=""):
        head = ttk.Frame(self)
        head.pack(fill="x", pady=(0, 6))
        row = ttk.Frame(head)
        row.pack(fill="x")
        tk.Label(row, text="◆", bg="#F6F3EC", fg="#C9A227", font=("Segoe UI Semibold", 12)).pack(side="left", padx=(0, 8))
        ttk.Label(row, text=title, style="PageTitle.TLabel").pack(side="left")
        if sub:
            ttk.Label(head, text=sub, style="Muted.TLabel", wraplength=900).pack(anchor="w", pady=(4, 0))
        divider(self).pack(fill="x", pady=(8, 12))

    def empty_hint(self, text: str):
        ttk.Label(self, text=text, style="Muted.TLabel", wraplength=900).pack(anchor="w", pady=(6, 0))

    def tree(self, parent, cols, widths=None):
        widths = widths or {}
        t = ttk.Treeview(parent, columns=cols, show="headings", selectmode="browse")
        for c in cols:
            t.heading(c, text=c.replace("_", " ").title())
            t.column(
                c,
                width=widths.get(c, 115),
                minwidth=70,
                anchor="e" if any(x in c for x in ("weight", "amount", "total", "rate", "gst", "cost", "paid", "balance", "debit", "credit")) else "w",
            )
        try:
            t.tag_configure("odd", background="#FFFFFF")
            t.tag_configure("even", background="#FAF7F0")
        except Exception:pass
        # Both scrollbars: many tables (purchases, trial balance) overflow horizontally at 1366px.
        ybar = ttk.Scrollbar(parent, orient="vertical", command=t.yview)
        xbar = ttk.Scrollbar(parent, orient="horizontal", command=t.xview)
        t.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        ybar.pack(side="right", fill="y")
        xbar.pack(side="bottom", fill="x")
        t.pack(side="left", fill="both", expand=True)
        return t

    def toolbar(self):
        f = ttk.Frame(self)
        f.pack(fill="x", pady=(0, 10))
        return f
