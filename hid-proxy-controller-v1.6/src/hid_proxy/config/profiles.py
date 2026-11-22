"""Profile management for different configurations.

Security:
- Profile names are sanitized to prevent path traversal
- Security settings (encryption, password) are NEVER saved in profiles
- Config is validated through schema when loading
"""
import json
import re
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
import logging

from hid_proxy.config.manager import ConfigManager
from hid_proxy.config.schema import AppConfig

log = logging.getLogger(__name__)


# Profile name validation: alphanumeric, dash, underscore, space only
PROFILE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9 _\-]{1,64}$")
# Keys that should NEVER be saved in profiles
EXCLUDED_CONFIG_KEYS = {
    "security.encryption_password",
    "security.encrypt_config",  # Let user choose per-session
}


def sanitize_profile_name(name: str) -> str:
    """Sanitize profile name to prevent path traversal.
    
    Returns sanitized name or raises ValueError if invalid.
    """
    name = name.strip()
    if not name:
        raise ValueError("Profile name cannot be empty")
    if not PROFILE_NAME_PATTERN.match(name):
        raise ValueError(
            "Profile name must be 1-64 chars: letters, numbers, space, dash, underscore only"
        )
    return name


def filter_config_for_profile(config: Dict) -> Dict:
    """Remove sensitive keys from config before saving as profile."""
    filtered = {}
    for key, value in config.items():
        if key == "security":
            # Save only non-sensitive security settings
            filtered["security"] = {
                k: v for k, v in value.items()
                if k not in ("encryption_password", "encrypt_config")
            }
        else:
            filtered[key] = value
    return filtered


@dataclass
class Profile:
    name: str
    config: Dict
    created_at: float
    description: str = ""


class ProfileManager:
    """Manages saved configuration profiles."""
    
    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
        self.profiles_dir = config_manager.config_dir / "profiles"
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        self._profiles: Dict[str, Profile] = {}
        self._load_all()

    def _load_all(self) -> None:
        for file in self.profiles_dir.glob("*.json"):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Validate profile name matches filename (security)
                expected_name = file.stem
                if data.get("name") != expected_name:
                    log.warning(f"Profile name mismatch in {file}: expected {expected_name}, got {data.get('name')}")
                    continue
                profile = Profile(**data)
                self._profiles[profile.name] = profile
            except Exception as e:
                log.error(f"Failed to load profile {file}: {e}")

    def _get_safe_profile_path(self, name: str) -> Path:
        """Get safe path for profile, validating it stays within profiles_dir."""
        safe_name = sanitize_profile_name(name)
        path = (self.profiles_dir / f"{safe_name}.json").resolve()
        # Ensure path is within profiles_dir (prevent path traversal)
        try:
            path.relative_to(self.profiles_dir.resolve())
        except ValueError:
            raise ValueError(f"Invalid profile name: {name}")
        return path

    def save_profile(self, name: str, description: str = "") -> bool:
        """Save current config as a profile (excluding security settings)."""
        try:
            safe_name = sanitize_profile_name(name)
            # Filter out sensitive config
            profile_config = filter_config_for_profile(self.config_manager.get_all())
            
            profile = Profile(
                name=safe_name,
                config=profile_config,
                created_at=__import__("time").time(),
                description=description
            )
            file = self._get_safe_profile_path(safe_name)
            with open(file, "w", encoding="utf-8") as f:
                json.dump(asdict(profile), f, indent=2)
            self._profiles[safe_name] = profile
            log.info(f"Saved profile: {safe_name}")
            return True
        except ValueError as e:
            log.error(f"Invalid profile name: {e}")
            return False
        except Exception as e:
            log.error(f"Save profile failed: {e}")
            return False

    def load_profile(self, name: str) -> bool:
        """Load a profile into current config with validation."""
        safe_name = sanitize_profile_name(name)
        profile = self._profiles.get(safe_name)
        if not profile:
            log.error(f"Profile not found: {safe_name}")
            return False
        try:
            # Merge profile config with current config (profile values override)
            merged = copy.deepcopy(self.config_manager.get_all())
            self._deep_merge(merged, profile.config)
            
            # Validate merged config through schema
            validated = self.config_manager._validate_config(merged)
            self.config_manager._config = validated
            self.config_manager._crypto = None  # Reset crypto cache
            self.config_manager.save()
            log.info(f"Loaded profile: {safe_name}")
            return True
        except Exception as e:
            log.error(f"Load profile failed: {e}")
            return False

    def _deep_merge(self, base: dict, update: dict) -> None:
        """Recursively merge update into base."""
        for k, v in update.items():
            if isinstance(v, dict) and k in base and isinstance(base[k], dict):
                self._deep_merge(base[k], v)
            else:
                base[k] = v

    def delete_profile(self, name: str) -> bool:
        safe_name = sanitize_profile_name(name)
        if safe_name in self._profiles:
            file = self._get_safe_profile_path(safe_name)
            try:
                file.unlink(missing_ok=True)
                del self._profiles[safe_name]
                log.info(f"Deleted profile: {safe_name}")
                return True
            except Exception as e:
                log.error(f"Delete profile failed: {e}")
        return False

    def list_profiles(self) -> List[Dict]:
        return [{"name": p.name, "description": p.description, "created_at": p.created_at}
                for p in self._profiles.values()]

    def get_profile(self, name: str) -> Optional[Profile]:
        safe_name = sanitize_profile_name(name)
        return self._profiles.get(safe_name)

    def export_profile(self, name: str, export_path: Path) -> bool:
        """Export profile to a file (excluding security settings)."""
        safe_name = sanitize_profile_name(name)
        profile = self._profiles.get(safe_name)
        if not profile:
            return False
        try:
            # Export filtered config
            export_data = asdict(profile)
            export_data["config"] = filter_config_for_profile(profile.config)
            with open(export_path, "w", encoding="utf-8") as f:
                json.dump(export_data, f, indent=2)
            return True
        except Exception as e:
            log.error(f"Export profile failed: {e}")
            return False

    def import_profile(self, import_path: Path) -> bool:
        """Import profile from a file with validation."""
        try:
            with open(import_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # Validate required fields
            if "name" not in data or "config" not in data:
                raise ValueError("Invalid profile file: missing name or config")
            
            safe_name = sanitize_profile_name(data["name"])
            # Filter config
            filtered_config = filter_config_for_profile(data["config"])
            
            profile = Profile(
                name=safe_name,
                config=filtered_config,
                created_at=data.get("created_at", __import__("time").time()),
                description=data.get("description", "")
            )
            
            file = self._get_safe_profile_path(safe_name)
            with open(file, "w", encoding="utf-8") as f:
                json.dump(asdict(profile), f, indent=2)
            self._profiles[safe_name] = profile
            log.info(f"Imported profile: {safe_name}")
            return True
        except ValueError as e:
            log.error(f"Invalid profile name in import: {e}")
            return False
        except Exception as e:
            log.error(f"Import profile failed: {e}")
            return False