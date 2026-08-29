# JewelLAN support runbook

## Billing unavailable

1. Confirm the main PC is powered on.
2. Confirm Windows network profile is Private on all JewelLAN PCs.
3. Confirm Task Scheduler shows `JewelLAN Server` running/ready; this is a scheduled task, not a Windows service.
4. From the server PC, run `JewelServer.exe --show-fingerprint` and compare the fingerprint with the counter's trusted identity if a certificate warning appears.
5. Do not bypass a certificate-change warning without verifying the main PC identity.

## Tally unavailable

Billing must continue. Tally synchronization is asynchronous. Confirm TallyPrime is open with the intended company loaded and its localhost HTTP integration is available. Then confirm `JewelLAN Tally Bridge` scheduled task is running. Resolve the bridge/test error and use Sync now/reconciliation after Tally is restored.

## Backup/recovery

Use JewelLAN's backup function. A backup is valid only after integrity/foreign-key verification and SHA-256 manifest creation. For restore, preserve the current database as a pre-restore rollback point, restore the chosen verified backup, restart the server, then run Data Health and day-close reconciliation before resuming billing.

## Suspected data inconsistency

Stop posting new transactions, create a backup, and run Data Health. Do not edit SQLite directly. Record the exact integrity/canonical/audit issue and correct through supported reversal/adjustment workflows or a tested migration.

## Reinstall/upgrade

Run the JewelLAN installer as administrator over the existing installation. The installer stops/deletes the JewelLAN scheduled tasks and terminates remaining JewelLAN processes before replacing binaries. ProgramData database/backups are intentionally preserved.
