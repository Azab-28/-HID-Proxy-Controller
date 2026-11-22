"""Configuration management with TOML persistence."""
import tomli
import tomli_w
from pathlib import Path
from typing import Any, Optional
import logging

log = logging.getLogger(__name__)

class ConfigManager:
    def __init__(self, config_dir: Optional[Path] = None):
        if config_dir is None:
            config_dir = Path.home() / "AppData" / "Local" / "HIDProxyController"
        self.config_dir = config_dir
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = config_dir / "config.toml"
        self._config = self._load_defaults()
        self.load()
    
    def _load_defaults(self) -> dict:
        return {
            "device": {"baudrate": 2000000, "auto_connect": True, "preferred_port": ""},
            "targeting": {"sensitivity": 1.0, "smoothing": 0.35, "deadzone": 4, 
                         "jitter": 1.5, "curve": "bezier", "priority": "closest", "fov": 300},
            "modules": {"mouse": {"enabled": True}, "keyboard": {"enabled": True}},
            "ui": {"theme": "dark", "minimize_to_tray": True, "show_notifications": True},
            "security": {"encrypt_config": True, "require_admin": False},
            "advanced": {"log_level": "INFO", "buffer_size": 4096},
        }
    
    def load(self) -> bool:
        if not self.config_file.exists():
            self.save()
            return True
        try:
            with open(self.config_file, "rb") as f:
                loaded = tomli.load(f)
            self._deep_update(self._config, loaded)
            return True
        except Exception as e:
            log.error(f"Config load failed: {e}")
            return False
    
    def save(self) -> bool:
        try:
            with open(self.config_file, "wb") as f:
                tomli_w.dump(self._config, f)
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
