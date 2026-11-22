# HID Proxy Controller v1.7.0 (First Stable Release)

Windows desktop application (`PySide6`) for proxying mouse and keyboard HID commands to an ESP32 over high-speed binary serial (`CRC-8`), featuring dual-thread non-blocking I/O, sub-pixel mouse accumulation, humanized Bezier trajectories, encrypted TOML configuration (`AES-256-GCM`), and native Qt system tray integration.

## Quick Start

```bash
python -m venv venv
venv\Scripts\activate
pip install -e .[dev]

# Run test suite
pytest -v

# Start application
python -m hid_proxy
```

## Build Standalone & Installer

```bash
python build/nuitka.build.py
makensis build/installer.nsi
```
