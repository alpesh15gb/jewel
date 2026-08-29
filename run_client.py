from __future__ import annotations

import importlib.util
import sys


def self_test() -> int:
    """Verify the packaged counter contains its required modules without starting Tk.

    The Windows client is a PyInstaller one-file GUI executable. Importing the full
    Tk application before handling --self-test makes the packaging check depend on
    one-file extraction/GUI startup time and can leave CI waiting on a window.  The
    real GUI is covered separately by the source smoke test; here we verify that the
    frozen importer can resolve every JewelPOS runtime module.
    """
    required = (
        "jewel_client.main",
        "jewel_client.api",
        "jewel_client.config",
        "jewel_client.scale",
        "jewel_client.ui_theme",
        "jewel_client.returns_page",
    )
    missing = [name for name in required if importlib.util.find_spec(name) is None]
    if missing:
        return 2

    # Import the lightweight hardware/config/API modules as a runtime sanity check.
    from jewel_client.api import Api, discover_servers  # noqa: F401
    from jewel_client.config import load_config, save_config  # noqa: F401
    from jewel_client.scale import read_scale  # noqa: F401

    return 0


def main() -> None:
    # Keep the GUI import out of the --self-test path. Normal application launches
    # still execute exactly the same jewel_client.main.main entry point.
    from jewel_client.main import main as app_main

    app_main()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    main()
