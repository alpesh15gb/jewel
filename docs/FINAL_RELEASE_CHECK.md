# Final release check

Before distributing a JewelLAN production installer, confirm: PR Windows workflow green; installer artifact built from the reviewed commit; SHA-256 recorded; production docs included; database migration tests green; TLS/returns/recovery regressions green; no one-time source-generator workflow remains in the branch; and the installer performs a safe in-place upgrade without deleting ProgramData business data.

## Code signing gate (required before broad distribution)
Current EXEs/installer are unsigned → SmartScreen Unknown publisher. Before live rollout: obtain org EV/OV code-signing cert, sign JewelServer.exe/JewelPOS.exe/JewelTallyBridge.exe + Setup.exe with timestamp, verify with signtool verify, record thumbprint in GO_LIVE_SIGNOFF. Cannot be fixed in code alone.
