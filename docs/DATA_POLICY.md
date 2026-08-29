# JewelLAN production data policy

For live Bijoria use, posted business records are corrected through explicit reversals, returns, credit notes or adjustment entries rather than direct database edits.

- Money-critical canonical values are integer paise.
- Weight-critical canonical values are integer milligrams.
- Jewellery tags, HUIDs and serialized stock state must remain unique and traceable.
- Posted sales, sale lines, journals and stock movements are treated as immutable business history.
- Returns create separate credit-note history and stock/accounting reversals.
- Audit-chain verification and canonical reconciliation are part of the Data Health gate.
- Backups must be verified before they are considered valid recovery points.
- Restore must be performed only through the supported recovery path and followed by integrity/day-close checks.
- Manual SQLite editing is not an accepted production support procedure.

Before the first live invoice, create and verify a baseline backup after business/users/Tally configuration and again after opening stock is entered.
