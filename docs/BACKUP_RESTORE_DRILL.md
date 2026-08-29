# Backup and restore drill

Run this before Bijoria goes live and after any major upgrade.

1. Post only test data in the candidate database.
2. Create a manual JewelLAN backup and record its SHA-256 value.
3. Verify the backup is reported healthy by JewelLAN.
4. Copy the backup to a separate test location/PC.
5. Restore it through the supported JewelServer restore path, never by copying a live WAL database manually.
6. Restart JewelServer and run Data Health.
7. Confirm SQLite integrity, foreign keys, audit-chain verification and canonical paise/milligram reconciliation pass.
8. Run day-close for the test date and compare sales/payment totals.
9. Open representative invoices/credit notes and scan an in-stock test tag.
10. Record the restore duration and result in the go-live sign-off sheet.

A backup strategy is not accepted until at least one restore drill succeeds.
