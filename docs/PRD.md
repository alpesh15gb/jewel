# JewelLAN Product Requirements Document (PRD)

**Product:** JewelLAN
**Document status:** Development baseline
**Primary source of truth for:** product purpose, users, scope, and acceptance outcomes

## 1. Product summary

JewelLAN is an offline-first jewellery ERP and point-of-sale system for Windows showrooms operating on a private local-area network. One Windows PC runs the central server and SQLite database. Counter and office PCs run the JewelPOS client and connect to the server over private-LAN HTTPS.

The product must keep core showroom work running when the internet is unavailable: inventory, barcode billing, GST calculations, payments, returns, purchases, customer records, repairs, orders, stock audits, accounting, reports, backups, and authentication. Optional internet integrations must be queued and must never block billing.

## 2. Problem statement

Jewellery showrooms need exact control over serialized items, weights, purity, wastage, making charges, stones, HUIDs, GST, customer credit, and stock movement. A disconnected or unreliable internet connection cannot be allowed to stop a sale. Shared database files, informal corrections, and opaque pricing create operational, financial, and audit risk.

JewelLAN addresses this with a server-owned database, auditable business transactions, explicit price breakdowns, role-based access, and a Windows-native LAN deployment.

## 3. Users and roles

| User | Primary needs | Key permissions |
|---|---|---|
| Admin | Configure the shop, users, security, backups, and integrations | Full administration and controlled reversals |
| Manager | Operate and supervise showroom workflows | Inventory, returns, approvals, reports, overrides |
| Cashier | Complete customer billing quickly and accurately | Quote/post sales, payments, customer lookup |
| Inventory operator | Receive, tag, move, and audit stock | Items, purchases, stock audits, stock movement |
| Accounts operator | Review financial and tax records | Ledgers, journals, reports, Tally queue |
| Owner/accountant | Review health and performance | Dashboards, reports, audit and day-close evidence |

## 4. Goals

- Complete core billing without internet access.
- Make every jewellery price component visible before posting.
- Prevent duplicate sales and multi-counter stock races.
- Preserve immutable, traceable history for posted business events.
- Support barcode-first operations with optional scale and RFID data paths.
- Provide recoverable backups and an operator-verifiable restore path.
- Keep the deployment practical for a small Windows private LAN.

## 5. Non-goals and boundaries

- No public internet-facing server, cloud-only billing, or router port forwarding.
- No direct editing of the SQLite database as a production correction process.
- No assumption that a vendor-specific RFID reader SDK is available.
- No requirement for live metal-rate, WhatsApp, SMS, gateway, or e-invoice connectivity during a sale.
- No silent mutation of posted invoices, stock movements, journals, or credit notes.

## 6. Functional requirements

### Authentication and setup

- A fresh installation creates an initial administrator account.
- Bootstrap uses a random one-time initial secret displayed only through the local setup path; a known default password is not acceptable in production.
- The administrator must change the initial password before normal operations.
- `password_change_required` and `company_setup_complete` are independent state flags. A failed or partial company setup must not force another password change.
- Users have named accounts, roles, active/inactive state, session expiry, and throttled login attempts.
- Company setup captures business identity, branch, GST details, address, contacts, counter count, numbering prefixes, tax defaults, and timezone.

### Inventory

- Each jewellery piece has a unique tag number and barcode.
- An item records category, metal, purity, gross/stone/net/fine weight, stone value, cost, making rule, wastage, HUID, certificate, HSN, GST rate, optional RFID EPC, branch/counter, and status.
- Every item weight is validated with a canonical integer milligram value and reconciled gram display mirror; entered-versus-derived rules are defined in the Backend Schema.
- Posted/sold records cannot be silently rewritten.
- Label PDFs can be generated for tagged items.

### Sales and payments

- A cashier can scan one or more serialized tags, select a customer, and review the complete quote.
- Quote details include net weight, rate, metal value, wastage, making, stones, discount allocation, taxable value, GST, round-off, and final total.
- Payment supports cash, card, UPI, customer credit, and old-gold exchange.
- Each tender is an immutable payment row with method, amount, account/reference, timestamp, and actor; header payment totals are derived or verified mirrors.
- The server is the pricing and posting authority.
- A quote has a server-issued quote ID/version/hash. Posting must use that exact quote context; if rates, item versions, tax settings, or other pricing inputs changed, the server rejects the post with a stale-quote error and returns a fresh quote.
- Posting is atomic and idempotent; a retried request must not create a duplicate invoice. The client durably stores pending posts and never labels a timeout as a definite failure.
- A GST invoice PDF is available after a successful post.

### Returns, operations, and accounting

- Item-level returns use the original posted sale values and generate an auditable credit note.
- Returns have their own idempotency key, deterministic partial-return allocation, and explicit disposition (`in_stock`, `quarantine`, `damaged`, or `scrap`).
- Sale cancellation and credit-note cancellation are controlled full reversals with role, timing, dependency, reason, stock, payment, journal, and Tally rules.
- Purchases create serialized stock and supplier/accounting records.
- Repairs, custom orders, karigar ledgers, approvals/Jangad, and physical stock audits have status-driven workflows.
- Sales and purchases create balanced double-entry journals.
- Reports include sales/payment summaries, stock, trial balance, account ledger, and printable stock output.
- TallyPrime synchronization is asynchronous and visible through queue/status information.

## 7. Non-functional requirements

- **Availability:** core operations remain usable without internet.
- **Integrity:** SQLite is server-owned; writes are serialized with transactions, foreign keys, WAL, and full synchronous durability.
- **Security:** private-LAN HTTPS uses a pinned server certificate fingerprint; the server is not internet-facing.
- **Performance:** on a healthy private LAN, barcode lookup p95 ≤ 300 ms, quote refresh p95 ≤ 500 ms, and business post p95 ≤ 2 s excluding PDF generation; list views use bounded result sets.
- **Recoverability:** backups are verified, retained by policy, and restorable through the supported server recovery path.
- **Auditability:** security and business events include actor, timestamp, action, and relevant references.

## 8. Success measures

- A counter can complete a normal sale with the internet disconnected.
- A duplicate client retry returns the original invoice rather than creating a second sale.
- Two counters cannot sell the same serialized item.
- An accountant can reconcile the displayed invoice, GST, payment total, journal, and stock movement.
- A tested backup can be restored and pass integrity/data-health checks.
- UAT operators can complete billing, return, purchase, stock audit, and day-close scenarios using the documented flow.

## 9. Normative financial and data contracts

- Seller, branch, customer, tax, and printable invoice identity are snapshotted at posting or the generated document is archived immutably. Reprinting an old invoice must not use current master data.
- Posted sales and purchases contain immutable branch attribution and, when performed at a counter, counter attribution. A client cannot change branch/counter context during an active cart.
- Invoice and purchase numbers are allocated transactionally from scoped sequences. Failed transactions may leave gaps; numbers are never reused.
- Customer, supplier, and karigar balances are cached projections. The authoritative source is the relevant payment/receivable/payable/karigar ledger plus journal entries; data health must reconcile projections.
- Old gold is a settlement/inventory transaction and does not reduce taxable value of new jewellery. Any excess value requires an explicit customer-credit/payable decision; it cannot become a negative invoice payment silently. A later partial return does not automatically unwind old gold; any unwind is a separate linked, approved transaction.
- Opening stock is posted through a dedicated opening-stock transaction with valuation, stock movement, opening-balance/equity accounting, actor, reference, and reversal path.
- Core stock state transitions, day-close locks, payment rows, and journal mappings are part of the acceptance contract, not implementation details.

## 10. Permission baseline

| Action | Admin | Manager | Cashier | Inventory | Accounts |
|---|---:|---:|---:|---:|---:|
| Login, billing, customer lookup | ✓ | ✓ | ✓ | — | ✓ |
| Inventory receive/edit/transfer | ✓ | ✓ | — | ✓ | view |
| Price/rate or exceptional weight override | ✓ | ✓ | — | — | — |
| Sale cancellation / credit-note cancellation | ✓ | ✓ | — | — | — |
| Returns | ✓ | ✓ | — | — | view |
| Purchases and opening stock | ✓ | ✓ | — | ✓ | ✓ |
| Reports, ledgers, day-close review | ✓ | ✓ | — | view | ✓ |
| Day-close lock/reopen | ✓ | ✓* | — | — | ✓* |
| User, branch, security, backup policy | ✓ | — | — | — | — |
| Offline restore / certificate re-trust | ✓ | — | — | — | — |

`*` only where explicitly delegated by policy. Branch scope is applied in addition to this action matrix. Deactivation or role change invalidates active sessions for the affected user.

## 11. Product decisions

The product is company-neutral, barcode-first, server-authoritative, and Windows/LAN focused. The current release candidate remains under shop UAT; production readiness is determined by the existing release gate and go-live sign-off documents.
