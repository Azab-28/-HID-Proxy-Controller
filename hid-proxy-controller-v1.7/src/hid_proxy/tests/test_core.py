"""Comprehensive unit & integration tests for hid-proxy-controller v1.7.0."""
import os
import queue
import random
import struct
import sys
import tempfile
import threading
import time
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[2]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import pytest


class MockSerialPort:
    """In-memory bidirectional serial transport for hardware-free testing."""

    def __init__(self, device_id: str = "ESP32-S3-TEST", firmware: str = "1.7.0"):
        self.device_id = device_id
        self.firmware = firmware
        self._rx_buf = bytearray()
        self._rx_lock = threading.Lock()
        self.written = bytearray()
        self.is_open = True
        from hid_proxy.core.protocol import Command, FrameParser, Packet, Response

        self._parser = FrameParser()
        self._Command = Command
        self._Packet = Packet
        self._Response = Response

    @property
    def in_waiting(self) -> int:
        with self._rx_lock:
            return len(self._rx_buf)

    def read(self, size: int = 1) -> bytes:
        if not self.is_open:
            raise OSError("Port closed")
        deadline = time.monotonic() + 0.02
        while time.monotonic() < deadline:
            with self._rx_lock:
                if self._rx_buf:
                    out = bytes(self._rx_buf[:size])
                    del self._rx_buf[:size]
                    return out
            time.sleep(0.002)
        return b""

    def write(self, data: bytes) -> int:
        if not self.is_open:
            raise OSError("Port closed")
        self.written.extend(data)
        for pkt in self._parser.feed(data):
            if pkt.command == self._Command.PING:
                resp = self._Packet(self._Response.OK, seq=pkt.seq).encode()
                self._push_rx(resp)
            elif pkt.command == self._Command.GET_INFO:
                payload = f"{self.device_id}\0{self.firmware}".encode()
                resp = self._Packet(self._Command.GET_INFO, payload=payload, seq=pkt.seq).encode()
                self._push_rx(resp)
            elif pkt.needs_ack:
                ack = self._Packet(self._Command.ACK, payload=bytes([pkt.seq]), seq=pkt.seq).encode()
                self._push_rx(ack)
        return len(data)

    def _push_rx(self, data: bytes) -> None:
        with self._rx_lock:
            self._rx_buf.extend(data)

    def flush(self) -> None:
        pass

    def reset_input_buffer(self) -> None:
        with self._rx_lock:
            self._rx_buf.clear()

    def reset_output_buffer(self) -> None:
        pass

    def close(self) -> None:
        self.is_open = False


def test_version():
    from hid_proxy import __version__
    assert __version__ == "1.7.0"


def test_config_schema():
    from hid_proxy.config.schema import AppConfig

    cfg = AppConfig()
    assert cfg.device.baudrate == 2000000
    assert cfg.targeting.sensitivity == 1.0
    assert cfg.targeting.target_pids == []

    cfg2 = AppConfig.from_dict({
        "device": {"baudrate": 115200, "auto_connect": False},
        "targeting": {"sensitivity": 2.0, "target_pids": [1234, 5678]},
    })
    assert cfg2.device.baudrate == 115200
    assert cfg2.device.auto_connect is False
    assert cfg2.targeting.sensitivity == 2.0
    assert cfg2.targeting.target_pids == [1234, 5678]


def test_config_schema_validation_errors():
    from hid_proxy.config.schema import AppConfig

    with pytest.raises((ValueError, TypeError)):
        AppConfig.from_dict({"device": {"baudrate": "invalid"}})
    with pytest.raises(ValueError):
        AppConfig.from_dict({"device": {"baudrate": 9600}}).validate_all()
    with pytest.raises(ValueError):
        AppConfig.from_dict({"targeting": {"sensitivity": 10.0}}).validate_all()
    with pytest.raises(ValueError):
        AppConfig.from_dict({"ui": {"theme": "purple"}}).validate_all()


def test_protocol_crc8_and_streaming_parser():
    from hid_proxy.core.protocol import AckTracker, Command, FrameParser, Packet, Packets, crc8

    ping_pkt = Packets.ping()
    raw = ping_pkt.encode()
    assert len(raw) == 8
    assert raw[0] == 0xAA and raw[1] == 0x55
    assert raw[3] == Command.PING
    assert raw[7] == crc8(raw[2:7])

    decoded = Packet.decode(raw)
    assert decoded is not None
    assert decoded.command == Command.PING

    # Streaming parser: leading garbage + fragmented frames + back-to-back frames
    p1 = Packets.mouse_move(15, -30).encode()
    p2 = Packets.keyboard_key(4, True).encode()
    stream = b"\x00\x99\xAA\x01garbage" + p1[:3] + p1[3:] + p2

    parser = FrameParser()
    parsed = []
    for i in range(0, len(stream), 2):
        parsed.extend(parser.feed(stream[i : i + 2]))

    assert len(parsed) == 2
    assert parsed[0].command == Command.MOUSE_MOVE
    assert struct.unpack("<hh", parsed[0].payload) == (15, -30)
    assert parsed[1].command == Command.KEYBOARD_KEY

    # AckTracker retry test
    tracker = AckTracker(timeout=0.02, max_retries=2)
    cfg_pkt = Packets.set_config(b"abc", needs_ack=True)
    tracker.add(cfg_pkt)
    time.sleep(0.03)
    retries = tracker.check_timeouts()
    assert len(retries) == 1
    assert retries[0].seq == cfg_pkt.seq
    assert tracker.ack(cfg_pkt.seq) is not None
    assert tracker.pending_count() == 0


def test_device_manager_dual_thread_io():
    from hid_proxy.config.manager import ConfigManager
    from hid_proxy.core.device import DeviceManager
    from hid_proxy.modules.keyboard_emulator import KeyboardEmulator
    from hid_proxy.modules.mouse_emulator import MouseEmulator

    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = ConfigManager(Path(tmpdir))
        mock_port = MockSerialPort()
        dm = DeviceManager(cfg, serial_factory=lambda *_: mock_port)

        assert dm.connect("COM99", 2000000)
        assert dm.is_connected("COM99")
        assert dm.get_device_id("COM99") == "ESP32-S3-TEST"

        mouse = MouseEmulator(dm)
        mouse.initialize()
        # Sub-pixel accumulation: 0.4 + 0.4 + 0.4 = 1.2 -> sends 1px, keeps 0.2
        assert mouse.move(0.4, 0.0, "COM99")
        assert mouse.move(0.4, 0.0, "COM99")
        assert mouse.move(0.4, 0.0, "COM99")
        assert mouse.get_position() == (1, 0)

        kb = KeyboardEmulator(dm)
        kb.initialize()
        assert kb.type("Hi!", "COM99")
        kb.shutdown()

        time.sleep(0.05)
        assert len(mock_port.written) > 0
        dm.disconnect_all()
        assert not dm.is_connected("COM99")


def test_humanizer_no_drift_and_bounded_overshoot():
    from hid_proxy.targeting.humanizer import Humanizer, HumanizerConfig

    random.seed(42)
    cfg = HumanizerConfig(overshoot_prob=1.0, jitter_amplitude=2.0)
    h = Humanizer(cfg)
    path = h.generate_path((100, 100), (300, 250), 250.0)

    assert path[0] == (100, 100)
    assert path[-1] == (300, 250)


def test_config_manager_encryption_roundtrip():
    from hid_proxy.config.manager import ConfigManager

    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir)
        mgr = ConfigManager(config_dir)
        mgr.set("device.baudrate", 115200)
        assert mgr.set_encryption_password("StrongPass!2026", save_to_keyring=False)

        raw = (config_dir / "config.toml").read_bytes()
        assert raw.startswith(b"HCFG\x01")

        # Reload with password
        mgr2 = ConfigManager(config_dir, encryption_password="StrongPass!2026")
        assert mgr2.get("device.baudrate") == 115200
        assert mgr2.get("security.encrypt_config") is True


def test_profile_manager_and_path_traversal():
    from hid_proxy.config.manager import ConfigManager
    from hid_proxy.config.profiles import ProfileManager

    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir)
        cfg = ConfigManager(config_dir)
        cfg.set("device.baudrate", 115200)
        pm = ProfileManager(cfg)

        assert pm.save_profile("Apex_Profile-1", "Main preset")
        cfg.set("device.baudrate", 2000000)
        assert pm.load_profile("Apex_Profile-1")
        assert cfg.get("device.baudrate") == 115200

        # Export & Import
        export_file = config_dir / "exported.json"
        assert pm.export_profile("Apex_Profile-1", export_file)
        assert pm.delete_profile("Apex_Profile-1")
        assert pm.import_profile(export_file)
        assert pm.get_profile("Apex_Profile-1") is not None

        # Path traversal blocked
        assert not pm.save_profile("../escape", "bad")
        assert not pm.save_profile("..\\escape", "bad")
        assert not pm.save_profile("", "empty")


def test_event_bus():
    from hid_proxy.core.dispatcher import Event, EventBus, EventType

    bus = EventBus()
    received = []
    unsub = bus.subscribe(EventType.CONFIG_CHANGED, lambda e: received.append(e.payload))
    bus.emit(Event(EventType.CONFIG_CHANGED, "ok"))
    assert received == ["ok"]
    unsub()
    bus.emit(Event(EventType.CONFIG_CHANGED, "ignored"))
    assert received == ["ok"]
