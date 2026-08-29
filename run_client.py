import sys

from jewel_client.main import main


def self_test() -> int:
    # Import every local module the packaged counter application requires.
    # This intentionally runs from the final EXE in CI so packaging mistakes
    # (such as a missing jewel_client.main) fail before an installer is built.
    from jewel_client.api import Api, discover_servers  # noqa: F401
    from jewel_client.config import load_config, save_config  # noqa: F401
    from jewel_client.scale import read_scale  # noqa: F401

    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    main()
