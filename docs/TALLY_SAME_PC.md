# TallyPrime on the main PC

Bijoria's supported topology keeps TallyPrime and JewelTallyBridge on the same main PC as JewelServer. TallyPrime remains on localhost:9000 and the bridge remains on localhost:8767. JewelServer reaches the bridge locally, so the bridge bearer token is not sent across the counter LAN. Do not change the bridge to a LAN listener unless the deployment topology changes and the transport is separately secured and reviewed.
