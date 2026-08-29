# Unsupported production configurations

Do not run the JewelLAN database from an SMB/network share. Do not expose JewelLAN/Tally ports through Internet router forwarding. Do not use plain HTTP on production counters. Do not share the administrator account for routine billing. Do not manually edit posted rows in SQLite. Do not consider a backup valid until verification and a restore drill have been completed. Do not enable Tally live sync until the exact company and ledger mappings are tested.
