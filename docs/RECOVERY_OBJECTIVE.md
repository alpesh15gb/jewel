# Recovery objective

The supported design prioritizes correctness and recoverability over continuous availability: if the main PC is unavailable, counters must not create divergent local invoices. Resume posting only when JewelServer is reachable and trusted again. Use verified backups and controlled restore rather than offline split-brain databases.
