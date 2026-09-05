"""Offline native thermal label commands for jewellery tags.

ZPL (Zebra) and TSPL (TSC/Argox) are generated locally — no internet, no driver.
Sizes come from settings label_width_mm/label_height_mm (mm). Density 8 dots/mm (203dpi).
Content: business (truncated), tag + metal/purity, GW/NW, HUID, Code128 barcode, QR tag|barcode|net.
"""
from __future__ import annotations
from typing import Any

def _size_mm(settings: dict[str, str]) -> tuple[float, float]:
    try:w = max(30, min(100, float(settings.get("label_width_mm", 60))))
    except Exception:w = 60
    try:h = max(15, min(60, float(settings.get("label_height_mm", 25))))
    except Exception:h = 25
    return w, h

def _txt(v: Any, n: int) -> str:
    # ZPL/TSPL: strip command-breaking chars including newlines (injection safe).
    s = str(v or "").replace("^", "").replace('"', "").replace("\\", "").replace("\n", " ").replace("\r", " ").strip()
    return s[:n]

def _weights(item: dict[str, Any]) -> tuple[float, float]:
    try:gw = float(item.get("gross_weight", 0)); nw = float(item.get("net_weight", 0))
    except Exception:raise ValueError("Tag weights must be numeric")
    if gw < 0 or nw < 0:raise ValueError("Tag weights cannot be negative")
    return gw, nw

def zpl_label(item: dict[str, Any], settings: dict[str, str]) -> str:
    w_mm, h_mm = _size_mm(settings)
    w, h = int(w_mm * 8), int(h_mm * 8)  # dots @203dpi
    biz = _txt(settings.get("business_name", "Jewellery"), 28)
    tag = _txt(item.get("tag_no"), 24)
    if not tag:raise ValueError("Tag number is required")
    metal = _txt(f"{item.get('metal','')} {item.get('purity','')}", 20)
    gw, nw = _weights(item)
    huid = _txt(item.get("huid") or "", 12)
    barcode = _txt(item.get("barcode") or tag, 30)
    if not barcode:raise ValueError("Barcode is required")
    qr = _txt(f"{tag}|{barcode}|{nw:.3f}g", 60)
    y = 8
    L = ["^XA", f"^PW{w}", f"^LL{h}", "^LH0,0", "^PR2", "^MD10"]
    L.append(f"^FO8,{y}^A0N,22,22^FD{biz}^FS"); y += 26
    L.append(f"^FO8,{y}^A0N,24,24^FD{tag} {metal}^FS"); y += 28
    L.append(f"^FO8,{y}^A0N,22,22^FDGW {gw:.3f}g NW {nw:.3f}g^FS"); y += 26
    if huid:
        L.append(f"^FO8,{y}^A0N,20,20^FDHUID {huid}^FS"); y += 24
    # Code128 barcode left, QR right (only if label tall enough for both, same 30mm rule as PDF).
    by = max(y + 2, h - 78)
    if by + 52 > h - 4:by = max(4, h - 56)  # shrink into tiny stock instead of overlap
    L.append(f"^FO8,{by}^BCN,48,Y,N,N^FD{barcode}^FS")
    if h_mm >= 30:
        L.append(f"^FO{w-92},{by}^BQN,2,4^FDQA,{qr}^FS")
    L.append("^XZ")
    return "\n".join(L) + "\n"

def tspl_label(item: dict[str, Any], settings: dict[str, str]) -> str:
    w_mm, h_mm = _size_mm(settings)
    biz = _txt(settings.get("business_name", "Jewellery"), 28)
    tag = _txt(item.get("tag_no"), 24)
    if not tag:raise ValueError("Tag number is required")
    metal = _txt(f"{item.get('metal','')} {item.get('purity','')}", 20)
    gw, nw = _weights(item)
    huid = _txt(item.get("huid") or "", 12)
    barcode = _txt(item.get("barcode") or tag, 30)
    if not barcode:raise ValueError("Barcode is required")
    qr = _txt(f"{tag}|{barcode}|{nw:.3f}g", 60)
    L = [f'SIZE {w_mm:.0f} mm,{h_mm:.0f} mm', "GAP 2 mm,0", "DIRECTION 1", "CLS"]
    L.append(f'TEXT 12,8,"0",0,1,1,"{biz}"')
    L.append(f'TEXT 12,34,"0",0,1,1,"{tag} {metal}"')
    L.append(f'TEXT 12,60,"0",0,1,1,"GW {gw:.3f}g NW {nw:.3f}g"')
    y = 86
    if huid:
        L.append(f'TEXT 12,{y},"0",0,1,1,"HUID {huid}"'); y += 26
    L.append(f'BARCODE 12,{y},"128",52,1,0,2,2,"{barcode}"')
    if h_mm >= 30:
        # QR on right side, x ~= width-110 dots (same 30mm rule as PDF/ZPL).
        x = max(200, int(w_mm * 8) - 110)
        L.append(f'QRCODE {x},{y},H,4,A,0,"{qr}"')
    L.append("PRINT 1")
    return "\n".join(L) + "\n"

def bulk_zpl(items: list[dict[str, Any]], settings: dict[str, str]) -> str:
    return "".join(zpl_label(it, settings) for it in items)

def bulk_tspl(items: list[dict[str, Any]], settings: dict[str, str]) -> str:
    # TSPL: repeat full job per tag (simplest, works on TSC/Argox).
    return "".join(tspl_label(it, settings) + "\n" for it in items)
