from pathlib import Path

path = Path("scripts/apply_ui_redesign.py")
text = path.read_text(encoding="utf-8")
start = text.index("FORM_DIALOG = r'''def form_dialog(parent, title, fields, defaults=None):")
end_marker = "text = between(text, \"def form_dialog(parent, title, fields, defaults=None):\", \"class LoginDialog\", FORM_DIALOG)"
end = text.index(end_marker, start)
replacement = r'''FORM_DIALOG = r\'''def form_dialog(parent, title, fields, defaults=None):
    defaults = defaults or {}
    d = tk.Toplevel(parent)
    d.title(title)
    d.configure(bg=PALETTE["bg"])
    screen_h = max(480, d.winfo_screenheight())
    desired_h = 190 + len(fields) * 44
    dialog_h = min(max(460, desired_h), max(460, screen_h - 120), 760)
    center(d, 620, dialog_h)
    d.minsize(520, min(460, dialog_h)); d.transient(parent); d.grab_set(); d.resizable(True, True)

    shell = ttk.Frame(d, style="Surface.TFrame", padding=22)
    shell.pack(fill="both", expand=True, padx=18, pady=18)
    ttk.Label(shell, text=title, style="Section.TLabel", font=("Segoe UI Semibold", 15)).pack(anchor="w", pady=(0, 12))

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

    vars_ = {}; result = {"value": None}; first_widget = None
    for i, spec in enumerate(fields):
        key, label = spec[0], spec[1]; values = spec[2] if len(spec) > 2 else None
        v = tk.StringVar(value=str(defaults.get(key, "") if defaults.get(key) is not None else "")); vars_[key] = v
        ttk.Label(form, text=label, style="SurfaceMuted.TLabel").grid(row=i, column=0, sticky="w", pady=5)
        widget = ttk.Combobox(form, textvariable=v, values=values, state="readonly") if values else ttk.Entry(form, textvariable=v)
        widget.grid(row=i, column=1, sticky="ew", padx=(16, 0), pady=5)
        if values and not v.get() and values: v.set(values[0])
        if first_widget is None: first_widget = widget
    form.columnconfigure(1, weight=1)

    def save():
        result["value"] = {k: v.get().strip() for k, v in vars_.items()}; d.destroy()

    divider(shell).pack(fill="x", pady=(12, 10))
    buttons = ttk.Frame(shell, style="Surface.TFrame")
    buttons.pack(fill="x")
    ttk.Label(buttons, text="Ctrl+Enter saves", style="SurfaceMuted.TLabel").pack(side="left")
    cancel_button = ttk.Button(buttons, text="Cancel", style="Secondary.TButton", command=d.destroy)
    cancel_button.pack(side="right")
    save_button = ttk.Button(buttons, text="Save", style="Primary.TButton", command=save)
    save_button.pack(side="right", padx=(0, 8))
    d.save_button = save_button
    d.cancel_button = cancel_button
    d.form_canvas = canvas

    def on_wheel(event):
        if canvas.bbox("all") and canvas.winfo_height() < form.winfo_reqheight():
            canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    d.bind("<MouseWheel>", on_wheel)
    d.bind("<Escape>", lambda _e: d.destroy())
    d.bind("<Control-Return>", lambda _e: save())
    if first_widget is not None: first_widget.focus_set()
    parent.wait_window(d)
    return result["value"]
\'''\n'''
text = text[:start] + replacement + text[end:]
path.write_text(text, encoding="utf-8")
print("updated", path)
