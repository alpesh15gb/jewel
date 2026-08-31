# JewelLAN Technical Design Document (TDD)

**Status:** Current architecture and implementation direction

This revision distinguishes existing implementation shape from required contracts. Items marked as required must be implemented and tested before financial workflows are treated as production-ready.

## 1. Architecture overview

```text
JewelPOS.exe (counter/office PCs)
        |
        | private-LAN HTTPS, certificate fingerprint pinning
        v
JewelServer.exe (main Windows PC)
        |
        +-- SQLite database, WAL, FULL synchronous mode
        +-- verified local backups + independent recovery copy
        +-- PDF generation
        +-- asynchronous Tally queue
        |
        v
JewelTallyBridge.exe -> localhost:9000 -> TallyPrime
```

The server owns all business writes and pricing decisions. Clients never open or share the SQLite file directly.

## 2. Technology stack

- Python 3.11 or newer.
- Tkinter/ttk for the Windows desktop client.
- FastAPI application served by Uvicorn in `jewel_server/main.py`.
- `requests` and `urllib3` transport support in the client.
- SQLite with WAL, foreign keys, busy timeout, and full synchronous durability.
- PDF generation in `jewel_server/pdfs.py`.
- Windows installer through Inno Setup (`installer/JewelLAN.iss`).
- Pytest test suite under `tests/`.

The dependency list in `requirements.txt` and the packaging metadata in `pyproject.toml` are authoritative for builds.

## 3. Runtime components

### Client

`jewel_client/main.py` owns login, navigation, common dialogs, dashboard, inventory, parties, purchases, jobs, stock audit, reports, and settings. `billing_page.py` and `returns_page.py` contain the richer billing and return workflows. `api.py` manages authentication headers, HTTPS transport, server discovery, and fingerprint validation. `scale.py` is the workstation input adapter for serial/USB-COM scale data.

### Server

`jewel_server/main.py` exposes the HTTP API and routes business requests. Domain modules separate concerns for company settings, security, TLS, returns, Tally, backups, PDF output, canonical values, integrity, audit chain, and services. `db.py` owns connection configuration, schema initialization, migrations, and transaction helpers.

### Tally bridge

`jewel_tally_bridge` is a localhost-oriented adapter. JewelLAN records queue state and retries asynchronously so Tally availability cannot block a sale.

Each exported business event has a stable external key such as `JewelLAN/{entity_type}/{entity_id}/{operation}/{version}`. The bridge sends that key with the export and records the remote voucher/master identity. If Tally accepts a voucher but the acknowledgement is lost, retry first reconciles by external key/reference; it must not create a second voucher. A conflict is retained for operator reconciliation rather than silently duplicated or discarded.

## 4. Request, quote, and transaction contracts

1. Client sends an authenticated request over HTTPS.
2. Server validates session, role, input shape, and business rules.
3. Read-only work uses a query-only connection.
4. Business writes use the serialized write path and `BEGIN IMMEDIATE`.
5. For a quote, the server returns `quote_id`, `quote_version`, `quote_hash`, pricing-input versions, and an expiry/requote policy.
6. A post request must include that quote context. The server recalculates only to verify that the exact quoted result still holds; it must return `QUOTE_STALE` and a fresh quote instead of silently posting a changed payable amount.
7. The transaction writes the business record, immutable snapshots, payments, stock movements, accounting effects, audit event, and integration queue entries as appropriate.
8. The server commits or rolls back the complete unit.
9. Client displays the response or an actionable error.

Every financially consequential creation—sale, purchase, return, payment/collection, opening stock, adjustment, and day-close submission—carries a client request UUID. The server stores it under the operation scope with a request fingerprint and final result reference. A duplicate UUID with the same fingerprint returns the original result; a duplicate UUID with a different fingerprint is rejected.

### Unknown outcome and durable client recovery

The client maintains a local durable `pending_posts` store (for example, a small SQLite/JSON state file under the client data directory) with request UUID, operation, cart/payload fingerprint, quote context, branch/counter, sanitized payment rows, created time, attempt count, and state: `pending`, `submitting`, `outcome_unknown`, `confirmed`, `rejected`, or `cancelled`.

A timeout, connection reset, or process termination after submission moves the record to `outcome_unknown`; it is never shown as a definite failure. On restart, Pending Posts queries a server reconciliation endpoint by request UUID. Retry is allowed only with the same fingerprint and UUID. The server must provide an unambiguous “not found and safe to retry” result or the original business result.

### Structured error contract

All API errors use a stable envelope, for example:

```json
{
  "error": {
    "code": "QUOTE_STALE",
    "message": "The quote changed before posting.",
    "retryable": true,
    "details": {"quote_id": "...", "fresh_quote_id": "..."},
    "request_id": "..."
  }
}
```

Minimum codes include `VALIDATION_ERROR`, `AUTH_REQUIRED`, `FORBIDDEN`, `CONNECTIVITY_UNKNOWN`, `BUSINESS_CONFLICT`, `STOCK_CONFLICT`, `QUOTE_STALE`, `IDEMPOTENCY_CONFLICT`, `DAY_CLOSED`, `NOT_FOUND`, and `INTERNAL_ERROR`. Clients branch on `code`, never on message text.

## 5. API surface by capability

The exact route implementation is in `jewel_server/main.py`; the capability groups are:

- `/api/auth/*`: login, password change, session control.
- `/api/company`, `/api/settings`: company, branch, counter, and settings.
- `/api/items/*`: inventory lookup, create/update, barcode lookup, labels.
- `/api/sales/*`: quote, post, list/detail, invoice PDF, cancel.
- `/api/sales/{id}/return-quote`, `/api/sales/{id}/return`: item-level returns.
- `/api/operations/reconcile/{operation}/{request_id}`: required unknown-outcome lookup for writes.
- `/api/returns/*`: credit-note list, PDF, cancellation.
- `/api/purchases/*`: supplier purchases and stock-in.
- `/api/customers`, `/api/suppliers`, `/api/karigars`: party masters.
- `/api/repairs`, `/api/orders`, `/api/approvals`: operational jobs.
- `/api/stock-audits/*`: audit sessions, scans, reconciliation.
- `/api/stock-adjustments/*`: required approved discrepancy transactions.
- `/api/day-close/*`: required period reconciliation, lock, evidence, and authorized reopen; the existing `/api/reports/day-close` remains a report endpoint until the persisted workflow is implemented.
- `/api/reports/*`: dashboard, accounting, stock, and operational reports.
- `/api/tally/*`: bridge health and queue state.
- `/api/backups/*`, `/api/integrity`: online backup/verification and integrity visibility; these routes must not perform a live restore.

## 6. Security design

- Production transport is HTTPS on TCP 8765 with a locally retained certificate.
- Clients verify and pin the server SHA-256 certificate fingerprint.
- UDP 8766 is discovery only and remains private-LAN scoped.
- Passwords use per-user salted PBKDF2-HMAC-SHA256 hashes.
- Sessions expire and password reset invalidates prior sessions.
- Endpoint permissions are role-aware.
- Audit records cover important business and security actions.
- The server, database, and Tally bridge are not intended for Internet exposure.

Fresh-install bootstrap generates a random one-time administrator secret, displays it only through a local setup/recovery path, stores only its password hash, and invalidates it after the first successful password change. Production must not use the development convenience credential. Bootstrap operations are local-only until the first password change and company setup are complete.

The first client trust is established by an operator comparing the live server fingerprint through a trusted local channel or the server console. A certificate replacement requires the administrator to record the reason, verify the new fingerprint out of band, explicitly re-trust it on each client, and audit the event. Server migration/disaster recovery should preserve the certificate identity where possible; if it cannot, the replacement procedure and evidence are mandatory. A suspected compromise blocks trust rather than offering an automatic override.

RBAC follows the permission matrix in the PRD, plus branch scope. User deactivation, role changes, and branch-scope changes invalidate all active sessions for the affected user.

## 7. Data integrity, precision, and state invariants

Money-critical values use exact paise representations and deterministic `ROUND_HALF_UP` calculations. Every item weight uses a canonical integer milligram field with a reconciled display mirror. Posted history is corrected by reversal, return, credit note, or adjustment workflows—not by overwriting old records.

SQLite is configured with foreign keys, WAL, `synchronous=FULL`, busy timeout, and serialized writes. Stock transitions are validated atomically so two counters cannot sell the same item.

Required stock state machine:

| From | Allowed next state | Required transaction |
|---|---|---|
| `in_stock` | `sold`, `approval`, `repair`, `karigar`, `transit`, `damaged`, `scrap` | Sale, approval issue, repair issue, karigar issue, transfer, or disposition |
| `sold` | `in_stock`, `quarantine`, `damaged`, `scrap` | Effective return or controlled sale cancellation with disposition |
| `approval` | `in_stock`, `sold` | Approval return or approval sale |
| `repair` | `in_stock`, `damaged`, `scrap` | Repair completion or disposition |
| `karigar` / `transit` | `in_stock`, `damaged`, `scrap` | Receipt/transfer completion or disposition |

Every transition has one stock movement, actor, timestamp, reference, and reason where required. `counter_id` must belong to `branch_id`; a composite foreign-key or equivalent service/database invariant is required. Mutable item updates require `expected_version`; a mismatch returns `VERSION_CONFLICT`.

The active-return uniqueness rule is enforced in the database and service transaction: one sale line can have at most one effective return, even under concurrent requests.

### Quote and partial-return allocation

At sale posting, persist line-level allocations for invoice discount and invoice round-off. For partial returns, the credit note is the sum of the selected stored line allocations; it never uses current metal rates. If a header round-off must be allocated, use weighted largest-remainder allocation against pre-round line totals, with `sale_item_id` as the deterministic tie-breaker. The selected lines’ allocated taxable, GST, round-off, and total values must reconcile exactly to the credit note.

### Cancellation rules

Full sale cancellation is a manager/admin operation before day close, with a mandatory reason, and is blocked if an effective return or dependent downstream transaction exists. It reverses payments/receivables, stock, COGS, revenue, GST, round-off, audit state, and queues a Tally cancellation. Credit-note cancellation follows the same controlled-reversal pattern, is blocked when a dependent refund/adjustment exists, and is never an in-place undo; a further correction is a new approved adjustment.

### Day-close rules

Day close is a persisted `day_closes` record keyed by business date and branch. The cutoff uses the configured business timezone. The close validates balanced journals, payment totals versus payment rows, stock conflicts, open unknown-outcome posts, pending Tally items according to policy, backup/data-health status, and unresolved audit discrepancies. Closing locks posting for that business date. Manager/admin/accounting roles may reopen only with a reason, actor, timestamp, and audit event; the close evidence contains the reconciliation totals and hashes of the relevant report set.

### Stock audit rules

An audit captures an expected-stock snapshot timestamp/version. Movements after that point are recorded and cause close conflict unless explicitly included by a manager. Duplicate scans are idempotently ignored. Missing/extra results cannot directly mutate `items`; closing an approved discrepancy creates a stock-adjustment header/line transaction with disposition, valuation, actor, reason, and journal/stock movement effects.

## 8. Accounting posting contract

The journal is the authoritative accounting history. Each entry must balance in paise, use a stable reference to its source transaction, and be immutable after posting. The following mappings are normative starting points and must become regression tests:

| Event | Debit | Credit |
|---|---|---|
| Cash/card/UPI sale | Tender accounts for received amounts; customer receivable for credit; old-gold inventory for accepted exchange | Sales revenue for taxable value; output GST; round-off account for difference |
| Sale cost recognition | COGS | Jewellery inventory at recorded cost |
| Supplier purchase | Jewellery inventory; input GST | Cash/bank or supplier payable |
| Customer collection | Cash/bank/card/UPI | Customer receivable |
| Customer order/repair advance | Cash/bank | Customer advances liability; later delivery applies it against the final receivable |
| Supplier advance | Supplier advance asset | Cash/bank |
| Sale return | Sales returns/contra-revenue; output GST reversal; round-off reversal as applicable | Refund tender, customer credit/receivable, or other refund account |
| Returned stock | Jewellery inventory at recorded cost | COGS reversal |
| Opening stock | Jewellery inventory at opening valuation | Opening balance/equity account |
| Old-gold acceptance | Old-gold inventory at accepted value | Sale settlement/tender-clearing account |

Discount is reflected in taxable/revenue allocation, not hidden as an unexplained payment. Sale cancellation is the exact inverse of the original sale journals, linked by the same source reference; credit-note cancellation is the exact inverse of the credit-note journals. Old gold does not reduce taxable value. An exchange value above the invoice total requires an explicit customer-credit/payable entry and approval. Partial returns reverse only the stored allocated line values; old gold is not automatically unwound unless a linked old-gold reversal transaction is explicitly approved.

## 9. Backup, recovery, and deployment

At least one verified recovery copy must be on an independent failure domain—such as a separately managed machine or removable/offline media—not only on the server’s system disk. Backup files must be encrypted at rest using OS-managed/volume encryption or an equivalent encrypted backup format, with restrictive Windows ACLs and access limited to designated administrator/service identities.

Online backup routes can create, verify, list, and report copies. They do not restore a running server. Restore is a server-side offline operation using the supported recovery command, followed by integrity, data-health, and day-close checks. The client flow must launch or document this utility rather than treating an offline restore as an API call.

The backup worker uses SQLite’s online backup API, writes manifests/hashes, verifies backup files, and prunes according to retention. Restore is a server-side offline operation using the supported restore command, followed by integrity and day-close checks.

The installer supports server/counter/Tally Bridge combinations, creates Windows scheduled tasks and Private-profile firewall rules, preserves data during upgrades/uninstall, and keeps the SQLite database under the server machine’s application-data directory.

## 10. Performance and testing strategy

- Unit tests for calculation, canonical values, security, TLS, returns, company settings, idempotency, startup, and hardening.
- Integration tests for API/database transactions and stock/accounting side effects.
- UAT scripts for billing, purchase, return, audit, backup/restore, Tally, multi-counter, and day-close flows.
- Release checks for installer upgrade behavior, service/task startup, Private-profile firewall scope, and no accidental Internet exposure.
- Contract tests for quote staleness, unknown-outcome reconciliation, return idempotency, partial-round-off allocation, numbering, payment-ledger reconciliation, day-close locks, audit movement conflicts, version conflicts, structured errors, and Tally acknowledgement loss.
- Performance tests for healthy-LAN barcode lookup p95 ≤ 300 ms, quote p95 ≤ 500 ms, and business post p95 ≤ 2 s excluding PDF generation.

## 11. Architectural constraints

Do not place SQLite on SMB/NAS. Do not add a cloud dependency to the core billing path. Keep vendor hardware integrations behind adapters. Preserve API boundaries so a future migration from SQLite to PostgreSQL can change storage without changing counter workflows.
