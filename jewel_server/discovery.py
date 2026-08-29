from __future__ import annotations

import json
import socket
import threading

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
                payload = json.dumps({"name":"JewelLAN Server","url":f"http://{ip}:{self.http_port}","version":1}).encode()
                sock.sendto(payload, addr)
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
