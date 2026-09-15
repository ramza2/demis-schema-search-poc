"""Unit tests for Target credential Fernet encryption helpers."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.security.credential_crypto import (
    CredentialCryptoError,
    decrypt_password,
    encrypt_password,
    validate_encryption_key,
)


def test_encrypt_decrypt_round_trip():
    key = Fernet.generate_key().decode()
    token = encrypt_password("db-secret-xyz", key)
    assert token != "db-secret-xyz"
    assert decrypt_password(token, key) == "db-secret-xyz"


def test_plaintext_never_equals_ciphertext():
    key = Fernet.generate_key().decode()
    plain = "plain-password-value"
    cipher = encrypt_password(plain, key)
    assert plain not in cipher
    assert cipher.startswith("gAAAA")  # Fernet token prefix


def test_missing_key_raises():
    with pytest.raises(CredentialCryptoError, match="not configured"):
        encrypt_password("x", None)
    with pytest.raises(CredentialCryptoError, match="not configured"):
        encrypt_password("x", "   ")


def test_invalid_key_raises():
    with pytest.raises(CredentialCryptoError, match="invalid"):
        encrypt_password("x", "not-a-fernet-key")
    with pytest.raises(CredentialCryptoError, match="invalid"):
        validate_encryption_key("not-a-fernet-key")


def test_validate_encryption_key_allows_empty():
    validate_encryption_key(None)
    validate_encryption_key("")
    validate_encryption_key("   ")


def test_wrong_key_decrypt_fails():
    key1 = Fernet.generate_key().decode()
    key2 = Fernet.generate_key().decode()
    token = encrypt_password("secret", key1)
    with pytest.raises(CredentialCryptoError, match="Failed to decrypt"):
        decrypt_password(token, key2)


def test_empty_password_rejected():
    key = Fernet.generate_key().decode()
    with pytest.raises(CredentialCryptoError, match="must not be empty"):
        encrypt_password("", key)
