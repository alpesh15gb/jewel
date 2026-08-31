# JewelLAN Implementation Plan

**Purpose:** ordered delivery plan for the team or an AI implementation agent
**Planning rule:** preserve the offline-first, server-authoritative architecture and complete each phase with tests and operator evidence

## 1. Delivery sequence

### Phase 0 — Baseline and safety

1. Confirm the working tree, Python version, dependencies, and test command.
2. Read the existing production, security, data, deployment, and release documents.
3. Establish a clean test database fixture and deterministic test data.
4. Record the current release-candidate status and known gaps.

**Exit:** baseline tests run; no feature work starts without a reproducible local setup.

### Phase 1 — Platform and identity

1. Validate server startup, database initialization, migrations, and local data paths.
2. Validate HTTPS certificate creation, discovery, and fingerprint pinning.
3. Define and implement random one-time admin bootstrap, independent password/setup flags, session invalidation, and the RBAC/branch-scope matrix.
4. Define certificate first-trust, replacement, migration, and compromise-recovery procedures.
5. Validate company, branch, counter, and transactional sequence/number allocation.

**Exit:** a fresh install can reach a configured Dashboard securely on the private LAN.

### Phase 2 — Inventory and purchase foundation

1. Finalize integer milligram fields, display mirrors, derivation rules, and item validation.
2. Implement or verify item CRUD, barcode lookup, tag PDF, supplier purchase, and stock movement history.
3. Add the stock state machine, branch/counter invariant, expected-version conflict handling, and multi-counter race tests.
4. Add explicit opening-stock transactions with valuation and opening-balance/equity accounting.
5. Define stock-audit snapshots, movement conflicts, and approved stock-adjustment transactions.
6. Seed and verify default accounts and metal-rate behavior.

**Exit:** opening stock can be entered, tagged, searched, and audited without direct database access.

### Phase 3 — Billing and accounting

1. Stabilize quote calculation, quote ID/version/hash, exact rounding, and stale-quote rejection.
2. Keep all price components visible in the POS client and persist immutable seller/branch/customer/tax snapshots.
3. Implement durable Pending Posts, unknown-outcome reconciliation, and operation-scoped idempotency.
4. Implement immutable payment rows, customer receivable ledger/collection, old-gold rules, split payment, and payment-total validation.
5. Implement normative accounting mappings and post sales atomically with stock/journal effects.
6. Generate and verify GST invoice PDFs from historical snapshots.

**Exit:** cashier UAT passes normal sale, discount, split payment, retry, and concurrent-stock scenarios.

### Phase 4 — Returns and operational workflows

1. Implement return idempotency, active sale-line uniqueness, original-value quote, and deterministic partial-return allocation.
2. Require per-item disposition and post credit notes with stock, refund-payment, receivable, and accounting reversal.
3. Specify and implement sale/credit-note cancellation dependencies, timing/day-close rules, reasons, approvals, and Tally effects.
4. Add repair, order, karigar, approval/Jangad, and remaining customer-balance workflows.
5. Add PDFs and role-aware cancellation/reversal controls.

**Exit:** manager UAT passes return, repeat-return prevention, cancellation conflict, repair, order, and approval scenarios.

### Phase 5 — Audit, reports, and recovery

1. Complete dashboard and operational reports, including measurable performance instrumentation.
2. Validate trial balance, ledgers, payment reconciliation, stock valuation, GST summaries, and accounting examples.
3. Implement persisted day-close reconciliation, business-date locks, evidence, and authorized reopen.
4. Verify audit-chain and the full data-health invariant set.
5. Verify automatic/manual backups, manifests, pruning, independent-copy protection, offline restore, and post-restore checks.

**Exit:** accountant and owner validation documents are signed; recovery drill succeeds.

### Phase 6 — Tally, installer, and release hardening

1. Verify queueing, stable external event keys, deduplication/reconciliation after lost acknowledgements, local bridge security, and Tally status reporting.
2. Test installer modes, scheduled tasks, firewall profile, upgrades, uninstall preservation, and startup visibility.
3. Run the complete UAT/release gate sequence.
4. Publish release notes, operator checklist, support runbook, and go-live sign-off.

**Exit:** all existing release gates pass and the business owner accepts the deployment.

## 2. Work item format

Every implementation task should state:

- User/problem being solved.
- Affected client, server, schema, installer, or docs files.
- API and data changes.
- Permission and audit implications.
- Automated tests.
- Manual/UAT evidence.
- Rollback or recovery path.

## 3. Definition of done

An item is done only when:

- The implementation is consistent with the PRD, flow, UI brief, TDD, and schema.
- Tests cover the normal path and the highest-risk failure path.
- Money/weight precision and transaction behavior are verified.
- Role, audit, idempotency, and status-transition rules are verified where relevant.
- The user-facing error and success states are understandable.
- Existing documentation is updated if operations or recovery behavior changed.

## 4. Priority backlog

| Priority | Work | Reason |
|---|---|---|
| P0 | Durable write recovery, quote/version contract, return idempotency, payment ledger, numbering, accounting mappings, stock invariants, day-close | Business continuity and financial integrity |
| P0 | Authentication bootstrap, certificate lifecycle, RBAC/branch scope, backup independent-copy and offline restore | Security and recoverability |
| P0 | Installer/startup/firewall/private-LAN verification | Safe Windows deployment |
| P1 | Returns/credit notes, purchases, accounting reports, day-close/data health | Complete controlled operations |
| P1 | Tally queue and bridge observability | Accounting workflow continuity |
| P2 | Vendor-specific RFID reader adapters, live rate feeds, e-invoice/WhatsApp connectors | Optional integrations that must remain asynchronous |
| P2 | PostgreSQL migration path for larger deployments | Scale beyond the practical SQLite topology |

## 5. Risks and mitigations

- **Database corruption or unsafe sharing:** keep SQLite server-local, use WAL/FULL, verified backups, and restore drills.
- **Duplicate or conflicting sales:** idempotency keys, serialized write transactions, and stock-state guards.
- **Unknown financial outcome:** durable client Pending Posts, server reconciliation, stable payload fingerprints, and same-request retries.
- **Rounding disputes:** canonical paise calculations, deterministic rounding, visible formula breakdown, and regression cases.
- **Ledger drift:** payment/receivable/karigar ledgers as authority, cached-balance reconciliation, and day-close checks.
- **Audit movement drift:** snapshot/versioned expected stock, movement conflict detection, and explicit adjustment transactions.
- **Certificate replacement confusion:** display the fingerprint and block changed identities until explicitly re-trusted.
- **Hardware variability:** isolate scale/RFID adapters and keep barcode keyboard mode as the baseline.
- **Over-expanding scope:** treat cloud/internet/vendor features as queued optional connectors, never billing prerequisites.

## 6. Release gates

The release gate also requires the TDD contract tests for unknown outcomes, quote staleness, returns, payments, numbering, accounting, stock audits, day close, RBAC, certificate lifecycle, structured errors, and Tally acknowledgement loss. The listed operational documents remain required evidence; this six-document pack is a design baseline, not a production approval.

Before go-live, complete the existing `RELEASE_GATE.md`, `FINAL_RELEASE_CHECK.md`, `GO_LIVE_SIGNOFF.md`, `BACKUP_RESTORE_DRILL.md`, `ACCOUNTANT_VALIDATION.md`, and `COUNTER_UAT.md` procedures. A release candidate is not a production approval; the owner’s sign-off and recovery evidence are required.
