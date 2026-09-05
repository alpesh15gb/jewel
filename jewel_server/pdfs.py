from __future__ import annotations

import io
import json
from typing import Any

from reportlab.graphics.barcode import code128
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _fmt(v: Any) -> str:
    try:
        return f"{float(v):,.2f}"
    except Exception:
        return str(v or "")


def _business_heading(settings: dict[str, str], styles) -> list[Any]:
    center = ParagraphStyle("biz-center", parent=styles["Normal"], fontSize=8, leading=10, alignment=TA_CENTER)
    story: list[Any] = [Paragraph(f"<b>{settings.get('business_name','Jewellery Store')}</b>", ParagraphStyle("biz-title", parent=styles["Title"], fontSize=15, leading=18))]
    if settings.get("business_address"):
        story.append(Paragraph(settings["business_address"], center))
    bits = [x for x in [settings.get("business_phone"), f"GSTIN: {settings.get('business_gstin')}" if settings.get("business_gstin") else ""] if x]
    if bits:
        story.append(Paragraph(" | ".join(bits), center))
    return story


def _draw_single_label(c, item: dict[str, Any], settings: dict[str, str], width: float, height: float) -> None:
    tag = str(item.get("tag_no") or "").strip()
    if not tag:raise ValueError("Tag number is required")
    barcode = str(item.get("barcode") or tag).strip()
    if not barcode:raise ValueError("Barcode is required")
    try:gw = float(item.get("gross_weight", 0)); nw = float(item.get("net_weight", 0))
    except Exception:raise ValueError("Tag weights must be numeric")
    c.setTitle(f"Tag {tag}")
    c.setFont("Helvetica-Bold", 7); c.drawString(2 * mm, height - 4 * mm, settings.get("business_name", "Jewellery")[:32])
    c.setFont("Helvetica", 6.5); c.drawString(2 * mm, height - 7.5 * mm, f"{tag}  {item.get('metal','')} {item.get('purity','')}")
    c.drawString(2 * mm, height - 11 * mm, f"GW {gw:.3f}g  NW {nw:.3f}g")
    huid = item.get("huid") or ""
    if huid: c.drawString(2 * mm, height - 14.5 * mm, f"HUID {huid}")
    # Code128 barcode — always printed (thermal + laser safe).
    barcode = str(item.get("barcode") or tag).strip()
    barcode = code128.Code128(barcode, barHeight=5 * mm, barWidth=0.28 * mm, humanReadable=False)
    barcode.drawOn(c, 2 * mm, 2.2 * mm); c.setFont("Helvetica", 5.5); c.drawCentredString(width * 0.52, 1.0 * mm, str(item.get("barcode") or tag)[:26])
    # QR only on taller stock (>=30mm) to avoid overlap on default 60x25.
    # Content is offline: tag|barcode|net — no internet needed.
    if height >= 30 * mm:
        try:
            from reportlab.graphics.barcode.qr import QrCodeWidget
            from reportlab.graphics.shapes import Drawing
            try:nw_q = float(item.get("net_weight", 0))
            except Exception:nw_q = 0.0
            qr = QrCodeWidget(f"{tag}|{str(item.get('barcode') or tag)}|{nw_q:.3f}g")
            d = Drawing(9 * mm, 9 * mm); d.add(qr)
            d.drawOn(c, width - 11 * mm, 1 * mm)
        except Exception:
            pass


def label_pdf(item: dict[str, Any], settings: dict[str, str]) -> bytes:
    try:w_mm = max(30, min(100, float(settings.get("label_width_mm", 60))))
    except Exception:w_mm = 60
    try:h_mm = max(15, min(60, float(settings.get("label_height_mm", 25))))
    except Exception:h_mm = 25
    width = w_mm * mm; height = h_mm * mm
    buf = io.BytesIO()
    from reportlab.pdfgen.canvas import Canvas
    c = Canvas(buf, pagesize=(width, height), pageCompression=1)
    _draw_single_label(c, item, settings, width, height)
    c.showPage(); c.save()
    return buf.getvalue()


def bulk_label_pdf(items: list[dict[str, Any]], settings: dict[str, str]) -> bytes:
    """One PDF page per tag for bulk re-print. Offline, no internet."""
    try:w_mm = max(30, min(100, float(settings.get("label_width_mm", 60))))
    except Exception:w_mm = 60
    try:h_mm = max(15, min(60, float(settings.get("label_height_mm", 25))))
    except Exception:h_mm = 25
    width = w_mm * mm; height = h_mm * mm
    buf = io.BytesIO()
    from reportlab.pdfgen.canvas import Canvas
    c = Canvas(buf, pagesize=(width, height), pageCompression=1)
    for it in items:
        _draw_single_label(c, it, settings, width, height)
        c.showPage()
    c.save()
    return buf.getvalue()


def estimation_pdf(est: dict[str, Any], lines: list[dict[str, Any]], customer: dict[str, Any] | None, settings: dict[str, str]) -> bytes:
    """Offline estimation/quotation — clearly NOT a tax invoice, no stock movement."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=12*mm, rightMargin=12*mm, topMargin=10*mm, bottomMargin=10*mm, title=str(est.get('est_no','EST')))
    styles = getSampleStyleSheet(); normal = ParagraphStyle("est-small", parent=styles["Normal"], fontSize=8, leading=10); right = ParagraphStyle("est-right", parent=normal, alignment=TA_RIGHT); center = ParagraphStyle("est-center", parent=normal, alignment=TA_CENTER)
    story = _business_heading(settings, styles)
    story.append(Spacer(1, 4*mm))
    story.append(Paragraph("<b>ESTIMATION / QUOTATION — NOT A TAX INVOICE</b><br/>Valid only as price quote. Stock reserved only on tax invoice.", center))
    story.append(Spacer(1, 3*mm))
    cust = customer or {}
    data = [["Tag", "Description", "NW", "Rate/g", "Taxable", "GST", "Total"]]
    for l in lines:
        data.append([l.get("tag_no",""), Paragraph(f"{l.get('description','')}<br/>{l.get('metal','')} {l.get('purity','')}", normal), f"{float(l.get('net_weight',0)):.3f}", _fmt(l.get("metal_rate")), _fmt(l.get("taxable")), _fmt(l.get("gst_amount")), _fmt(l.get("line_total"))])
    t = Table(data, repeatRows=1, colWidths=[22*mm,55*mm,18*mm,24*mm,24*mm,20*mm,24*mm]); t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eeeeee')),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),7),('GRID',(0,0),(-1,-1),0.35,colors.grey),('ALIGN',(2,1),(-1,-1),'RIGHT')])); story.append(t)
    est_no = est.get('est_no',''); total = float(est.get('total_paise',0))/100.0 if 'total_paise' in est else float(est.get('total',0))
    story += [Spacer(1,4*mm), Paragraph(f"<b>Estimation {est_no} — Total Rs. {_fmt(total)}</b>", right), Spacer(1,2*mm), Paragraph(f"Customer: {cust.get('name','Walk-in')} {cust.get('phone','')}", normal)]
    doc.build(story); return buf.getvalue()


def invoice_pdf(sale: dict[str, Any], lines: list[dict[str, Any]], customer: dict[str, Any] | None, settings: dict[str, str], old_gold: list[dict[str, Any]] | None = None) -> bytes:
    snapshot = {}
    try:
        snapshot = json.loads(sale.get("print_snapshot_json") or "{}")
    except (TypeError, ValueError):
        snapshot = {}
    effective_settings = dict(settings)
    effective_settings.update(snapshot.get("seller") or {})
    branch = snapshot.get("branch") or {}
    if branch.get("address"):
        effective_settings["business_address"] = branch["address"]
    if branch.get("phone"):
        effective_settings["business_phone"] = branch["phone"]
    if branch.get("gstin"):
        effective_settings["business_gstin"] = branch["gstin"]
    customer = (snapshot.get("customer") or customer or {})
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=12*mm, rightMargin=12*mm, topMargin=10*mm, bottomMargin=10*mm, title=sale["invoice_no"])
    styles = getSampleStyleSheet(); normal = ParagraphStyle("small", parent=styles["Normal"], fontSize=8, leading=10); right = ParagraphStyle("right", parent=normal, alignment=TA_RIGHT); center = ParagraphStyle("center", parent=normal, alignment=TA_CENTER)
    story = _business_heading(effective_settings, styles)
    story.append(Spacer(1, 4*mm)); cust = customer or {}
    invoice_date = sale.get("business_date") or str(sale.get("created_at") or "")[:10]
    header = Table([[Paragraph(f"<b>Tax Invoice</b><br/>Invoice: {sale['invoice_no']}<br/>Date: {invoice_date}", normal), Paragraph(f"<b>Customer</b><br/>{cust.get('name','Walk-in Customer')}<br/>{cust.get('phone','')}<br/>{cust.get('gstin','')}", normal)]], colWidths=[90*mm, 90*mm])
    header.setStyle(TableStyle([('BOX',(0,0),(-1,-1),0.5,colors.grey),('VALIGN',(0,0),(-1,-1),'TOP'),('PADDING',(0,0),(-1,-1),5)])); story += [header, Spacer(1, 4*mm)]
    data = [["Tag", "Description", "GW", "NW", "Rate/g", "Taxable", "GST", "Total"]]
    for l in lines: data.append([l["tag_no"], Paragraph(f"{l['description']}<br/>{l['metal']} {l['purity']}", normal), f"{l['gross_weight']:.3f}", f"{l['net_weight']:.3f}", _fmt(l["metal_rate"]), _fmt(l["taxable"]), _fmt(l["gst_amount"]), _fmt(l["line_total"])])
    t = Table(data, repeatRows=1, colWidths=[22*mm,47*mm,16*mm,16*mm,22*mm,23*mm,18*mm,23*mm]); t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eeeeee')),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),7),('GRID',(0,0),(-1,-1),0.35,colors.grey),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('ALIGN',(2,1),(-1,-1),'RIGHT'),('PADDING',(0,0),(-1,-1),3)])); story.append(t)
    if old_gold:
        story.append(Spacer(1,3*mm)); rows=[["Old Gold","Purity","Gross","Pure Wt","Rate","Value"]]
        for og in old_gold: rows.append([og["metal"],og["purity"],f"{og['gross_weight']:.3f}",f"{og['pure_weight']:.3f}",_fmt(og["rate"]),_fmt(og["value"])])
        ot=Table(rows,colWidths=[35*mm,25*mm,25*mm,25*mm,30*mm,30*mm]);ot.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.35,colors.grey),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),7),('ALIGN',(2,1),(-1,-1),'RIGHT')]));story.append(ot)
    totals=[["Subtotal",_fmt(sale["subtotal"])],["Discount",_fmt(sale["discount"])],["Taxable",_fmt(sale["taxable"])],["GST",_fmt(sale["gst"])],["Round off",_fmt(sale["round_off"])],["Grand Total",f"Rs. {_fmt(sale['total'])}"]]
    tt=Table(totals,colWidths=[35*mm,35*mm],hAlign='RIGHT');tt.setStyle(TableStyle([('ALIGN',(1,0),(1,-1),'RIGHT'),('FONTNAME',(0,-1),(-1,-1),'Helvetica-Bold'),('LINEABOVE',(0,-1),(-1,-1),0.7,colors.black),('FONTSIZE',(0,0),(-1,-1),8),('PADDING',(0,0),(-1,-1),3)]));story += [Spacer(1,3*mm),tt]
    pay=f"Cash {_fmt(sale['payment_cash'])} | Card {_fmt(sale['payment_card'])} | UPI {_fmt(sale['payment_upi'])} | Credit {_fmt(sale['payment_credit'])} | Old Gold {_fmt(sale['old_gold_value'])}";story += [Spacer(1,3*mm),Paragraph(pay,right),Spacer(1,8*mm),Paragraph("Thank you for your business.",center)];doc.build(story);return buf.getvalue()


def credit_note_pdf(ret: dict[str, Any], items: list[dict[str, Any]], customer: dict[str, Any] | None, settings: dict[str, str]) -> bytes:
    snapshot = {}
    try:
        snapshot = json.loads(ret.get("print_snapshot_json") or "{}")
    except (TypeError, ValueError):
        snapshot = {}
    effective_settings = dict(settings)
    effective_settings.update(snapshot.get("seller") or {})
    branch = snapshot.get("branch") or {}
    if branch.get("address"):
        effective_settings["business_address"] = branch["address"]
    if branch.get("phone"):
        effective_settings["business_phone"] = branch["phone"]
    if branch.get("gstin"):
        effective_settings["business_gstin"] = branch["gstin"]
    customer = snapshot.get("customer") or customer
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=12*mm, rightMargin=12*mm, topMargin=10*mm, bottomMargin=10*mm, title=ret["return_no"])
    styles = getSampleStyleSheet(); normal = ParagraphStyle("cn-small", parent=styles["Normal"], fontSize=8, leading=10); right = ParagraphStyle("cn-right", parent=normal, alignment=TA_RIGHT); center = ParagraphStyle("cn-center", parent=normal, alignment=TA_CENTER)
    story = _business_heading(effective_settings, styles); story.append(Spacer(1,4*mm)); cust=customer or {}
    header=Table([[Paragraph(f"<b>GST Credit Note</b><br/>Credit Note: {ret['return_no']}<br/>Date: {ret.get('business_date','')}<br/>Original Invoice: {ret.get('invoice_no','')}",normal),Paragraph(f"<b>Customer</b><br/>{cust.get('name',ret.get('customer_name') or 'Walk-in Customer')}<br/>{cust.get('phone','')}<br/>{cust.get('gstin','')}",normal)]],colWidths=[90*mm,90*mm])
    header.setStyle(TableStyle([('BOX',(0,0),(-1,-1),0.5,colors.grey),('VALIGN',(0,0),(-1,-1),'TOP'),('PADDING',(0,0),(-1,-1),5)]));story += [header,Spacer(1,4*mm)]
    data=[["Tag","Taxable","GST","Round off","Credit"]]
    for x in items:data.append([x.get('tag_no',''),_fmt(x.get('taxable')), _fmt(x.get('gst_amount')), _fmt(x.get('round_off')), _fmt(x.get('line_total'))])
    t=Table(data,repeatRows=1,colWidths=[55*mm,30*mm,30*mm,30*mm,35*mm]);t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eeeeee')),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),8),('GRID',(0,0),(-1,-1),0.35,colors.grey),('ALIGN',(1,1),(-1,-1),'RIGHT'),('PADDING',(0,0),(-1,-1),4)]));story.append(t)
    totals=[["Taxable",_fmt(ret.get('taxable'))],["CGST",_fmt(ret.get('cgst'))],["SGST",_fmt(ret.get('sgst'))],["IGST",_fmt(ret.get('igst'))],["GST Total",_fmt(ret.get('gst'))],["Round off",_fmt(ret.get('round_off'))],["Credit Note Total",f"Rs. {_fmt(ret.get('total'))}"]]
    tt=Table(totals,colWidths=[38*mm,38*mm],hAlign='RIGHT');tt.setStyle(TableStyle([('ALIGN',(1,0),(1,-1),'RIGHT'),('FONTNAME',(0,-1),(-1,-1),'Helvetica-Bold'),('LINEABOVE',(0,-1),(-1,-1),0.7,colors.black),('FONTSIZE',(0,0),(-1,-1),8),('PADDING',(0,0),(-1,-1),3)]));story += [Spacer(1,3*mm),tt]
    refund=f"Refund: Cash {_fmt(ret.get('refund_cash'))} | Card {_fmt(ret.get('refund_card'))} | UPI {_fmt(ret.get('refund_upi'))} | Customer A/c {_fmt(ret.get('refund_credit'))}";story += [Spacer(1,3*mm),Paragraph(refund,right),Spacer(1,2*mm),Paragraph(f"Reason: {ret.get('reason','')}",normal)]
    if ret.get('status')=='cancelled':story += [Spacer(1,3*mm),Paragraph("<b>CANCELLED / REVERSED</b>",center)]
    story += [Spacer(1,8*mm),Paragraph("This credit note references the original tax invoice shown above.",center)];doc.build(story);return buf.getvalue()


def stock_report_pdf(rows: list[dict[str, Any]], settings: dict[str, str], title: str = "Stock Report") -> bytes:
    buf=io.BytesIO();doc=SimpleDocTemplate(buf,pagesize=A4,leftMargin=8*mm,rightMargin=8*mm,topMargin=8*mm,bottomMargin=8*mm);styles=getSampleStyleSheet();story=[Paragraph(f"<b>{settings.get('business_name','Jewellery Store')}</b> - {title}",styles['Heading2']),Spacer(1,3*mm)];data=[["Tag","Item","Metal","Purity","GW","NW","HUID","Status"]]
    for r in rows:data.append([r['tag_no'],r['name'][:24],r['metal'],r['purity'],f"{r['gross_weight']:.3f}",f"{r['net_weight']:.3f}",r.get('huid') or '',r['status']])
    t=Table(data,repeatRows=1,colWidths=[25*mm,45*mm,20*mm,18*mm,18*mm,18*mm,30*mm,22*mm]);t.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.3,colors.grey),('BACKGROUND',(0,0),(-1,0),colors.lightgrey),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),7),('ALIGN',(4,1),(5,-1),'RIGHT')]));story.append(t);doc.build(story);return buf.getvalue()
