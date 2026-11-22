"""Unit tests for hid-proxy-controller."""
import sys
import tempfile
import os
import threading
from pathlib import Path

# Add src to path (test file is at src/hid_proxy/tests/test_core.py, so parent.parent.parent = project root)
SRC_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(SRC_ROOT))

import pytest


def test_version():
    """Test package version is accessible."""
    from hid_proxy import __version__
    assert __version__ == "1.3.0"


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


def test_config_schema_validation_errors():
    """Test schema rejects invalid values."""
    from hid_proxy.config.schema import AppConfig

    # Invalid baudrate type
    with pytest.raises((ValueError, TypeError)):
        AppConfig.from_dict({"device": {"baudrate": "invalid"}})

    # Invalid baudrate value
    with pytest.raises(ValueError):
        AppConfig.from_dict({"device": {"baudrate": 9600}})

    # Invalid sensitivity
    with pytest.raises(ValueError):
        AppConfig.from_dict({"targeting": {"sensitivity": 10.0}})

    # Invalid theme
    with pytest.raises(ValueError):
        AppConfig.from_dict({"ui": {"theme": "purple"}})

    # Encryption enabled but no password
    with pytest.raises(ValueError):
        AppConfig.from_dict({"security": {"encrypt_config": True, "encryption_password": ""}})


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


def test_humanizer_path_generation_deterministic():
    """Test humanizer generates valid paths with fixed seed."""
    from hid_proxy.targeting.humanizer import HumanizerConfig
    from hid_proxy.targeting.detector import Humanizer
    import random

    # Use fixed seed for reproducibility
    random.seed(42)

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

    # Test pause probability with fixed seed
    random.seed(123)
    pauses = sum(1 for _ in range(1000) if humanizer.should_pause())
    # ~2% pause probability, with fixed seed should be consistent
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

        # Test get_all returns DEEP copy
        all_cfg = mgr.get_all()
        all_cfg["device"]["baudrate"] = 9999
        # Original should be unchanged (deep copy)
        assert mgr.get("device.baudrate") == 115200


def test_config_manager_encryption():
    """Test ConfigManager encryption round-trip with environment variable password."""
    from hid_proxy.config.manager import ConfigManager
    import tempfile
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir)
        
        # Set password via environment variable (simulates user input)
        os.environ["HIDPROXY_ENCRYPTION_PASSWORD"] = "test_password_123"
        try:
            # Create manager with encryption
            mgr = ConfigManager(config_dir)
            mgr.set("device.baudrate", 115200)
            mgr.set("security.encrypt_config", True)
            # This should trigger encryption
            assert mgr.save()
            
            # Verify file is encrypted (not plain TOML)
            config_bytes = config_dir.joinpath("config.toml").read_bytes()
            # Encrypted data starts with 12-byte nonce, not "device"
            assert not config_bytes.startswith(b"device")
            assert len(config_bytes) > 12  # nonce + ciphertext

            # Create new manager instance, should decrypt via env var
            mgr2 = ConfigManager(config_dir)
            assert mgr2.get("device.baudrate") == 115200
            # encryption_password should NOT be in config (never stored)
            assert "encryption_password" not in mgr2.get_all().get("security", {})
        finally:
            os.environ.pop("HIDPROXY_ENCRYPTION_PASSWORD", None)


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


def test_keyboard_emulator_modifiers():
    """Test keyboard emulator modifier handling."""
    from hid_proxy.modules.keyboard_emulator import KeyboardEmulator, MOD_LEFT_SHIFT
    from hid_proxy.modules.base import BaseModule

    class MockDeviceManager:
        def send(self, port, packet):
            return True
        def get_connected_ports(self):
            return ["COM1"]

    # Create emulator with mocked device manager
    emulator = KeyboardEmulator(MockDeviceManager())
    emulator.initialize()

    # Test shift + key
    assert emulator._type_char('A', "")  # Uppercase needs shift
    assert emulator._type_char('a', "")  # Lowercase no shift
    assert emulator._type_char('1', "")  # Number no shift
    assert emulator._type_char('!', "")  # Symbol needs shift

    emulator.shutdown()


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


def test_device_manager_has_locks():
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
        assert isinstance(dm._lock, type(threading.Lock()))


def test_connection_monitor_has_backoff():
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
        assert monitor._base_reconnect_delay == 1.0
        assert monitor._max_reconnect_delay == 60.0


def test_profile_manager():
    """Test ProfileManager save/load."""
    from hid_proxy.config.manager import ConfigManager
    from hid_proxy.config.profiles import ProfileManager
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir)
        config = ConfigManager(config_dir)
        config.set("device.baudrate", 115200)
        
        pm = ProfileManager(config)
        
        # Save profile
        assert pm.save_profile("test_profile", "Test description")
        
        # List profiles
        profiles = pm.list_profiles()
        assert len(profiles) == 1
        assert profiles[0]["name"] == "test_profile"
        
        # Modify config
        config.set("device.baudrate", 2000000)
        
        # Load profile
        assert pm.load_profile("test_profile")
        assert config.get("device.baudrate") == 115200
        
        # Delete profile
        assert pm.delete_profile("test_profile")
        assert len(pm.list_profiles()) == 0


def test_profile_manager_path_traversal():
    """Test ProfileManager rejects path traversal attempts."""
    from hid_proxy.config.manager import ConfigManager
    from hid_proxy.config.profiles import ProfileManager
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir)
        config = ConfigManager(config_dir)
        pm = ProfileManager(config)
        
        # These should all fail
        assert not pm.save_profile("../escape", "bad")
        assert not pm.save_profile("..\\escape", "bad")
        assert not pm.save_profile("sub/../escape", "bad")
        assert not pm.save_profile("", "empty")
        assert not pm.save_profile("a" * 100, "too long")
        
        # Valid names should work
        assert pm.save_profile("valid_name", "ok")
        assert pm.save_profile("Valid Name-123", "ok")


def test_app_request_shutdown():
    """Test Application.request_shutdown exists."""
    from hid_proxy.app import Application
    import inspect
    
    assert hasattr(Application, 'request_shutdown')
    assert callable(getattr(Application, 'request_shutdown'))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])