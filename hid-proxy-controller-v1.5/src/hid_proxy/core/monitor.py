"""Connection monitor with auto-reconnection and exponential backoff."""
import threading
import time
import logging
from typing import Callable, List, Dict
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
        # Per-port reconnection state
        self._reconnect_attempts: Dict[str, int] = {}
        self._max_reconnect_attempts = 10
        self._base_reconnect_delay = 1.0  # seconds
        self._max_reconnect_delay = 60.0  # seconds

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
            self._thread.join(timeout=5.0)
        log.info("Connection monitor stopped")

    def _calculate_backoff(self, attempts: int) -> float:
        """Exponential backoff with jitter."""
        delay = min(self._base_reconnect_delay * (2 ** attempts), self._max_reconnect_delay)
        # Add jitter (±25%)
        import random
        jitter = delay * 0.25 * (2 * random.random() - 1)
        return delay + jitter

    def _monitor_loop(self):
        while self._running:
            try:
                current_ports = set(p["port"] for p in self.device_manager.scan_ports())
                new_ports = current_ports - self._known_ports
                lost_ports = self._known_ports - current_ports

                # New ports - auto connect if enabled
                for port in new_ports:
                    if self.config.get("device.auto_connect"):
                        self.device_manager.connect(port, self.config.get("device.baudrate"))
                    # Reset reconnect counter on new connection
                    self._reconnect_attempts.pop(port, None)

                # Lost ports - schedule reconnect with backoff
                for port in lost_ports:
                    if self.device_manager.is_connected(port):
                        log.warning(f"Device {port} lost, scheduling reconnect...")
                        self.device_manager.disconnect(port)
                        self._schedule_reconnect(port)

                self._known_ports = current_ports

            except Exception as e:
                log.error(f"Monitor loop error: {e}")

            time.sleep(2.0)

    def _schedule_reconnect(self, port: str):
        """Schedule a reconnection attempt with exponential backoff."""
        attempts = self._reconnect_attempts.get(port, 0)
        if attempts >= self._max_reconnect_attempts:
            log.error(f"Max reconnect attempts reached for {port}, giving up")
            self.device_error.emit(port, "Max reconnect attempts reached")
            return

        delay = self._calculate_backoff(attempts)
        log.info(f"Reconnecting to {port} in {delay:.1f}s (attempt {attempts + 1}/{self._max_reconnect_attempts})")

        def attempt_reconnect():
            time.sleep(delay)
            if not self._running:
                return
            if self.config.get("device.auto_connect"):
                success = self.device_manager.connect(port, self.config.get("device.baudrate"))
                if success:
                    self._reconnect_attempts.pop(port, None)
                    log.info(f"Reconnected to {port} successfully")
                else:
                    self._reconnect_attempts[port] = attempts + 1
                    self._schedule_reconnect(port)

        threading.Thread(target=attempt_reconnect, daemon=True, name=f"HID-Reconnect-{port}").start()
        self._reconnect_attempts[port] = attempts + 1

    def _on_connected(self, port: str):
        self._known_ports.add(port)
        self._reconnect_attempts.pop(port, None)  # Reset on successful connection
        self.device_connected.emit(port)

    def _on_disconnected(self, port: str):
        self._known_ports.discard(port)
        self.device_disconnected.emit(port)

    def _on_error(self, port: str, error: str):
        self.device_error.emit(port, error)