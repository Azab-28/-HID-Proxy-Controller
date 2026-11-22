"""Configuration schema validation with type checking."""
from dataclasses import dataclass, field, fields
from typing import Optional, Dict, Any, get_origin, get_args
import re


def _validate_type(value: Any, expected_type: Any, path: str = "") -> Any:
    """Validate and coerce value to expected type."""
    origin = get_origin(expected_type)
    args = get_args(expected_type)

    # Handle Optional[T]
    if origin is Union or (origin is type and args and type(None) in args):
        if value is None:
            return None
        # Get the non-None type
        non_none_args = [a for a in args if a is not type(None)]
        if non_none_args:
            return _validate_type(value, non_none_args[0], path)
        return value

    # Handle Dict[str, Any]
    if origin is dict:
        if not isinstance(value, dict):
            raise TypeError(f"{path}: expected dict, got {type(value).__name__}")
        return value

    # Handle List
    if origin is list:
        if not isinstance(value, list):
            raise TypeError(f"{path}: expected list, got {type(value).__name__}")
        return value

    # Basic types
    if expected_type is int:
        if isinstance(value, bool):  # bool is subclass of int
            raise TypeError(f"{path}: expected int, got bool")
        if isinstance(value, (str, float)):
            try:
                return int(value)
            except ValueError:
                raise TypeError(f"{path}: cannot convert {value!r} to int")
        if not isinstance(value, int):
            raise TypeError(f"{path}: expected int, got {type(value).__name__}")
        return value

    if expected_type is float:
        if isinstance(value, bool):
            raise TypeError(f"{path}: expected float, got bool")
        if isinstance(value, (int, str)):
            return float(value)
        if not isinstance(value, float):
            raise TypeError(f"{path}: expected float, got {type(value).__name__}")
        return value

    if expected_type is bool:
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes", "on")
        if isinstance(value, (int, float)):
            return bool(value)
        if not isinstance(value, bool):
            raise TypeError(f"{path}: expected bool, got {type(value).__name__}")
        return value

    if expected_type is str:
        if not isinstance(value, str):
            return str(value)
        return value

    # Default: return as-is
    return value


@dataclass
class DeviceConfig:
    baudrate: int = 2000000
    auto_connect: bool = True
    preferred_port: str = ""

    def validate(self) -> None:
        if not isinstance(self.baudrate, int) or self.baudrate <= 0:
            raise ValueError("baudrate must be positive integer")
        if self.baudrate not in (115200, 921600, 2000000):
            raise ValueError("baudrate must be 115200, 921600, or 2000000")


@dataclass
class TargetingConfig:
    sensitivity: float = 1.0
    smoothing: float = 0.35
    deadzone: int = 4
    jitter: float = 1.5
    curve: str = "bezier"
    priority: str = "closest"
    fov: int = 300

    def validate(self) -> None:
        if not 0.1 <= self.sensitivity <= 5.0:
            raise ValueError("sensitivity must be 0.1-5.0")
        if not 0.0 <= self.smoothing <= 1.0:
            raise ValueError("smoothing must be 0.0-1.0")
        if not 0 <= self.deadzone <= 50:
            raise ValueError("deadzone must be 0-50")
        if not 0.0 <= self.jitter <= 10.0:
            raise ValueError("jitter must be 0.0-10.0")
        if self.curve not in ("bezier", "linear", "catmull"):
            raise ValueError("curve must be bezier/linear/catmull")
        if self.priority not in ("closest", "head"):
            raise ValueError("priority must be closest/head")
        if not 50 <= self.fov <= 1000:
            raise ValueError("fov must be 50-1000")


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

    def validate(self) -> None:
        if self.theme not in ("dark", "light", "system"):
            raise ValueError("theme must be dark/light/system")


@dataclass
class SecurityConfig:
    encrypt_config: bool = True
    require_admin: bool = False
    encryption_password: str = ""  # Empty = disabled

    def validate(self) -> None:
        if self.encrypt_config and not self.encryption_password:
            raise ValueError("encryption_password required when encrypt_config=true")


@dataclass
class AdvancedConfig:
    log_level: str = "INFO"
    buffer_size: int = 4096

    def validate(self) -> None:
        if self.log_level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
            raise ValueError("log_level must be DEBUG/INFO/WARNING/ERROR")
        if not isinstance(self.buffer_size, int) or self.buffer_size < 256:
            raise ValueError("buffer_size must be >= 256")


@dataclass
class AppConfig:
    device: DeviceConfig = field(default_factory=DeviceConfig)
    targeting: TargetingConfig = field(default_factory=TargetingConfig)
    modules: ModuleConfig = field(default_factory=ModuleConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    advanced: AdvancedConfig = field(default_factory=AdvancedConfig)

    def validate_all(self) -> None:
        """Validate all sub-configs."""
        for f in fields(self):
            sub = getattr(self, f.name)
            if hasattr(sub, "validate"):
                sub.validate()

    def to_dict(self) -> Dict[str, Any]:
        import dataclasses
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        """Create from dict with type validation."""
        # Validate and coerce each section
        validated = {}
        for f in fields(cls):
            section_name = f.name
            section_type = f.type
            section_data = data.get(section_name, {})
            
            if hasattr(section_type, "__dataclass_fields__"):
                # It's a dataclass - validate each field
                coerced = {}
                for sf in fields(section_type):
                    key = sf.name
                    expected_type = sf.type
                    raw_value = section_data.get(key)
                    
                    # Get default if not provided
                    if raw_value is None:
                        if hasattr(section_type, key):
                            default = getattr(section_type, key)
                            if not callable(default):
                                raw_value = default
                    
                    if raw_value is not None:
                        coerced[key] = _validate_type(raw_value, expected_type, f"{section_name}.{key}")
                    elif sf.default is not field.default:
                        # Has default value
                        pass
                    elif sf.default_factory is not field.default_factory:
                        # Has default factory
                        pass
                    else:
                        # Required field missing
                        raise ValueError(f"Missing required config: {section_name}.{key}")
                
                validated[section_name] = section_type(**coerced)
            else:
                validated[section_name] = section_data

        return cls(**validated)