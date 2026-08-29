# JewelLAN product specification

JewelLAN is a jewellery-first ERP/POS designed for a showroom that may have **no internet connection at all**. One Windows computer owns the database and runs the API server. Counter PCs connect to it over the private LAN. Clients never open the SQLite file directly, which avoids the corruption and locking problems caused by placing SQLite on a Windows network share.

## Product research

The workflow was informed by public feature descriptions and screenshots from Omunim/Online Munim (accessed August 2026), without using or copying their proprietary code or assets:

- https://omunim.com/
- https://omunim.com/jewellery-billing-software
- https://omunim.com/rfid-for-jewellery
- https://omunim.com/jewellery-software-free-demo

Useful patterns from that research are: fast jewellery-specific billing; serialized tags with barcode/QR/RFID; gross/net/stone weights; HUID; weighing-scale capture; touch-friendly POS; role-based staff access; customer history; karigar workflows; repairs; approvals/Jangad; physical stock tally; GST reports; accounting; multi-counter and multi-branch visibility. Omunim also advertises online/e-commerce/WhatsApp/payment integrations. JewelLAN intentionally treats those as optional future integrations because the core requirement here is operation with the internet disconnected.

## Architecture

```text
                    PRIVATE SHOP LAN (no internet required)

       Counter PC 1        Counter PC 2       Office PC / Laptop
       JewelPOS.exe         JewelPOS.exe       JewelPOS.exe
            |                    |                    |
            +--------------------+--------------------+
                                 |
                         TCP 8765 / HTTP API
                                 |
                      Windows server / main PC
                           JewelServer.exe
                                 |
                         one SQLite database
                           WAL + FULL sync
                                 |
                         automatic backups

USB barcode scanners and COM-port weighing scales attach to the counter PCs.
Barcode/label and invoice PDFs are generated from the central server and opened
on the counter PC so that each counter can use its own Windows printers.
```

### Why central SQLite instead of a shared `.db` file?

SQLite is reliable when a single server process owns the database. A SQLite file placed directly on an SMB/network share is not appropriate for a busy multi-counter POS. JewelLAN therefore serializes writes in the server process, uses `BEGIN IMMEDIATE`, WAL journaling, `synchronous=FULL`, foreign keys, a busy timeout, idempotency keys on sales/purchases, and atomic stock-status transitions. If a shop later grows beyond the practical scale of this architecture, the API boundary permits migration to PostgreSQL without changing counter workflows.

## Implemented workflows

### Inventory and tags

Each physical jewellery piece is serialized. The item record contains tag number, barcode, optional RFID EPC, category/design name, metal, purity, gross/stone/net/fine weight, cost, stone value, making type/value, wastage, HUID, certificate, GST/HSN, branch/counter and status. The system records every stock movement and prevents the same item being sold from two counters at once.

Code128 label PDFs contain business name, tag, metal/purity, gross/net weight, HUID and barcode. Common USB scanners work as keyboard devices, so scanning does not depend on a vendor SDK.

### POS / GST billing

The counter scans serialized tags. Pricing is derived on the server from the latest metal rate, net weight, wastage, making charge, stones and GST. Invoice-level discounts are allocated back to lines so line GST reconciles with invoice GST. Payments can be split among cash, card, UPI, credit and old-gold exchange. Posting a sale is one database transaction: invoice, sale lines, stock status, stock movements, customer balance and accounting journal either all succeed or all roll back.

Sales carry a client request UUID. If a counter loses LAN connectivity after pressing Post and retries, the server returns the already-created invoice instead of creating a duplicate.

### Old gold

Old-gold exchange records metal, purity, gross weight, deduction, computed fine weight, rate and value. Its value is treated as a payment against the new invoice and posted to Old Gold Inventory in accounting.

### Purchasing

A supplier purchase can receive one or more serialized jewellery pieces, create tags and stock movements, update supplier payable balance and post inventory/input-GST/cash/payable journal lines.

### Repairs and custom orders

Repairs track customer, item description/tag, weight, received/promised dates, karigar, estimate/advance/final amount and statuses from received through delivered. Custom orders track metal/purity, target weight, karigar, amount/advance/due date and work status.

### Karigar ledger

The database supports metal issue/receive entries, making charges and cash debit/credit with separate metal-weight and cash balances.

### Approval / Jangad

Items can leave the showroom on approval. Their stock status changes to `approval`, preventing sale at a different counter. Returned items go back to stock and the approval closes automatically when nothing is outstanding.

### Physical stock audit

An audit accepts barcode/RFID scans from the counter. Reconciliation identifies missing expected pieces and extra/misplaced scanned pieces.

### Accounting and reports

Sales and purchases post double-entry journals. The application exposes sales/payment summaries, stock quantity/weight/cost by metal/purity, trial balance, individual account ledger and a printable stock PDF. Default accounts cover cash, bank/card/UPI, receivables, jewellery inventory, old-gold inventory, supplier payables, GST output/input, equity, sales and COGS.

### Security and audit

Passwords use PBKDF2-HMAC-SHA256 with per-user random salts. Sessions expire, roles restrict APIs, first login requires a password change, and administrative/business events are written to an append-only audit log. The server should only be allowed on a Windows **Private** network profile and must not be port-forwarded to the internet.

### Backups

SQLite online backup API is used while the system is running. Backups are automatically created according to server settings and old backups are pruned by retention. Manual backup is available from the client. Restore is intentionally performed on the server while the application is offline using `JewelServer.exe --restore <backup.db>`.

## Deliberately not dependent on the internet

Core billing, tagging, stock, accounting, repairs, orders, approvals, reports, authentication, LAN discovery, scale input and backups have no cloud dependency. GST e-invoice submission, WhatsApp/SMS, payment-gateway reconciliation, BIS lookups and live metal-rate feeds cannot be truly offline by definition; they should be implemented as optional connectors that queue work and never block shop operations.

## Hardware interface policy

- **Barcode scanner:** USB HID/keyboard mode, Enter suffix recommended.
- **Label printer:** any Windows printer capable of printing the generated label PDF; Zebra/TSC can be added later through direct ZPL/TSPL adapters.
- **Invoice printer:** A4/thermal through the Windows PDF printing stack.
- **Weighing scale:** serial/USB-COM. Configure COM port and baud rate per workstation. The parser accepts common ASCII scale output and can be extended in `jewel_client/scale.py` for a specific model.
- **RFID:** data model and stock-audit scan path already accept EPC strings. Vendor-reader SDK integration is hardware-specific and belongs in a workstation adapter, not in core business logic.
