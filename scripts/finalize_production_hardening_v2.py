from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"release-gate anchor not found: {label}")
    return text.replace(old, new, 1)


def update(path: str, transform) -> None:
    p = Path(path)
    before = p.read_text(encoding="utf-8")
    after = transform(before)
    if after == before:
        print("unchanged", path)
    else:
        p.write_text(after, encoding="utf-8")
        print("updated", path)


def patch_main(text: str) -> str:
    old = '''@app.get('/api/dashboard')
def dashboard(u=Depends(require('dashboard'))):
    today=dt.date.today().isoformat()
    with read_db() as c:
        stock=c.execute("SELECT count(*) c,coalesce(sum(gross_weight),0) gw,coalesce(sum(net_weight),0) nw,coalesce(sum(cost_amount),0) cost FROM items WHERE status='in_stock'").fetchone();sales=c.execute("SELECT count(*) c,coalesce(sum(total),0) total FROM sales WHERE status='posted' AND substr(created_at,1,10)=?",(today,)).fetchone();rep=c.execute("SELECT count(*) FROM repairs WHERE status NOT IN ('delivered','cancelled')").fetchone()[0];orders=c.execute("SELECT count(*) FROM orders WHERE status NOT IN ('delivered','cancelled')").fetchone()[0];cats=rowsdict(c.execute("SELECT category,count(*) c FROM items WHERE status='in_stock' GROUP BY category ORDER BY c DESC LIMIT 6").fetchall());rates=rowsdict(c.execute("SELECT r.metal,r.purity,r.rate_per_gram,r.effective_at FROM metal_rates r JOIN (SELECT metal,purity,max(id) id FROM metal_rates GROUP BY metal,purity) x ON x.id=r.id ORDER BY r.metal,r.purity").fetchall())
    return {'stock':dict(stock),'today_sales':dict(sales),'pending_repairs':rep,'pending_orders':orders,'categories':cats,'rates':rates}
'''
    new = '''@app.get('/api/dashboard')
def dashboard(u=Depends(require('dashboard'))):
    with read_db() as c:
        today=business_date(c)
        stock=c.execute("SELECT count(*) c,coalesce(sum(gross_mg),0)/1000.0 gw,coalesce(sum(net_mg),0)/1000.0 nw,coalesce(sum(cost_amount_paise),0)/100.0 cost FROM items WHERE status='in_stock'").fetchone();sales=c.execute("SELECT count(*) c,coalesce(sum(total_paise),0)/100.0 total FROM sales WHERE status='posted' AND business_date=?",(today,)).fetchone();rep=c.execute("SELECT count(*) FROM repairs WHERE status NOT IN ('delivered','cancelled')").fetchone()[0];orders=c.execute("SELECT count(*) FROM orders WHERE status NOT IN ('delivered','cancelled')").fetchone()[0];cats=rowsdict(c.execute("SELECT category,count(*) c FROM items WHERE status='in_stock' GROUP BY category ORDER BY c DESC LIMIT 6").fetchall());rates=rowsdict(c.execute("SELECT r.metal,r.purity,r.rate_per_gram,r.effective_at FROM metal_rates r JOIN (SELECT metal,purity,max(id) id FROM metal_rates GROUP BY metal,purity) x ON x.id=r.id ORDER BY r.metal,r.purity").fetchall())
    return {'business_date':today,'stock':dict(stock),'today_sales':dict(sales),'pending_repairs':rep,'pending_orders':orders,'categories':cats,'rates':rates}
'''
    text = replace_once(text, old, new, "dashboard business date")
    text = replace_once(
        text,
        "date_from=date_from or dt.date.today().replace(day=1).isoformat();date_to=date_to or dt.date.today().isoformat();return reconcile(date_from,date_to)",
        "with read_db() as c:today=business_date(c)\n    date_from=date_from or today[:8]+'01';date_to=date_to or today;return reconcile(date_from,date_to)",
        "Tally reconcile business date",
    )
    text = replace_once(
        text,
        "date_from=date_from or dt.date.today().replace(day=1).isoformat();date_to=date_to or dt.date.today().isoformat()\n    with read_db() as c:s=c.execute",
        "with read_db() as c:\n        today=business_date(c);date_from=date_from or today[:8]+'01';date_to=date_to or today;s=c.execute",
        "summary business date",
    )
    text = replace_once(
        text,
        "date_to=date_to or dt.date.today().isoformat()\n    with read_db() as c:return rowsdict",
        "with read_db() as c:\n        date_to=date_to or business_date(c);return rowsdict",
        "trial balance business date",
    )
    old_day = '''@app.get('/api/reports/day-close')
def day_close_report(date:str='',u=Depends(require('reports'))):
    business_date=date or dt.date.today().isoformat()
    try:dt.date.fromisoformat(business_date)
    except ValueError:raise HTTPException(400,'Date must be YYYY-MM-DD')
    with read_db() as c:return day_close(c,business_date)
'''
    new_day = '''@app.get('/api/reports/day-close')
def day_close_report(date:str='',u=Depends(require('reports'))):
    with read_db() as c:
        report_date=date or business_date(c)
        try:dt.date.fromisoformat(report_date)
        except ValueError:raise HTTPException(400,'Date must be YYYY-MM-DD')
        return day_close(c,report_date)
'''
    return replace_once(text, old_day, new_day, "day-close business date")


def patch_tally(text: str) -> str:
    text = replace_once(text, 'date=_voucher_date(sale["created_at"]),', 'date=_voucher_date(sale.get("business_date") or sale["created_at"]),', "Tally sale business date")
    text = replace_once(text, 'date=_voucher_date(sale["created_at"]),', 'date=_voucher_date(sale.get("business_date") or sale["created_at"]),', "Tally COGS business date")
    text = replace_once(text, 'date=_voucher_date(pur["created_at"]),', 'date=_voucher_date(pur.get("business_date") or pur["created_at"]),', "Tally purchase business date")
    return text


def patch_installer(text: str) -> str:
    return replace_once(text, '#define MyAppVersion "1.0.0"', '#define MyAppVersion "1.2.0-rc1"', "installer version")


def patch_ci(text: str) -> str:
    text = replace_once(
        text,
        "from jewel_client.main import App, POSPage, TallyPage",
        "from jewel_client.main import AdminPage, App, POSPage, TallyPage",
        "Data Health GUI import",
    )
    text = replace_once(
        text,
        "if path == '/api/users': return []\n                  raise RuntimeError(f'Unexpected GUI smoke-test GET: {path}')",
        "if path == '/api/users': return []\n                  if path == '/api/integrity': return {'ok': True, 'sqlite_quick_check':['ok'], 'foreign_key_violations':0, 'issue_count':0, 'audit_chain':{'ok':True}, 'canonical':{'ok':True,'mismatches':0}, 'issues':[]}\n                  if path == '/api/reports/day-close': return {'date':'2026-08-30','sales':{'count':0,'total':0,'payments_match_sales':True},'journal':{'balanced':True}}\n                  if path == '/api/health': return {'ok':True,'backup':{'ok':True,'at':'2026-08-30T00:00:00+00:00'}}\n                  raise RuntimeError(f'Unexpected GUI smoke-test GET: {path}')",
        "Data Health GUI API fixtures",
    )
    text = replace_once(
        text,
        "app.show(TallyPage, 'TallyPrime'); root.update_idletasks(); assert app.current_page.winfo_exists()\n          root.destroy()\n          print('Redesigned Dashboard, Billing and Tally screens constructed successfully.')",
        "app.show(TallyPage, 'TallyPrime'); root.update_idletasks(); assert app.current_page.winfo_exists()\n          app.show(AdminPage, 'Administration'); root.update_idletasks(); assert app.current_page.health_text.winfo_exists()\n          root.destroy()\n          print('Dashboard, Billing, Tally and Data Health screens constructed successfully.')",
        "Data Health GUI construction",
    )
    text = replace_once(
        text,
        "--hidden-import jewel_server.backup --hidden-import jewel_server.discovery\n          --hidden-import jewel_server.tally",
        "--hidden-import jewel_server.backup --hidden-import jewel_server.discovery\n          --hidden-import jewel_server.audit_chain --hidden-import jewel_server.canonical\n          --hidden-import jewel_server.integrity --hidden-import jewel_server.precision\n          --hidden-import jewel_server.tally",
        "server hidden imports",
    )
    return text


def main() -> None:
    update("jewel_server/main.py", patch_main)
    update("jewel_server/tally.py", patch_tally)
    update("installer/JewelLAN.iss", patch_installer)
    update(".github/workflows/windows-build.yml", patch_ci)


if __name__ == "__main__":
    main()
