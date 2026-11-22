"""Typed Event Bus for decoupled component communication."""
import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Generic, List, Optional, TypeVar

log = get_logger = logging.getLogger(__name__)

T = TypeVar("T")


class EventType(Enum):
    CONFIG_CHANGED = "config_changed"
    DEVICE_CONNECTED = "device_connected"
    DEVICE_DISCONNECTED = "device_disconnected"
    DEVICE_ERROR = "device_error"
    DEVICE_DATA = "device_data"
    MODULE_ENABLED = "module_enabled"
    MODULE_DISABLED = "module_disabled"
    TARGET_SELECTED = "target_selected"
    TARGET_LOST = "target_lost"
    UI_SETTINGS_CHANGED = "ui_settings_changed"
    UI_PROFILE_LOADED = "ui_profile_loaded"
    SHUTDOWN_REQUESTED = "shutdown_requested"


@dataclass
class Event(Generic[T]):
    type: EventType
    payload: T
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


@dataclass
class ConfigChangedPayload:
    key: str
    old_value: Any
    new_value: Any


@dataclass
class DeviceConnectedPayload:
    port: str
    device_id: str
    firmware_version: str


@dataclass
class DeviceDisconnectedPayload:
    port: str
    reason: str = ""


@dataclass
class DeviceDataPayload:
    port: str
    packet: Any


@dataclass
class TargetSelectedPayload:
    target_id: str
    x: int
    y: int
    distance: float


class EventBus:
    """Thread-safe typed event bus for decoupled component communication."""

    def __init__(self):
        self._handlers: Dict[EventType, List[Callable]] = defaultdict(list)
        self._lock = threading.RLock()
        self._event_history: List[Event] = []
        self._max_history = 1000

    def subscribe(self, event_type: EventType, handler: Callable[[Event], None]) -> Callable[[], None]:
        with self._lock:
            self._handlers[event_type].append(handler)

        def unsubscribe() -> None:
            with self._lock:
                if handler in self._handlers[event_type]:
                    self._handlers[event_type].remove(handler)

        return unsubscribe

    def subscribe_many(
        self, event_types: List[EventType], handler: Callable[[Event], None]
    ) -> Callable[[], None]:
        unsubscribers = [self.subscribe(et, handler) for et in event_types]

        def unsubscribe_all() -> None:
            for u in unsubscribers:
                u()

        return unsubscribe_all

    def emit(self, event: Event) -> None:
        with self._lock:
            self._event_history.append(event)
            if len(self._event_history) > self._max_history:
                self._event_history.pop(0)
            handlers = self._handlers.get(event.type, []).copy()

        for handler in handlers:
            try:
                handler(event)
            except Exception as e:
                log.error(f"Event handler error for {event.type}: {e}")

    def emit_sync(self, event: Event) -> List[Any]:
        with self._lock:
            handlers = self._handlers.get(event.type, []).copy()

        results = []
        for handler in handlers:
            try:
                results.append(handler(event))
            except Exception as e:
                log.error(f"Sync event handler error for {event.type}: {e}")
                results.append(None)
        return results

    def get_history(self, event_type: Optional[EventType] = None, limit: int = 100) -> List[Event]:
        with self._lock:
            history = self._event_history
            if event_type:
                history = [e for e in history if e.type == event_type]
            return history[-limit:]

    def clear_history(self) -> None:
        with self._lock:
            self._event_history.clear()


_global_event_bus: Optional[EventBus] = None
_event_bus_lock = threading.Lock()


def get_event_bus() -> EventBus:
    global _global_event_bus
    with _event_bus_lock:
        if _global_event_bus is None:
            _global_event_bus = EventBus()
        return _global_event_bus


def set_event_bus(bus: EventBus) -> None:
    global _global_event_bus
    with _event_bus_lock:
        _global_event_bus = bus


def emit_config_changed(key: str, old_value: Any, new_value: Any) -> None:
    get_event_bus().emit(Event(EventType.CONFIG_CHANGED, ConfigChangedPayload(key, old_value, new_value)))


def emit_device_connected(port: str, device_id: str, firmware_version: str) -> None:
    get_event_bus().emit(
        Event(EventType.DEVICE_CONNECTED, DeviceConnectedPayload(port, device_id, firmware_version))
    )


def emit_device_disconnected(port: str, reason: str = "") -> None:
    get_event_bus().emit(Event(EventType.DEVICE_DISCONNECTED, DeviceDisconnectedPayload(port, reason)))


def emit_device_data(port: str, packet: Any) -> None:
    get_event_bus().emit(Event(EventType.DEVICE_DATA, DeviceDataPayload(port, packet)))


class CommandDispatcher:
    """Backward-compatible wrapper around DeviceManager/EventBus."""

    def __init__(self, device_manager):
        self.device_manager = device_manager
        self._handlers: Dict[str, List[Callable]] = {}
        self._default_port: str = ""

    def register(self, command: str, handler: Callable) -> None:
        self._handlers.setdefault(command, []).append(handler)

    def unregister(self, command: str, handler: Callable) -> None:
        if command in self._handlers and handler in self._handlers[command]:
            self._handlers[command].remove(handler)

    def dispatch(self, command: str, *args, **kwargs) -> List[Any]:
        results = []
        for handler in self._handlers.get(command, []):
            try:
                results.append(handler(*args, **kwargs))
            except Exception as e:
                log.error(f"Dispatch error ({command}): {e}")
        return results

    def set_default_port(self, port: str) -> None:
        self._default_port = port

    def send_to_device(self, packet: Any) -> bool:
        if not self._default_port:
            ports = self.device_manager.get_connected_ports()
            if not ports:
                return False
            self._default_port = ports[0]
        return self.device_manager.send(self._default_port, packet)
