# JewelLAN private-LAN security model

JewelLAN is intended for a trusted Windows private LAN, not direct Internet exposure.

## Server transport

Production clients use HTTPS on TCP 8765. The JewelLAN server creates and retains a local server certificate and exposes its SHA-256 fingerprint. Counter clients pin that fingerprint after the operator verifies the server identity on first connection. A changed fingerprint is treated as an identity change and must not be silently accepted.

UDP 8766 is used only for private-LAN discovery. Discovery advertises the HTTPS endpoint and fingerprint; the client still probes the live certificate before trust.

Plain HTTP is a development-only escape hatch and must not be used for the Bijoria production deployment.

## TallyPrime

Because TallyPrime is on the same PC as the JewelLAN server for Bijoria, TallyPrime remains on localhost:9000 and JewelTallyBridge remains on localhost:8767 by default. The bridge bearer token therefore does not need to traverse the LAN.

## Windows network

The JewelLAN TCP and discovery firewall rules are limited to the Windows Private profile. No router port forwarding, public cloud tunnel, public reverse proxy or direct Internet exposure is part of the supported production architecture.

## Credentials

The initial administrator password must be changed before privileged operations. Production counters should use individual named accounts with the least role required. Shared administrator use for routine billing is not an accepted production configuration.

## Data and recovery

The SQLite database is accessed only by JewelServer on the main PC and is never placed on an SMB share. WAL/FULL synchronous mode, foreign keys, serialized writes, integrity checks, verified backups and restore validation are used to reduce corruption and recovery risk.
