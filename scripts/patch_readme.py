from __future__ import annotations

from pathlib import Path

def write_if_changed(path: str, text: str) -> None:
    p = Path(path)
    old = p.read_text(encoding="utf-8")
    if old != text:
        p.write_text(text, encoding="utf-8")
        print("updated", path)
    else:
        print("unchanged", path)

def must_replace(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Could not find patch anchor: {label}")
    return text.replace(old, new, 1)

def patch_readme() -> None:
    path = "README.md"
    text = Path(path).read_text(encoding="utf-8")
    if "## TallyPrime integration" not in text:
        text += '''\n\n## TallyPrime integration\n\nJewelLAN includes an optional **JewelTallyBridge.exe** for offline TallyPrime accounting sync. Install the Tally Bridge component on the Windows PC running TallyPrime. TallyPrime continues to listen only on localhost (normally port 9000); the authenticated JewelLAN bridge is the only service exposed to the Private LAN.\n\nSales, sale COGS journals and purchases are committed to JewelLAN first and placed into a durable Tally sync queue in the same database transaction. Billing never waits for Tally. The queue uses stable REMOTEID values, exponential retry, response validation, configurable ledger mappings, automatic Sundry Debtor/Creditor ledger creation, and Day Book reconciliation. See `docs/TALLY_INTEGRATION.md`.\n'''
    write_if_changed(path, text)

if __name__ == "__main__":
    patch_readme()
