"""Connection monitor with auto-reconnection."""
import threading
import time
import logging
from typing import Callable, List
from PySide6.QtCore import QObject, Signal

from hid_proxy.core.device import DeviceManager
from hid_proxy.config.manager import ConfigManager

log = logging.getLogger(__name__)

class ConnectionMonitor(QObject):
    device_connected = Signal(str)
    device_disconnected = Signal(str)
    device_error = Signal(str, str)
    
    def __init__(self, device_manager: DeviceManager, config: ConfigManager):
        super().__init__()
        self.device_manager = device_manager
        self.config = config
        self._running = False
        self._thread = None
        self._known_ports = set()
        
        device_manager.register_callback("connected", self._on_connected)
        device_manager.register_callback("disconnected", self._on_disconnected)
        device_manager.register_callback("error", self._on_error)
    
    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="HID-Monitor")
        self._thread.start()
        log.info("Connection monitor started")
    
    def stop(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        log.info("Connection monitor stopped")
    
    def _monitor_loop(self):
        while self._running:
            try:
                current_ports = set(p["port"] for p in self.device_manager.scan_ports())
                new_ports = current_ports - self._known_ports
                lost_ports = self._known_ports - current_ports
                
                for port in new_ports:
                    if self.config.get("device.auto_connect"):
                        self.device_manager.connect(port, self.config.get("device.baudrate"))
                
                for port in lost_ports:
                    if self.device_manager.is_connected(port):
                        log.warning(f"Device {port} lost, attempting reconnect...")
                        self.device_manager.disconnect(port)
                        time.sleep(1)
                        self.device_manager.connect(port, self.config.get("device.baudrate"))
                
                self._known_ports = current_ports
            except Exception as e:
                log.error(f"Monitor loop error: {e}")
            time.sleep(2.0)
    
    def _on_connected(self, port: str):
        self._known_ports.add(port)
        self.device_connected.emit(port)
    
    def _on_disconnected(self, port: str):
        self._known_ports.discard(port)
        self.device_disconnected.emit(port)
    
    def _on_error(self, port: str, error: str):
        self.device_error.emit(port, error)
