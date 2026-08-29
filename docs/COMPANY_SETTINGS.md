# Company settings

JewelLAN installers are company-neutral. A fresh database contains no shop name, GSTIN or GST state code. After the administrator changes the initial password, the desktop client requires Company Setup before the normal application opens.

Company Setup stores the company name, main branch/showroom, GST state code, optional GSTIN, address, PIN, phone, email, counter count, invoice/tag prefixes, GST default and business timezone in the server database. These values are editable later under **Administration > Company settings**.

The RC1/RC2 Bijoria seed was a release-candidate mistake. Schema migration 6 removes it only from untouched databases that still exactly match that obsolete seed; databases containing business data or a customized company name are never renamed.
