# Bijoria go-live configuration

This document is the clean-start deployment profile for Bijoria.

- Business: Bijoria
- State: Telangana
- GST state code: 36
- Business timezone: IST (UTC+05:30 / +330 minutes)
- Windows PCs: 3
- Main PC: JewelLAN Server + JewelLAN POS + TallyPrime + JewelLAN Tally Bridge
- Counter PCs: 2 x JewelLAN POS
- Core operation: offline private LAN; no Internet dependency for billing/inventory
- TallyPrime integration endpoint on main PC: localhost:9000
- JewelLAN Tally Bridge: localhost:8767 by default
- JewelLAN Server: private LAN port 8765 with TLS and certificate pinning
- LAN discovery: UDP 8766 on Windows Private network only

## First-day setup order

1. Install Server + Counter + Tally Bridge on the main PC.
2. Install Counter only on the two counter PCs.
3. Verify and trust the JewelLAN server certificate fingerprint on each counter.
4. Change the initial administrator password and create individual named users.
5. Enter Bijoria legal address, phone and GSTIN when available; keep GSTIN blank until the correct value is known.
6. Confirm business state code 36 and timezone offset +330.
7. Configure invoice/tag prefixes and the financial-year policy with the accountant.
8. Configure the exact Tally company and ledger mappings; test with Tally sync disabled until Test succeeds.
9. Configure metal/purity masters and current rates.
10. Enter opening stock with tag/barcode, gross/stone/net weight and HUID where applicable.
11. Print and scan sample labels; validate the actual printer/scanner/weighing scale.
12. Complete the production acceptance checklist before issuing live invoices.

Do not expose ports 8765, 8766, 8767 or 9000 to the public Internet and do not configure router port-forwarding for JewelLAN or TallyPrime.
