# JewelLAN incident response

If a production transaction, stock state, audit-chain or database-integrity issue is suspected: stop new posting on all counters, preserve a verified backup and installer/version details, run Data Health, record exact error/invoice/tag IDs, and do not edit SQLite directly. Recovery or correction must be performed through supported reversal/credit-note/adjustment/restore workflows or a separately tested migration. Reopen counters only after integrity and day-close reconciliation pass.
