from __future__ import annotations

import json
import socket
import time
from typing import Any

import requests

DISCOVERY_PORT = 8766
MAGIC = b"JEWELLAN_DISCOVER_V1"


class ApiError(RuntimeError):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


class Api:
    def __init__(self, base_url: str = ""):
        self.base_url = base_url.rstrip("/")
        self.token = ""
        self.session = requests.Session()

    def set_url(self, url: str):
        self.base_url = url.rstrip("/")

    def headers(self):
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def request(self, method: str, path: str, *, params=None, json_body=None, timeout=10, retry_get=True):
        if not self.base_url:
            raise ApiError("Server not configured")
        url = self.base_url + path
        tries = 2 if method.upper() == "GET" and retry_get else 1
        last = None
        for attempt in range(tries):
            try:
                r = self.session.request(method, url, headers=self.headers(), params=params, json=json_body, timeout=timeout)
                if r.status_code >= 400:
                    try:
                        detail = r.json().get("detail", r.text)
                    except Exception:
                        detail = r.text
                    raise ApiError(str(detail), r.status_code)
                ctype = r.headers.get("content-type", "")
                return r.content if "application/pdf" in ctype or "octet-stream" in ctype else r.json()
            except ApiError:
                raise
            except requests.RequestException as e:
                last = e
                if attempt + 1 < tries:
                    time.sleep(.25)
        raise ApiError(f"Cannot reach JewelLAN server: {last}")

    def get(self, path, **kw):
        return self.request("GET", path, params=kw or None)

    def post(self, path, body=None):
        return self.request("POST", path, json_body=body or {}, retry_get=False)

    def put(self, path, body=None):
        return self.request("PUT", path, json_body=body or {}, retry_get=False)

    def login(self, username, password):
        data = self.post("/api/auth/login", {"username": username, "password": password, "client_name": socket.gethostname()})
        self.token = data["token"]
        return data["user"]


def discover_servers(timeout: float = 1.2) -> list[dict[str, Any]]:
    found = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(.2)
    try:
        sock.bind(("", 0))
        sock.sendto(MAGIC, ("255.255.255.255", DISCOVERY_PORT))
        end = time.time() + timeout
        while time.time() < end:
            try:
                data, addr = sock.recvfrom(2048)
                payload = json.loads(data.decode())
                payload["source_ip"] = addr[0]
                found[payload.get("url", addr[0])] = payload
            except socket.timeout:
                continue
            except Exception:
                continue
    finally:
        sock.close()
    return list(found.values())
