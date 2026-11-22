"""ESP32 device management with auto-reconnection and thread-safe I/O."""
import serial
import serial.tools.list_ports
import threading
import time
import struct
import logging
from typing import Optional, Dict, Callable, List
from dataclasses import dataclass

from hid_proxy.core.protocol import Packet, Command, Response, Packets

log = logging.getLogger(__name__)


@dataclass
class DeviceInfo:
    port: str
    device_id: str
    firmware_version: str
    capabilities: list
    connected_at: float


class DeviceManager:
    ESP32_VID_PID = [
        (0x303A, 0x1001),  # Espressif
        (0x1A86, 0x7523),  # CH343
        (0x10C4, 0xEA60),  # CP210x
    ]

    def __init__(self, config_manager):
        self.config = config_manager
        self._devices: Dict[str, serial.Serial] = {}
        self._device_info: Dict[str, DeviceInfo] = {}
        self._port_locks: Dict[str, threading.Lock] = {}  # Per-port I/O lock
        self._lock = threading.RLock()  # For dict operations
        self._callbacks: Dict[str, List[Callable]] = {
            "connected": [], "disconnected": [], "data": [], "error": []
        }
        self._reader_threads: Dict[str, threading.Thread] = {}
        self._stop_events: Dict[str, threading.Event] = {}

    def register_callback(self, event: str, callback: Callable) -> None:
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    def _emit(self, event: str, *args) -> None:
        for cb in self._callbacks.get(event, []):
            try:
                cb(*args)
            except Exception as e:
                log.error(f"Callback error ({event}): {e}")

    def scan_ports(self) -> List[dict]:
        ports = []
        for port in serial.tools.list_ports.comports():
            if (port.vid, port.pid) in self.ESP32_VID_PID:
                ports.append({
                    "port": port.device, "description": port.description,
                    "hwid": port.hwid, "vid": port.vid, "pid": port.pid
                })
        return ports

    def _get_port_lock(self, port: str) -> threading.Lock:
        """Get or create lock for a port."""
        with self._lock:
            if port not in self._port_locks:
                self._port_locks[port] = threading.Lock()
            return self._port_locks[port]

    def connect(self, port: str, baudrate: int = 2000000) -> bool:
        with self._lock:
            if port in self._devices:
                return True
            try:
                ser = serial.Serial(port=port, baudrate=baudrate, timeout=0.001,
                                   write_timeout=0.001, exclusive=True)
                time.sleep(0.2)
                ser.reset_input_buffer()
                ser.reset_output_buffer()

                if not self._handshake(ser):
                    ser.close()
                    return False

                info = self._query_device_info(ser, port)
                self._devices[port] = ser
                self._device_info[port] = info
                # Ensure port lock exists
                self._port_locks[port] = threading.Lock()

                stop_event = threading.Event()
                self._stop_events[port] = stop_event
                reader = threading.Thread(target=self._reader_loop, args=(port, ser, stop_event),
                                        daemon=True, name=f"HID-Reader-{port}")
                self._reader_threads[port] = reader
                reader.start()

                log.info(f"Connected to {port} (ID: {info.device_id})")
                self._emit("connected", port)
                return True
            except Exception as e:
                log.error(f"Connection failed ({port}): {e}")
                return False

    def _handshake(self, ser: serial.Serial) -> bool:
        ser.write(Packets.ping())
        ser.flush()
        start = time.time()
        while time.time() - start < 2.0:
            if ser.in_waiting >= 6:
                data = ser.read(ser.in_waiting)
                packet = Packet.decode(data)
                if packet and packet.command == Response.OK:
                    return True
            time.sleep(0.01)
        return False

    def _query_device_info(self, ser: serial.Serial, port: str) -> DeviceInfo:
        ser.write(Packets.get_info())
        ser.flush()
        start = time.time()
        while time.time() - start < 1.0:
            if ser.in_waiting >= 6:
                data = ser.read(ser.in_waiting)
                packet = Packet.decode(data)
                if packet and packet.command == Command.GET_INFO:
                    parts = packet.payload.split(b"\0")
                    device_id = parts[0].decode() if parts else "UNKNOWN"
                    firmware = parts[1].decode() if len(parts) > 1 else "1.0"
                    return DeviceInfo(port, device_id, firmware, [], time.time())
            time.sleep(0.01)
        return DeviceInfo(port, "UNKNOWN", "1.0", [], time.time())

    def _reader_loop(self, port: str, ser: serial.Serial, stop_event: threading.Event) -> None:
        buffer = bytearray()
        port_lock = self._get_port_lock(port)
        while not stop_event.is_set():
            try:
                with port_lock:
                    if not ser.is_open:
                        break
                    if ser.in_waiting:
                        data = ser.read(ser.in_waiting)
                        buffer.extend(data)

                # Process buffer outside the lock to minimize hold time
                while len(buffer) >= 6:
                    if buffer[0] == 0xAA and buffer[1] == 0x55:
                        if len(buffer) >= 5:
                            length = struct.unpack("<H", buffer[3:5])[0]
                            if len(buffer) >= 6 + length:
                                packet_data = bytes(buffer[:6+length])
                                del buffer[:6+length]
                                packet = Packet.decode(packet_data)
                                if packet:
                                    self._emit("data", port, packet)
                                continue
                    try:
                        idx = buffer.index(0xAA, 1)
                        del buffer[:idx]
                    except ValueError:
                        buffer.clear()
                        break
                time.sleep(0.001)
            except Exception as e:
                log.error(f"Reader error ({port}): {e}")
                self._emit("error", port, str(e))
                break

    def send(self, port: str, packet: Packet) -> bool:
        port_lock = self._get_port_lock(port)
        with port_lock:
            with self._lock:
                ser = self._devices.get(port)
            if not ser or not ser.is_open:
                return False
            try:
                ser.write(packet.encode())
                return True
            except Exception as e:
                log.error(f"Send failed ({port}): {e}")
                self._handle_disconnect(port)
                return False

    def send_text(self, port: str, data: bytes) -> bool:
        port_lock = self._get_port_lock(port)
        with port_lock:
            with self._lock:
                ser = self._devices.get(port)
            if not ser or not ser.is_open:
                return False
            try:
                ser.write(data)
                return True
            except Exception as e:
                log.error(f"Text send failed ({port}): {e}")
                return False

    def disconnect(self, port: str) -> None:
        with self._lock:
            self._handle_disconnect(port)

    def _handle_disconnect(self, port: str) -> None:
        stop_event = self._stop_events.pop(port, None)
        if stop_event:
            stop_event.set()
        reader = self._reader_threads.pop(port, None)
        if reader and reader.is_alive():
            reader.join(timeout=1.0)
        with self._lock:
            ser = self._devices.pop(port, None)
            self._port_locks.pop(port, None)
        if ser:
            try:
                ser.close()
            except Exception:
                pass
        self._device_info.pop(port, None)
        self._emit("disconnected", port)

    def disconnect_all(self) -> None:
        for port in list(self._devices.keys()):
            self.disconnect(port)

    def get_device_id(self, port: str) -> Optional[str]:
        info = self._device_info.get(port)
        return info.device_id if info else None

    def is_connected(self, port: str) -> bool:
        with self._lock:
            return port in self._devices

    def get_connected_ports(self) -> List[str]:
        with self._lock:
            return list(self._devices.keys())