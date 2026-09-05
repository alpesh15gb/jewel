# JewelLAN

**Offline-first jewellery ERP/POS for Windows private LANs.**

JewelLAN is being built for jewellery showrooms that must continue billing even when the internet is unavailable. One Windows PC runs the central JewelLAN server and local SQLite database; counter/office PCs run JewelLAN POS and connect to the server over the shop's private LAN.

> **Release status:** current software line is **1.2.0-rc6** (Windows file version `1.2.0.5`). The automated Windows release pipeline is green, but JewelLAN is still a **release candidate under shop UAT**. Do not treat this README as a statement that the product is certified for live production billing yet.

## Current architecture

```text
Counter 1 JewelPOS.exe ----\
Counter 2 JewelPOS.exe -----+---- private LAN / HTTPS ---- JewelServer.exe ---- SQLite WAL DB
Office   JewelPOS.exe ------/                              |
                                                          +---- local verified backups
                                                          +---- Tally sync queue

Same-PC Tally option:
JewelServer.exe ---- local bridge ---- JewelTallyBridge.exe ---- localhost:9000 ---- TallyPrime
```

Important architecture rules:

- The SQLite database lives on the **server PC only**. Do not put the database on SMB/NAS/network shares.
- Counter/server traffic uses private-LAN HTTPS with a pinned self-signed JewelLAN server certificate.
- The server is not intended to be internet-facing. Do not port-forward TCP `8765` or UDP `8766`.
- TallyPrime remains localhost-only by default. `JewelTallyBridge.exe` is also loopback-only in the supported same-PC deployment.
- Optional internet features must be asynchronous/queued so loss of internet never stops billing.

---

# What is implemented

## 1. Windows installation and LAN operation

- Inno Setup Windows installer: `JewelLAN-Setup.exe`.
- Installer modes:
  - Server + Counter
  - Server + Counter + Tally Bridge
  - Server only
  - Counter only
  - Tally Bridge only
- Server binary/data under `C:\ProgramData\JewelLAN`.
- Windows Private-profile firewall rules for server TCP `8765` and discovery UDP `8766`.
- Automatic server startup through the Windows scheduled task **JewelLAN Server** running as SYSTEM.
- Automatic Tally bridge startup through the Windows scheduled task **JewelLAN Tally Bridge** when that component is installed.
- Reinstall/upgrade handling stops tasks/processes before replacing binaries.
- Database and backups are preserved on uninstall.
- LAN server discovery plus manual server-address entry.
- HTTPS server identity/fingerprint verification on counters.
- Saved server fingerprint mismatch blocks login instead of silently trusting a changed server.

## 2. Authentication and user controls

- Roles:
  - admin
  - manager
  - cashier
  - inventory
  - accounts
- Initial administrator account for a fresh installation.
- Mandatory first-password change before normal operations.
- Password/session hardening and login throttling.
- Password reset invalidates previous sessions.
- Role-aware navigation and endpoint permissions.
- Audit logging for important business/security operations.

## 3. Company setup and settings

JewelLAN is **company-neutral**. No jewellery shop name, state or number of counters is hard-coded into the product.

Implemented Company Setup / Company Settings include:

- Company/business name.
- Main branch/showroom name.
- GST state and state code.
- GSTIN.
- Address and PIN.
- Phone and email.
- Counter count.
- Invoice prefix.
- Tag/barcode prefix.
- Default GST rate.
- Business timezone.
- Editable settings after initial setup.

Fresh installations require company setup before normal billing can proceed.

## 4. Jewellery inventory master

- Serialized jewellery inventory.
- Tag number and barcode.
- RFID EPC field in the inventory data model.
- HUID field with six-character format validation.
- Certificate/reference field.
- Gold, silver and platinum.
- Purity.
- Gross weight.
- Stone weight.
- Net weight.
- Fine weight.
- Exact canonical integer storage for critical weights (milligrams) alongside display values.
- Server-side weight validation.
- Manager/admin override path for exceptional weight cases with a reason.
- Posted/sold item protections so historical business data cannot be silently rewritten.
- Code128 jewellery-tag PDF generation.

## 5. Jewellery pricing engine

The server is the pricing authority. Current pricing supports:

- Metal rate per gram.
- Wastage percentage.
- Making charge:
  - per gram
  - percentage
  - fixed
- Stone value.
- Invoice discount allocation.
- GST.
- Invoice round-off.
- Exact paise-based financial mirrors and deterministic `ROUND_HALF_UP` handling.

The RC5 billing screen now exposes the calculation instead of hiding important jewellery components. The invoice grid/formula view includes:

- net weight
- rate per gram
- metal value
- wastage %
- wastage value
- making charge
- stone value
- allocated discount
- taxable value
- GST
- line total
- invoice round-off
- final invoice amount

Invoice discount now re-quotes automatically and is quoted again immediately before posting.

### Verified RC5 calculation example

For the UAT case that exposed the earlier confusing UI:

```text
Net weight             3.765 g
Metal rate             ₹14,550.00 / g
Metal value            ₹54,780.75
Wastage                 9.00%
Wastage value          ₹4,930.27
Making                 ₹7,530.00
Stone                   ₹5,000.00
---------------------------------
Taxable before discount ₹72,241.02
GST @ 3%               ₹2,167.23
Gross                  ₹74,408.25
Round-off              -₹0.25
Invoice total          ₹74,408.00
```

With a ₹1,000 invoice discount:

```text
Taxable                ₹71,241.02
GST @ 3%               ₹2,137.23
Gross                  ₹73,378.25
Round-off              -₹0.25
Invoice total          ₹73,378.00
```

Regression tests cover both calculations.

## 6. POS billing and payments

- Barcode/tag-first billing workflow.
- USB HID barcode scanners work as keyboard input when configured to append Enter.
- Multiple serialized items per invoice.
- Customer selection including walk-in customer.
- Split payments:
  - cash
  - card
  - UPI
  - customer credit
- Old-gold exchange/payment entry.
- Exact payment-total checks before posting.
- Atomic sale posting.
- Idempotency key/duplicate-sale protection.
- Multi-counter stock race protection.
- GST invoice PDF.
- Full invoice cancellation with stock/accounting reversal when allowed.

## 7. Item-level returns and GST credit notes

- Find original posted sale/invoice.
- Select one or more serialized sold tags for return.
- Prevent returning the same serialized sale item twice.
- Credit-note calculation from original sale values rather than current metal rates.
- Exact taxable/GST reversal values.
- Returned serialized stock is restored through an auditable stock movement.
- Refund split support.
- Credit-note PDF.
- Recent credit-note view.
- Controlled credit-note cancellation/reversal.
- Original-sale cancellation conflicts with existing item returns are blocked.
- Tally reversal/credit-note queue support.

## 8. Purchases and stock-in

- Supplier purchase entry.
- Tagged/serialized item creation from purchases.
- Purchase accounting entries.
- Posted purchase records protected from silent historical mutation.

## 9. Customers, suppliers, karigars and jewellery workflows

Implemented baseline modules include:

- Customers.
- Suppliers.
- Karigars.
- Karigar metal/cash ledger API.
- Repairs.
- Custom orders.
- Approval/Jangad issue and return API.
- Customer receivable balance support.

## 10. Physical stock audit

- Physical inventory audit sessions.
- Barcode/RFID EPC scan data path.
- Comparison of scanned stock against system stock.

RFID EPC is present in the model/audit workflow; direct vendor-reader SDK integration is **not** complete (see Remaining Work).

## 11. Accounting and reports

- Double-entry journals.
- Journal balance validation in exact paise.
- Trial balance.
- Ledger report.
- Sales summary/reporting.
- Payment reporting.
- Stock reporting.
- Day-close/integrity checks.
- Customer receivable posting.
- Sales/COGS/inventory journal posting.
- Purchase accounting posting.
- Sale cancellation reversals.
- Credit-note/return reversals.

## 12. TallyPrime integration

Optional `JewelTallyBridge.exe` is implemented for TallyPrime accounting synchronization.

Current integration includes:

- JewelLAN remains the source of truth for serialized jewellery stock.
- Tally is treated as the accounting/statutory system of record where configured.
- Sales are committed to JewelLAN before Tally sync.
- Tally outages do not block billing.
- Durable synchronization queue in the JewelLAN database.
- Stable REMOTEID values.
- Exponential retry.
- Tally XML response validation.
- Day Book reconciliation support.
- Configurable ledger mappings.
- Party/debtor/creditor handling.
- Sale voucher export.
- COGS/inventory journal export.
- Purchase export.
- GST CGST/SGST/IGST mapping support.
- Cancellation/reversal handling.
- Return/credit-note support.

See `docs/TALLY_INTEGRATION.md`.

## 13. Database integrity and recovery

- SQLite foreign keys enabled.
- WAL mode.
- `synchronous=FULL`.
- Busy timeout.
- Process write lock plus `BEGIN IMMEDIATE` write transactions.
- Schema migrations.
- Exact integer mirrors for money/weight-critical values.
- Triggers/guards protecting immutable posted records.
- Append-only stock/sale/journal/audit-oriented controls.
- SHA-256 chained audit records for tamper evidence.
- Data Health / integrity administration screen.
- Automatic local backups.
- Manual backup.
- Backup SHA-256 manifest/status verification.
- Restore with safety backup.
- Database integrity checks.

The audit chain is **tamper-evident**, not tamper-proof; there is currently no external/HMAC audit anchor.

## 14. Hardware currently supported

- USB HID barcode scanners.
- Windows printers through generated PDF labels/invoices.
- USB/serial COM weighing scale reader.
- RFID EPC field/storage/audit data path.

## 15. Build and automated testing

The Windows CI pipeline currently performs:

- Python compilation.
- Source import validation.
- Desktop GUI smoke tests.
- Automated server/business-logic tests.
- TLS/pinned-certificate regression tests.
- Company setup/settings tests.
- Exact jewellery pricing regression tests.
- Return/credit-note tests.
- Tally tests.
- Server EXE build.
- JewelPOS EXE build.
- Tally Bridge EXE build.
- Packaged executable self-tests.
- Inno Setup installer build.
- Portable developer package build.
- Artifact upload.

---

# Known gaps / remaining work

This section is intentionally explicit. These items should not be hidden behind a statement that the application is "finished".

## P0 — Metal-rate workflow must be improved before live use

**Current state:** manual metal-rate creation exists, and historical sales preserve the rate used at posting.

**Known gap discovered during UAT:** after entering a rate, the operator workflow for correcting/amending the current rate is not good enough for a real jewellery showroom. Gold and silver rates change frequently and sometimes more than once per day.

Required production design:

- Daily rate book/dashboard.
- Gold, silver and platinum current rate cards.
- Effective date/time on every rate revision.
- Multiple revisions per business day.
- Manual **Set new rate / Correct current rate** workflow.
- Never rewrite the rate stored on already-posted historical invoices.
- Rate revision history with user/time/source/audit trail.
- Day-opening "confirm today's rates" workflow.
- Optional manager approval rule for large rate changes.
- Purity/rate derivation policy made explicit (for example base 24K/999 and derived display rates where appropriate).
- Optional online **Sync Rates** adapter with provider/source recorded on each imported rate.
- Manual entry must always remain available if the internet/provider is down.
- Online rate synchronization must never block POS billing.
- No external provider will be trusted blindly; operator should be able to review/accept a synchronized rate before it becomes the shop rate.

**No production live-gold/silver-price provider/API is integrated yet.** A provider must be selected and its commercial terms, India coverage, units, taxes/premiums and update frequency validated before implementation.

## P0 — Full jewellery-workflow/UI audit

RC5 substantially improves Billing, but UAT has already shown that a technically implemented backend feature can still have an incomplete operator workflow.

Before go-live every screen needs a real jeweller workflow review for:

- create
- view
- edit/amend where legally/business-appropriate
- cancel/reverse instead of destructive editing
- search/filter
- keyboard/scanner operation
- confirmation/error messages
- audit history visibility
- sensible defaults
- no hidden price components
- no clipped controls at common Windows resolutions/DPI settings

Priority screens: Rates, Inventory, Billing, Returns, Purchases, Customers, Karigars, Repairs, Approvals, Stock Audit, Reports, Backups and Administration.

## P0 — Physical shop UAT is still required

Automated CI cannot certify actual showroom hardware or Windows network behaviour. Before first live invoice, test:

- Main server PC plus at least two simultaneous counter PCs.
- LAN disconnect/reconnect while counters are open.
- Two counters attempting to sell the same tag.
- Windows restart with server scheduled-task recovery.
- Unexpected server power loss/reboot recovery.
- Actual barcode scanner.
- Actual jewellery tag printer/label stock.
- Actual invoice printer/PDF layout.
- Actual weighing scale and serial protocol.
- Backup to separate physical media.
- Full restore drill from that backup.
- TallyPrime test company sync/reconciliation.
- Return/credit-note flow after original sale.
- Day close after mixed cash/card/UPI/credit transactions.

## P0 — Accounting/GST validation by a practising CA/accountant

Software tests verify internal arithmetic and double-entry balance; they do not replace statutory review.

Still required:

- GST invoice wording/layout review.
- CGST/SGST/IGST scenario review.
- Credit-note/return treatment review.
- Old-gold purchase/exchange accounting review.
- Customer-credit treatment review.
- Purchase accounting review.
- Tally ledger mapping review.
- Tally test-company reconciliation against expected books.

## P1 — Opening-stock/bulk import

Implemented in rc6: Inventory → Bulk CSV with preview, per-row validation, duplicate detection, weight-equation checks, atomic all-or-nothing post via `/api/opening-stock`, batch reference + audit record, row-numbered error report. XLSX template and current-stock export remain future polish. Performance script: `python scripts/bulk_perf_check.py --count 2000`.

Target requirements:

- CSV/XLSX import template.
- Preview before commit.
- Validate every row before writing anything.
- Duplicate tag/barcode/HUID detection.
- Weight-equation validation.
- Atomic all-or-nothing import.
- Import batch ID and audit record.
- Error report with row numbers.
- Current-stock export.
- Performance test with thousands of tagged items.

## P1 — Dedicated exchange workflow

Implemented in rc6: Exchange page links original return/credit note → exchange credit → new sale → net balance with audit trail and Tally entries. Item return/credit note is implemented, and a replacement item can be sold separately. A polished one-screen **Exchange** workflow should still link:

1. original sale return/credit note;
2. exchange credit;
3. new replacement sale;
4. balance/refund collection;
5. audit trail and Tally entries.

The original invoice must remain immutable.

## P1 — Branch/multi-showroom workflows

Branch/counter concepts exist, but production multi-showroom operation still needs dedicated work if JewelLAN is deployed across multiple physical locations, including:

- inter-branch stock transfer;
- goods-in-transit;
- branch-wise permissions;
- branch rate policy;
- consolidated reporting;
- conflict/reconnect strategy across separate sites.

The current supported topology is a **single private LAN/site**.

## P1 — Direct RFID integration

Still vendor-specific and not implemented end-to-end.

Required after choosing actual hardware:

- reader vendor/model;
- SDK/driver;
- EPC read filtering/debounce;
- bulk tray scan workflow;
- error/offline handling;
- physical stock-audit test.

## P1 — Direct label-printer command support

Implemented in rc6: offline PDF + native ZPL (Zebra) + TSPL (TSC) generation with same mm sizing, single + bulk (max 100), Serial COM / TCP 9100 direct send or file save. Must still be tested against the actual printer model and tag stock before being claimed as supported for that model.

## P1 — Weighing-scale hardware qualification

USB-COM reading exists, but every scale manufacturer uses its own framing/protocol/settings. Actual shop scale model(s) still need protocol qualification and physical UAT.

## P1 — Optional internet connectors

Not yet production-integrated:

- GST e-invoice provider/API.
- E-way bill provider/API where applicable.
- WhatsApp/SMS notifications.
- Payment/UPI reconciliation.
- Live metal-rate provider.
- Cloud/off-site backup replication.

These must remain **optional queued adapters**. Internet failure must never disable local billing/inventory.

## P1 — BIS/HUID online verification

JewelLAN stores HUID and validates its local format. It does **not** currently claim direct BIS/HUID online verification.

Any future BIS integration must use an official/authorized mechanism and must not prevent offline billing when the online service is unavailable.

## P1 — Code signing

The current Windows installer/executables are not Authenticode-signed, so Windows SmartScreen may display **Unknown publisher**.

Before broad production distribution:

- obtain organisation code-signing certificate;
- sign EXEs and installer;
- timestamp signatures;
- verify signature in the release pipeline.

## P2 — Audit-chain strengthening

Current SHA-256 chaining is useful for detecting ordinary record tampering but is not a cryptographic external proof.

Potential future hardening:

- keyed HMAC signing;
- external daily audit anchor;
- write-once/off-device integrity report.

---

# Metal-rate design principle

Metal rates are **effective-dated business inputs**, not values that should be overwritten in historical invoices.

The intended model is:

```text
Rate revision
-------------
metal            Gold / Silver / Platinum
purity/base       configured rate basis
rate_per_gram     exact current business rate
effective_from    business date + time
source            manual / provider name
created_by        user
audit timestamp
status            active/superseded
```

When an item is quoted/sold, the price calculation should copy the applicable rate into the sale line. Later changing today's shop rate must affect **new quotes only**, never previous posted invoices or returns derived from those invoices.

---

# Installation

Download the latest successful **main** branch `JewelLAN-Installer` artifact from GitHub Actions and run:

```text
JewelLAN-Setup.exe
```

No PowerShell commands are required for a normal installation.

Typical main-PC setup:

```text
Server + Counter + Tally Bridge
```

Additional billing PCs:

```text
Counter only
```

On each counter, open JewelLAN POS and choose **Discover**. If discovery is unavailable, enter the server's private LAN HTTPS address manually, for example:

```text
https://192.168.1.20:8765
```

The first connection displays/verifies the JewelLAN server certificate fingerprint before trusting that server.

**Fresh-install initial account:**

```text
Username: admin
Password: Jewel@123
```

The first login requires changing the initial password, followed by company setup on an unconfigured database.

> The current installer is not digitally signed. SmartScreen/Unknown Publisher warnings are expected during release-candidate testing.

---

# Run from source

Requires Python 3.11+.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest -q
python run_server.py
```

Then on another terminal/PC:

```bash
python run_client.py
```

Production Windows server data defaults to:

```text
C:\ProgramData\JewelLAN
```

---

# Backups and recovery

Automatic backups are created on the server. Backup verification includes SHA-256 metadata. Restore creates a safety backup first.

For production use, maintain at least one backup copy on a **different physical device** and perform a real restore drill before go-live.

See `docs/OPERATIONS.md` and `docs/PRODUCTION_ACCEPTANCE.md`.

---

# Security notes

- Private LAN only.
- HTTPS certificate pinning between JewelPOS and JewelServer.
- Do not expose JewelServer directly to the public internet.
- Do not put the SQLite database on a Windows network share.
- Do not disable certificate checks as a workaround for LAN problems.
- Tally bridge uses bearer authentication and is loopback-only in the supported same-PC configuration.
- Audit chains are tamper-evident, not tamper-proof.

---

# Product status summary

| Area | Status |
|---|---|
| Windows installer | Implemented / CI tested |
| Private-LAN HTTPS | Implemented / CI tested |
| Company setup/settings | Implemented / UAT ongoing |
| Serialized jewellery inventory | Implemented / UAT ongoing |
| Barcode POS | Implemented / UAT ongoing |
| Jewellery calculation engine | Implemented / regression tested |
| Billing calculation visibility | Implemented in RC5 / UAT ongoing |
| Split payments | Implemented / UAT ongoing |
| Old gold | Implemented baseline / CA + UAT review required |
| Returns / GST credit notes | Implemented / UAT ongoing |
| Purchases | Implemented baseline / UAT ongoing |
| Repairs/custom orders | Implemented baseline / UAT ongoing |
| Approval/Jangad | Backend/API baseline / UI workflow review required |
| Karigar ledger | Backend/API baseline / UI workflow review required |
| Physical stock audit | Implemented baseline / hardware UAT required |
| Accounting journals/reports | Implemented baseline / CA validation required |
| TallyPrime bridge | Implemented / Tally test-company UAT required |
| Backup/restore/integrity | Implemented / physical restore drill required |
| Manual metal rates | Implemented baseline |
| Rate amendment/day-opening workflow | **Remaining P0** |
| Live gold/silver rate sync | **Not implemented** |
| Bulk opening-stock import | Implemented rc6 (CSV preview + atomic) / XLSX + export polish left |
| Dedicated exchange wizard | Implemented rc6 / shop UAT ongoing |
| Direct RFID SDK | **Not implemented** |
| Native ZPL/TSPL printing | Implemented rc6 (PDF+ZPL+TSPL offline) / model-specific UAT required |
| E-invoice/e-way bill adapters | **Not implemented** |
| WhatsApp/payment reconciliation | **Not implemented** |
| Direct BIS/HUID online verification | **Not implemented** |
| Authenticode code signing | **Remaining before broad distribution** |
| Real showroom go-live certification | **Not complete** |

---

# Definition of done for live use

JewelLAN should only move from release candidate to a live-production release after all of the following are true:

1. P0 workflow defects found during UAT are closed, especially metal-rate lifecycle and critical operator screens.
2. The exact release commit passes the complete Windows CI/packaging pipeline.
3. Real multi-counter private-LAN UAT passes.
4. Actual scanner/printer/scale hardware passes.
5. Backup + restore drill passes on another physical device.
6. Tally reconciliation passes in a test company where Tally is used.
7. GST/accounting treatment is reviewed by the shop's practising CA/accountant.
8. No unresolved release-blocking data-integrity, stock, pricing, payment or recovery defect remains.

Until those gates are complete, JewelLAN should be described as a **production-oriented release candidate**, not as a production-certified jewellery ERP.

---

See also:

- `docs/PRODUCT_SPEC.md`
- `docs/OPERATIONS.md`
- `docs/PRODUCTION_ACCEPTANCE.md`
- `docs/TALLY_INTEGRATION.md`
