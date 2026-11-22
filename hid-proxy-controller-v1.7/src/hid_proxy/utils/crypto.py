"""Encryption utilities for config/profile protection.

Encrypted payload format:
  MAGIC (5 bytes: b"HCFG\x01") + SALT (32 bytes) + NONCE (12 bytes) + CIPHERTEXT+TAG
Self-contained header ensures encrypted files are always detectable on load
without circular dependency on unencrypted config flags.
"""
import os
from pathlib import Path
from typing import Optional
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

from hid_proxy.utils.logging import get_logger

log = get_logger(__name__)

MAGIC_HEADER = b"HCFG\x01"
SALT_SIZE = 32
NONCE_SIZE = 12
PBKDF2_ITERATIONS = 200_000


def is_encrypted_blob(data: bytes) -> bool:
    """Return True if data starts with the HCFG magic header."""
    return len(data) > (len(MAGIC_HEADER) + SALT_SIZE + NONCE_SIZE) and data.startswith(MAGIC_HEADER)


class Crypto:
    """AES-256-GCM encryption with PBKDF2-HMAC-SHA256 key derivation."""

    def __init__(self, password: bytes, salt: Optional[bytes] = None):
        if not password:
            raise ValueError("Password required for encryption/decryption")
        self._password = password
        self._salt = salt if salt is not None else os.urandom(SALT_SIZE)
        self.key = self._derive_key(password, self._salt)

    @staticmethod
    def _derive_key(password: bytes, salt: bytes) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=PBKDF2_ITERATIONS,
        )
        return kdf.derive(password)

    def encrypt(self, data: bytes) -> bytes:
        """Encrypt data into self-contained MAGIC + SALT + NONCE + CIPHERTEXT blob."""
        salt = os.urandom(SALT_SIZE)
        key = self._derive_key(self._password, salt)
        aesgcm = AESGCM(key)
        nonce = os.urandom(NONCE_SIZE)
        ct = aesgcm.encrypt(nonce, data, MAGIC_HEADER)
        return MAGIC_HEADER + salt + nonce + ct

    @classmethod
    def decrypt_with_password(cls, encrypted: bytes, password: bytes) -> bytes:
        """Decrypt a self-contained encrypted blob using password."""
        if not password:
            raise ValueError("Password required for decryption")
        if not is_encrypted_blob(encrypted):
            raise ValueError("Data is not a valid encrypted HCFG payload")
        offset = len(MAGIC_HEADER)
        salt = encrypted[offset : offset + SALT_SIZE]
        offset += SALT_SIZE
        nonce = encrypted[offset : offset + NONCE_SIZE]
        ct = encrypted[offset + NONCE_SIZE :]
        key = cls._derive_key(password, salt)
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce, ct, MAGIC_HEADER)

    def decrypt(self, encrypted: bytes) -> bytes:
        """Decrypt encrypted blob using this instance's password."""
        return self.decrypt_with_password(encrypted, self._password)

    @staticmethod
    def generate_key() -> bytes:
        return os.urandom(32)


def get_crypto_from_config(config_manager) -> Crypto:
    """Create Crypto instance from ConfigManager password."""
    password = config_manager.get_encryption_password()
    if not password:
        raise ValueError("Encryption password not configured.")
    return Crypto(password.encode("utf-8"))
