# JewelLAN Jewellery ERP Completeness Audit

This document is the product-completeness checklist for a real Indian jewellery showroom. It is intentionally stricter than a generic POS feature list. A module is not considered complete merely because an API exists; the operator workflow, permissions, auditability, reports, recovery behavior and Windows UI must also exist.

## Research basis

Public workflow references reviewed for this audit include:

- India Bullion and Jewellers Association (IBJA) daily benchmark Gold/Silver rates and API documentation: https://www.ibjarates.com/ and https://indiagoldratesapi.com/Documentation.aspx
- Online Munim / Omunim jewellery workflows: daily metal rates, bhav cut, old gold, karigar, repairs, approvals, RFID/barcode, GST/e-invoicing, day book and daily cash reports: https://omunim.com/
- GehnaERP: jewellery billing, live rates, HUID/tagging, karigar/order, returns, stock, loyalty/schemes and reports: https://www.gehnaerp.com/
- Aurex ERP: daily rate control, chronological rate history, karigar metal ledger, repairs and day closing: https://www.aurexerp.com/
- BIS hallmarking/HUID public guidance: https://www.bis.gov.in/hallmarking-overview/hallmarking-faqs/hallmarking-faq/?lang=en

These are workflow references only. JewelLAN does not copy proprietary code, assets or branding.

## Product rule

JewelLAN remains offline-first. Internet-dependent functions such as market-rate reference sync, e-invoice, WhatsApp and payment reconciliation must be optional adapters. Billing, inventory, local reports, user authentication, backups and Tally queueing must continue to work when the internet is unavailable.

## P0 — required before live showroom billing

| Area | Required operator workflow | Current state after RC6 rate work | Gate |
|---|---|---|---|
| Company setup | Editable legal/shop identity, GST state, counters, invoice/tag prefixes | Implemented | UAT |
| Daily rates | Change rates any time, append-only history, visible current board, stale warning | RC6 implements board/history | CI + UAT |
| Market reference | Optional IBJA reference sync, never silently overwrite shop rates | RC6 implements manual sync/review/apply | CI + subscribed-token UAT |
| Billing | Barcode-first invoice, transparent metal/wastage/making/stone/GST/round-off | Implemented RC5 | UAT |
| Rate-change safety | No silent price change between quote and final post | Needs explicit quote/rate lock | BLOCKER |
| Sales history | Find invoice, view, reprint, payment breakdown, controlled cancel/return | Backend partial; desktop workflow incomplete | BLOCKER |
| Returns | Item-level return/credit note, exact historical tax/value reversal | Implemented | UAT |
| Customers | Create, edit, search, GSTIN/contact, dues/receipts/advances | Create exists; edit/receipt workflow incomplete | BLOCKER |
| Inventory | Create/edit unsold tag, barcode, HUID, weights, status, label | Implemented core | UAT |
| Opening stock | CSV preview/validate/atomic import plus export | Missing | BLOCKER for first stock load |
| Stock movement | Counter/branch transfer UI with movement history | Backend exists; desktop workflow incomplete | BLOCKER if >1 location |
| Purchases | Supplier stock-in, GST/cost, document history, cancellation/return controls | Basic stock-in only | BLOCKER for regular purchasing |
| Old gold | Assay, deduction, reference/shop rate, value, separate old-gold stock/accounting | Basic sale exchange exists; rate/audit workflow needs hardening | BLOCKER |
| Cash/day close | Opening cash, receipts/payments, expenses, tender reconciliation, close/reopen control | Day-close report exists; cashier workflow missing | BLOCKER |
| Backups | Automatic + manual verified backups, visible status, restore drill | Backend implemented; desktop restore/status UX limited | UAT |
| Roles/audit | Admin/manager/cashier/inventory/accounts with audit trail | Implemented core | UAT |
| Concurrency | Two counters cannot sell/return same tag twice | Implemented/tested | 3-PC UAT |
| TallyPrime | Durable async sync, reconciliation, outage never blocks billing | Implemented core | Tally test-company UAT |
| Printer/scanner/scale | HID barcode, invoice/tag print, USB-COM scale | Core available | Physical UAT |

## P1 — jewellery-business completeness

| Area | Required workflow | State |
|---|---|---|
| Karigar/job work | Metal issue/receipt, fine-weight balance, wastage/tunch, labour settlement, job status | Backend foundations exist; desktop ledger workflow incomplete |
| Approval/Jangad | Issue tagged items, partial return, sale conversion, overdue list | Backend foundations exist; desktop workflow incomplete |
| Repairs | Receipt, image/description, weight, karigar, estimate, advance, delivery, receipt print | Basic workflow exists; needs detail/edit/payment UX |
| Custom orders | Estimate, advance, metal/purity/target weight, karigar, delivery settlement | Basic workflow exists; needs richer settlement UX |
| Supplier/party ledger | Purchases, payments, metal/cash balances, outstanding aging | Partial |
| Customer ledger | Sales, returns, receipts, advances and statements | Partial |
| Expenses | Cash/bank expense entry, categories and day-book impact | Missing |
| Schemes/loyalty | Gold savings/chit instalments, maturity/redemption, loyalty earn/redeem | Missing |
| Diamonds/gemstones | 4Cs, certificate, pieces/carat, stone costing and pricing | Certificate/stone value basic only |
| Multiple branches | Branch-specific rate policy, transfers and consolidated reporting | Data model foundations; branch-rate policy incomplete |
| Stock ageing/profit | Age buckets, GP by item/category/metal, dead stock | Minimal reports |
| Estimates/quotations | Non-posting estimate with expiry/rate snapshot and convert-to-sale | Missing |

## P2 — optional connected adapters

- GST e-invoice/e-way bill provider adapter where legally/applicably required. Core billing must not depend on it.
- WhatsApp/SMS sharing via configured provider.
- Payment gateway/UPI reconciliation.
- Direct RFID reader SDK integration after actual hardware/SDK selection.
- Remote/mobile dashboard only if it can be added without weakening the offline core.

## Daily rate design

A jewellery shop rate is a business decision, not merely a market feed. JewelLAN therefore keeps two concepts separate:

1. **Reference rate** — optional market benchmark such as IBJA.
2. **Shop rate** — the rate actually used for billing.

A reference sync must never silently reprice billing. An operator reviews the reference and explicitly applies it, optionally adding a premium/adjustment and rounding rule. Manual shop-rate entry always remains available offline. Every shop-rate change appends a new historical row rather than rewriting an older row.

IBJA publishes benchmark Gold and Silver rates, with Gold represented per 10 g and Silver per kg on its public rate site. Its API documentation describes a paid token-authenticated API, production/UAT endpoints and two daily updates. JewelLAN converts received references to INR per gram before presenting them for application.

## Release discipline

No release candidate is called production-ready until all P0 software blockers are closed, Windows CI is green, and physical UAT passes on the actual server/counter PCs with simultaneous billing, printer/scanner/scale, restart/recovery, verified backup restore and Tally reconciliation.
