"""Local-CA certificate generation for optional HTTPS (mkcert-style).

outo-llms keeps its own root CA under ``data/certs/`` (``ca.crt`` /
``ca.key``) and signs the server's TLS certificate with it. Clients only
need ``data/certs/ca.crt`` in their trust store - after that, curl and
browsers trust the server with no warning, even on LAN/private IPs where
Let's Encrypt cannot issue. Generation is announced and logged; nothing
here runs without the user opting in during ``setup``.
"""

from __future__ import annotations

import datetime as dt
import ipaddress
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from . import consent, paths

_VALID_DAYS = 825
_CA_VALID_DAYS = 3650
_RENEW_BEFORE_DAYS = 30


def _name_entry(name: str) -> x509.GeneralName:
    try:
        return x509.IPAddress(ipaddress.ip_address(name))
    except ValueError:
        return x509.DNSName(name)


def _san_entries(common_name: str, extra_names: list[str]) -> list[x509.GeneralName]:
    entries: list[x509.GeneralName] = [
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
        _name_entry(common_name),
    ]
    seen = {"localhost", "127.0.0.1", common_name}
    for name in extra_names:
        if name in seen:
            continue
        seen.add(name)
        entries.append(_name_entry(name))
    return entries


def _write_key(path: Path, key: rsa.RSAPrivateKey) -> None:
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    path.chmod(0o600)


def _write_cert(path: Path, cert: x509.Certificate) -> None:
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    path.chmod(0o644)


def ensure_local_ca() -> tuple[Path, Path]:
    """Return ``(ca_cert_path, ca_key_path)``, generating the root CA if absent.

    The CA persists across server-cert regenerations so clients only ever
    install one CA file.
    """
    paths.ensure_dirs()
    ca_cert_path = paths.certs_dir() / "ca.crt"
    ca_key_path = paths.certs_dir() / "ca.key"
    if ca_cert_path.is_file() and ca_key_path.is_file():
        return ca_cert_path, ca_key_path

    consent.announce("generate local certificate authority", str(ca_cert_path))
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = dt.datetime.now(dt.timezone.utc)
    name = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "outo-llms local CA"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "outo-llms"),
        ]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=_CA_VALID_DAYS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=None,
                decipher_only=None,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    _write_key(ca_key_path, key)
    _write_cert(ca_cert_path, cert)
    consent.log_action("generate_ca", str(ca_cert_path))
    return ca_cert_path, ca_key_path


def ensure_server_cert(
    common_name: str, extra_names: list[str] | None = None
) -> tuple[Path, Path]:
    """Return ``(cert_path, key_path)`` for a CA-signed server certificate.

    Reuses the existing pair only when it was issued by our CA for the same
    common name and is not within 30 days of expiry; otherwise regenerates.
    """
    paths.ensure_dirs()
    ca_cert_path, ca_key_path = ensure_local_ca()
    ca_cert = x509.load_pem_x509_certificate(ca_cert_path.read_bytes())
    ca_key = serialization.load_pem_private_key(ca_key_path.read_bytes(), password=None)
    if not isinstance(ca_key, rsa.RSAPrivateKey):
        raise RuntimeError(
            f"local CA key at {ca_key_path} is not an RSA key; "
            "delete ca.crt and ca.key under the certs directory and re-run setup"
        )

    cert_path = paths.certs_dir() / "server.crt"
    key_path = paths.certs_dir() / "server.key"
    now = dt.datetime.now(dt.timezone.utc)
    if cert_path.is_file() and key_path.is_file():
        try:
            existing = x509.load_pem_x509_certificate(cert_path.read_bytes())
            existing_cn = existing.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[
                0
            ].value
            issued_by_our_ca = existing.issuer == ca_cert.subject
            fresh_enough = existing.not_valid_after_utc > now + dt.timedelta(
                days=_RENEW_BEFORE_DAYS
            )
        except Exception:
            # A corrupt or unparseable certificate must not block setup;
            # fall through and regenerate the pair.
            existing_cn = None
            issued_by_our_ca = False
            fresh_enough = False
        if existing_cn == common_name and issued_by_our_ca and fresh_enough:
            return cert_path, key_path

    extras = extra_names if extra_names is not None else []
    consent.announce("generate CA-signed HTTPS certificate", str(cert_path))
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    ca_ski = ca_cert.extensions.get_extension_for_class(x509.SubjectKeyIdentifier).value
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=_VALID_DAYS))
        .add_extension(
            x509.SubjectAlternativeName(_san_entries(common_name, extras)),
            critical=False,
        )
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
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_subject_key_identifier(ca_ski),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    _write_key(key_path, key)
    _write_cert(cert_path, cert)
    consent.log_action(
        "generate_cert", f"{cert_path} (CN={common_name}, issued by local CA)"
    )
    return cert_path, key_path
