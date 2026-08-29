# Hardware acceptance record

Complete this on the Bijoria main PC before live use. Keep the completed record with the release notes.

| Device | Model / connection | Test | Result |
| --- | --- | --- | --- |
| Barcode scanner |  | Scan tag into Billing and Inventory |  |
| Receipt/A4 printer |  | Print GST invoice and verify layout |  |
| Barcode label printer |  | Print label and rescan barcode |  |
| Weighing scale |  | Read stable known weight through configured COM port |  |
| RFID reader (optional) |  | Inventory audit/reader SDK test |  |
| Main PC |  | Reboot and automatic JewelLAN server startup |  |
| Counter PC 2 |  | TLS trust, login, scan and bill |  |
| Counter PC 3 |  | TLS trust, login, scan and bill |  |
| TallyPrime | Main PC | Test bridge, voucher post and credit-note reconciliation |  |

Any failed row blocks the production declaration for the affected workflow until corrected and retested.
