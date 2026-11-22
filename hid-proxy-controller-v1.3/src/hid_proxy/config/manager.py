"""Configuration management with TOML persistence and schema validation."""
import tomli
import tomli_w
from pathlib import Path
from typing import Any, Optional
import logging

from hid_proxy.config.schema import AppConfig

log = logging.getLogger(__name__)


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
        self.load()

    def _load_defaults(self) -> dict:
        return AppConfig().to_dict()

    def load(self) -> bool:
        if not self.config_file.exists():
            self.save()
            return True
        try:
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
            return app_config.to_dict()
        except Exception as e:
            log.warning(f"Config validation failed, using defaults for invalid keys: {e}")
            # Return only valid keys by merging with defaults
            defaults = AppConfig().to_dict()
            self._deep_update(defaults, data)
            # Validate again
            try:
                return AppConfig.from_dict(defaults).to_dict()
            except Exception:
                return defaults

    def save(self) -> bool:
        try:
            # Validate before saving
            validated = self._validate_config(self._config)
            with open(self.config_file, "wb") as f:
                tomli_w.dump(validated, f)
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
        self.save()

    def get_all(self) -> dict:
        return self._config.copy()