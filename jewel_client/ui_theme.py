from __future__ import annotations

import tkinter as tk
from tkinter import ttk

PALETTE = {
    "bg": "#F4F5F7",
    "surface": "#FFFFFF",
    "surface_alt": "#FAFAFB",
    "nav": "#151821",
    "nav_hover": "#222735",
    "nav_active": "#B4874A",
    "text": "#1C2430",
    "muted": "#6B7280",
    "border": "#E2E5E9",
    "accent": "#A8783F",
    "accent_dark": "#805B30",
    "success": "#247A52",
    "danger": "#A33A3A",
    "warning": "#9A6A22",
}


def apply_theme(root: tk.Misc) -> ttk.Style:
    root.configure(bg=PALETTE["bg"])
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure("TFrame", background=PALETTE["bg"])
    style.configure("Surface.TFrame", background=PALETTE["surface"])
    style.configure("Nav.TFrame", background=PALETTE["nav"])
    style.configure("TLabel", background=PALETTE["bg"], foreground=PALETTE["text"], font=("Segoe UI", 10))
    style.configure("Surface.TLabel", background=PALETTE["surface"], foreground=PALETTE["text"])
    style.configure("Muted.TLabel", background=PALETTE["bg"], foreground=PALETTE["muted"])
    style.configure("SurfaceMuted.TLabel", background=PALETTE["surface"], foreground=PALETTE["muted"])
    style.configure("Title.TLabel", background=PALETTE["bg"], foreground=PALETTE["text"], font=("Segoe UI Semibold", 22))
    style.configure("PageTitle.TLabel", background=PALETTE["bg"], foreground=PALETTE["text"], font=("Segoe UI Semibold", 21))
    style.configure("Section.TLabel", background=PALETTE["surface"], foreground=PALETTE["text"], font=("Segoe UI Semibold", 12))
    style.configure("Metric.TLabel", background=PALETTE["surface"], foreground=PALETTE["text"], font=("Segoe UI Semibold", 22))
    style.configure("Money.TLabel", background=PALETTE["surface"], foreground=PALETTE["text"], font=("Segoe UI Semibold", 16))
    style.configure("NavBrand.TLabel", background=PALETTE["nav"], foreground="#FFFFFF", font=("Segoe UI Semibold", 18))
    style.configure("NavMuted.TLabel", background=PALETTE["nav"], foreground="#9CA3AF", font=("Segoe UI", 9))
    style.configure("NavUser.TLabel", background=PALETTE["nav"], foreground="#E5E7EB", font=("Segoe UI", 9))

    style.configure("TButton", font=("Segoe UI Semibold", 10), padding=(12, 8))
    style.configure("Primary.TButton", foreground="#FFFFFF", background=PALETTE["accent"], borderwidth=0, padding=(14, 10))
    style.map("Primary.TButton", background=[("active", PALETTE["accent_dark"]), ("pressed", PALETTE["accent_dark"])])
    style.configure("Secondary.TButton", foreground=PALETTE["text"], background=PALETTE["surface"], bordercolor=PALETTE["border"], padding=(12, 8))
    style.map("Secondary.TButton", background=[("active", "#F1F2F4")])
    style.configure("Danger.TButton", foreground="#FFFFFF", background=PALETTE["danger"], borderwidth=0, padding=(12, 8))
    style.map("Danger.TButton", background=[("active", "#842E2E")])
    style.configure("Nav.TButton", foreground="#D8DCE3", background=PALETTE["nav"], borderwidth=0, anchor="w", font=("Segoe UI", 10), padding=(16, 11))
    style.map("Nav.TButton", background=[("active", PALETTE["nav_hover"])], foreground=[("active", "#FFFFFF")])
    style.configure("NavActive.TButton", foreground="#FFFFFF", background=PALETTE["nav_active"], borderwidth=0, anchor="w", font=("Segoe UI Semibold", 10), padding=(16, 11))
    style.map("NavActive.TButton", background=[("active", PALETTE["nav_active"]), ("pressed", PALETTE["nav_active"])])

    style.configure("TEntry", fieldbackground=PALETTE["surface"], foreground=PALETTE["text"], bordercolor=PALETTE["border"], lightcolor=PALETTE["border"], darkcolor=PALETTE["border"], padding=8)
    style.configure("TCombobox", fieldbackground=PALETTE["surface"], foreground=PALETTE["text"], padding=7)
    style.configure("Treeview", background=PALETTE["surface"], fieldbackground=PALETTE["surface"], foreground=PALETTE["text"], rowheight=31, borderwidth=0, font=("Segoe UI", 9))
    style.configure("Treeview.Heading", background="#F0F1F3", foreground="#4B5563", font=("Segoe UI Semibold", 9), relief="flat", padding=(8, 8))
    style.map("Treeview", background=[("selected", "#E9DCCB")], foreground=[("selected", PALETTE["text"])])
    style.map("Treeview.Heading", background=[("active", "#E7E9EC")])

    style.configure("TNotebook", background=PALETTE["bg"], borderwidth=0)
    style.configure("TNotebook.Tab", background="#E9EAED", foreground=PALETTE["muted"], padding=(14, 8), font=("Segoe UI", 9))
    style.map("TNotebook.Tab", background=[("selected", PALETTE["surface"])], foreground=[("selected", PALETTE["text"])])
    style.configure("TLabelframe", background=PALETTE["surface"], bordercolor=PALETTE["border"], relief="solid")
    style.configure("TLabelframe.Label", background=PALETTE["surface"], foreground=PALETTE["muted"], font=("Segoe UI Semibold", 9))
    style.configure("TSeparator", background=PALETTE["border"])
    return style


def card(parent, padding=16, **pack_kwargs) -> ttk.Frame:
    frame = ttk.Frame(parent, style="Surface.TFrame", padding=padding)
    if pack_kwargs:
        frame.pack(**pack_kwargs)
    return frame


def status_pill(parent, text: str, kind: str = "neutral") -> tk.Label:
    colors = {
        "success": ("#E7F4ED", PALETTE["success"]),
        "danger": ("#F8EAEA", PALETTE["danger"]),
        "warning": ("#FBF1DD", PALETTE["warning"]),
        "neutral": ("#ECEEF1", PALETTE["muted"]),
        "accent": ("#F2E8DA", PALETTE["accent_dark"]),
    }
    bg, fg = colors.get(kind, colors["neutral"])
    return tk.Label(parent, text=text, bg=bg, fg=fg, font=("Segoe UI Semibold", 9), padx=9, pady=4)


def divider(parent) -> tk.Frame:
    return tk.Frame(parent, height=1, bg=PALETTE["border"])
