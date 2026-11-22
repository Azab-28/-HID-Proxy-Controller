"""Encryption utilities for config/profile protection."""
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

class Crypto:
    def __init__(self, password: bytes = None):
        if password is None:
            password = b"HIDProxyControllerDefaultKey2024"
        self.key = self._derive_key(password)
    
    def _derive_key(self, password: bytes) -> bytes:
        salt = b"HIDProxySalt2024"
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        return kdf.derive(password)
    
    def encrypt(self, data: bytes) -> bytes:
        aesgcm = AESGCM(self.key)
        nonce = os.urandom(12)
        ct = aesgcm.encrypt(nonce, data, None)
        return nonce + ct
    
    def decrypt(self, encrypted: bytes) -> bytes:
        aesgcm = AESGCM(self.key)
        nonce = encrypted[:12]
        ct = encrypted[12:]
        return aesgcm.decrypt(nonce, ct, None)
    
    @staticmethod
    def generate_key() -> bytes:
        return os.urandom(32)
