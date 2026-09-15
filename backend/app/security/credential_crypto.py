"""Encrypt/decrypt Target DB passwords at rest (Fernet authenticated encryption)."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class CredentialCryptoError(ValueError):
    """Raised when encryption key is missing/invalid or decrypt fails."""


def _fernet(encryption_key: str | None) -> Fernet:
    key = (encryption_key or "").strip()
    if not key:
        raise CredentialCryptoError(
            "TARGET_CREDENTIAL_ENCRYPTION_KEY is not configured. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\""
        )
    try:
        return Fernet(key.encode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — invalid key material
        raise CredentialCryptoError(
            "TARGET_CREDENTIAL_ENCRYPTION_KEY is invalid "
            "(expected a Fernet url-safe base64 32-byte key)"
        ) from exc


def validate_encryption_key(encryption_key: str | None) -> None:
    """Validate key format when a non-empty value is provided."""
    if encryption_key is None or not str(encryption_key).strip():
        return
    _fernet(encryption_key)


def encrypt_password(plaintext: str, encryption_key: str | None) -> str:
    """Encrypt a Target password; the empty string is a valid passwordless credential."""
    if plaintext is None:
        raise CredentialCryptoError("password must not be None")
    token = _fernet(encryption_key).encrypt(plaintext.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_password(ciphertext: str, encryption_key: str | None) -> str:
    if not ciphertext:
        raise CredentialCryptoError("no saved credential to decrypt")
    try:
        return _fernet(encryption_key).decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise CredentialCryptoError(
            "Failed to decrypt saved Target credential "
            "(check TARGET_CREDENTIAL_ENCRYPTION_KEY)"
        ) from exc
