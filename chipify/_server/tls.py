"""
tls.py – Self-signed cert generation + SHA-256 fingerprint helper.

The chipify server uses a self-signed cert by default, generated lazily on
first start under ``~/.chipify/server-{cert,key}.pem``. The client pins the
cert's SHA-256 fingerprint via TOFU on first contact (mirrors the SSH
host-key UX the project used previously).

Fingerprint format matches what OpenSSH and ``openssl x509 -fingerprint
-sha256`` produce: ``SHA256:<base64url-no-padding>``.
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import logging
import os
import socket
from pathlib import Path

log = logging.getLogger("chipify._server.tls")


def fingerprint_sha256(pem_or_der: bytes) -> str:
    """Return ``SHA256:<base64url-no-padding>`` for the cert.

    Accepts PEM (``-----BEGIN CERTIFICATE-----``) or DER. PEM is decoded to
    DER before hashing so the result matches ``openssl x509 -fingerprint
    -sha256`` (which always hashes the DER body).
    """
    data = pem_or_der.strip()
    if data.startswith(b"-----BEGIN"):
        # Strip header/footer + any whitespace, then base64-decode.
        body = b"".join(
            line for line in data.splitlines()
            if line and not line.startswith(b"-----")
        )
        data = base64.b64decode(body)
    digest = hashlib.sha256(data).digest()
    return "SHA256:" + base64.b64encode(digest).rstrip(b"=").decode("ascii")


def ensure_self_signed_cert(
    cert_path: Path,
    key_path: Path,
    *,
    common_name: str = "chipify-server",
    sans: list[str] | None = None,
    days_valid: int = 3650,
) -> tuple[Path, Path]:
    """Create an RSA-2048 self-signed cert pair if either file is missing.

    Writes key 0600 and cert 0644. Returns the (cert, key) paths. If both
    files already exist, returns immediately without inspecting them.
    """
    cert_path = Path(cert_path)
    key_path  = Path(key_path)
    if cert_path.is_file() and key_path.is_file():
        return cert_path, key_path

    # Defer the cryptography import so ``chipify[remote]`` (client-only)
    # users never need it.
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    if sans is None:
        sans = ["localhost", "127.0.0.1"]
        try:
            host = socket.gethostname()
            if host and host not in sans:
                sans.append(host)
        except OSError:
            pass

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
    ])
    san_objs: list[x509.GeneralName] = []
    for entry in sans:
        try:
            import ipaddress
            san_objs.append(x509.IPAddress(ipaddress.ip_address(entry)))
        except ValueError:
            san_objs.append(x509.DNSName(entry))

    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=days_valid))
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None), critical=True,
        )
        .add_extension(
            x509.SubjectAlternativeName(san_objs), critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    cert_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    cert_path.write_bytes(cert_pem)
    key_path.write_bytes(key_pem)
    try:
        os.chmod(key_path, 0o600)
        os.chmod(cert_path, 0o644)
    except OSError:
        # chmod is best-effort on Windows / network filesystems.
        pass

    log.info(
        "Generated self-signed TLS cert: %s (fingerprint %s)",
        cert_path, fingerprint_sha256(cert_pem),
    )
    return cert_path, key_path
