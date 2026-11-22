"""Configuration schema validation with strict type checking."""
import dataclasses
from dataclasses import dataclass, field, fields
from typing import Optional, Dict, Any, List, get_origin, get_args, Union


def _validate_type(value: Any, expected_type: Any, path: str = "") -> Any:
    """Validate and coerce value to expected type."""
    origin = get_origin(expected_type)
    args = get_args(expected_type)

    if origin is Union:
        if value is None and type(None) in args:
            return None
        non_none_args = [a for a in args if a is not type(None)]
        if non_none_args:
            return _validate_type(value, non_none_args[0], path)
        return value

    if origin is dict:
        if not isinstance(value, dict):
            raise TypeError(f"{path}: expected dict, got {type(value).__name__}")
        return value

    if origin is list:
        if not isinstance(value, list):
            raise TypeError(f"{path}: expected list, got {type(value).__name__}")
        if args and args[0] is int:
            return [_validate_type(item, int, f"{path}[]") for item in value]
        return value

    if expected_type is int:
        if isinstance(value, bool):
            raise TypeError(f"{path}: expected int, got bool")
        if isinstance(value, (str, float)):
            try:
                return int(value)
            except ValueError as exc:
                raise TypeError(f"{path}: cannot convert {value!r} to int") from exc
        if not isinstance(value, int):
            raise TypeError(f"{path}: expected int, got {type(value).__name__}")
        return value

    if expected_type is float:
        if isinstance(value, bool):
            raise TypeError(f"{path}: expected float, got bool")
        if isinstance(value, (int, str)):
            try:
                return float(value)
            except ValueError as exc:
                raise TypeError(f"{path}: cannot convert {value!r} to float") from exc
        if not isinstance(value, float):
            raise TypeError(f"{path}: expected float, got {type(value).__name__}")
        return value

    if expected_type is bool:
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in ("true", "1", "yes", "on"):
                return True
            if lowered in ("false", "0", "no", "off"):
                return False
            raise TypeError(f"{path}: cannot convert {value!r} to bool")
        if isinstance(value, (int, float)):
            return bool(value)
        if not isinstance(value, bool):
            raise TypeError(f"{path}: expected bool, got {type(value).__name__}")
        return value

    if expected_type is str:
        if not isinstance(value, str):
            return str(value)
        return value

    return value


@dataclass
class DeviceConfig:
    baudrate: int = 2000000
    auto_connect: bool = True
    preferred_port: str = ""

    def validate(self) -> None:
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
    target_pids: List[int] = field(default_factory=list)

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
    composite: Dict[str, Any] = field(default_factory=lambda: {"enabled": True})
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
    """Security settings. Password is NEVER stored in config dict."""
    encrypt_config: bool = False
    require_admin: bool = False

    def validate(self) -> None:
        if not isinstance(self.encrypt_config, bool):
            raise ValueError("encrypt_config must be bool")
        if not isinstance(self.require_admin, bool):
            raise ValueError("require_admin must be bool")


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
        for f in fields(self):
            sub = getattr(self, f.name)
            if hasattr(sub, "validate"):
                sub.validate()

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        if not isinstance(data, dict):
            raise TypeError("Config root must be a dict")
        validated: Dict[str, Any] = {}
        for f in fields(cls):
            section_name = f.name
            section_type = f.type
            section_data = data.get(section_name, {})
            if section_data is None:
                section_data = {}
            if not isinstance(section_data, dict):
                raise TypeError(f"{section_name}: expected dict, got {type(section_data).__name__}")

            if dataclasses.is_dataclass(section_type):
                coerced: Dict[str, Any] = {}
                for sf in fields(section_type):
                    key = sf.name
                    if key in section_data and section_data[key] is not None:
                        coerced[key] = _validate_type(
                            section_data[key], sf.type, f"{section_name}.{key}"
                        )
                    elif sf.default is not dataclasses.MISSING:
                        coerced[key] = sf.default
                    elif sf.default_factory is not dataclasses.MISSING:
                        coerced[key] = sf.default_factory()
                    else:
                        raise ValueError(f"Missing required config: {section_name}.{key}")
                validated[section_name] = section_type(**coerced)
            else:
                validated[section_name] = section_data

        return cls(**validated)
