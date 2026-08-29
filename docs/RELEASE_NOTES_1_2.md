# JewelLAN 1.2 production candidate

This release consolidates the production-hardening work for a clean-start jewellery store deployment.

Highlights include exact canonical paise/milligram reconciliation, server/database weight and HUID validation, immutable posted accounting/stock records, tamper-evident audit chaining, verified backups, day-close checks, authentication hardening, HTTPS private-LAN transport with certificate pinning, safe Windows in-place upgrades, asynchronous TallyPrime integration, Tally XML compatibility, item-level credit-note returns, stock/accounting reversal controls, and expanded Windows regression tests.

The target first deployment is Bijoria, Telangana, with three Windows PCs and TallyPrime on the main JewelLAN server PC. The business profile remains configurable rather than being permanently hard-coded into application source.

The production label is conditional on both the full CI release gate and the physical acceptance checklist in `docs/PRODUCTION_ACCEPTANCE.md`.
