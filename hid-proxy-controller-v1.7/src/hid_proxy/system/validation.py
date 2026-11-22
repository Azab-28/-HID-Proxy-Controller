"""Startup validation for dependencies and configuration (non-blocking for hot-plug devices)."""
import importlib.util
import sys
from typing import List, Tuple


class StartupValidator:
    def __init__(self, config_manager, device_manager):
        self.config = config_manager
        self.device_manager = device_manager

    def validate_all(self) -> Tuple[bool, List[str], List[str]]:
        """Return (is_healthy, fatal_errors, warnings)."""
        errors: List[str] = []
        warnings: List[str] = []

        required = ["PySide6", "serial", "psutil", "cryptography"]
        if sys.platform == "win32":
            required.append("win32api")

        for pkg in required:
            if importlib.util.find_spec(pkg) is None:
                errors.append(f"Missing required package: {pkg}")

        if self.config.get("device.baudrate") not in (115200, 921600, 2000000):
            errors.append("Invalid baudrate configuration")

        ports = self.device_manager.scan_ports()
        if not ports:
            warnings.append("No compatible ESP32 device detected yet (waiting for USB connection)")

        return len(errors) == 0, errors, warnings
