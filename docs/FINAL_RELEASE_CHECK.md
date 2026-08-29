# Final release check

Before distributing a JewelLAN production installer, confirm: PR Windows workflow green; installer artifact built from the reviewed commit; SHA-256 recorded; production docs included; database migration tests green; TLS/returns/recovery regressions green; no one-time source-generator workflow remains in the branch; and the installer performs a safe in-place upgrade without deleting ProgramData business data.
