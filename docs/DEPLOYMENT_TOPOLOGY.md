# Bijoria deployment topology

```
Counter PC 2 (JewelPOS) --\
Counter PC 3 (JewelPOS) --- private LAN --> Main PC: JewelServer + JewelPOS
Main PC JewelPOS ----------/                       |
                                                  +-- local SQLite WAL database/backups
                                                  +-- JewelTallyBridge localhost:8767
                                                          |
                                                  TallyPrime localhost:9000
```

Counter-to-server traffic uses HTTPS on TCP 8765 with certificate fingerprint pinning. UDP 8766 is private-LAN discovery only. TallyPrime and the bridge remain local to the main PC in the Bijoria deployment.
