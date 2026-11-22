"""Configuration management with TOML persistence, schema validation, and optional encryption."""
import tomli
import tomli_w
from pathlib import Path
from typing import Any, Optional
import logging
import copy

from hid_proxy.config.schema import AppConfig
from hid_proxy.utils.crypto import Crypto, get_crypto_from_config
from hid_proxy.utils.logging import get_logger

log = get_logger(__name__)


class ConfigManager:
    def __init__(self, config_dir: Optional[Path] = None):
        if config_dir is None:
            # Use platformdirs for cross-platform config directory
            try:
                from platformdirs import user_config_dir
                config_dir = Path(user_config_dir("HIDProxyController"))
            except ImportError:
                config_dir = Path.home() / "AppData" / "Local" / "HIDProxyController"
        self.config_dir = config_dir
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = config_dir / "config.toml"
        self._config = self._load_defaults()
        self._crypto: Optional[Crypto] = None
        self.load()

    def _load_defaults(self) -> dict:
        return AppConfig().to_dict()

    def _get_crypto(self) -> Optional[Crypto]:
        """Get or create Crypto instance if encryption is enabled."""
        if self._crypto is not None:
            return self._crypto
        
        if not self._config.get("security", {}).get("encrypt_config", False):
            return None
        
        password = self._config.get("security", {}).get("encryption_password", "")
        if not password:
            log.warning("encrypt_config=true but encryption_password not set; disabling encryption")
            self._config.setdefault("security", {})["encrypt_config"] = False
            return None
        
        try:
            self._crypto = Crypto(password.encode("utf-8"))
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
                    # Try loading as plain (migration)
                    with open(self.config_file, "rb") as f:
                        loaded = tomli.load(f)
                    # Re-save encrypted
                    self._config = self._load_defaults()
                    self._deep_update(self._config, loaded)
                    self.save()
                    return True
            else:
                # Load plain config
                with open(self.config_file, "rb") as f:
                    loaded = tomli.load(f)
            
            # Validate loaded config against schema
            validated = self._validate_config(loaded)
            self._deep_update(self._config, validated)
            return True
        except Exception as e:
            log.error(f"Config load failed: {e}")
            # Fallback to defaults
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
            # Return only valid keys by merging with defaults
            defaults = AppConfig().to_dict()
            self._deep_update(defaults, data)
            # Validate again
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
                # Save plain
                with open(self.config_file, "wb") as f:
                    tomli_w.dump(validated, f)
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
        # Invalidate crypto cache if security settings changed
        if key.startswith("security."):
            self._crypto = None
        self.save()

    def get_all(self) -> dict:
        """Return deep copy of entire config."""
        return copy.deepcopy(self._config)

    def set_encryption_password(self, password: str) -> bool:
        """Set or change encryption password. Re-encrypts existing config."""
        try:
            # Get current plain config
            plain_config = self.get_all()
            
            # Update password
            self._config.setdefault("security", {})["encryption_password"] = password
            self._config.setdefault("security", {})["encrypt_config"] = True
            
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
            self._config.setdefault("security", {})["encryption_password"] = ""
            self._crypto = None
            return self.save()
        except Exception as e:
            log.error(f"Failed to remove encryption: {e}")
            return False