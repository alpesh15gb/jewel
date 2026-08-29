# JewelLAN

**Offline-first jewellery ERP/POS for Windows with multi-counter LAN access.**

JewelLAN is designed for a jewellery showroom where the internet can be unplugged indefinitely. One Windows PC runs `JewelServer.exe`; every sales/office PC runs `JewelPOS.exe` and connects over the shop's private LAN. The central database is never opened over a network share.

## What is implemented

- Windows counter client and Windows server build pipeline
- LAN server auto-discovery; manual IP configuration also works
- Role-based users: admin, manager, cashier, inventory and accounts
- Serialized jewellery inventory with barcode/tag, RFID EPC field, HUID and certificate
- Gold/silver/platinum purity, gross/stone/net/fine weights
- Metal rates, wastage, per-gram/percent/fixed making charge, stones and GST
- Code128 jewellery tag PDF generation
- Fast barcode-scan POS with split payments
- Old-gold exchange as an invoice payment
- GST invoice PDF, customer credit and invoice cancellation with stock reversal
- Supplier purchases / stock-in with tagged-item creation
- Customers, suppliers and karigars
- Repairs and custom orders
- Karigar metal/cash ledger API
- Approval/Jangad issue and return API
- Physical stock audit by barcode/RFID scan
- Double-entry journals, trial balance, ledger, stock/sales/payment reports
- Automatic online backups plus manual backup and offline restore
- Atomic multi-counter sale protection and request idempotency
- USB-COM weighing scale reader in the Windows client
- Append-only audit log

See `docs/PRODUCT_SPEC.md` for the product design and the public Omunim feature research that informed the workflows. Omunim is a reference only; JewelLAN uses no Omunim code or assets.

## Architecture

```text
Counter 1 JewelPOS.exe ----\
Counter 2 JewelPOS.exe -----+---- private LAN ---- JewelServer.exe ---- SQLite WAL database
Office   JewelPOS.exe ------/                         |
                                                     +---- automatic backups
```

SQLite is local to the **server process**, not on an SMB share. The server uses WAL mode, full synchronous writes, foreign keys, transactional stock transitions and a process write lock. The API boundary keeps a future PostgreSQL migration possible without replacing the clients.

## Windows build

GitHub Actions runs the tests and creates a `JewelLAN-Windows.zip` artifact containing:

- `JewelServer.exe`
- `JewelPOS.exe`
- server/client PowerShell install helpers

Open the repository's **Actions -> Windows build** run and download the artifact after the workflow completes.

### Server installation

On the main Windows PC, extract the zip and run PowerShell as Administrator:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install-server.ps1
```

The server listens on TCP `8765`; discovery uses UDP `8766`. Firewall rules are limited to the Windows Private network profile.

### Counter installation

Run `JewelPOS.exe` directly or use:

```powershell
.\install-client.ps1
```

On the login screen choose **Discover**. If discovery is blocked, enter the server PC's address, e.g. `http://192.168.1.20:8765`.

**Initial account:** `admin` / `Jewel@123`. The client forces an initial password change. Create individual cashier/inventory accounts before production use.

## Run from source

Requires Python 3.11+.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest -q
python run_server.py
```

On another terminal/PC:

```bash
python run_client.py
```

Production Windows data defaults to `C:\ProgramData\JewelLAN`.

## Barcode and hardware

USB barcode scanners that operate in keyboard/HID mode work immediately; configure the scanner to append Enter. The server produces Code128 label PDFs. Each workstation can use its own Windows printer. Weighing scales that expose a serial/USB-COM port can be configured per workstation. RFID EPC is supported in the data model and stock audit; direct reader SDK integration is vendor-specific.

## Backups

Automatic backups are created on the server and retained according to business settings. To restore, stop the server and run:

```powershell
JewelServer.exe --restore C:\path\to\backup.db
```

A safety backup is made before restore. Keep a second copy of backups on another physical device.

## Production notes

JewelLAN is intentionally **LAN-only**. Do not port-forward the server or expose it directly to the internet. Optional online services such as GST e-invoice submission, WhatsApp, SMS, payment reconciliation or live metal-rate feeds should be added as queued connectors so a network outage never stops billing.

Before live rollout, test the exact barcode printer, invoice format, weighing scale protocol, GST configuration and backup/restore procedure with the shop's accountant and hardware vendor.

## Development status

This repository is a complete v1 operational baseline rather than a mock UI: server, client, schema, transactional sale/purchase logic, PDFs, security, backups, tests and Windows packaging are present. Hardware-specific RFID/ZPL/TSPL integrations and government/cloud APIs are intentionally isolated as future adapters because they depend on the exact devices/services selected.
