"""Startup validation for dependencies and device."""
from typing import List, Tuple
import serial.tools.list_ports
import importlib.util

class StartupValidator:
    def __init__(self, config_manager, device_manager):
        self.config = config_manager
        self.device_manager = device_manager
    
    def validate_all(self) -> Tuple[bool, List[str]]:
        issues = []
        
        # Check Python packages
        required = ["PySide6", "serial", "pystray", "psutil", "win32api", "numpy", "cryptography"]
        for pkg in required:
            if importlib.util.find_spec(pkg) is None:
                issues.append(f"Missing package: {pkg}")
        
        # Check ESP32 device
        ports = self.device_manager.scan_ports()
        if not ports:
            issues.append("No compatible ESP32 device detected (check USB connection)")
        
        # Check config
        if not self.config.get("device.baudrate"):
            issues.append("Invalid baudrate configuration")
        
        return len(issues) == 0, issues
