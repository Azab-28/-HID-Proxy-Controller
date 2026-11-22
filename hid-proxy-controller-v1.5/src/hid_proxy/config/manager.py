"""Configuration management with TOML persistence, schema validation, and optional encryption.

Encryption Design:
- encryption_password is NEVER stored in config file (avoids circular dependency)
- Password is provided at runtime via prompt or environment variable
- Uses Windows Credential Manager (keyring) if available for convenience
- Config file is encrypted with AES-GCM + PBKDF2 (200k iterations)
- Salt is stored separately (~/.config/HIDProxyController/salt.bin)
"""
import os
import tomli
import tomli_w
from pathlib import Path
from typing import Any, Optional
import logging
import copy

from hid_proxy.config.schema import AppConfig
from hid_proxy.utils.crypto import Crypto
from hid_proxy.utils.logging import get_logger

log = get_logger(__name__)

# Try to import keyring for Windows Credential Manager
try:
    import keyring
    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False

KEYRING_SERVICE = "HIDProxyController"
KEYRING_USERNAME = "encryption_password"


class ConfigManager:
    def __init__(self, config_dir: Optional[Path] = None, encryption_password: Optional[str] = None):
        if config_dir is None:
            try:
                from platformdirs import user_config_dir
                config_dir = Path(user_config_dir("HIDProxyController"))
            except ImportError:
                config_dir = Path.home() / "AppData" / "Local" / "HIDProxyController"
        self.config_dir = config_dir
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = config_dir / "config.toml"
        self.salt_file = config_dir / "salt.bin"
        
        self._config = self._load_defaults()
        self._crypto: Optional[Crypto] = None
        self._encryption_password = encryption_password
        self._password_source = "init" if encryption_password else None
        self.load()

    def _load_defaults(self) -> dict:
        return AppConfig().to_dict()

    def _get_encryption_password(self) -> Optional[str]:
        """Get encryption password from various sources (priority order):
        1. Provided at init (for tests/automation)
        2. Environment variable
        3. Windows Credential Manager (keyring)
        4. Interactive prompt (if running with UI)
        """
        # 1. Provided at init
        if self._encryption_password:
            return self._encryption_password

        # 2. Environment variable
        env_pass = os.environ.get("HIDPROXY_ENCRYPTION_PASSWORD")
        if env_pass:
            self._encryption_password = env_pass
            self._password_source = "env"
            return env_pass

        # 3. Keyring (Windows Credential Manager)
        if KEYRING_AVAILABLE:
            try:
                stored = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
                if stored:
                    self._encryption_password = stored
                    self._password_source = "keyring"
                    return stored
            except Exception as e:
                log.debug(f"Keyring read failed: {e}")

        return None

    def _prompt_for_password(self) -> Optional[str]:
        """Prompt user for encryption password via GUI dialog."""
        try:
            from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox
            app = QApplication.instance() or QApplication([])
            password, ok = QInputDialog.getText(
                None, "Encryption Password",
                "Enter encryption password to unlock config:",
                QInputDialog.EchoMode.Password
            )
            if ok and password:
                return password
            if not ok:
                # User cancelled - offer to disable encryption
                reply = QMessageBox.question(
                    None, "Encryption Required",
                    "Config is encrypted but no password provided.\n"
                    "Disable encryption and continue with defaults?",
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply == QMessageBox.Yes:
                    self._config.setdefault("security", {})["encrypt_config"] = False
                    self.save()
                    return None
        except Exception as e:
            log.error(f"Password prompt failed: {e}")
        return None

    def _get_crypto(self) -> Optional[Crypto]:
        """Get or create Crypto instance if encryption is enabled."""
        if self._crypto is not None:
            return self._crypto

        if not self._config.get("security", {}).get("encrypt_config", False):
            return None

        password = self._get_encryption_password()
        if not password:
            # Try prompting if we have a GUI
            password = self._prompt_for_password()
            if not password:
                log.warning("encrypt_config=true but no password available; disabling encryption")
                self._config.setdefault("security", {})["encrypt_config"] = False
                self.save()
                return None

        try:
            self._crypto = Crypto(password.encode("utf-8"), salt_file=self.salt_file)
            return self._crypto
        except Exception as e:
            log.error(f"Failed to initialize crypto: {e}")
            return None

    def load(self) -> bool:
        if not self.config_file.exists():
            self.save()
            return True
        try:
            crypto = self._get_crypto()

            if crypto:
                # Load encrypted config
                encrypted_data = self.config_file.read_bytes()
                try:
                    decrypted = crypto.decrypt(encrypted_data)
                    loaded = tomli.loads(decrypted.decode("utf-8"))
                except Exception as e:
                    log.error(f"Failed to decrypt config: {e}")
                    # Try loading as plain (migration from old version)
                    try:
                        with open(self.config_file, "rb") as f:
                            loaded = tomli.load(f)
                        log.info("Loaded plain config (migration from unencrypted)")
                        # Will be re-saved encrypted on next save
                    except Exception:
                        log.error("Config file corrupted, using defaults")
                        loaded = {}
            else:
                # Load plain config
                try:
                    with open(self.config_file, "rb") as f:
                        loaded = tomli.load(f)
                except Exception:
                    log.error("Failed to load plain config, using defaults")
                    loaded = {}

            # Validate loaded config against schema
            validated = self._validate_config(loaded)
            self._deep_update(self._config, validated)
            return True
        except Exception as e:
            log.error(f"Config load failed: {e}")
            self._config = self._load_defaults()
            self.save()
            return False

    def _validate_config(self, data: dict) -> dict:
        """Validate config against AppConfig schema, return validated dict."""
        try:
            app_config = AppConfig.from_dict(data)
            app_config.validate_all()
            return app_config.to_dict()
        except Exception as e:
            log.warning(f"Config validation failed, using defaults for invalid keys: {e}")
            defaults = AppConfig().to_dict()
            self._deep_update(defaults, data)
            try:
                app_config = AppConfig.from_dict(defaults)
                app_config.validate_all()
                return app_config.to_dict()
            except Exception:
                return defaults

    def save(self) -> bool:
        try:
            # Validate before saving
            validated = self._validate_config(self._config)

            # Check if encryption is enabled
            crypto = self._get_crypto()

            if crypto:
                # Save encrypted
                toml_bytes = tomli_w.dumps(validated).encode("utf-8")
                encrypted = crypto.encrypt(toml_bytes)
                self.config_file.write_bytes(encrypted)
                log.debug("Config saved (encrypted)")
            else:
                # Save plain - REMOVE security.encryption_password if present
                save_config = copy.deepcopy(validated)
                if "security" in save_config:
                    save_config["security"].pop("encryption_password", None)
                with open(self.config_file, "wb") as f:
                    tomli_w.dump(save_config, f)
                log.debug("Config saved (plain)")
            return True
        except Exception as e:
            log.error(f"Config save failed: {e}")
            return False

    def _deep_update(self, base: dict, update: dict) -> None:
        for k, v in update.items():
            if isinstance(v, dict) and k in base and isinstance(base[k], dict):
                self._deep_update(base[k], v)
            else:
                base[k] = v

    def get(self, key: str, default: Any = None) -> Any:
        keys = key.split(".")
        val = self._config
        for k in keys:
            if isinstance(val, dict) and k in val:
                val = val[k]
            else:
                return default
        return val

    def set(self, key: str, value: Any) -> None:
        keys = key.split(".")
        cfg = self._config
        for k in keys[:-1]:
            cfg = cfg.setdefault(k, {})
        cfg[keys[-1]] = value
        if key.startswith("security."):
            self._crypto = None
        self.save()

    def get_all(self) -> dict:
        """Return deep copy of entire config (WITHOUT encryption_password)."""
        config_copy = copy.deepcopy(self._config)
        # Never expose encryption_password
        if "security" in config_copy:
            config_copy["security"].pop("encryption_password", None)
        return config_copy

    def get_all_with_secrets(self) -> dict:
        """Return deep copy INCLUDING encryption_password (for internal use only)."""
        return copy.deepcopy(self._config)

    def set_encryption_password(self, password: str, save_to_keyring: bool = True) -> bool:
        """Set or change encryption password. Re-encrypts existing config."""
        try:
            # Get current plain config (without password)
            plain_config = self.get_all()
            
            # Update config
            self._config.setdefault("security", {})["encrypt_config"] = True
            # Don't store password in _config!
            
            # Store in keyring if available
            if save_to_keyring and KEYRING_AVAILABLE:
                try:
                    keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, password)
                except Exception as e:
                    log.warning(f"Failed to store password in keyring: {e}")
            
            # Update internal password cache
            self._encryption_password = password
            self._password_source = "set_encryption_password"
            
            # Reset crypto and save (will encrypt)
            self._crypto = None
            return self.save()
        except Exception as e:
            log.error(f"Failed to set encryption password: {e}")
            return False

    def remove_encryption(self) -> bool:
        """Disable encryption and save config as plain text."""
        try:
            plain_config = self.get_all()
            self._config.setdefault("security", {})["encrypt_config"] = False
            # Remove from keyring
            if KEYRING_AVAILABLE:
                try:
                    keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
                except Exception:
                    pass
            self._encryption_password = None
            self._password_source = None
            self._crypto = None
            return self.save()
        except Exception as e:
            log.error(f"Failed to remove encryption: {e}")
            return False