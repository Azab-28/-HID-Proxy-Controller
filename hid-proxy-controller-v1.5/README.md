# HID Proxy Controller

**Human Interface Device Proxy Controller for Embedded Devices**

A Windows desktop application (PySide6) that proxies HID input (mouse/keyboard) via ESP32 over serial. Features humanized mouse movement paths, target detection/prediction, and game automation capabilities.

## Features

- **Serial Communication**: Binary protocol with checksum for reliable ESP32 communication
- **Mouse Emulation**: Move, click, wheel with humanized Bezier paths + noise
- **Keyboard Emulation**: Full key support including modifiers (Ctrl/Shift/Alt/Gui), hotkeys, text typing
- **Humanizer**: Anti-detection mouse paths with fatigue, jitter, overshoot/correction
- **Targeting**: Target detection with priority (closest/head), movement prediction
- **Profiles**: Save/load/export/import configuration profiles
- **System Tray**: Background operation with context menu
- **Auto-start**: Windows Registry integration
- **Encryption**: AES-GCM config/profile encryption with PBKDF2 key derivation
- **Single Instance**: Mutex-based single instance enforcement

## Architecture

```
src/hid_proxy/
├── config/          # Configuration management (TOML, profiles, schema validation)
├── core/            # Device manager, protocol, dispatcher, connection monitor
├── modules/         # Plugin-style modules (mouse, keyboard, composite)
├── targeting/       # Humanizer, target detector, predictor
├── ui/              # PySide6 UI (tray, settings, profiles, targets)
├── system/          # Windows integration (autostart, process enum, validation)
├── utils/           # Crypto, logging, helpers
└── tests/           # Unit tests
```

## Requirements

- Python 3.11+
- Windows 10/11 (uses `pywin32`, Windows Registry, mutex)
- ESP32 device with compatible firmware (VID/PID: Espressif, CH343, CP210x)

## Installation

### Development

```bash
# Clone and install in development mode
git clone <repo>
cd hid-proxy-controller
pip install -e .[dev]  # Includes pytest, ruff, mypy

# Or install with computer vision extras
pip install -e .[cv]   # Includes opencv, ultralytics, dxcam
```

### Build Standalone Executable

```bash
# Requires Nuitka
pip install nuitka
python -m nuitka --standalone --follow-imports \
  --enable-plugin=pyside6 --enable-plugin=numpy --enable-plugin=cryptography \
  --output-dir=dist --onefile --windows-disable-console \
  --windows-icon-from-ico=src/hid_proxy/ui/resources/icons/tray_idle.ico \
  --include-package-data=hid_proxy.ui.resources \
  src/hid_proxy/__main__.py
```

### NSIS Installer

```bash
# Requires NSIS (makensis)
makensis build/installer.nsi
```

## Usage

```bash
# Run from source
python -m hid_proxy

# Or installed entry point
hid-proxy
```

The application runs in the system tray. Right-click the tray icon for:
- **Show Settings** — Configure device, targeting, UI
- **Profiles** — Save/load/export/import profiles
- **Auto-connect** — Toggle automatic ESP32 connection
- **Auto-start** — Toggle Windows startup registration
- **Exit** — Graceful shutdown

## Configuration

Config stored at:
- **Windows**: `%LOCALAPPDATA%\HIDProxyController\config.toml`
- **Linux/macOS**: `~/.config/HIDProxyController/config.toml` (via `platformdirs`)

Key settings:
```toml
[device]
baudrate = 2000000
auto_connect = true
preferred_port = ""

[targeting]
sensitivity = 1.0
smoothing = 0.35
deadzone = 4
jitter = 1.5
curve = "bezier"
priority = "closest"
fov = 300

[ui]
theme = "dark"
minimize_to_tray = true
show_notifications = true

[security]
encrypt_config = true
encryption_password = ""  # Set in Settings UI
```

## Encryption

When `encryption_password` is set in Settings:
- Config and profiles are encrypted with AES-GCM
- Key derived via PBKDF2 (200,000 iterations) from password + per-user salt
- Salt stored at `%LOCALAPPDATA%\HIDProxyController\salt.bin`
- **Without the password, data cannot be decrypted** — no backdoors, no hardcoded keys

## Testing

```bash
# Run unit tests
pytest src/hid_proxy/tests/ -v

# Lint
ruff src/hid_proxy/

# Type check
mypy src/hid_proxy/
```

## Protocol

Binary frame: `[0xAA, 0x55, CMD, LEN_LO, LEN_HI, PAYLOAD..., CHECKSUM]`

Commands (host→device):
- `0x01` PING
- `0x02` GET_INFO
- `0x10` GET_CONFIG
- `0x11` SET_CONFIG
- `0x20` MOUSE_MOVE (dx, dy)
- `0x21` MOUSE_BUTTON (button, pressed)
- `0x23` KEYBOARD_KEY (keycode, pressed)
- `0x24` KEYBOARD_MOD (modifiers bitmask)
- `0x30` MODULE_ENABLE

Responses (device→host):
- `0x00` OK
- `0x01` ERROR
- `0x02` INVALID_CMD
- `0x03` INVALID_PARAM
- `0x05` CHECKSUM_FAIL

## Project Structure

```
hid-proxy-controller/
├── build/
│   ├── installer.nsi       # NSIS installer script
│   └── nuitka.build.py     # Nuitka build script
├── src/hid_proxy/          # Main package
├── tests/                  # Unit tests (in src/hid_proxy/tests/)
├── pyproject.toml          # Project metadata, deps, build config
├── requirements.txt        # Pip requirements (synced with pyproject.toml)
└── README.md               # This file
```

## License

MIT License — see LICENSE file.

## Author

Ahmed — djmido27@gmail.com