from __future__ import annotations

import io
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


def label_pdf(item: dict[str, Any], settings: dict[str, str]) -> bytes:
    width = float(settings.get("label_width_mm", 60)) * mm
    height = float(settings.get("label_height_mm", 25)) * mm
    buf = io.BytesIO()
    from reportlab.pdfgen.canvas import Canvas
    c = Canvas(buf, pagesize=(width, height), pageCompression=1)
    c.setTitle(f"Tag {item['tag_no']}")
    c.setFont("Helvetica-Bold", 7); c.drawString(2 * mm, height - 4 * mm, settings.get("business_name", "Jewellery")[:32])
    c.setFont("Helvetica", 6.5); c.drawString(2 * mm, height - 7.5 * mm, f"{item['tag_no']}  {item['metal']} {item['purity']}")
    c.drawString(2 * mm, height - 11 * mm, f"GW {item['gross_weight']:.3f}g  NW {item['net_weight']:.3f}g")
    huid = item.get("huid") or ""
    if huid: c.drawString(2 * mm, height - 14.5 * mm, f"HUID {huid}")
    barcode = code128.Code128(str(item["barcode"]), barHeight=6 * mm, barWidth=0.27 * mm, humanReadable=False)
    barcode.drawOn(c, 2 * mm, 2.5 * mm); c.setFont("Helvetica", 5.5); c.drawCentredString(width * 0.66, 1.1 * mm, str(item["barcode"])[:30]); c.save()
    return buf.getvalue()


def invoice_pdf(sale: dict[str, Any], lines: list[dict[str, Any]], customer: dict[str, Any] | None, settings: dict[str, str], old_gold: list[dict[str, Any]] | None = None) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=12*mm, rightMargin=12*mm, topMargin=10*mm, bottomMargin=10*mm, title=sale["invoice_no"])
    styles = getSampleStyleSheet(); normal = ParagraphStyle("small", parent=styles["Normal"], fontSize=8, leading=10); right = ParagraphStyle("right", parent=normal, alignment=TA_RIGHT); center = ParagraphStyle("center", parent=normal, alignment=TA_CENTER)
    story = [Paragraph(f"<b>{settings.get('business_name','Jewellery Store')}</b>", ParagraphStyle("title", parent=styles["Title"], fontSize=15, leading=18))]
    if settings.get("business_address"): story.append(Paragraph(settings["business_address"], center))
    contact_bits = [x for x in [settings.get("business_phone"), f"GSTIN: {settings.get('business_gstin')}" if settings.get("business_gstin") else ""] if x]
    if contact_bits: story.append(Paragraph(" | ".join(contact_bits), center))
    story.append(Spacer(1, 4*mm)); cust = customer or {}
    header = Table([[Paragraph(f"<b>Tax Invoice</b><br/>Invoice: {sale['invoice_no']}<br/>Date: {sale['created_at'][:19].replace('T',' ')}", normal), Paragraph(f"<b>Customer</b><br/>{cust.get('name','Walk-in Customer')}<br/>{cust.get('phone','')}<br/>{cust.get('gstin','')}", normal)]], colWidths=[90*mm, 90*mm])
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


def stock_report_pdf(rows: list[dict[str, Any]], settings: dict[str, str], title: str = "Stock Report") -> bytes:
    buf=io.BytesIO();doc=SimpleDocTemplate(buf,pagesize=A4,leftMargin=8*mm,rightMargin=8*mm,topMargin=8*mm,bottomMargin=8*mm);styles=getSampleStyleSheet();story=[Paragraph(f"<b>{settings.get('business_name','Jewellery Store')}</b> - {title}",styles['Heading2']),Spacer(1,3*mm)];data=[["Tag","Item","Metal","Purity","GW","NW","HUID","Status"]]
    for r in rows:data.append([r['tag_no'],r['name'][:24],r['metal'],r['purity'],f"{r['gross_weight']:.3f}",f"{r['net_weight']:.3f}",r.get('huid') or '',r['status']])
    t=Table(data,repeatRows=1,colWidths=[25*mm,45*mm,20*mm,18*mm,18*mm,18*mm,30*mm,22*mm]);t.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.3,colors.grey),('BACKGROUND',(0,0),(-1,0),colors.lightgrey),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),7),('ALIGN',(4,1),(5,-1),'RIGHT')]));story.append(t);doc.build(story);return buf.getvalue()
