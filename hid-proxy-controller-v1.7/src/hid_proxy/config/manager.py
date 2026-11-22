"""Configuration management with TOML persistence, schema validation, and AES-GCM encryption."""
import copy
import os
import tempfile
import threading
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]
import tomli_w
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Optional

from hid_proxy.config.schema import AppConfig
from hid_proxy.core.dispatcher import emit_config_changed
from hid_proxy.utils.crypto import Crypto, is_encrypted_blob
from hid_proxy.utils.logging import get_logger

log = get_logger(__name__)

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
                config_dir = Path(user_config_dir("HIDProxyController", appauthor=False))
            except ImportError:
                config_dir = Path.home() / "AppData" / "Local" / "HIDProxyController"
        self.config_dir = config_dir
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = config_dir / "config.toml"

        self._lock = threading.RLock()
        self._batch_depth = 0
        self._pending_events: list[tuple[str, Any, Any]] = []
        self._config: Dict[str, Any] = self._load_defaults()
        self._crypto: Optional[Crypto] = None
        self._encryption_password = encryption_password
        self._password_source = "init" if encryption_password else None
        self.load()

    def _load_defaults(self) -> Dict[str, Any]:
        return AppConfig().to_dict()

    def get_encryption_password(self) -> Optional[str]:
        """Resolve encryption password from init, env, or OS keyring."""
        if self._encryption_password:
            return self._encryption_password

        env_pass = os.environ.get("HIDPROXY_ENCRYPTION_PASSWORD")
        if env_pass:
            self._encryption_password = env_pass
            self._password_source = "env"
            return env_pass

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
        """Prompt user for password if QApplication is active."""
        try:
            from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox
            app = QApplication.instance()
            if app is None:
                return None
            password, ok = QInputDialog.getText(
                None,
                "Encryption Password",
                "Enter encryption password to unlock config:",
                QInputDialog.EchoMode.Password,
            )
            if ok and password:
                self._encryption_password = password
                self._password_source = "prompt"
                return password
            if not ok:
                reply = QMessageBox.question(
                    None,
                    "Encryption Required",
                    "Config is encrypted but no password was provided.\n"
                    "Disable encryption and continue with defaults?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply == QMessageBox.StandardButton.Yes:
                    self._config = self._load_defaults()
                    self._config["security"]["encrypt_config"] = False
                    self.save()
        except Exception as e:
            log.error(f"Password prompt failed: {e}")
        return None

    def _get_crypto(self, prompt_if_missing: bool = False) -> Optional[Crypto]:
        """Return Crypto instance when encryption is active."""
        if self._crypto is not None:
            return self._crypto

        password = self.get_encryption_password()
        if not password and prompt_if_missing:
            password = self._prompt_for_password()
        if not password:
            return None

        try:
            self._crypto = Crypto(password.encode("utf-8"))
            return self._crypto
        except Exception as e:
            log.error(f"Failed to initialize crypto: {e}")
            return None

    def load(self) -> bool:
        with self._lock:
            if not self.config_file.exists():
                self.save()
                return True
            try:
                raw_bytes = self.config_file.read_bytes()
                if is_encrypted_blob(raw_bytes):
                    password = self.get_encryption_password() or self._prompt_for_password()
                    if not password:
                        log.warning("Encrypted config found without password; using defaults in memory")
                        self._config = self._load_defaults()
                        return False
                    decrypted = Crypto.decrypt_with_password(raw_bytes, password.encode("utf-8"))
                    loaded = tomllib.loads(decrypted.decode("utf-8"))
                    self._crypto = Crypto(password.encode("utf-8"))
                    loaded.setdefault("security", {})["encrypt_config"] = True
                else:
                    loaded = tomllib.loads(raw_bytes.decode("utf-8"))

                validated = self._validate_config(loaded)
                self._config = self._load_defaults()
                self._deep_update(self._config, validated)
                return True
            except Exception as e:
                log.error(f"Config load failed: {e}")
                self._config = self._load_defaults()
                return False

    def _validate_config(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate config against AppConfig schema, falling back per-field on errors."""
        try:
            app_config = AppConfig.from_dict(data)
            app_config.validate_all()
            return app_config.to_dict()
        except Exception as e:
            log.warning(f"Config validation fallback: {e}")
            defaults = AppConfig().to_dict()
            self._deep_update(defaults, data)
            try:
                app_config = AppConfig.from_dict(defaults)
                app_config.validate_all()
                return app_config.to_dict()
            except Exception:
                return AppConfig().to_dict()

    def _atomic_write(self, target: Path, payload: bytes) -> None:
        """Write bytes atomically via temp file + os.replace."""
        fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=".tmp_cfg_")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(payload)
            os.replace(tmp_name, target)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def save(self) -> bool:
        with self._lock:
            try:
                validated = self._validate_config(self._config)
                self._config = validated
                encrypt_enabled = bool(validated.get("security", {}).get("encrypt_config", False))

                if encrypt_enabled:
                    crypto = self._get_crypto(prompt_if_missing=False)
                    if crypto:
                        toml_bytes = tomli_w.dumps(validated).encode("utf-8")
                        encrypted = crypto.encrypt(toml_bytes)
                        self._atomic_write(self.config_file, encrypted)
                        log.debug("Config saved (encrypted)")
                        return True
                    log.warning("encrypt_config=True but no password set; saving plain")
                    validated["security"]["encrypt_config"] = False

                toml_bytes = tomli_w.dumps(validated).encode("utf-8")
                self._atomic_write(self.config_file, toml_bytes)
                log.debug("Config saved (plain)")
                return True
            except Exception as e:
                log.error(f"Config save failed: {e}")
                return False

    def _deep_update(self, base: Dict[str, Any], update: Dict[str, Any]) -> None:
        for k, v in update.items():
            if isinstance(v, dict) and k in base and isinstance(base[k], dict):
                self._deep_update(base[k], v)
            else:
                base[k] = v

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            keys = key.split(".")
            val: Any = self._config
            for k in keys:
                if isinstance(val, dict) and k in val:
                    val = val[k]
                else:
                    return default
            return copy.deepcopy(val)

    def set(self, key: str, value: Any) -> None:
        events_to_emit: list[tuple[str, Any, Any]] = []
        with self._lock:
            old_value = self.get(key)
            keys = key.split(".")
            cfg = self._config
            for k in keys[:-1]:
                cfg = cfg.setdefault(k, {})
            cfg[keys[-1]] = value
            if key.startswith("security."):
                self._crypto = None

            if self._batch_depth > 0:
                self._pending_events.append((key, old_value, value))
            else:
                self.save()
                if old_value != value:
                    events_to_emit.append((key, old_value, value))

        for k, old_v, new_v in events_to_emit:
            emit_config_changed(k, old_v, new_v)

    @contextmanager
    def batch(self):
        """Group multiple set() calls into a single disk save and event flush."""
        with self._lock:
            self._batch_depth += 1
        try:
            yield self
        finally:
            events_to_emit: list[tuple[str, Any, Any]] = []
            with self._lock:
                self._batch_depth -= 1
                if self._batch_depth == 0:
                    self.save()
                    events_to_emit = list(self._pending_events)
                    self._pending_events.clear()
            for k, old_v, new_v in events_to_emit:
                if old_v != new_v:
                    emit_config_changed(k, old_v, new_v)

    def update_many(self, updates: Dict[str, Any]) -> bool:
        """Apply multiple dotted keys with one validation and one disk write."""
        if not updates:
            return True
        with self.batch():
            for key, value in updates.items():
                self.set(key, value)
        return True

    def get_all(self) -> Dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._config)

    def set_encryption_password(self, password: str, save_to_keyring: bool = True) -> bool:
        if not password:
            return False
        with self._lock:
            try:
                self._config.setdefault("security", {})["encrypt_config"] = True
                if save_to_keyring and KEYRING_AVAILABLE:
                    try:
                        keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, password)
                    except Exception as e:
                        log.warning(f"Failed to store password in keyring: {e}")

                self._encryption_password = password
                self._password_source = "set_encryption_password"
                self._crypto = Crypto(password.encode("utf-8"))
                ok = self.save()
            except Exception as e:
                log.error(f"Failed to set encryption password: {e}")
                return False
        if ok:
            emit_config_changed("security.encrypt_config", False, True)
        return ok

    def remove_encryption(self) -> bool:
        with self._lock:
            try:
                self._config.setdefault("security", {})["encrypt_config"] = False
                if KEYRING_AVAILABLE:
                    try:
                        keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
                    except Exception:
                        pass
                self._encryption_password = None
                self._password_source = None
                self._crypto = None
                ok = self.save()
            except Exception as e:
                log.error(f"Failed to remove encryption: {e}")
                return False
        if ok:
            emit_config_changed("security.encrypt_config", True, False)
        return ok
