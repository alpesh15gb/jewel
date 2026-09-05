"""Offline direct thermal send — ZPL/TSPL bytes to printer, no internet.
Supports: serial COM (USB-serial Zebra/TSC) and TCP raw 9100 (LAN Zebra).
All local. Failures return clear operator errors.
"""
from __future__ import annotations

def send_serial(data: bytes | str, port: str, baud: int = 9600, timeout: float = 5.0) -> None:
    if not port:
        raise RuntimeError("No printer port selected")
    try:
        import serial
    except Exception as e:
        raise RuntimeError("pyserial is not installed") from e
    raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
    with serial.Serial(port, baudrate=int(baud or 9600), timeout=timeout) as s:
        s.write(raw)
        s.flush()

def send_tcp(data: bytes | str, host: str, port: int = 9100, timeout: float = 5.0) -> None:
    import socket
    if not host:
        raise RuntimeError("No printer IP entered")
    raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
    with socket.create_connection((host.strip(), int(port or 9100)), timeout=timeout) as sock:
        sock.sendall(raw)

def save_file(data: bytes | str, path: str) -> None:
    raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
    with open(path, "wb") as fh:
        fh.write(raw)
