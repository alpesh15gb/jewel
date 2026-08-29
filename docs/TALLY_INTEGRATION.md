# TallyPrime integration

JewelLAN's Tally integration is designed for a shop that can remain completely offline from the internet. TallyPrime is not called by billing counters. Instead, JewelLAN commits the jewellery transaction to its own database first and writes a durable sync-queue row in the same transaction. A background worker later sends the accounting voucher through **JewelTallyBridge.exe**.

## Network layout

```text
JewelPOS counters -> JewelServer.exe:8765 -> JewelTallyBridge.exe:8767 -> TallyPrime localhost:9000
```

Install the Tally Bridge component on the PC where TallyPrime runs. The installer opens TCP 8767 only on the Windows **Private** firewall profile. TallyPrime itself can remain on `127.0.0.1:9000`.

The bridge generates a random authentication token on first start at:

```text
C:\ProgramData\JewelLAN\tally-bridge-token.txt
```

Use the Start Menu shortcut **JewelLAN Tally Bridge Token** on the Tally PC to display it. Enter the bridge PC URL, token, exact Tally company name and ledger mappings in JewelLAN **Administration -> TallyPrime**.

## Prerequisites in TallyPrime

TallyPrime must be running, the target company must be loaded, and HTTP/XML integration must be enabled on port 9000 (or the port passed to the bridge). JewelLAN follows Tally's documented XML-over-HTTP envelope format and validates the import response (`CREATED`, `ALTERED`, `CANCELLED`, `ERRORS`, and voucher/master IDs) before marking a queue row as synced.

## What syncs

- Sales -> Tally `Sales` accounting voucher.
- Sale cost -> Tally `Journal` voucher, debit COGS / credit Jewellery Inventory.
- Purchases -> Tally `Purchase` accounting voucher.
- Credit customers -> individual Sundry Debtor ledgers, created automatically when enabled.
- Unpaid suppliers -> individual Sundry Creditor ledgers, created automatically when enabled.
- Cash, Card/UPI, sales, GST, inventory, COGS, old gold and round-off use configurable mappings.
- Sale cancellations enqueue matching `Cancel` operations for the Tally Sales and COGS vouchers.

JewelLAN does **not** push individual jewellery tags into Tally stock by default. JewelLAN remains the source of truth for serialized jewellery/HUID/barcode stock; Tally is the accounting/statutory book.

## GST

New JewelLAN sales store explicit `CGST`, `SGST`, `IGST` and place-of-supply fields. The split is determined from the configured business state code/GSTIN and the customer's GSTIN/place of supply. Credit sales require a customer. Before production, have the shop's CA validate the ledger groups, GST ledgers, voucher types and old-gold accounting treatment.

## Reliability model

A Tally outage does not block billing. Queue statuses are `pending`, `sending`, `synced`, `failed` and `conflict`. Failed rows retry with exponential backoff. Each generated Tally voucher gets a stable UUID `REMOTEID` derived from the JewelLAN entity, reducing duplicate risk when a request must be retried after a lost response.

The TallyPrime tab provides connection testing, mapping validation, manual sync, queue backfill and Day Book reconciliation. Reconciliation compares expected JewelLAN voucher numbers/amounts to vouchers exported from Tally's Day Book for the selected date range.

## Production checklist

1. Back up both JewelLAN and Tally companies.
2. Configure the exact Tally company and ledger mappings.
3. Use **Test** until every required mapped ledger exists.
4. Post test sales covering cash, card/UPI, credit, old gold, CGST/SGST and IGST.
5. Reconcile the same date range in JewelLAN and verify Tally's Day Book, Sales Register, Purchase Register, GST reports and Trial Balance with the CA.
6. Only then enable historical backfill or live production sync.
