from __future__ import annotations

import tkinter as tk
from tkinter import ttk

PALETTE = {
    "bg": "#F6F3EC",  # warm ivory — jewellery premium, 2026 calm luxury
    "surface": "#FFFFFF",
    "surface_alt": "#FBF9F4",
    "nav": "#14161D",  # deep charcoal-navy
    "nav_hover": "#232838",
    "nav_active": "#C9A227",  # champagne gold active
    "nav_active_text": "#14161D",
    "text": "#1A1C22",
    "muted": "#5B6472",  # 4.5:1 on white
    "border": "#E3DCCB",  # warm champagne border
    "border_cool": "#D8DDE3",
    "accent": "#8A642F",  # deep gold — white text passes 4.5:1
    "accent_dark": "#6E4E24",
    "gold": "#C9A227",  # decorative champagne (large text/icons only)
    "gold_soft": "#F2E8DA",
    "focus": "#2563EB",  # trust-blue keyboard ring
    "success": "#1F6B45",
    "success_bg": "#E7F4ED",
    "danger": "#9C2F2F",
    "danger_bg": "#F8EAEA",
    "warning": "#7A5410",
    "warning_bg": "#FBF1DD",
}

# Unicode glyphs (no emoji): geometric, stable across Windows fonts.
ICONS = {
    "overview": "◈",
    "billing": "▣",
    "estimation": "▤",
    "returns": "↩",
    "exchange": "⇄",
    "pending": "◷",
    "inventory": "▦",
    "parties": "◉",
    "purchases": "▧",
    "jobs": "✦",
    "approvals": "✔",
    "karigar": "⬢",
    "schemes": "⬣",
    "audit": "▩",
    "reports": "▥",
    "tally": "◬",
    "admin": "⚙",
}

FONTS = {
    "brand": ("Segoe UI Semibold", 20),
    "title": ("Segoe UI Semibold", 24),
    "page": ("Segoe UI Semibold", 22),
    "section": ("Segoe UI Semibold", 13),
    "body": ("Segoe UI", 10),
    "small": ("Segoe UI", 9),
    "micro": ("Segoe UI Semibold", 8),
    "metric": ("Segoe UI Semibold", 24),
    "money": ("Segoe UI Semibold", 17),
    "mono": ("Consolas", 10),
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
    style.configure("Surface.TLabel", background=PALETTE["surface"], foreground=PALETTE["text"], font=("Segoe UI", 10))
    style.configure("Muted.TLabel", background=PALETTE["bg"], foreground=PALETTE["muted"], font=("Segoe UI", 9))
    style.configure("SurfaceMuted.TLabel", background=PALETTE["surface"], foreground=PALETTE["muted"], font=("Segoe UI", 9))
    style.configure("Title.TLabel", background=PALETTE["bg"], foreground=PALETTE["text"], font=("Segoe UI Semibold", 24))
    style.configure("PageTitle.TLabel", background=PALETTE["bg"], foreground=PALETTE["text"], font=("Segoe UI Semibold", 22))
    style.configure("Section.TLabel", background=PALETTE["surface"], foreground=PALETTE["text"], font=("Segoe UI Semibold", 13))
    style.configure("CardTitle.TLabel", background=PALETTE["surface"], foreground=PALETTE["text"], font=("Segoe UI Semibold", 13))
    style.configure("Metric.TLabel", background=PALETTE["surface"], foreground=PALETTE["text"], font=("Segoe UI Semibold", 24))
    style.configure("Money.TLabel", background=PALETTE["surface"], foreground=PALETTE["text"], font=("Segoe UI Semibold", 17))
    style.configure("HeroTitle.TLabel", background=PALETTE["nav"], foreground="#FFFFFF", font=("Segoe UI Semibold", 20))
    style.configure("HeroSub.TLabel", background=PALETTE["nav"], foreground="#C9CDD6", font=("Segoe UI", 10))
    style.configure("NavSection.TLabel", background=PALETTE["nav"], foreground="#8A93A6", font=("Segoe UI Semibold", 8))
    style.configure("NavBrand.TLabel", background=PALETTE["nav"], foreground="#FFFFFF", font=("Segoe UI Semibold", 20))
    style.configure("NavMuted.TLabel", background=PALETTE["nav"], foreground="#AEB6C6", font=("Segoe UI", 9))
    style.configure("NavUser.TLabel", background=PALETTE["nav"], foreground="#E5E7EB", font=("Segoe UI", 9))

    style.configure("TButton", font=("Segoe UI Semibold", 10), padding=(14, 11), focuscolor=PALETTE["focus"])
    style.configure("Primary.TButton", foreground="#FFFFFF", background=PALETTE["accent"], borderwidth=0, padding=(16, 12), focuscolor=PALETTE["focus"])
    style.map("Primary.TButton",
              background=[("disabled", "#C9CDD3"), ("pressed", PALETTE["accent_dark"]), ("active", PALETTE["accent_dark"])],
              foreground=[("disabled", "#6B7280")],
              focuscolor=[("focus", PALETTE["focus"])])
    style.configure("Secondary.TButton", foreground=PALETTE["text"], background=PALETTE["surface"], bordercolor=PALETTE["border"], padding=(14, 11), focuscolor=PALETTE["focus"])
    style.map("Secondary.TButton",
              background=[("disabled", "#EDEFF2"), ("active", "#EDEFF2")],
              foreground=[("disabled", "#8A94A3")])
    style.configure("Danger.TButton", foreground="#FFFFFF", background=PALETTE["danger"], borderwidth=0, padding=(14, 11), focuscolor=PALETTE["focus"])
    style.map("Danger.TButton", background=[("disabled", "#C9CDD3"), ("active", "#7E2424"), ("pressed", "#7E2424")])
    style.configure("Nav.TButton", foreground="#D8DCE3", background=PALETTE["nav"], borderwidth=0, anchor="w", font=("Segoe UI", 10), padding=(14, 10), focuscolor=PALETTE["focus"])
    style.map("Nav.TButton", background=[("active", PALETTE["nav_hover"]), ("focus", PALETTE["nav_hover"])], foreground=[("active", "#FFFFFF"), ("focus", "#FFFFFF")])
    style.configure("NavActive.TButton", foreground=PALETTE["nav_active_text"], background=PALETTE["nav_active"], borderwidth=0, anchor="w", font=("Segoe UI Semibold", 10), padding=(14, 10))
    style.map("NavActive.TButton", background=[("active", "#D4AF37"), ("pressed", "#B8941F"), ("focus", "#D4AF37")])

    style.configure("TEntry", fieldbackground=PALETTE["surface"], foreground=PALETTE["text"], bordercolor=PALETTE["border"], lightcolor=PALETTE["focus"], darkcolor=PALETTE["border"], padding=10, focuscolor=PALETTE["focus"])
    style.map("TEntry", bordercolor=[("focus", PALETTE["focus"])], lightcolor=[("focus", PALETTE["focus"])])
    style.configure("TCombobox", fieldbackground=PALETTE["surface"], foreground=PALETTE["text"], padding=9, focuscolor=PALETTE["focus"])
    style.map("TCombobox", bordercolor=[("focus", PALETTE["focus"])], fieldbackground=[("disabled", "#EDEFF2")])
    # Tabular numbers prevent money/weight layout shift; taller rows meet 44px touch guidance.
    style.configure("Treeview", background=PALETTE["surface"], fieldbackground=PALETTE["surface"], foreground=PALETTE["text"], rowheight=36, borderwidth=0, font=("Segoe UI", 10))
    style.configure("Treeview.Heading", background="#EDEFF2", foreground="#3A4354", font=("Segoe UI Semibold", 9), relief="flat", padding=(8, 10))
    style.map("Treeview", background=[("selected", "#E4D3B8"), ("selected", "#E4D3B8")], foreground=[("selected", PALETTE["text"])])
    style.map("Treeview.Heading", background=[("active", "#E0E4E9")])

    style.configure("TNotebook", background=PALETTE["bg"], borderwidth=0)
    style.configure("TNotebook.Tab", background="#E9EAED", foreground=PALETTE["muted"], padding=(14, 8), font=("Segoe UI", 9))
    style.map("TNotebook.Tab", background=[("selected", PALETTE["surface"])], foreground=[("selected", PALETTE["text"])])
    style.configure("TLabelframe", background=PALETTE["surface"], bordercolor=PALETTE["border"], relief="solid")
    style.configure("TLabelframe.Label", background=PALETTE["surface"], foreground=PALETTE["muted"], font=("Segoe UI Semibold", 9))
    style.configure("TSeparator", background=PALETTE["border"])
    return style


def card(parent, padding=16, **pack_kwargs) -> ttk.Frame:
    frame = ttk.Frame(parent, style="Surface.TFrame", padding=padding, borderwidth=1, relief="solid")
    try:
        frame.configure(bordercolor=PALETTE["border"])
    except Exception:
        pass
    if pack_kwargs:
        frame.pack(**pack_kwargs)
    return frame


def hero_card(parent) -> tk.Frame:
    """Deep-navy hero banner with gold rule — 2026 premium dashboard header."""
    outer = tk.Frame(parent, bg=PALETTE["nav"], highlightthickness=0, borderwidth=0)
    rule = tk.Frame(outer, bg=PALETTE["gold"], height=3)
    rule.pack(side="bottom", fill="x")
    return outer


def kpi_card(parent, icon: str, label: str):
    """KPI card returning (frame, value_var, note_var) with icon + tabular value."""
    f = card(parent, 16)
    top = ttk.Frame(f, style="Surface.TFrame")
    top.pack(fill="x")
    tk.Label(top, text=icon, bg=PALETTE["surface"], fg=PALETTE["accent"], font=("Segoe UI Semibold", 14)).pack(side="left")
    ttk.Label(top, text=label.upper(), style="SurfaceMuted.TLabel", font=("Segoe UI Semibold", 8)).pack(side="left", padx=(8, 0))
    val = tk.StringVar(value="—")
    tk.Label(f, textvariable=val, bg=PALETTE["surface"], fg=PALETTE["text"], font=("Segoe UI Semibold", 24)).pack(anchor="w", pady=(8, 2))
    note = tk.StringVar(value="")
    ttk.Label(f, textvariable=note, style="SurfaceMuted.TLabel", font=("Segoe UI", 8)).pack(anchor="w")
    return f, val, note


def status_pill(parent, text: str, kind: str = "neutral") -> tk.Label:
    colors = {
        "success": (PALETTE["success_bg"], PALETTE["success"]),
        "danger": (PALETTE["danger_bg"], PALETTE["danger"]),
        "warning": (PALETTE["warning_bg"], PALETTE["warning"]),
        "neutral": ("#ECEEF1", PALETTE["muted"]),
        "accent": (PALETTE["gold_soft"], PALETTE["accent_dark"]),
        "gold": (PALETTE["gold_soft"], PALETTE["accent_dark"]),
    }
    bg, fg = colors.get(kind, colors["neutral"])
    return tk.Label(parent, text=text, bg=bg, fg=fg, font=("Segoe UI Semibold", 9), padx=9, pady=4)


def nav_badge(parent, text: str) -> tk.Label:
    return tk.Label(parent, text=text, bg=PALETTE["danger"], fg="#FFFFFF", font=("Segoe UI Semibold", 8), padx=6, pady=1)


def stepper(parent, steps: list[tuple[str, str]], active: int):
    """Horizontal step indicator: [(icon,label)] with active index. Returns frame."""
    bar = ttk.Frame(parent, style="Surface.TFrame")
    bar.pack(fill="x", pady=(0, 10))
    for i, (icon, label) in enumerate(steps):
        done = i < active
        cur = i == active
        bg = PALETTE["accent"] if cur else (PALETTE["success"] if done else "#E8E2D2")
        fg = "#FFFFFF" if (cur or done) else PALETTE["muted"]
        cell = ttk.Frame(bar, style="Surface.TFrame")
        cell.pack(side="left", fill="x", expand=True)
        badge = tk.Label(cell, text=f" {icon} {i+1} ", bg=bg, fg=fg, font=("Segoe UI Semibold", 9), padx=6, pady=3)
        badge.pack(side="left")
        ttk.Label(cell, text=f" {label}", style="Surface.TLabel" if cur else "SurfaceMuted.TLabel", font=("Segoe UI Semibold", 9) if cur else ("Segoe UI", 9)).pack(side="left")
        if i < len(steps) - 1:
            tk.Frame(cell, bg=PALETTE["border"], width=12, height=2).pack(side="left", padx=6)
    return bar


def divider(parent) -> tk.Frame:
    return tk.Frame(parent, height=1, bg=PALETTE["border"])
