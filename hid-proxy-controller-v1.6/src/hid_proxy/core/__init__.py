"""Core functionality package."""

from .device import DeviceManager, DeviceInfo, ConnectionState
from .protocol import (Packet, Command, Response, Packets, FrameParser, 
                       AckTracker, crc8)
from .dispatcher import (EventBus, Event, EventType, get_event_bus, set_event_bus,
                         ConfigChangedPayload, DeviceConnectedPayload, 
                         DeviceDisconnectedPayload, DeviceDataPayload, TargetSelectedPayload,
                         emit_config_changed, emit_device_connected, emit_device_disconnected, emit_device_data,
                         CommandDispatcher)
from .monitor import ConnectionMonitor

__all__ = [
    "DeviceManager", "DeviceInfo", "ConnectionState",
    "Packet", "Command", "Response", "Packets", "FrameParser", "AckTracker", "crc8",
    "EventBus", "Event", "EventType", "get_event_bus", "set_event_bus",
    "ConfigChangedPayload", "DeviceConnectedPayload", "DeviceDisconnectedPayload", 
    "DeviceDataPayload", "TargetSelectedPayload",
    "emit_config_changed", "emit_device_connected", "emit_device_disconnected", "emit_device_data",
    "CommandDispatcher",
    "ConnectionMonitor"
]