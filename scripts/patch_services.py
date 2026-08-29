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


def patch_services() -> None:
    path = "jewel_server/services.py"
    text = Path(path).read_text(encoding="utf-8")
    if "from .tally import enqueue_tally" not in text:
        text = must_replace(
            text,
            'from .db import audit,get_settings,next_sequence,utcnow\n',
            'from .db import audit,get_settings,next_sequence,utcnow\nfrom .tally import enqueue_tally\n',
            "Tally service import",
        )
    if "def gst_components" not in text:
        anchor = 'def latest_rate(conn,metal,purity):\n'
        helper = '''def _gst_state_code(value):
    s=str(value or '').strip()
    return s[:2] if len(s)>=2 and s[:2].isdigit() else ''

def gst_components(conn,customer_id,gst,payload):
    total=money(gst);settings=get_settings(conn);business=_gst_state_code(settings.get('business_state_code')) or _gst_state_code(settings.get('business_gstin'));customer=None
    if customer_id:customer=conn.execute('SELECT gstin FROM customers WHERE id=?',(customer_id,)).fetchone()
    place=_gst_state_code(payload.get('place_of_supply_code')) or (_gst_state_code(customer['gstin']) if customer else '') or business
    if business and place and business!=place:return place,0.0,0.0,total
    cgst=money(total/2);return place,cgst,money(total-cgst),0.0

'''
        text = must_replace(text, anchor, helper + anchor, "GST component helper")

    sale_setup_anchor = "s=get_settings(conn);inv=next_sequence(conn,'invoice',s.get('invoice_prefix','INV')+'-'+dt.datetime.now().strftime('%y%m')+'-',6);now=utcnow();cid=payload.get('customer_id') or None;bid=int(payload.get('branch_id') or 1);counter=payload.get('counter_id') or None"
    sale_setup_extra = "\n    if credit and not cid:raise HTTPException(400,'Credit payment requires a customer')\n    place,cgst,sgst,igst=gst_components(conn,cid,q['gst'],payload)"

    # This patch is deliberately idempotent. Earlier versions searched only for
    # sale_setup_anchor, which remains a prefix after patching and therefore
    # appended sale_setup_extra on every CI run. Collapse any historical repeats
    # and add the block only when it is genuinely absent.
    while sale_setup_extra + sale_setup_extra in text:
        text = text.replace(sale_setup_extra + sale_setup_extra, sale_setup_extra, 1)
    if sale_setup_anchor + sale_setup_extra not in text:
        text = must_replace(
            text,
            sale_setup_anchor,
            sale_setup_anchor + sale_setup_extra,
            "sale credit/GST setup",
        )

    if "place_of_supply_code,cgst,sgst,igst" not in text:
        old_insert = "cur=conn.execute(\"INSERT INTO sales(invoice_no,client_request_id,branch_id,counter_id,customer_id,subtotal,discount,taxable,gst,round_off,total,payment_cash,payment_card,payment_upi,payment_credit,old_gold_value,notes,status,user_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'posted',?,?)\",(inv,req,bid,counter,cid,q['subtotal'],q['discount'],q['taxable'],q['gst'],q['round_off'],q['total'],cash,card,upi,credit,old_value,payload.get('notes'),user['id'],now));sid=cur.lastrowid;cost=0"
        new_insert = "cur=conn.execute(\"INSERT INTO sales(invoice_no,client_request_id,branch_id,counter_id,customer_id,subtotal,discount,taxable,gst,place_of_supply_code,cgst,sgst,igst,round_off,total,payment_cash,payment_card,payment_upi,payment_credit,old_gold_value,notes,status,user_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'posted',?,?)\",(inv,req,bid,counter,cid,q['subtotal'],q['discount'],q['taxable'],q['gst'],place,cgst,sgst,igst,q['round_off'],q['total'],cash,card,upi,credit,old_value,payload.get('notes'),user['id'],now));sid=cur.lastrowid;cost=0"
        text = must_replace(text, old_insert, new_insert, "sale GST columns")
    old_end = "_journal(conn,user['id'],f'Sale {inv}','sale',sid,jl);audit(conn,user['id'],'create','sale',sid,{'invoice_no':inv,'total':q['total']},client_ip);return {'id':sid,'invoice_no':inv,'total':q['total'],'payable':q['payable'],'idempotent':False}"
    if old_end in text:
        new_end = "_journal(conn,user['id'],f'Sale {inv}','sale',sid,jl);audit(conn,user['id'],'create','sale',sid,{'invoice_no':inv,'total':q['total']},client_ip);enqueue_tally(conn,'sale',sid,'create');\n    if cost:enqueue_tally(conn,'sale_cogs',sid,'create')\n    return {'id':sid,'invoice_no':inv,'total':q['total'],'payable':q['payable'],'idempotent':False}"
        text = text.replace(old_end, new_end, 1)
    old_cancel = "audit(conn,user['id'],'cancel','sale',sale_id,{'reason':reason},client_ip);return {'ok':True,'invoice_no':sale['invoice_no']}"
    if old_cancel in text:
        new_cancel = "audit(conn,user['id'],'cancel','sale',sale_id,{'reason':reason},client_ip);enqueue_tally(conn,'sale',sale_id,'cancel');\n    cost=money(conn.execute('SELECT coalesce(sum(cost_amount),0) FROM sale_items WHERE sale_id=?',(sale_id,)).fetchone()[0])\n    if cost:enqueue_tally(conn,'sale_cogs',sale_id,'cancel')\n    return {'ok':True,'invoice_no':sale['invoice_no']}"
        text = text.replace(old_cancel, new_cancel, 1)
    write_if_changed(path, text)


if __name__ == "__main__":
    patch_services()
