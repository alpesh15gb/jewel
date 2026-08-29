from __future__ import annotations

import datetime as dt
import hashlib
import ipaddress
import os
import socket
import subprocess
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from .db import app_data_dir

TLS_DIR_NAME = "tls"
CERT_NAME = "server-cert.pem"
KEY_NAME = "server-key.pem"


def tls_dir() -> Path:
    path = app_data_dir() / TLS_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def cert_path() -> Path:
    return tls_dir() / CERT_NAME


def key_path() -> Path:
    return tls_dir() / KEY_NAME


def _local_addresses() -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    values: set[str] = {"127.0.0.1", "::1"}
    try:
        for family, _, _, _, sockaddr in socket.getaddrinfo(socket.gethostname(), None):
            if family in (socket.AF_INET, socket.AF_INET6):
                values.add(sockaddr[0].split("%", 1)[0])
    except OSError:
        pass
    out = []
    for value in sorted(values):
        try:
            out.append(ipaddress.ip_address(value))
        except ValueError:
            continue
    return out


def _restrict_private_key(path: Path) -> None:
    if os.name != "nt":
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return
    # The production server runs as SYSTEM. Remove inherited ACLs and allow only
    # SYSTEM and local Administrators to read the private key.
    try:
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", "SYSTEM:F", "Administrators:F"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
    except Exception as exc:
        raise RuntimeError(f"Could not secure JewelLAN TLS private key ACL: {exc}") from exc


def generate_server_certificate() -> tuple[Path, Path]:
    cert = cert_path()
    key = key_path()
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    now = dt.datetime.now(dt.timezone.utc)
    hostname = socket.gethostname() or "JewelLAN-Server"
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "JewelLAN"),
            x509.NameAttribute(NameOID.COMMON_NAME, "JewelLAN Private LAN Server"),
        ]
    )
    san_values: list[x509.GeneralName] = [x509.DNSName("localhost"), x509.DNSName(hostname)]
    san_values.extend(x509.IPAddress(addr) for addr in _local_addresses())
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName(san_values), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=None,
                decipher_only=None,
            ),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(private_key=private_key, algorithm=hashes.SHA256())
    )
    key_tmp = key.with_suffix(".tmp")
    cert_tmp = cert.with_suffix(".tmp")
    key_tmp.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_tmp.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    _restrict_private_key(key_tmp)
    os.replace(key_tmp, key)
    os.replace(cert_tmp, cert)
    _restrict_private_key(key)
    return cert, key


def ensure_server_certificate() -> tuple[Path, Path]:
    cert = cert_path()
    key = key_path()
    if cert.exists() and key.exists():
        try:
            loaded = x509.load_pem_x509_certificate(cert.read_bytes())
            now = dt.datetime.now(dt.timezone.utc)
            expiry = loaded.not_valid_after_utc
            if expiry > now + dt.timedelta(days=30):
                _restrict_private_key(key)
                return cert, key
        except Exception:
            pass
    return generate_server_certificate()


def certificate_fingerprint(path: Path | None = None) -> str:
    cert = x509.load_pem_x509_certificate((path or cert_path()).read_bytes())
    raw = cert.public_bytes(serialization.Encoding.DER)
    return hashlib.sha256(raw).hexdigest().upper()


def formatted_fingerprint(value: str | None = None) -> str:
    raw = (value or certificate_fingerprint()).replace(":", "").upper()
    return ":".join(raw[i : i + 2] for i in range(0, len(raw), 2))


def tls_identity() -> dict[str, str]:
    cert, key = ensure_server_certificate()
    fp = certificate_fingerprint(cert)
    return {"cert": str(cert), "key": str(key), "fingerprint_sha256": fp, "fingerprint": formatted_fingerprint(fp)}
