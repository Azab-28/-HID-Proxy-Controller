"""Encryption utilities for config/profile protection."""
import os
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

from hid_proxy.utils.logging import get_logger

log = get_logger(__name__)

# Default salt file location (per-user, not in repo)
DEFAULT_SALT_FILE = Path.home() / "AppData" / "Local" / "HIDProxyController" / "salt.bin"


class Crypto:
    """AES-GCM encryption with PBKDF2 key derivation.

    Key is derived from user-provided password + stored salt.
    No hardcoded secrets - without password, data cannot be decrypted.
    """

    def __init__(self, password: bytes, salt_file: Optional[Path] = None):
        """Initialize with user password (required).
        
        Args:
            password: User password as bytes
            salt_file: Optional custom salt file path (for testing)
        """
        if not password:
            raise ValueError("Password required for encryption/decryption")
        self._salt_file = salt_file or DEFAULT_SALT_FILE
        self.key = self._derive_key(password)

    def _derive_key(self, password: bytes) -> bytes:
        """Derive key from password using stored/generated salt."""
        salt = self._get_or_create_salt()
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=200000,
        )
        return kdf.derive(password)

    def _get_or_create_salt(self) -> bytes:
        """Get existing salt or generate new one."""
        self._salt_file.parent.mkdir(parents=True, exist_ok=True)
        if self._salt_file.exists():
            return self._salt_file.read_bytes()
        salt = os.urandom(32)
        self._salt_file.write_bytes(salt)
        log.info(f"Generated new salt at {self._salt_file}")
        return salt

    def encrypt(self, data: bytes) -> bytes:
        """Encrypt data, return nonce + ciphertext."""
        aesgcm = AESGCM(self.key)
        nonce = os.urandom(12)
        ct = aesgcm.encrypt(nonce, data, None)
        return nonce + ct

    def decrypt(self, encrypted: bytes) -> bytes:
        """Decrypt data (nonce + ciphertext)."""
        aesgcm = AESGCM(self.key)
        nonce = encrypted[:12]
        ct = encrypted[12:]
        return aesgcm.decrypt(nonce, ct, None)

    @staticmethod
    def generate_key() -> bytes:
        """Generate random key for non-password use cases."""
        return os.urandom(32)


from typing import Optional


def get_crypto_from_config(config_manager, salt_file: Optional[Path] = None) -> Crypto:
    """Create Crypto instance from config password.

    Expects config_manager.get("security.encryption_password") to return
    a user-set password string, or prompts if not set.
    """
    password = config_manager.get("security.encryption_password")
    if not password:
        raise ValueError("Encryption password not configured. Set 'security.encryption_password' in settings.")
    return Crypto(password.encode("utf-8"), salt_file=salt_file)