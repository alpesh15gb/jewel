from pathlib import Path

from patch_db import patch_db
from patch_services import patch_services
from patch_main import patch_main
from patch_client import patch_client
from patch_installer import patch_installer
from patch_readme import patch_readme


def main():
    # The patch modules were migration helpers used while the Tally integration
    # was being introduced. Once production-hardening is incorporated into the
    # committed source, rerunning old source-rewrite patches would be dangerous.
    marker_files = ("jewel_server/services.py", "jewel_server/main.py", "jewel_client/main.py")
    if all("PRODUCTION_HARDENED_V1 = True" in Path(p).read_text(encoding="utf-8") for p in marker_files):
        print("Tally upgrade already incorporated in production-hardened source.")
        return
    patch_db()
    patch_services()
    patch_main()
    patch_client()
    patch_installer()
    patch_readme()


if __name__ == "__main__":
    main()
