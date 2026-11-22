"""Typed Event Bus for decoupled component communication.

Replaces the string-based CommandDispatcher with a type-safe event system.
"""
import logging
import threading
from typing import Dict, List, Callable, Any, TypeVar, Generic, Type
from dataclasses import dataclass
from enum import Enum
from collections import defaultdict

log = logging.getLogger(__name__)

T = TypeVar('T')


class EventType(Enum):
    """Core event types for the application."""
    # Config events
    CONFIG_CHANGED = "config_changed"
    
    # Device events
    DEVICE_CONNECTED = "device_connected"
    DEVICE_DISCONNECTED = "device_disconnected"
    DEVICE_ERROR = "device_error"
    DEVICE_DATA = "device_data"
    
    # Module events
    MODULE_ENABLED = "module_enabled"
    MODULE_DISABLED = "module_disabled"
    
    # Targeting events
    TARGET_SELECTED = "target_selected"
    TARGET_LOST = "target_lost"
    
    # UI events
    UI_SETTINGS_CHANGED = "ui_settings_changed"
    UI_PROFILE_LOADED = "ui_profile_loaded"
    
    # System events
    SHUTDOWN_REQUESTED = "shutdown_requested"


@dataclass
class Event(Generic[T]):
    """Base event with payload."""
    type: EventType
    payload: T
    timestamp: float = 0.0
    
    def __post_init__(self):
        if self.timestamp == 0.0:
            import time
            self.timestamp = time.time()


# Specific event payloads
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
    packet: Any  # Protocol Packet

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
        """Subscribe to an event type. Returns unsubscribe function."""
        with self._lock:
            self._handlers[event_type].append(handler)
        
        def unsubscribe():
            with self._lock:
                if handler in self._handlers[event_type]:
                    self._handlers[event_type].remove(handler)
        return unsubscribe
    
    def subscribe_many(self, event_types: List[EventType], handler: Callable[[Event], None]) -> Callable[[], None]:
        """Subscribe to multiple event types with same handler."""
        unsubscribers = []
        for et in event_types:
            unsubscribers.append(self.subscribe(et, handler))
        
        def unsubscribe_all():
            for u in unsubscribers:
                u()
        return unsubscribe_all
    
    def emit(self, event: Event) -> None:
        """Emit event to all subscribers (async, non-blocking)."""
        # Store in history
        with self._lock:
            self._event_history.append(event)
            if len(self._event_history) > self._max_history:
                self._event_history.pop(0)
            handlers = self._handlers.get(event.type, []).copy()
        
        # Call handlers outside lock
        for handler in handlers:
            try:
                handler(event)
            except Exception as e:
                log.error(f"Event handler error for {event.type}: {e}")
    
    def emit_sync(self, event: Event) -> List[Any]:
        """Emit event and wait for all handlers to complete. Returns list of results."""
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
    
    def get_history(self, event_type: EventType = None, limit: int = 100) -> List[Event]:
        """Get recent event history."""
        with self._lock:
            history = self._event_history
            if event_type:
                history = [e for e in history if e.type == event_type]
            return history[-limit:]
    
    def clear_history(self):
        with self._lock:
            self._event_history.clear()


# Global event bus instance
_global_event_bus = None
_event_bus_lock = threading.Lock()


def get_event_bus() -> EventBus:
    """Get the global event bus instance."""
    global _global_event_bus
    with _event_bus_lock:
        if _global_event_bus is None:
            _global_event_bus = EventBus()
        return _global_event_bus


def set_event_bus(bus: EventBus):
    """Set a custom global event bus (for testing)."""
    global _global_event_bus
    with _event_bus_lock:
        _global_event_bus = bus


# Convenience functions for common events
def emit_config_changed(key: str, old_value: Any, new_value: Any):
    bus = get_event_bus()
    bus.emit(Event(EventType.CONFIG_CHANGED, ConfigChangedPayload(key, old_value, new_value)))


def emit_device_connected(port: str, device_id: str, firmware_version: str):
    bus = get_event_bus()
    bus.emit(Event(EventType.DEVICE_CONNECTED, DeviceConnectedPayload(port, device_id, firmware_version)))


def emit_device_disconnected(port: str, reason: str = ""):
    bus = get_event_bus()
    bus.emit(Event(EventType.DEVICE_DISCONNECTED, DeviceDisconnectedPayload(port, reason)))


def emit_device_data(port: str, packet):
    bus = get_event_bus()
    bus.emit(Event(EventType.DEVICE_DATA, DeviceDataPayload(port, packet)))


# Legacy CommandDispatcher compatibility
class CommandDispatcher:
    """Legacy string-based command dispatcher (deprecated, use EventBus instead)."""
    
    def __init__(self, device_manager):
        self.device_manager = device_manager
        self._handlers: Dict[str, List[Callable]] = {}
        self._default_port: str = ""
        log.warning("CommandDispatcher is deprecated, use EventBus instead")
    
    def register(self, command: str, handler: Callable) -> None:
        if command not in self._handlers:
            self._handlers[command] = []
        self._handlers[command].append(handler)
    
    def unregister(self, command: str, handler: Callable) -> None:
        if command in self._handlers:
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
    
    def send_to_device(self, packet) -> bool:
        if not self._default_port:
            ports = self.device_manager.get_connected_ports()
            if not ports:
                return False
            self._default_port = ports[0]
        return self.device_manager.send(self._default_port, packet)