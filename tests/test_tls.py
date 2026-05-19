"""Cert generation + fingerprint helper tests."""
from __future__ import annotations

import os
import pytest

cryptography = pytest.importorskip("cryptography")
from chipify._server.tls import ensure_self_signed_cert, fingerprint_sha256


def test_self_signed_generates_pair(tmp_path):
    cert = tmp_path / "cert.pem"
    key  = tmp_path / "key.pem"
    out_cert, out_key = ensure_self_signed_cert(cert, key)
    assert out_cert == cert and out_key == key
    assert cert.is_file() and key.is_file()
    assert cert.read_bytes().startswith(b"-----BEGIN CERTIFICATE-----")
    assert b"PRIVATE KEY" in key.read_bytes()


def test_self_signed_does_not_overwrite(tmp_path):
    cert = tmp_path / "cert.pem"
    key  = tmp_path / "key.pem"
    ensure_self_signed_cert(cert, key)
    before = cert.read_bytes()
    ensure_self_signed_cert(cert, key)
    assert cert.read_bytes() == before, "should not regenerate when both files exist"


def test_fingerprint_is_reproducible(tmp_path):
    cert = tmp_path / "cert.pem"
    key  = tmp_path / "key.pem"
    ensure_self_signed_cert(cert, key)
    pem = cert.read_bytes()
    fp1 = fingerprint_sha256(pem)
    fp2 = fingerprint_sha256(pem)
    assert fp1 == fp2
    assert fp1.startswith("SHA256:")
    # Strip prefix + base64 → 32 bytes of digest. base64 of 32 bytes
    # without padding is 43 characters (32*4/3 rounded up to 43).
    assert len(fp1[len("SHA256:"):]) == 43


def test_fingerprint_pem_matches_der(tmp_path):
    cert = tmp_path / "cert.pem"
    key  = tmp_path / "key.pem"
    ensure_self_signed_cert(cert, key)
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    pem = cert.read_bytes()
    cert_obj = x509.load_pem_x509_certificate(pem)
    der = cert_obj.public_bytes(serialization.Encoding.DER)
    assert fingerprint_sha256(pem) == fingerprint_sha256(der)
