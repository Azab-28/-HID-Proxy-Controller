"""Configuration schema validation."""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

@dataclass
class DeviceConfig:
    baudrate: int = 2000000
    auto_connect: bool = True
    preferred_port: str = ""

@dataclass
class TargetingConfig:
    sensitivity: float = 1.0
    smoothing: float = 0.35
    deadzone: int = 4
    jitter: float = 1.5
    curve: str = "bezier"
    priority: str = "closest"
    fov: int = 300

@dataclass
class ModuleConfig:
    mouse: Dict[str, Any] = field(default_factory=lambda: {"enabled": True})
    keyboard: Dict[str, Any] = field(default_factory=lambda: {"enabled": True})
    targeting: Dict[str, Any] = field(default_factory=dict)

@dataclass
class UIConfig:
    theme: str = "dark"
    minimize_to_tray: bool = True
    show_notifications: bool = True

@dataclass
class SecurityConfig:
    encrypt_config: bool = True
    require_admin: bool = False

@dataclass
class AdvancedConfig:
    log_level: str = "INFO"
    buffer_size: int = 4096

@dataclass
class AppConfig:
    device: DeviceConfig = field(default_factory=DeviceConfig)
    targeting: TargetingConfig = field(default_factory=TargetingConfig)
    modules: ModuleConfig = field(default_factory=ModuleConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    advanced: AdvancedConfig = field(default_factory=AdvancedConfig)
    
    def to_dict(self) -> Dict[str, Any]:
        import dataclasses
        return dataclasses.asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        return cls(
            device=DeviceConfig(**data.get("device", {})),
            targeting=TargetingConfig(**data.get("targeting", {})),
            modules=ModuleConfig(**data.get("modules", {})),
            ui=UIConfig(**data.get("ui", {})),
            security=SecurityConfig(**data.get("security", {})),
            advanced=AdvancedConfig(**data.get("advanced", {})),
        )
