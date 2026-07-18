"""Self-signed certificate generation for optional HTTPS.

Certificates live in ``data/certs/``. Generation is announced and logged;
nothing here runs without the user opting in during ``setup``.
"""

from __future__ import annotations

import datetime as dt
import ipaddress
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from . import consent, paths

_VALID_DAYS = 825


def _san_entries(common_name: str) -> list[x509.GeneralName]:
    entries: list[x509.GeneralName] = [
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
    ]
    try:
        entries.append(x509.IPAddress(ipaddress.ip_address(common_name)))
    except ValueError:
        entries.append(x509.DNSName(common_name))
    return entries


def ensure_self_signed_cert(common_name: str) -> tuple[Path, Path]:
    """Return ``(cert_path, key_path)``, generating a self-signed pair if absent."""
    paths.ensure_dirs()
    cert_path = paths.certs_dir() / "server.crt"
    key_path = paths.certs_dir() / "server.key"
    if cert_path.is_file() and key_path.is_file():
        return cert_path, key_path

    consent.announce("generate self-signed HTTPS certificate", str(cert_path))
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = dt.datetime.now(dt.timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + dt.timedelta(days=_VALID_DAYS))
        .add_extension(x509.SubjectAlternativeName(_san_entries(common_name)), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    consent.log_action("generate_cert", f"{cert_path} (CN={common_name})")
    return cert_path, key_path
