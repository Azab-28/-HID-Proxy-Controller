"""Connection monitor with auto-reconnection and exponential backoff (thread-safe)."""
import threading
import time
import logging
import random
from typing import Callable, List, Dict, Set
from PySide6.QtCore import QObject, Signal

from hid_proxy.core.device import DeviceManager, ConnectionState
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
        
        # Thread-safe state
        self._state_lock = threading.RLock()
        self._known_ports: Set[str] = set()
        self._reconnect_attempts: Dict[str, int] = {}
        self._reconnect_threads: Dict[str, threading.Thread] = {}
        self._reconnect_stop_events: Dict[str, threading.Event] = {}
        
        # Configurable backoff parameters
        self._max_reconnect_attempts = 10
        self._base_reconnect_delay = 1.0
        self._max_reconnect_delay = 60.0

        # Register callbacks
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
        
        # Stop all reconnect threads
        with self._state_lock:
            for stop_event in self._reconnect_stop_events.values():
                stop_event.set()
            for thread in self._reconnect_threads.values():
                if thread.is_alive():
                    thread.join(timeout=1.0)
            self._reconnect_threads.clear()
            self._reconnect_stop_events.clear()
        
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        log.info("Connection monitor stopped")

    def _calculate_backoff(self, attempts: int) -> float:
        """Exponential backoff with jitter."""
        delay = min(self._base_reconnect_delay * (2 ** attempts), self._max_reconnect_delay)
        jitter = delay * 0.25 * (2 * random.random() - 1)
        return delay + jitter

    def _monitor_loop(self):
        while self._running:
            try:
                current_ports = set(p["port"] for p in self.device_manager.scan_ports())
                
                with self._state_lock:
                    new_ports = current_ports - self._known_ports
                    lost_ports = self._known_ports - current_ports
                    self._known_ports = current_ports
                
                # Handle new ports
                for port in new_ports:
                    if self.config.get("device.auto_connect"):
                        self.device_manager.connect(port, self.config.get("device.baudrate"))
                    # Reset reconnect counter on new connection
                    with self._state_lock:
                        self._reconnect_attempts.pop(port, None)
                
                # Handle lost ports
                for port in lost_ports:
                    if self.device_manager.is_connected(port):
                        log.warning(f"Device {port} lost, scheduling reconnect...")
                        self.device_manager.disconnect(port)
                        self._schedule_reconnect(port)
                
            except Exception as e:
                log.error(f"Monitor loop error: {e}")

            time.sleep(2.0)

    def _schedule_reconnect(self, port: str):
        """Schedule a reconnection attempt with exponential backoff (thread-safe)."""
        with self._state_lock:
            attempts = self._reconnect_attempts.get(port, 0)
            if attempts >= self._max_reconnect_attempts:
                log.error(f"Max reconnect attempts reached for {port}, giving up")
                self.device_error.emit(port, "Max reconnect attempts reached")
                return
            
            # Check if already reconnecting
            if port in self._reconnect_threads and self._reconnect_threads[port].is_alive():
                log.debug(f"Reconnect already in progress for {port}")
                return
            
            delay = self._calculate_backoff(attempts)
            self._reconnect_attempts[port] = attempts + 1
            
            stop_event = threading.Event()
            self._reconnect_stop_events[port] = stop_event

        log.info(f"Reconnecting to {port} in {delay:.1f}s (attempt {attempts + 1}/{self._max_reconnect_attempts})")

        def attempt_reconnect():
            # Wait with periodic check for stop
            waited = 0.0
            while waited < delay and not stop_event.is_set():
                time.sleep(min(0.5, delay - waited))
                waited += 0.5
            
            if stop_event.is_set() or not self._running:
                with self._state_lock:
                    self._reconnect_threads.pop(port, None)
                    self._reconnect_stop_events.pop(port, None)
                return
            
            if self.config.get("device.auto_connect"):
                success = self.device_manager.connect(port, self.config.get("device.baudrate"))
                if success:
                    with self._state_lock:
                        self._reconnect_attempts.pop(port, None)
                    log.info(f"Reconnected to {port} successfully")
                else:
                    # Will retry on next monitor loop iteration
                    pass
            
            # Cleanup
            with self._state_lock:
                self._reconnect_threads.pop(port, None)
                self._reconnect_stop_events.pop(port, None)

        thread = threading.Thread(target=attempt_reconnect, daemon=True, name=f"HID-Reconnect-{port}")
        with self._state_lock:
            self._reconnect_threads[port] = thread
        thread.start()

    def _on_connected(self, port: str):
        with self._state_lock:
            self._known_ports.add(port)
            self._reconnect_attempts.pop(port, None)
            # Stop any pending reconnect
            stop_event = self._reconnect_stop_events.pop(port, None)
            if stop_event:
                stop_event.set()
            thread = self._reconnect_threads.pop(port, None)
        if thread and thread.is_alive():
            thread.join(timeout=1.0)
        self.device_connected.emit(port)

    def _on_disconnected(self, port: str):
        with self._state_lock:
            self._known_ports.discard(port)
        self.device_disconnected.emit(port)

    def _on_error(self, port: str, error: str):
        self.device_error.emit(port, error)