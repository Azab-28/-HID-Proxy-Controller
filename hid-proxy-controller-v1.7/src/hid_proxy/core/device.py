"""ESP32 device management with dual-thread non-blocking I/O and injectable serial transport."""
import logging
import queue
import struct
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union

import serial
import serial.tools.list_ports

from hid_proxy.core.dispatcher import (
    emit_device_connected,
    emit_device_data,
    emit_device_disconnected,
)
from hid_proxy.core.protocol import (
    AckTracker,
    Command,
    FrameParser,
    Packet,
    Packets,
    Response,
)

log = logging.getLogger(__name__)


@dataclass
class DeviceInfo:
    port: str
    device_id: str
    firmware_version: str
    capabilities: list
    connected_at: float


class ConnectionState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTING = "disconnecting"


@dataclass
class PortState:
    ser: Optional[Any] = None
    info: Optional[DeviceInfo] = None
    state: ConnectionState = ConnectionState.DISCONNECTED
    stop_event: threading.Event = field(default_factory=threading.Event)
    reader_thread: Optional[threading.Thread] = None
    writer_thread: Optional[threading.Thread] = None
    write_queue: "queue.Queue[Union[Packet, bytes]]" = field(
        default_factory=lambda: queue.Queue(maxsize=1000)
    )
    ack_tracker: AckTracker = field(default_factory=AckTracker)
    last_activity: float = 0.0


class DeviceManager:
    """Manages ESP32 HID proxy devices with dual-thread I/O."""

    ESP32_VID_PID = [
        (0x303A, 0x1001),  # Espressif native USB (ESP32-S2/S3/C3)
        (0x1A86, 0x55D3),  # WCH CH343
        (0x1A86, 0x7523),  # WCH CH340
        (0x10C4, 0xEA60),  # Silicon Labs CP210x
    ]

    HANDSHAKE_TIMEOUT = 2.0
    INFO_QUERY_TIMEOUT = 1.0
    READ_TIMEOUT = 0.05
    WRITE_TIMEOUT = 0.1
    MAX_WRITE_QUEUE_SIZE = 1000
    COALESCE_WINDOW_MS = 2

    def __init__(
        self,
        config_manager,
        serial_factory: Optional[Callable[..., Any]] = None,
    ):
        self.config = config_manager
        self._serial_factory = serial_factory or self._default_serial_factory
        self._ports: Dict[str, PortState] = {}
        self._ports_lock = threading.RLock()
        self._callbacks: Dict[str, List[Callable]] = {
            "connected": [],
            "disconnected": [],
            "data": [],
            "error": [],
        }
        self._frame_parsers: Dict[str, FrameParser] = {}

    @staticmethod
    def _default_serial_factory(port: str, baudrate: int, read_timeout: float, write_timeout: float):
        return serial.Serial(
            port=port,
            baudrate=baudrate,
            timeout=read_timeout,
            write_timeout=write_timeout,
            exclusive=True,
            dtr=False,
            rts=False,
        )

    def register_callback(self, event: str, callback: Callable) -> None:
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    def _emit(self, event: str, *args) -> None:
        """Emit callback outside any internal locks."""
        for cb in list(self._callbacks.get(event, [])):
            try:
                cb(*args)
            except Exception as e:
                log.error(f"Callback error ({event}): {e}")

    def scan_ports(self) -> List[dict]:
        ports = []
        for port in serial.tools.list_ports.comports():
            if (port.vid, port.pid) in self.ESP32_VID_PID:
                ports.append({
                    "port": port.device,
                    "description": port.description,
                    "hwid": port.hwid,
                    "vid": port.vid,
                    "pid": port.pid,
                })
        return ports

    def connect(self, port: str, baudrate: int = 2000000) -> bool:
        """Connect to a serial port with framed handshake and device info query."""
        with self._ports_lock:
            ps = self._ports.get(port)
            if ps and ps.state in (ConnectionState.CONNECTED, ConnectionState.CONNECTING):
                return True

            ps = PortState(
                write_queue=queue.Queue(maxsize=self.MAX_WRITE_QUEUE_SIZE),
            )
            ps.state = ConnectionState.CONNECTING
            self._ports[port] = ps
            self._frame_parsers[port] = FrameParser()

        try:
            ser = self._serial_factory(port, baudrate, self.READ_TIMEOUT, self.WRITE_TIMEOUT)
            time.sleep(0.05)
            if hasattr(ser, "reset_input_buffer"):
                ser.reset_input_buffer()
            if hasattr(ser, "reset_output_buffer"):
                ser.reset_output_buffer()

            if not self._handshake(ser):
                try:
                    ser.close()
                except Exception:
                    pass
                with self._ports_lock:
                    ps.state = ConnectionState.DISCONNECTED
                return False

            info = self._query_device_info(ser, port)
            if not info:
                try:
                    ser.close()
                except Exception:
                    pass
                with self._ports_lock:
                    ps.state = ConnectionState.DISCONNECTED
                return False

            with self._ports_lock:
                ps.ser = ser
                ps.info = info
                ps.state = ConnectionState.CONNECTED
                ps.last_activity = time.monotonic()

                ps.reader_thread = threading.Thread(
                    target=self._reader_loop, args=(port,), daemon=True, name=f"HID-RX-{port}"
                )
                ps.writer_thread = threading.Thread(
                    target=self._writer_loop, args=(port,), daemon=True, name=f"HID-TX-{port}"
                )
                ps.reader_thread.start()
                ps.writer_thread.start()

            log.info(f"Connected to {port} (ID: {info.device_id}, FW: {info.firmware_version})")
            self._emit("connected", port)
            emit_device_connected(port, info.device_id, info.firmware_version)
            return True

        except Exception as e:
            log.error(f"Connection failed ({port}): {e}")
            with self._ports_lock:
                if port in self._ports:
                    self._ports[port].state = ConnectionState.DISCONNECTED
            self._emit("error", port, str(e))
            return False

    def _handshake(self, ser: Any) -> bool:
        parser = FrameParser()
        ser.write(Packets.ping().encode())
        if hasattr(ser, "flush"):
            ser.flush()
        deadline = time.monotonic() + self.HANDSHAKE_TIMEOUT
        while time.monotonic() < deadline:
            waiting = getattr(ser, "in_waiting", 0)
            if waiting:
                data = ser.read(waiting)
                for packet in parser.feed(data):
                    if packet.command == Response.OK:
                        return True
            else:
                chunk = ser.read(1)
                if chunk:
                    for packet in parser.feed(chunk):
                        if packet.command == Response.OK:
                            return True
            time.sleep(0.005)
        return False

    def _query_device_info(self, ser: Any, port: str) -> Optional[DeviceInfo]:
        parser = FrameParser()
        ser.write(Packets.get_info().encode())
        if hasattr(ser, "flush"):
            ser.flush()
        deadline = time.monotonic() + self.INFO_QUERY_TIMEOUT
        while time.monotonic() < deadline:
            waiting = getattr(ser, "in_waiting", 0)
            data = ser.read(waiting) if waiting else ser.read(1)
            if data:
                for packet in parser.feed(data):
                    if packet.command == Command.GET_INFO:
                        parts = packet.payload.split(b"\0")
                        device_id = parts[0].decode(errors="replace") if parts and parts[0] else "UNKNOWN"
                        firmware = (
                            parts[1].decode(errors="replace")
                            if len(parts) > 1 and parts[1]
                            else "1.0"
                        )
                        return DeviceInfo(port, device_id, firmware, [], time.time())
            time.sleep(0.005)
        return None

    def _reader_loop(self, port: str) -> None:
        with self._ports_lock:
            ps = self._ports.get(port)
            if not ps or not ps.ser:
                return
            ser = ps.ser
            parser = self._frame_parsers.get(port, FrameParser())

        unexpected_exit = False
        try:
            while not ps.stop_event.is_set():
                try:
                    data = ser.read(1)
                    if not data:
                        continue
                    waiting = getattr(ser, "in_waiting", 0)
                    if waiting:
                        data += ser.read(waiting)

                    for packet in parser.feed(data):
                        ps.last_activity = time.monotonic()
                        if packet.command == Command.ACK and len(packet.payload) >= 1:
                            ps.ack_tracker.ack(packet.payload[0])
                        self._emit("data", port, packet)
                        emit_device_data(port, packet)
                except serial.SerialException as e:
                    if not ps.stop_event.is_set():
                        log.warning(f"Serial read error on {port}: {e}")
                        unexpected_exit = True
                    break
                except Exception as e:
                    if not ps.stop_event.is_set():
                        log.error(f"Reader error ({port}): {e}")
                        unexpected_exit = True
                    break
        finally:
            if unexpected_exit and not ps.stop_event.is_set():
                threading.Thread(
                    target=self._handle_disconnect,
                    args=(port, "read_error"),
                    daemon=True,
                    name=f"HID-Cleanup-{port}",
                ).start()

    def _writer_loop(self, port: str) -> None:
        with self._ports_lock:
            ps = self._ports.get(port)
            if not ps or not ps.ser:
                return
            ser = ps.ser

        coalesce_buffer: List[Packet] = []
        last_flush = time.monotonic()
        unexpected_exit = False

        try:
            while not ps.stop_event.is_set():
                try:
                    item = ps.write_queue.get(timeout=0.01)

                    if isinstance(item, bytes):
                        if coalesce_buffer:
                            self._write_coalesced_moves(ser, coalesce_buffer)
                            coalesce_buffer.clear()
                        ser.write(item)
                        continue

                    if item.command == Command.MOUSE_MOVE and not item.needs_ack:
                        coalesce_buffer.append(item)
                        now = time.monotonic()
                        if (now - last_flush) * 1000.0 >= self.COALESCE_WINDOW_MS or ps.write_queue.empty():
                            self._write_coalesced_moves(ser, coalesce_buffer)
                            coalesce_buffer.clear()
                            last_flush = now
                        continue

                    if coalesce_buffer:
                        self._write_coalesced_moves(ser, coalesce_buffer)
                        coalesce_buffer.clear()

                    if item.needs_ack:
                        ps.ack_tracker.add(item)
                    ser.write(item.encode())

                except queue.Empty:
                    if coalesce_buffer:
                        self._write_coalesced_moves(ser, coalesce_buffer)
                        coalesce_buffer.clear()
                        last_flush = time.monotonic()
                    # Check ACK retries
                    for retry_pkt in ps.ack_tracker.check_timeouts():
                        ser.write(retry_pkt.encode())
                    continue
                except serial.SerialException as e:
                    if not ps.stop_event.is_set():
                        log.warning(f"Serial write error on {port}: {e}")
                        unexpected_exit = True
                    break
                except Exception as e:
                    if not ps.stop_event.is_set():
                        log.error(f"Writer error ({port}): {e}")
                        unexpected_exit = True
                    break
        finally:
            if unexpected_exit and not ps.stop_event.is_set():
                threading.Thread(
                    target=self._handle_disconnect,
                    args=(port, "write_error"),
                    daemon=True,
                    name=f"HID-Cleanup-{port}",
                ).start()

    def _write_coalesced_moves(self, ser: Any, moves: List[Packet]) -> None:
        """Merge consecutive relative mouse moves into a single wire packet."""
        if not moves:
            return
        if len(moves) == 1:
            ser.write(moves[0].encode())
            return

        total_dx = 0
        total_dy = 0
        for m in moves:
            if len(m.payload) >= 4:
                dx, dy = struct.unpack("<hh", m.payload[:4])
                total_dx += dx
                total_dy += dy
        total_dx = max(-32768, min(32767, total_dx))
        total_dy = max(-32768, min(32767, total_dy))
        merged = Packet(Command.MOUSE_MOVE, struct.pack("<hh", total_dx, total_dy), seq=moves[-1].seq)
        ser.write(merged.encode())

    def send(self, port: str, packet: Union[Packet, bytes]) -> bool:
        """Enqueue a Packet (or raw bytes) for non-blocking TX transmission."""
        if not port:
            return False
        with self._ports_lock:
            ps = self._ports.get(port)
            if not ps or ps.state != ConnectionState.CONNECTED:
                return False
            try:
                ps.write_queue.put_nowait(packet)
                return True
            except queue.Full:
                log.warning(f"Write queue full for {port}, dropping packet")
                return False

    def send_text(self, port: str, data: bytes) -> bool:
        """Queue raw bytes through the TX thread to avoid concurrent serial writes."""
        return self.send(port, data)

    def _handle_disconnect(self, port: str, reason: str = "requested") -> None:
        """Synchronously clean up port resources without holding _ports_lock during joins."""
        with self._ports_lock:
            ps = self._ports.get(port)
            if not ps or ps.state in (ConnectionState.DISCONNECTED, ConnectionState.DISCONNECTING):
                return
            ps.state = ConnectionState.DISCONNECTING
            ps.stop_event.set()
            reader = ps.reader_thread
            writer = ps.writer_thread
            ser = ps.ser

        current = threading.current_thread()
        for t_name, thread in (("reader", reader), ("writer", writer)):
            if thread and thread.is_alive() and thread is not current:
                thread.join(timeout=1.0)
                if thread.is_alive():
                    log.warning(f"{t_name} thread for {port} did not stop in time")

        if ser:
            try:
                ser.close()
            except Exception:
                pass

        with self._ports_lock:
            ps.ser = None
            ps.info = None
            ps.state = ConnectionState.DISCONNECTED
            ps.ack_tracker.clear()
            ps.write_queue = queue.Queue(maxsize=self.MAX_WRITE_QUEUE_SIZE)
            self._frame_parsers.pop(port, None)

        log.info(f"Disconnected from {port} ({reason})")
        self._emit("disconnected", port)
        emit_device_disconnected(port, reason)

    def disconnect(self, port: str) -> None:
        self._handle_disconnect(port, "requested")

    def disconnect_all(self) -> None:
        with self._ports_lock:
            ports = list(self._ports.keys())
        for port in ports:
            self.disconnect(port)

    def get_device_id(self, port: str) -> Optional[str]:
        with self._ports_lock:
            ps = self._ports.get(port)
            return ps.info.device_id if ps and ps.info else None

    def get_device_info(self, port: str) -> Optional[DeviceInfo]:
        with self._ports_lock:
            ps = self._ports.get(port)
            return ps.info if ps else None

    def is_connected(self, port: str) -> bool:
        with self._ports_lock:
            ps = self._ports.get(port)
            return ps is not None and ps.state == ConnectionState.CONNECTED

    def get_connected_ports(self) -> List[str]:
        with self._ports_lock:
            return [p for p, ps in self._ports.items() if ps.state == ConnectionState.CONNECTED]

    def get_port_state(self, port: str) -> Optional[ConnectionState]:
        with self._ports_lock:
            ps = self._ports.get(port)
            return ps.state if ps else None
