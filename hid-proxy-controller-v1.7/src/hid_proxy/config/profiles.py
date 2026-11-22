"""Profile management for different configurations with path-traversal protection."""
import copy
import json
import re
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional

from hid_proxy.config.manager import ConfigManager
from hid_proxy.core.dispatcher import emit_config_changed
from hid_proxy.utils.logging import get_logger

log = get_logger(__name__)

PROFILE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9 _\-]{1,64}$")


def sanitize_profile_name(name: str) -> str:
    """Validate profile name against strict allowlist to block path traversal."""
    if not isinstance(name, str):
        raise ValueError("Profile name must be a string")
    cleaned = name.strip()
    if not cleaned or not PROFILE_NAME_PATTERN.match(cleaned):
        raise ValueError(
            "Profile name must be 1-64 chars: letters, numbers, space, dash, underscore only"
        )
    return cleaned


def filter_config_for_profile(config: Dict) -> Dict:
    """Strip sensitive security keys before saving or exporting a profile."""
    filtered = copy.deepcopy(config)
    if "security" in filtered and isinstance(filtered["security"], dict):
        filtered["security"].pop("encryption_password", None)
        filtered["security"].pop("encrypt_config", None)
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
                expected_name = file.stem
                if data.get("name") != expected_name:
                    log.warning(f"Profile name mismatch in {file}: expected {expected_name}")
                    continue
                profile = Profile(
                    name=data["name"],
                    config=data.get("config", {}),
                    created_at=float(data.get("created_at", 0.0)),
                    description=str(data.get("description", "")),
                )
                self._profiles[profile.name] = profile
            except Exception as e:
                log.error(f"Failed to load profile {file}: {e}")

    def _get_safe_profile_path(self, name: str) -> Path:
        safe_name = sanitize_profile_name(name)
        base_resolved = self.profiles_dir.resolve()
        path = (self.profiles_dir / f"{safe_name}.json").resolve()
        try:
            path.relative_to(base_resolved)
        except ValueError as exc:
            raise ValueError(f"Invalid profile path for: {name}") from exc
        return path

    def save_profile(self, name: str, description: str = "") -> bool:
        try:
            safe_name = sanitize_profile_name(name)
            profile_config = filter_config_for_profile(self.config_manager.get_all())
            profile = Profile(
                name=safe_name,
                config=profile_config,
                created_at=time.time(),
                description=description,
            )
            file = self._get_safe_profile_path(safe_name)
            with open(file, "w", encoding="utf-8") as f:
                json.dump(asdict(profile), f, indent=2)
            self._profiles[safe_name] = profile
            log.info(f"Saved profile: {safe_name}")
            return True
        except Exception as e:
            log.error(f"Save profile failed: {e}")
            return False

    def load_profile(self, name: str) -> bool:
        try:
            safe_name = sanitize_profile_name(name)
        except ValueError as e:
            log.error(str(e))
            return False

        profile = self._profiles.get(safe_name)
        if not profile:
            log.error(f"Profile not found: {safe_name}")
            return False

        try:
            merged = copy.deepcopy(self.config_manager.get_all())
            self._deep_merge(merged, filter_config_for_profile(profile.config))
            validated = self.config_manager._validate_config(merged)
            with self.config_manager._lock:
                self.config_manager._config = validated
                self.config_manager.save()
            emit_config_changed("profile.loaded", None, safe_name)
            log.info(f"Loaded profile: {safe_name}")
            return True
        except Exception as e:
            log.error(f"Load profile failed: {e}")
            return False

    def _deep_merge(self, base: Dict, update: Dict) -> None:
        for k, v in update.items():
            if isinstance(v, dict) and k in base and isinstance(base[k], dict):
                self._deep_merge(base[k], v)
            else:
                base[k] = v

    def delete_profile(self, name: str) -> bool:
        try:
            safe_name = sanitize_profile_name(name)
        except ValueError:
            return False
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
        return [
            {"name": p.name, "description": p.description, "created_at": p.created_at}
            for p in self._profiles.values()
        ]

    def get_profile(self, name: str) -> Optional[Profile]:
        try:
            safe_name = sanitize_profile_name(name)
            return self._profiles.get(safe_name)
        except ValueError:
            return None

    def export_profile(self, name: str, export_path: Path) -> bool:
        try:
            safe_name = sanitize_profile_name(name)
        except ValueError:
            return False
        profile = self._profiles.get(safe_name)
        if not profile:
            return False
        try:
            export_data = asdict(profile)
            export_data["config"] = filter_config_for_profile(profile.config)
            with open(export_path, "w", encoding="utf-8") as f:
                json.dump(export_data, f, indent=2)
            return True
        except Exception as e:
            log.error(f"Export profile failed: {e}")
            return False

    def import_profile(self, import_path: Path) -> bool:
        try:
            with open(import_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or "name" not in data or "config" not in data:
                raise ValueError("Invalid profile file: missing name or config")
            safe_name = sanitize_profile_name(data["name"])
            filtered_config = filter_config_for_profile(data["config"])
            # Validate config structure before accepting
            self.config_manager._validate_config(filtered_config)

            profile = Profile(
                name=safe_name,
                config=filtered_config,
                created_at=float(data.get("created_at", time.time())),
                description=str(data.get("description", "")),
            )
            file = self._get_safe_profile_path(safe_name)
            with open(file, "w", encoding="utf-8") as f:
                json.dump(asdict(profile), f, indent=2)
            self._profiles[safe_name] = profile
            log.info(f"Imported profile: {safe_name}")
            return True
        except Exception as e:
            log.error(f"Import profile failed: {e}")
            return False
