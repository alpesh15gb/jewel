# Jewellery ERP/POS workflow audit

This checklist is a release-control document, not a marketing feature list. JewelLAN should not be described as production-ready until the software gates and physical showroom UAT are complete.

## Reference workflow findings

Indian jewellery systems commonly treat the daily bullion/shop rate as a first-class dated master rather than a one-time setting. Public Marg jewellery documentation includes today's Gold/Silver sale and purchase rates, date-wise rate history, BHAV/metal settlement, karigar, approval, repairs and sales/purchase reports. IBJA publishes benchmark Gold/Silver rates by purity with AM/PM observations; Gold is quoted per 10 g and Silver per kg, excluding GST/making. External market feeds therefore belong in JewelLAN as reference inputs, not an automatic replacement for a store's approved selling rate.

Reference sources reviewed:

- IBJA Rates: https://www.ibjarates.com/
- IBJA API endpoint: https://ibjarates.com/API/GoldRates/
- Marg jewellery today's rate workflow: https://care.margcompusoft.com/margerp/jewellery/417/1/how-to-feed-today-gold-or-silver-rate-in-jewellery-setup-of-marg-erp-software
- Marg jewellery POS feature overview: https://margcompusoft.com/pos-software-for-jewellery-shop.html
- GoldAPI XAU/INR and XAG/INR documentation: https://www.goldapi.io/

## Required jewellery workflows

| Area | Required behavior | Current release status |
| --- | --- | --- |
| Daily metal rates | Day-start confirmation, intraday change, dated history, Gold/Silver market units, purity policy, audit | RC6 implementation/testing |
| Reference-rate sync | Optional internet reference, timeout/failure isolation, operator review before apply | RC6 implementation/testing |
| Billing calculation | Metal + wastage + making + stone + discount + GST + round-off visibly reconciled | Implemented; RC5 regression coverage |
| Quote/rate lock | Accepted customer quote must not silently change if manager updates rate while bill is open | **P0 gap** |
| Serialized stock | Unique tag/barcode/HUID/certificate, exact weights, sold-stock protection | Implemented |
| Returns/exchange | Item-level credit note, no double return, stock/accounting reversal | Implemented; physical UAT still required |
| Old gold | Weight/purity/deduction/rate/value, audit and accounting treatment | Implemented baseline; CA/accountant review required |
| Karigar/job work | Metal/cash ledger, issue/receive, making/job settlement | Baseline implemented; deeper BHAV/manufacturing audit required |
| Approval/Jangad | Issue/return serialized pieces and preserve stock state | Implemented baseline |
| Purchases | Supplier purchase, tagged stock-in, GST/accounting | Implemented baseline |
| Repairs/orders | Intake, promised date, status, advances, karigar | Implemented baseline |
| Counter/day close | Per-counter cashier shift, opening cash, tender reconciliation, closing variance/signoff | **P0 workflow gap** |
| CRM/schemes | Customer history, loyalty/savings schemes, maturity/redemption | **P1 gap** |
| Compliance | GST invoice/credit note, HSN/POS review, optional e-invoice/e-way adapter | Core GST present; accountant/compliance signoff required |
| Tally | Durable async export, retry/reconcile; JewelLAN remains stock source of truth | Implemented baseline; test-company UAT required |
| Recovery | Verified backup/restore, power-loss recovery, DB integrity | Automated controls present; physical recovery drill required |

## Rate-control rules

1. The shop-approved rate is authoritative for billing. An internet feed is only a reference until an authorised operator applies it.
2. Manual entry must always work with the internet disconnected.
3. Rate changes are append-only. Old rows and posted invoices are never rewritten.
4. A newer metal-rate batch supersedes stale purity rows. Purity-specific values only override derivation when deliberately included in the newest batch.
5. Freshness is checked per active metal. Updating Gold does not confirm stale Silver.
6. Day-start confirmation and any intraday change are audited with operator, timestamp, source and note.
7. Gold is displayed to operators in ₹/10 g and Silver in ₹/kg; the pricing engine stores/calculates exact ₹/g values.
8. A future quote-lock gate must bind the displayed quote to a rate/version so an in-progress customer bill cannot silently reprice after a concurrent rate change.

## Go-live blockers discovered by this audit

- Implement server-issued quote/rate locking with expiry and explicit re-quote acknowledgement.
- Implement cashier shift/opening cash/day-close variance workflow per counter.
- Run accountant validation for GST, old-gold treatment, returns/credit notes and Tally postings.
- Complete physical 3-counter LAN UAT with scanner, printer, actual scale, reboot/power-loss and backup-restore drill.
- Validate every optional internet adapter fails closed without delaying or blocking local billing.

## Release discipline

Every P0 change must have a regression test and pass the Windows build, packaged EXE self-tests and installer build. A green CI build is a software gate only; it is not a substitute for showroom UAT.
