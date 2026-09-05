from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path


def self_test() -> int:
    """Verify the packaged counter contains its required modules without starting Tk."""
    required = (
        "jewel_client.main",
        "jewel_client.api",
        "jewel_client.config",
        "jewel_client.scale",
        "jewel_client.ui_theme",
        "jewel_client.ui_common",
        "jewel_client.returns_page",
        "jewel_client.billing_page",
        "jewel_client.label_send",
    )
    missing = [name for name in required if importlib.util.find_spec(name) is None]
    if missing:
        return 2

    from jewel_client.api import Api, ApiError, discover_servers, format_fingerprint, probe_server_fingerprint, secure_url  # noqa: F401
    from jewel_client.billing_page import POSPage  # noqa: F401
    from jewel_client.config import load_config, load_pending_posts, remove_pending_post, save_config, save_pending_posts, upsert_pending_post  # noqa: F401
    from jewel_client.scale import read_scale  # noqa: F401
    from jewel_client.ui_common import Page, center, form_dialog, money, open_pdf  # noqa: F401
    from jewel_client.ui_theme import PALETTE, apply_theme, card, divider, status_pill  # noqa: F401
    from jewel_client.returns_page import ReturnsPage  # noqa: F401
    from jewel_client.label_send import save_file, send_serial, send_tcp  # noqa: F401
    import jewel_client.main as _m  # noqa: F401
    assert hasattr(_m, "App") and hasattr(_m, "LoginDialog") and hasattr(_m, "POSPage")

    return 0


def _prepare_setup_parent(root) -> None:
    """Map the Tk root before creating transient post-login setup dialogs.

    On Windows, a Toplevel marked transient to a withdrawn root can disappear when
    the login window is destroyed. Company/password setup happens before the main
    App frame exists, so keep a tiny mapped root alive as the modal owner.
    """
    root.deiconify()
    root.geometry("1x1+0+0")
    root.update_idletasks()


def _crash_log(exc: BaseException) -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "JewelLAN"
    base.mkdir(parents=True, exist_ok=True)
    path = base / "client-crash.log"
    stamp = datetime.now(timezone.utc).isoformat()
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"\n[{stamp}] JewelPOS startup failure\n")
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=fh)
    return path


def _install_enhanced_billing_page():
    """Ensure App uses the unified billing screen.

    main.py now imports POSPage from billing_page directly; this hook is kept
    for backwards compatibility (tests + older entry points) and simply
    re-asserts the binding.
    """
    import jewel_client.main as main_module
    from jewel_client.billing_page import POSPage as BillingPOSPage

    main_module.POSPage = BillingPOSPage
    return main_module


def launch() -> None:
    import tkinter as tk
    from tkinter import messagebox

    from jewel_client.api import Api
    from jewel_client.config import load_config

    main_module = _install_enhanced_billing_page()
    App = main_module.App
    LoginDialog = main_module.LoginDialog
    ensure_company_setup = main_module.ensure_company_setup
    force_initial_password_change = main_module.force_initial_password_change

    root = tk.Tk()
    root.withdraw()
    try:
        cfg = load_config()
        api = Api(cfg.get("server_url", ""), cfg.get("server_fingerprint", ""))
        login = LoginDialog(root, api, cfg)
        root.wait_window(login)
        user = login.user
        if not user:
            root.destroy()
            return

        # The login Toplevel is now gone. Map the owner before opening password or
        # company setup, otherwise Windows can hide transient children with it.
        _prepare_setup_parent(root)

        if user.get("must_change_password") and not force_initial_password_change(root, api, user):
            root.destroy()
            return
        if not ensure_company_setup(root, api):
            root.destroy()
            return

        App(root, api, cfg, user)
        root.mainloop()
    except BaseException as exc:
        log_path = _crash_log(exc)
        try:
            if root.winfo_exists():
                root.deiconify()
                root.geometry("520x180+80+80")
                root.update_idletasks()
                messagebox.showerror(
                    "JewelLAN could not start",
                    "JewelLAN hit a startup error instead of closing silently.\n\n"
                    f"{exc}\n\nCrash details were written to:\n{log_path}",
                    parent=root,
                )
        except Exception:
            pass
        finally:
            try:
                if root.winfo_exists():
                    root.destroy()
            except Exception:
                pass


def main() -> None:
    launch()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    main()
