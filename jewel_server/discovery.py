from __future__ import annotations

import json
import os
import socket
import threading

from .tls import tls_identity

DISCOVERY_PORT = 8766
MAGIC = b"JEWELLAN_DISCOVER_V1"


class DiscoveryResponder(threading.Thread):
    daemon = True
    def __init__(self, http_port: int = 8765):
        super().__init__(name="JewelLAN-Discovery")
        self.http_port = http_port
        self.stop_event = threading.Event()
        self.sock: socket.socket | None = None

    def run(self) -> None:
        insecure = os.environ.get("JEWELLAN_INSECURE_HTTP") == "1"
        try:
            identity = {} if insecure else tls_identity()
        except OSError:
            # Discovery must never take down the server if certificate
            # material is temporarily locked during startup or rotation.
            return
        scheme = "http" if insecure else "https"
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock = sock
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", DISCOVERY_PORT)); sock.settimeout(1)
        while not self.stop_event.is_set():
            try:
                data, addr = sock.recvfrom(1024)
                if data.strip() != MAGIC: continue
                probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                try:
                    probe.connect((addr[0], 9)); ip = probe.getsockname()[0]
                except OSError:
                    ip = socket.gethostbyname(socket.gethostname())
                finally:
                    probe.close()
                payload = {
                    "name":"JewelLAN Server",
                    "url":f"{scheme}://{ip}:{self.http_port}",
                    "version":3,
                    "transport":scheme,
                }
                if identity:
                    payload["fingerprint_sha256"] = identity["fingerprint_sha256"]
                    payload["fingerprint"] = identity["fingerprint"]
                sock.sendto(json.dumps(payload).encode(), addr)
            except socket.timeout:
                pass
            except OSError:
                break
        sock.close()

    def stop(self) -> None:
        self.stop_event.set()
        if self.sock:
            try: self.sock.close()
            except OSError: pass
