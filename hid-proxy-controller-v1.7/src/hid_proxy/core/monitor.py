"""Connection monitor with auto-reconnection and exponential backoff (thread-safe)."""
import logging
import random
import threading
import time
from typing import TYPE_CHECKING, Dict, Set

from PySide6.QtCore import QObject, Signal

if TYPE_CHECKING:
    from hid_proxy.config.manager import ConfigManager
from hid_proxy.core.device import DeviceManager

log = logging.getLogger(__name__)


class ConnectionMonitor(QObject):
    device_connected = Signal(str)
    device_disconnected = Signal(str)
    device_error = Signal(str, str)

    def __init__(self, device_manager: DeviceManager, config: "ConfigManager"):
        super().__init__()
        self.device_manager = device_manager
        self.config = config
        self._running = False
        self._thread: threading.Thread | None = None

        self._state_lock = threading.RLock()
        self._known_ports: Set[str] = set()
        self._reconnect_attempts: Dict[str, int] = {}
        self._reconnect_threads: Dict[str, threading.Thread] = {}
        self._reconnect_stop_events: Dict[str, threading.Event] = {}

        self._max_reconnect_attempts = 10
        self._base_reconnect_delay = 1.0
        self._max_reconnect_delay = 60.0

        device_manager.register_callback("connected", self._on_connected)
        device_manager.register_callback("disconnected", self._on_disconnected)
        device_manager.register_callback("error", self._on_error)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="HID-Monitor")
        self._thread.start()
        log.info("Connection monitor started")

    def stop(self) -> None:
        self._running = False
        with self._state_lock:
            stop_events = list(self._reconnect_stop_events.values())
            threads = list(self._reconnect_threads.values())
            self._reconnect_stop_events.clear()
            self._reconnect_threads.clear()

        for ev in stop_events:
            ev.set()
        current = threading.current_thread()
        for t in threads:
            if t.is_alive() and t is not current:
                t.join(timeout=1.0)

        if self._thread and self._thread.is_alive() and self._thread is not current:
            self._thread.join(timeout=3.0)
        log.info("Connection monitor stopped")

    def _calculate_backoff(self, attempts: int) -> float:
        delay = min(self._base_reconnect_delay * (2 ** attempts), self._max_reconnect_delay)
        jitter = delay * 0.25 * (2 * random.random() - 1)
        return max(0.1, delay + jitter)

    def _monitor_loop(self) -> None:
        while self._running:
            try:
                scanned = self.device_manager.scan_ports()
                current_ports = {p["port"] for p in scanned}

                with self._state_lock:
                    new_ports = current_ports - self._known_ports
                    lost_ports = self._known_ports - current_ports
                    self._known_ports = current_ports

                if self.config.get("device.auto_connect", True):
                    preferred = self.config.get("device.preferred_port", "")
                    for port in new_ports:
                        if preferred and preferred in current_ports and port != preferred:
                            continue
                        if not self.device_manager.is_connected(port):
                            self.device_manager.connect(port, self.config.get("device.baudrate", 2000000))
                        with self._state_lock:
                            self._reconnect_attempts.pop(port, None)

                for port in lost_ports:
                    if self.device_manager.is_connected(port):
                        log.warning(f"Device {port} lost, scheduling reconnect...")
                        self.device_manager.disconnect(port)
                        self._schedule_reconnect(port)

            except Exception as e:
                log.error(f"Monitor loop error: {e}")

            # Interruptible sleep
            for _ in range(20):
                if not self._running:
                    break
                time.sleep(0.1)

    def _schedule_reconnect(self, port: str) -> None:
        with self._state_lock:
            attempts = self._reconnect_attempts.get(port, 0)
            if attempts >= self._max_reconnect_attempts:
                log.error(f"Max reconnect attempts reached for {port}, giving up")
                self.device_error.emit(port, "Max reconnect attempts reached")
                return

            existing = self._reconnect_threads.get(port)
            if existing and existing.is_alive():
                return

            delay = self._calculate_backoff(attempts)
            self._reconnect_attempts[port] = attempts + 1
            stop_event = threading.Event()
            self._reconnect_stop_events[port] = stop_event

        log.info(f"Reconnecting to {port} in {delay:.1f}s (attempt {attempts + 1}/{self._max_reconnect_attempts})")

        def attempt_reconnect() -> None:
            waited = 0.0
            while waited < delay and not stop_event.is_set():
                step = min(0.25, delay - waited)
                time.sleep(step)
                waited += step

            if stop_event.is_set() or not self._running:
                with self._state_lock:
                    self._reconnect_threads.pop(port, None)
                    self._reconnect_stop_events.pop(port, None)
                return

            if self.config.get("device.auto_connect", True):
                success = self.device_manager.connect(port, self.config.get("device.baudrate", 2000000))
                if success:
                    with self._state_lock:
                        self._reconnect_attempts.pop(port, None)
                    log.info(f"Reconnected to {port} successfully")

            with self._state_lock:
                self._reconnect_threads.pop(port, None)
                self._reconnect_stop_events.pop(port, None)

        thread = threading.Thread(target=attempt_reconnect, daemon=True, name=f"HID-Reconnect-{port}")
        with self._state_lock:
            self._reconnect_threads[port] = thread
        thread.start()

    def _on_connected(self, port: str) -> None:
        current = threading.current_thread()
        with self._state_lock:
            self._known_ports.add(port)
            self._reconnect_attempts.pop(port, None)
            stop_event = self._reconnect_stop_events.pop(port, None)
            thread = self._reconnect_threads.pop(port, None)

        if stop_event:
            stop_event.set()
        if thread and thread.is_alive() and thread is not current:
            thread.join(timeout=1.0)

        self.device_connected.emit(port)

    def _on_disconnected(self, port: str) -> None:
        with self._state_lock:
            self._known_ports.discard(port)
        self.device_disconnected.emit(port)

    def _on_error(self, port: str, error: str) -> None:
        self.device_error.emit(port, error)
