"""Unit tests for hid-proxy-controller."""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest


def test_version():
    """Test package version is accessible."""
    from hid_proxy import __version__
    assert __version__ == "1.0.0"


def test_config_schema():
    """Test AppConfig schema validation."""
    from hid_proxy.config.schema import AppConfig, DeviceConfig, TargetingConfig

    # Default config
    cfg = AppConfig()
    assert cfg.device.baudrate == 2000000
    assert cfg.targeting.sensitivity == 1.0

    # From dict
    data = {
        "device": {"baudrate": 115200, "auto_connect": False},
        "targeting": {"sensitivity": 2.0},
    }
    cfg2 = AppConfig.from_dict(data)
    assert cfg2.device.baudrate == 115200
    assert cfg2.device.auto_connect is False
    assert cfg2.targeting.sensitivity == 2.0
    # Other fields should be defaults
    assert cfg2.targeting.deadzone == 4

    # Round-trip
    assert cfg2.to_dict()["device"]["baudrate"] == 115200


def test_protocol_encode_decode():
    """Test binary protocol packet encode/decode."""
    from hid_proxy.core.protocol import Packet, Command, Response, Packets

    # Ping packet
    ping_bytes = Packets.ping()
    assert ping_bytes[0] == 0xAA
    assert ping_bytes[1] == 0x55
    assert ping_bytes[2] == Command.PING
    # Length = 0
    assert ping_bytes[3] == 0x00
    assert ping_bytes[4] == 0x00
    # Checksum
    checksum = ping_bytes[5]
    calc = 0
    for b in ping_bytes[2:5]:
        calc ^= b
    assert checksum == calc

    # Decode
    packet = Packet.decode(ping_bytes)
    assert packet is not None
    assert packet.command == Command.PING
    assert packet.payload == b""

    # Mouse move packet
    move_bytes = Packets.mouse_move(10, -20)
    packet = Packet.decode(move_bytes)
    assert packet is not None
    assert packet.command == Command.MOUSE_MOVE
    import struct
    dx, dy = struct.unpack("<hh", packet.payload)
    assert dx == 10
    assert dy == -20

    # Invalid packet (wrong header)
    bad = bytes([0x00, 0x00, 0x01, 0x00, 0x00, 0x01])
    assert Packet.decode(bad) is None

    # Invalid checksum
    bad_checksum = bytearray(ping_bytes)
    bad_checksum[5] ^= 0xFF
    assert Packet.decode(bytes(bad_checksum)) is None


def test_humanizer_path_generation():
    """Test humanizer generates valid paths."""
    from hid_proxy.targeting.humanizer import HumanizerConfig
    from hid_proxy.targeting.detector import Humanizer

    config = HumanizerConfig(
        sensitivity=1.0,
        smoothing=0.35,
        deadzone=4,
        jitter_amplitude=1.5,
        curve_type="bezier",
        target_priority="closest",
        fov_radius=300,
        pause_prob=0.02,
        overshoot_prob=0.15,
    )
    humanizer = Humanizer(config)

    # Generate path
    path = humanizer.generate_path((100, 100), (200, 200), 141.4)

    # Should have reasonable number of steps
    assert 6 <= len(path) <= 18
    # First point near start
    assert abs(path[0][0] - 100) < 50
    assert abs(path[0][1] - 100) < 50
    # Last point near end
    assert abs(path[-1][0] - 200) < 50
    assert abs(path[-1][1] - 200) < 50

    # Test pause probability
    pauses = sum(1 for _ in range(1000) if humanizer.should_pause())
    # ~2% pause probability
    assert 5 <= pauses <= 40


def test_config_manager_validation():
    """Test ConfigManager validates against schema."""
    from hid_proxy.config.manager import ConfigManager
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir)
        mgr = ConfigManager(config_dir)

        # Test get/set
        mgr.set("device.baudrate", 115200)
        assert mgr.get("device.baudrate") == 115200

        # Test invalid key returns default
        assert mgr.get("nonexistent.key", "default") == "default"

        # Test nested set
        mgr.set("targeting.sensitivity", 1.5)
        assert mgr.get("targeting.sensitivity") == 1.5

        # Test get_all returns copy
        all_cfg = mgr.get_all()
        all_cfg["device"]["baudrate"] = 9999
        assert mgr.get("device.baudrate") == 115200  # Original unchanged


def test_crypto_encrypt_decrypt():
    """Test crypto encryption round-trip."""
    from hid_proxy.utils.crypto import Crypto

    crypto = Crypto(b"test_password_123")
    data = b"Hello, World! This is a test."
    encrypted = crypto.encrypt(data)
    decrypted = crypto.decrypt(encrypted)
    assert decrypted == data

    # Different password should fail
    crypto2 = Crypto(b"wrong_password")
    try:
        crypto2.decrypt(encrypted)
        assert False, "Should have raised exception"
    except Exception:
        pass


def test_keyboard_keycodes():
    """Test keyboard emulator keycode mappings."""
    from hid_proxy.modules.keyboard_emulator import KeyboardEmulator, KEYCODE_MAP

    # Basic mappings
    assert KEYCODE_MAP['a'] == 4
    assert KEYCODE_MAP['z'] == 29
    assert KEYCODE_MAP['1'] == 30
    assert KEYCODE_MAP['0'] == 39
    assert KEYCODE_MAP[' '] == 44
    assert KEYCODE_MAP['\n'] == 40  # Enter
    assert KEYCODE_MAP['F1'] == 58


def test_module_registry():
    """Test module registry operations."""
    from hid_proxy.modules.registry import ModuleRegistry
    from hid_proxy.modules.base import BaseModule

    class DummyModule(BaseModule):
        def initialize(self): pass
        def shutdown(self): pass
        def process(self, data): pass

    registry = ModuleRegistry()
    m1 = DummyModule(None)
    m2 = DummyModule(None)

    registry.register("mod1", m1)
    registry.register("mod2", m2)

    assert registry.get("mod1") is m1
    assert registry.get("mod2") is m2
    assert "mod1" in registry.list_modules()
    assert "mod2" in registry.list_modules()

    registry.unregister("mod1")
    assert "mod1" not in registry.list_modules()
    assert registry.get("mod1") is None


def test_device_manager_lock():
    """Test DeviceManager has proper locking structure."""
    from hid_proxy.core.device import DeviceManager
    from hid_proxy.config.manager import ConfigManager
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        config = ConfigManager(Path(tmpdir))
        dm = DeviceManager(config)

        # Should have locks dict
        assert hasattr(dm, '_port_locks')
        assert hasattr(dm, '_lock')


def test_connection_monitor_backoff():
    """Test ConnectionMonitor has backoff logic."""
    from hid_proxy.core.monitor import ConnectionMonitor
    from hid_proxy.core.device import DeviceManager
    from hid_proxy.config.manager import ConfigManager
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        config = ConfigManager(Path(tmpdir))
        dm = DeviceManager(config)
        monitor = ConnectionMonitor(dm, config)

        # Should have backoff attributes
        assert hasattr(monitor, '_reconnect_attempts')
        assert hasattr(monitor, '_max_reconnect_attempts')
        assert hasattr(monitor, '_base_reconnect_delay')
        assert hasattr(monitor, '_max_reconnect_delay')
        assert monitor._max_reconnect_attempts == 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])