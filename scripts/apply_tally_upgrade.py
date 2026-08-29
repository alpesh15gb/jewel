from patch_db import patch_db
from patch_services import patch_services
from patch_main import patch_main
from patch_client import patch_client
from patch_installer import patch_installer
from patch_readme import patch_readme


def main():
    patch_db()
    patch_services()
    patch_main()
    patch_client()
    patch_installer()
    patch_readme()


if __name__ == "__main__":
    main()
