from __future__ import annotations

import re
import ssl
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from cryptography import x509
from cryptography.x509.oid import ExtensionOID

from jewel_client.api import Api, ApiError, format_fingerprint, normalize_fingerprint, probe_server_fingerprint, secure_url
from jewel_server import tls


def test_client_requires_sha256_fingerprint(monkeypatch):
    fp = "AB" * 32
    assert normalize_fingerprint(":".join(fp[i:i+2] for i in range(0, 64, 2))) == fp
    assert format_fingerprint(fp).count(":") == 31
    assert secure_url("192.168.1.10:8765") == "https://192.168.1.10:8765"
    assert secure_url("http://192.168.1.10:8765") == "https://192.168.1.10:8765"
    monkeypatch.setenv("JEWELLAN_ALLOW_INSECURE_HTTP", "1")
    assert secure_url("http://192.168.1.10:8765") == "http://192.168.1.10:8765"
    try:
        normalize_fingerprint("1234")
    except ApiError:
        pass
    else:
        raise AssertionError("short fingerprints must be rejected")


def test_generated_server_identity_is_stable_and_valid(tmp_path, monkeypatch):
    monkeypatch.setenv("JEWELLAN_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(tls, "_restrict_private_key", lambda _path: None)

    first = tls.tls_identity()
    second = tls.tls_identity()
    assert first["fingerprint_sha256"] == second["fingerprint_sha256"]
    assert re.fullmatch(r"[0-9A-F]{64}", first["fingerprint_sha256"])
    assert first["fingerprint"] == format_fingerprint(first["fingerprint_sha256"])

    cert = x509.load_pem_x509_certificate(tls.cert_path().read_bytes())
    san = cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value
    assert "localhost" in san.get_values_for_type(x509.DNSName)
    assert any(str(ip) == "127.0.0.1" for ip in san.get_values_for_type(x509.IPAddress))
    assert tls.key_path().exists()


def test_pinned_https_request_accepts_self_signed_cert_and_rejects_wrong_pin(tmp_path, monkeypatch):
    monkeypatch.setenv("JEWELLAN_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(tls, "_restrict_private_key", lambda _path: None)
    identity = tls.tls_identity()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(identity["cert"], identity["key"])
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"https://127.0.0.1:{server.server_port}"
        live = probe_server_fingerprint(url)
        assert live == identity["fingerprint_sha256"]
        assert Api(url, live).get("/health") == {"ok": True}

        wrong = ("0" if live[0] != "0" else "1") + live[1:]
        with pytest.raises(ApiError, match="identity check failed"):
            Api(url, wrong).get("/health")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
