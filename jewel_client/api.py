from __future__ import annotations

import hashlib
import json
import os
import socket
import ssl
import time
from typing import Any
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3 import PoolManager

DISCOVERY_PORT = 8766
MAGIC = b"JEWELLAN_DISCOVER_V1"


class ApiError(RuntimeError):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


def normalize_fingerprint(value: str | None) -> str:
    raw = "".join(ch for ch in str(value or "") if ch in "0123456789abcdefABCDEF").upper()
    if raw and len(raw) != 64:
        raise ApiError("Server certificate fingerprint must be a SHA-256 fingerprint")
    return raw


def format_fingerprint(value: str) -> str:
    raw = normalize_fingerprint(value)
    return ":".join(raw[i : i + 2] for i in range(0, len(raw), 2))


def secure_url(url: str) -> str:
    raw = (url or "").strip().rstrip("/")
    if not raw:
        return raw
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urlparse(raw)
    if parsed.scheme.lower() == "http" and os.environ.get("JEWELLAN_ALLOW_INSECURE_HTTP") != "1":
        raw = "https://" + parsed.netloc + parsed.path
    return raw.rstrip("/")


def probe_server_fingerprint(url: str, timeout: float = 4.0) -> str:
    parsed = urlparse(secure_url(url))
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ApiError("Production JewelLAN connections require HTTPS")
    port = parsed.port or 443
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((parsed.hostname, port), timeout=timeout) as raw:
            with context.wrap_socket(raw, server_hostname=parsed.hostname) as tls:
                der = tls.getpeercert(binary_form=True)
    except OSError as exc:
        raise ApiError(f"Could not reach the JewelLAN server securely: {exc}") from exc
    if not der:
        raise ApiError("The server did not present a TLS certificate")
    return hashlib.sha256(der).hexdigest().upper()


class FingerprintAdapter(HTTPAdapter):
    def __init__(self, fingerprint: str, *args, **kwargs):
        self.fingerprint = normalize_fingerprint(fingerprint)
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        pool_kwargs.update(
            ssl_context=context,
            assert_fingerprint=self.fingerprint,
            cert_reqs=ssl.CERT_NONE,
            assert_hostname=False,
        )
        self.poolmanager = PoolManager(num_pools=connections, maxsize=maxsize, block=block, **pool_kwargs)

    def cert_verify(self, conn, url, verify, cert):
        # Trust is supplied by urllib3's SHA-256 assert_fingerprint above.
        return


class Api:
    def __init__(self, base_url: str = "", fingerprint: str = ""):
        self.base_url = secure_url(base_url)
        self.fingerprint = normalize_fingerprint(fingerprint)
        self.token = ""
        self.session = requests.Session()
        self._configure_transport()

    def _configure_transport(self):
        try:
            self.session.close()
        except Exception:
            pass
        self.session = requests.Session()
        self.session.trust_env = False
        if self.base_url.startswith("https://") and self.fingerprint:
            self.session.mount("https://", FingerprintAdapter(self.fingerprint))

    def set_url(self, url: str, fingerprint: str | None = None):
        self.base_url = secure_url(url)
        if fingerprint is not None:
            self.fingerprint = normalize_fingerprint(fingerprint)
        self._configure_transport()

    def trust_server(self, url: str, fingerprint: str):
        self.base_url = secure_url(url)
        self.fingerprint = normalize_fingerprint(fingerprint)
        self._configure_transport()

    def headers(self):
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def request(self, method: str, path: str, *, params=None, json_body=None, timeout=10, retry_get=True):
        if not self.base_url:
            raise ApiError("Server not configured")
        if self.base_url.startswith("https://") and not self.fingerprint:
            raise ApiError("This server has not been trusted yet. Verify its SHA-256 fingerprint first.")
        if self.base_url.startswith("http://") and os.environ.get("JEWELLAN_ALLOW_INSECURE_HTTP") != "1":
            raise ApiError("Insecure HTTP is disabled. JewelLAN production connections require HTTPS.")
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
            except requests.exceptions.SSLError as exc:
                raise ApiError("Server identity check failed. The TLS certificate fingerprint changed; do not continue until the server is verified.") from exc
            except requests.RequestException as exc:
                last = exc
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
                data, addr = sock.recvfrom(4096)
                payload = json.loads(data.decode())
                url = secure_url(payload.get("url") or f"https://{addr[0]}:8765")
                fingerprint = normalize_fingerprint(payload.get("fingerprint_sha256") or payload.get("fingerprint"))
                if not fingerprint:
                    continue
                found[url] = {
                    "url": url,
                    "name": payload.get("name", "JewelLAN Server"),
                    "source_ip": addr[0],
                    "fingerprint_sha256": fingerprint,
                    "fingerprint": format_fingerprint(fingerprint),
                }
            except socket.timeout:
                continue
            except Exception:
                continue
    finally:
        sock.close()
    return list(found.values())
