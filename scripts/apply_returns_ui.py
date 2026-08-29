from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"returns UI anchor not found: {label}")
    return text.replace(old, new, 1)


def patch_main() -> None:
    path = Path("jewel_client/main.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        'from .ui_theme import PALETTE, apply_theme, card, divider, status_pill',
        'from .ui_theme import PALETTE, apply_theme, card, divider, status_pill\nfrom .returns_page import ReturnsPage',
        "ReturnsPage import",
    )
    text = replace_once(
        text,
        '        if role in ("admin","manager","cashier"): pages.insert(1, ("Billing", POSPage))\n        if role in ("admin","manager","inventory"): pages.append(("Purchases", PurchasesPage))',
        '        if role in ("admin","manager","cashier"): pages.insert(1, ("Billing", POSPage))\n        if role in ("admin","manager"): pages.insert(2, ("Returns & Credit Notes", ReturnsPage))\n        if role in ("admin","manager","inventory"): pages.append(("Purchases", PurchasesPage))',
        "manager Returns navigation",
    )
    path.write_text(text, encoding="utf-8")


def patch_workflow() -> None:
    path = Path(".github/workflows/windows-build.yml")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        'python -c "import jewel_client.main, jewel_client.ui_theme, jewel_server.main, jewel_server.tally, jewel_server.audit_chain, jewel_server.canonical, jewel_server.integrity, jewel_server.precision, jewel_server.tls, jewel_tally_bridge.main, jewel_tally_bridge.xml_compat; print(\'imports ok\')"',
        'python -c "import jewel_client.main, jewel_client.ui_theme, jewel_client.returns_page, jewel_server.main, jewel_server.returns, jewel_server.tally, jewel_server.audit_chain, jewel_server.canonical, jewel_server.integrity, jewel_server.precision, jewel_server.tls, jewel_tally_bridge.main, jewel_tally_bridge.xml_compat; print(\'imports ok\')"',
        "source imports",
    )
    text = replace_once(
        text,
        '          from jewel_client.main import AdminPage, App, POSPage, TallyPage',
        '          from jewel_client.main import AdminPage, App, POSPage, TallyPage\n          from jewel_client.returns_page import ReturnsPage',
        "GUI Returns import",
    )
    text = replace_once(
        text,
        "                  if path == '/api/customers': return []",
        "                  if path == '/api/sales': return []\n                  if path == '/api/returns': return []\n                  if path == '/api/customers': return []",
        "GUI dummy sales/returns",
    )
    text = replace_once(
        text,
        "          app.show(TallyPage, 'TallyPrime'); root.update_idletasks(); assert app.current_page.winfo_exists()\n          app.show(AdminPage, 'Administration'); root.update_idletasks(); assert app.current_page.health_text.winfo_exists()",
        "          app.show(TallyPage, 'TallyPrime'); root.update_idletasks(); assert app.current_page.winfo_exists()\n          app.show(ReturnsPage, 'Returns & Credit Notes'); root.update_idletasks(); assert app.current_page.returns_tree.winfo_exists()\n          app.show(AdminPage, 'Administration'); root.update_idletasks(); assert app.current_page.health_text.winfo_exists()",
        "GUI Returns construction",
    )
    text = replace_once(
        text,
        "          print('Dashboard, Billing, Tally and Data Health screens constructed successfully.')",
        "          print('Dashboard, Billing, Returns, Tally and Data Health screens constructed successfully.')",
        "GUI smoke message",
    )
    text = replace_once(
        text,
        "          --hidden-import jewel_server.integrity --hidden-import jewel_server.precision\n          --hidden-import jewel_server.tally",
        "          --hidden-import jewel_server.integrity --hidden-import jewel_server.precision\n          --hidden-import jewel_server.returns --hidden-import jewel_server.tally",
        "server PyInstaller returns",
    )
    text = replace_once(
        text,
        "          --hidden-import jewel_client.scale --hidden-import jewel_client.ui_theme",
        "          --hidden-import jewel_client.scale --hidden-import jewel_client.ui_theme\n          --hidden-import jewel_client.returns_page",
        "client PyInstaller ReturnsPage",
    )
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    patch_main()
    patch_workflow()
    print("Returns UI integrated")
