"""Profile management for different configurations."""
import json
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
import logging

from hid_proxy.config.manager import ConfigManager

log = logging.getLogger(__name__)


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
                profile = Profile(**data)
                self._profiles[profile.name] = profile
            except Exception as e:
                log.error(f"Failed to load profile {file}: {e}")

    def save_profile(self, name: str, description: str = "") -> bool:
        """Save current config as a profile."""
        try:
            profile = Profile(
                name=name,
                config=self.config_manager.get_all(),
                created_at=__import__("time").time(),
                description=description
            )
            file = self.profiles_dir / f"{name}.json"
            with open(file, "w", encoding="utf-8") as f:
                json.dump(asdict(profile), f, indent=2)
            self._profiles[name] = profile
            log.info(f"Saved profile: {name}")
            return True
        except Exception as e:
            log.error(f"Save profile failed: {e}")
            return False

    def load_profile(self, name: str) -> bool:
        """Load a profile into current config."""
        profile = self._profiles.get(name)
        if not profile:
            log.error(f"Profile not found: {name}")
            return False
        try:
            for key, value in profile.config.items():
                self.config_manager._config[key] = value
            self.config_manager.save()
            log.info(f"Loaded profile: {name}")
            return True
        except Exception as e:
            log.error(f"Load profile failed: {e}")
            return False

    def delete_profile(self, name: str) -> bool:
        if name in self._profiles:
            file = self.profiles_dir / f"{name}.json"
            try:
                file.unlink(missing_ok=True)
                del self._profiles[name]
                log.info(f"Deleted profile: {name}")
                return True
            except Exception as e:
                log.error(f"Delete profile failed: {e}")
        return False

    def list_profiles(self) -> List[Dict]:
        return [{"name": p.name, "description": p.description, "created_at": p.created_at}
                for p in self._profiles.values()]

    def get_profile(self, name: str) -> Optional[Profile]:
        return self._profiles.get(name)

    def export_profile(self, name: str, export_path: Path) -> bool:
        """Export profile to a file."""
        profile = self._profiles.get(name)
        if not profile:
            return False
        try:
            with open(export_path, "w", encoding="utf-8") as f:
                json.dump(asdict(profile), f, indent=2)
            return True
        except Exception as e:
            log.error(f"Export profile failed: {e}")
            return False

    def import_profile(self, import_path: Path) -> bool:
        """Import profile from a file."""
        try:
            with open(import_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            profile = Profile(**data)
            file = self.profiles_dir / f"{profile.name}.json"
            with open(file, "w", encoding="utf-8") as f:
                json.dump(asdict(profile), f, indent=2)
            self._profiles[profile.name] = profile
            log.info(f"Imported profile: {profile.name}")
            return True
        except Exception as e:
            log.error(f"Import profile failed: {e}")
            return False