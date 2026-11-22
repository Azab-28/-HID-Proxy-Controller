"""ESP32 device management with dual-thread non-blocking I/O.

Architecture:
- TX Writer Thread per port: consumes from queue, writes to serial (non-blocking)
- RX Reader Thread per port: blocking read with state-machine frame parser
- No locks held during callbacks or thread joins
- All cross-thread communication via thread-safe queues
"""
import serial
import serial.tools.list_ports
import threading
import time
import struct
import logging
import queue
from typing import Optional, Dict, Callable, List
from dataclasses import dataclass, field
from enum import Enum

from hid_proxy.core.protocol import Packet, Command, Response, Packets, FrameParser

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
    """All mutable state for a single port."""
    ser: Optional[serial.Serial] = None
    info: Optional[DeviceInfo] = None
    state: ConnectionState = ConnectionState.DISCONNECTED
    stop_event: threading.Event = field(default_factory=threading.Event)
    reader_thread: Optional[threading.Thread] = None
    writer_thread: Optional[threading.Thread] = None
    write_queue: "queue.Queue[Packet]" = field(default_factory=queue.Queue)
    last_activity: float = 0.0


class DeviceManager:
    """Manages ESP32 HID proxy devices with dual-thread I/O."""
    
    # VID/PID pairs for supported USB-serial chips
    ESP32_VID_PID = [
        (0x303A, 0x1001),  # Espressif (ESP32 native USB)
        (0x1A86, 0x55D3),  # CH343 (corrected from CH340's 0x7523)
        (0x10C4, 0xEA60),  # CP210x (Silicon Labs)
    ]

    # Protocol constants
    HANDSHAKE_TIMEOUT = 2.0
    INFO_QUERY_TIMEOUT = 1.0
    READ_TIMEOUT = 0.05  # 50ms blocking read
    WRITE_TIMEOUT = 0.1
    RECONNECT_DELAY = 1.0
    MAX_WRITE_QUEUE_SIZE = 1000
    COALESCE_WINDOW_MS = 2  # Coalesce mouse moves within this window

    def __init__(self, config_manager):
        self.config = config_manager
        self._ports: Dict[str, PortState] = {}
        self._ports_lock = threading.RLock()
        self._callbacks: Dict[str, List[Callable]] = {
            "connected": [], "disconnected": [], "data": [], "error": []
        }
        self._frame_parsers: Dict[str, FrameParser] = {}

    # ─────────────────────────────────────────────────────────────
    # Callbacks
    # ─────────────────────────────────────────────────────────────

    def register_callback(self, event: str, callback: Callable) -> None:
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    def _emit(self, event: str, *args) -> None:
        """Emit callback WITHOUT holding any locks."""
        for cb in self._callbacks.get(event, []):
            try:
                cb(*args)
            except Exception as e:
                log.error(f"Callback error ({event}): {e}")

    # ─────────────────────────────────────────────────────────────
    # Port Discovery
    # ─────────────────────────────────────────────────────────────

    def scan_ports(self) -> List[dict]:
        ports = []
        for port in serial.tools.list_ports.comports():
            if (port.vid, port.pid) in self.ESP32_VID_PID:
                ports.append({
                    "port": port.device,
                    "description": port.description,
                    "hwid": port.hwid,
                    "vid": port.vid,
                    "pid": port.pid
                })
        return ports

    # ─────────────────────────────────────────────────────────────
    # Connection Management
    # ─────────────────────────────────────────────────────────────

    def connect(self, port: str, baudrate: int = 2000000) -> bool:
        """Connect to a port. Thread-safe, non-blocking after connection."""
        with self._ports_lock:
            ps = self._ports.get(port)
            if ps and ps.state in (ConnectionState.CONNECTED, ConnectionState.CONNECTING):
                return True
            
            # Create new port state
            ps = PortState()
            ps.state = ConnectionState.CONNECTING
            self._ports[port] = ps
            self._frame_parsers[port] = FrameParser()

        # Attempt connection outside the lock
        try:
            ser = serial.Serial(
                port=port,
                baudrate=baudrate,
                timeout=self.READ_TIMEOUT,
                write_timeout=self.WRITE_TIMEOUT,
                exclusive=True,
                dtr=False,   # Prevent ESP32 reset on connect
                rts=False,   # Prevent ESP32 reset on connect
            )
            time.sleep(0.1)  # Brief settle
            ser.reset_input_buffer()
            ser.reset_output_buffer()

            if not self._handshake(ser):
                ser.close()
                with self._ports_lock:
                    ps.state = ConnectionState.DISCONNECTED
                return False

            info = self._query_device_info(ser, port)
            if not info:
                ser.close()
                with self._ports_lock:
                    ps.state = ConnectionState.DISCONNECTED
                return False

            # Success - populate state and start threads
            with self._ports_lock:
                ps.ser = ser
                ps.info = info
                ps.state = ConnectionState.CONNECTED
                ps.last_activity = time.time()

            # Start I/O threads
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
            return True

        except Exception as e:
            log.error(f"Connection failed ({port}): {e}")
            with self._ports_lock:
                if port in self._ports:
                    self._ports[port].state = ConnectionState.DISCONNECTED
            return False

    def _handshake(self, ser: serial.Serial) -> bool:
        """Perform handshake with proper framing."""
        parser = FrameParser()
        ser.write(Packets.ping())
        ser.flush()
        start = time.time()
        while time.time() - start < self.HANDSHAKE_TIMEOUT:
            if ser.in_waiting:
                data = ser.read(ser.in_waiting)
                for packet in parser.feed(data):
                    if packet and packet.command == Response.OK:
                        return True
            time.sleep(0.01)
        return False

    def _query_device_info(self, ser: serial.Serial, port: str) -> Optional[DeviceInfo]:
        """Query device info with proper framing."""
        parser = FrameParser()
        ser.write(Packets.get_info())
        ser.flush()
        start = time.time()
        while time.time() - start < self.INFO_QUERY_TIMEOUT:
            if ser.in_waiting:
                data = ser.read(ser.in_waiting)
                for packet in parser.feed(data):
                    if packet and packet.command == Command.GET_INFO:
                        parts = packet.payload.split(b"\0")
                        device_id = parts[0].decode() if parts else "UNKNOWN"
                        firmware = parts[1].decode() if len(parts) > 1 else "1.0"
                        return DeviceInfo(port, device_id, firmware, [], time.time())
            time.sleep(0.01)
        return None

    # ─────────────────────────────────────────────────────────────
    # RX Reader Thread (Blocking Read + State Machine Parser)
    # ─────────────────────────────────────────────────────────────

    def _reader_loop(self, port: str) -> None:
        """RX thread: blocking read + frame parser. No locks held."""
        with self._ports_lock:
            ps = self._ports.get(port)
            if not ps or not ps.ser:
                return
            ser = ps.ser
            parser = self._frame_parsers.get(port, FrameParser())

        log.debug(f"Reader started for {port}")
        try:
            while not ps.stop_event.is_set():
                try:
                    # Blocking read with timeout
                    data = ser.read(1)  # Read first byte
                    if not data:
                        continue
                    
                    # Read rest of available data
                    if ser.in_waiting:
                        data += ser.read(ser.in_waiting)
                    
                    # Feed to frame parser
                    for packet in parser.feed(data):
                        if packet:
                            ps.last_activity = time.time()
                            # Emit WITHOUT lock
                            self._emit("data", port, packet)
                    
                except serial.SerialException as e:
                    log.warning(f"Serial error on {port}: {e}")
                    break
                except Exception as e:
                    log.error(f"Reader error ({port}): {e}")
                    break
        finally:
            # Schedule disconnect OUTSIDE any lock
            self._schedule_disconnect(port)

    # ─────────────────────────────────────────────────────────────
    # TX Writer Thread (Queue Consumer)
    # ─────────────────────────────────────────────────────────────

    def _writer_loop(self, port: str) -> None:
        """TX thread: consumes from write_queue, writes to serial."""
        with self._ports_lock:
            ps = self._ports.get(port)
            if not ps or not ps.ser:
                return
            ser = ps.ser

        log.debug(f"Writer started for {port}")
        coalesce_buffer: List[Packet] = []
        last_flush = time.time()

        try:
            while not ps.stop_event.is_set():
                try:
                    # Wait for packet with timeout
                    packet = ps.write_queue.get(timeout=0.01)
                    
                    # Coalesce consecutive MOUSE_MOVE packets
                    if packet.command == Command.MOUSE_MOVE:
                        coalesce_buffer.append(packet)
                        # Flush if window exceeded or queue empty
                        now = time.time()
                        if (now - last_flush) * 1000 >= self.COALESCE_WINDOW_MS or ps.write_queue.empty():
                            if coalesce_buffer:
                                self._write_coalesced_moves(ser, coalesce_buffer)
                                coalesce_buffer.clear()
                            last_flush = now
                        continue
                    
                    # Flush any pending moves before other commands
                    if coalesce_buffer:
                        self._write_coalesced_moves(ser, coalesce_buffer)
                        coalesce_buffer.clear()
                    
                    # Write packet
                    ser.write(packet.encode())
                    
                except queue.Empty:
                    continue
                except serial.SerialException as e:
                    log.warning(f"Serial write error on {port}: {e}")
                    break
                except Exception as e:
                    log.error(f"Writer error ({port}): {e}")
                    break
        finally:
            # Flush any remaining moves
            if coalesce_buffer and ps.ser and ps.ser.is_open:
                try:
                    self._write_coalesced_moves(ps.ser, coalesce_buffer)
                except Exception:
                    pass
            # Schedule disconnect
            self._schedule_disconnect(port)

    def _write_coalesced_moves(self, ser: serial.Serial, moves: List[Packet]) -> None:
        """Write coalesced mouse moves as a single batch if possible, else sequentially."""
        if len(moves) == 1:
            ser.write(moves[0].encode())
            return
        
        # For now, write sequentially. Could optimize with batch protocol later.
        for m in moves:
            ser.write(m.encode())

    # ─────────────────────────────────────────────────────────────
    # Public Send API
    # ─────────────────────────────────────────────────────────────

    def send(self, port: str, packet: Packet) -> bool:
        """Non-blocking send. Returns False if queue full or port disconnected."""
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
        """Send raw bytes (bypasses packet encoding)."""
        with self._ports_lock:
            ps = self._ports.get(port)
            if not ps or ps.state != ConnectionState.CONNECTED or not ps.ser:
                return False
        
        try:
            ps.ser.write(data)
            return True
        except Exception as e:
            log.error(f"Text send failed ({port}): {e}")
            return False

    # ─────────────────────────────────────────────────────────────
    # Disconnect Handling
    # ─────────────────────────────────────────────────────────────

    def _schedule_disconnect(self, port: str) -> None:
        """Schedule disconnect on main thread via callback."""
        # Use a timer to avoid calling _handle_disconnect from RX/TX threads
        def do_disconnect():
            self._handle_disconnect(port)
        threading.Timer(0, do_disconnect).start()

    def _handle_disconnect(self, port: str) -> None:
        """Handle cleanup. Called from main thread only."""
        with self._ports_lock:
            ps = self._ports.get(port)
            if not ps:
                return
            if ps.state == ConnectionState.DISCONNECTED:
                return
            ps.state = ConnectionState.DISCONNECTING

        # Signal threads to stop
        ps.stop_event.set()

        # Wait for threads to finish (with timeout)
        for t_name, thread in [("reader", ps.reader_thread), ("writer", ps.writer_thread)]:
            if thread and thread.is_alive():
                thread.join(timeout=1.0)
                if thread.is_alive():
                    log.warning(f"{t_name} thread for {port} did not stop in time")

        # Close serial port
        with self._ports_lock:
            if ps.ser:
                try:
                    ps.ser.close()
                except Exception:
                    pass
            ps.ser = None
            ps.info = None
            ps.state = ConnectionState.DISCONNECTED
            ps.write_queue = queue.Queue()  # Clear queue
            self._frame_parsers.pop(port, None)

        log.info(f"Disconnected from {port}")
        self._emit("disconnected", port)

    def disconnect(self, port: str) -> None:
        """Public disconnect. Schedules cleanup."""
        self._schedule_disconnect(port)

    def disconnect_all(self) -> None:
        with self._ports_lock:
            ports = list(self._ports.keys())
        for port in ports:
            self.disconnect(port)

    # ─────────────────────────────────────────────────────────────
    # Status Queries
    # ─────────────────────────────────────────────────────────────

    def get_device_id(self, port: str) -> Optional[str]:
        with self._ports_lock:
            ps = self._ports.get(port)
            return ps.info.device_id if ps and ps.info else None

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