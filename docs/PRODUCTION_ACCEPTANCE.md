# JewelLAN production acceptance gate

Target deployment: Bijoria, Telangana (GST state code 36), India Standard Time, three Windows PCs, with JewelLAN Server + POS + TallyPrime + Tally Bridge on the main PC and POS on two counter PCs.

A release must not be described as production-ready unless all software gates below are green and the physical shop acceptance checks have been completed.

## Automated software gates

- Database migrations apply to a fresh database and an upgraded database.
- Canonical money is reconciled in integer paise and weights in integer milligrams.
- Posted sales, journals, stock movements and credit notes cannot be silently rewritten.
- HUID and jewellery gross/stone/net/fine-weight validation is enforced by the server and database.
- Concurrent sale attempts for the same serialized tag allow only one successful sale.
- Partial item returns produce credit notes, reverse stock and accounting exactly once, and cannot exceed the original sold quantity/value.
- Tally posting remains asynchronous and cannot block POS billing; credit-note/reversal paths are covered by tests.
- TLS is enabled for the private LAN, clients pin the server SHA-256 certificate fingerprint, and changed identities are rejected.
- The Tally bridge remains loopback-only by default when TallyPrime runs on the JewelLAN server PC.
- Backups pass SQLite integrity/foreign-key checks and SHA-256 manifest verification before restore.
- Day-close verifies sales/payments and double-entry journal balance.
- Windows GUI smoke tests construct Dashboard, Billing, TallyPrime and Data Health screens.
- JewelServer.exe, JewelPOS.exe and JewelTallyBridge.exe build and packaged self-tests pass.
- Inno Setup produces JewelLAN-Setup.exe and supports safe in-place upgrades.

## Physical acceptance before first live invoice

1. Install the release on the main PC and two counter PCs on a Windows Private network.
2. Verify the displayed server TLS fingerprint on each counter before trusting it.
3. Create individual named users; do not share the administrator login for counter billing.
4. Enter Bijoria GSTIN/address/phone and confirm Telangana state code 36 and IST business date.
5. Configure the exact Tally company and ledger mappings, then validate sample cash, UPI/card, credit, intra-state GST, inter-state GST, purchase and credit-note vouchers in a test Tally company.
6. Test the actual barcode scanner, barcode/receipt/A4 printers and weighing scale.
7. Post a sale on Counter 1 while Counter 2 attempts the same tag; exactly one must succeed.
8. Test a partial item return/credit note and then a return/exchange workflow.
9. Create a manual backup, verify it, restore it on a test copy and confirm integrity/day-close after restore.
10. Reboot the main PC and verify the JewelLAN scheduled task starts the server, both counters reconnect, and no invoice/stock data is lost.
11. Disconnect the LAN during an attempted operation and confirm the client reports failure without creating a duplicate transaction when connectivity returns.
12. Have the accountant validate representative GST invoices, credit notes, day-close totals and Tally vouchers before live opening stock is entered.

Only after these checks should opening stock be entered and the first live invoice issued.
