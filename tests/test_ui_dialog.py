import os
import tkinter as tk

import pytest

from jewel_client.main import InventoryPage, form_dialog
from jewel_client.ui_theme import apply_theme


def test_tall_inventory_form_keeps_save_action_visible():
    if os.name != "nt":
        pytest.skip("Windows desktop layout regression test")

    root = tk.Tk()
    root.withdraw()
    apply_theme(root)
    observed = {}

    def inspect_dialog():
        dialogs = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
        if not dialogs:
            observed["error"] = "dialog was not created"
            root.after(25, inspect_dialog)
            return
        dialog = dialogs[-1]
        dialog.update_idletasks()
        save = getattr(dialog, "save_button", None)
        canvas = getattr(dialog, "form_canvas", None)
        observed["save_exists"] = save is not None
        if save is not None:
            # The test root is intentionally withdrawn, so winfo_ismapped() is
            # false for descendants even when Tk has correctly laid them out.
            # Verify that Save is managed by pack and sits inside the dialog.
            observed["save_managed"] = save.winfo_manager() == "pack"
            observed["save_text"] = str(save.cget("text"))
            observed["save_inside"] = (
                save.winfo_rooty() + save.winfo_height()
                <= dialog.winfo_rooty() + dialog.winfo_height()
            )
        if canvas is not None:
            observed["scrollable"] = canvas.yview()[1] < 1.0
        dialog.destroy()

    root.after(100, inspect_dialog)
    form_dialog(
        root,
        "Jewellery item",
        InventoryPage.FIELDS,
        {"metal": "Gold", "purity": "916", "making_type": "per_gram", "category": "Ring"},
    )
    root.destroy()

    assert observed.get("save_exists"), observed
    assert observed.get("save_managed"), observed
    assert observed.get("save_text") == "Save", observed
    assert observed.get("save_inside"), observed
    assert observed.get("scrollable"), observed
