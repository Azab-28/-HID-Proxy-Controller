"""Core functionality package."""

from .device import ConnectionState, DeviceInfo, DeviceManager
from .dispatcher import (
    CommandDispatcher,
    ConfigChangedPayload,
    DeviceConnectedPayload,
    DeviceDataPayload,
    DeviceDisconnectedPayload,
    Event,
    EventBus,
    EventType,
    TargetSelectedPayload,
    emit_config_changed,
    emit_device_connected,
    emit_device_data,
    emit_device_disconnected,
    get_event_bus,
    set_event_bus,
)
from .monitor import ConnectionMonitor
from .protocol import AckTracker, Command, FrameParser, Packet, Packets, Response, crc8

__all__ = [
    "DeviceManager",
    "DeviceInfo",
    "ConnectionState",
    "Packet",
    "Command",
    "Response",
    "Packets",
    "FrameParser",
    "AckTracker",
    "crc8",
    "EventBus",
    "Event",
    "EventType",
    "get_event_bus",
    "set_event_bus",
    "ConfigChangedPayload",
    "DeviceConnectedPayload",
    "DeviceDisconnectedPayload",
    "DeviceDataPayload",
    "TargetSelectedPayload",
    "emit_config_changed",
    "emit_device_connected",
    "emit_device_disconnected",
    "emit_device_data",
    "CommandDispatcher",
    "ConnectionMonitor",
]
