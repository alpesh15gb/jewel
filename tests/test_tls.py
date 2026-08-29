from __future__ import annotations

import re

from cryptography import x509
from cryptography.x509.oid import ExtensionOID

from jewel_client.api import ApiError, format_fingerprint, normalize_fingerprint, secure_url
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
    # Unit tests validate certificate contents; the packaged Windows self-test
    # exercises the real icacls private-key ACL path.
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
