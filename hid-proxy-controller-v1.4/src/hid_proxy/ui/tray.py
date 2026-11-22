"""System tray icon implementation using pystray."""
import threading
from pathlib import Path
from typing import Callable, Optional

import pystray
from PIL import Image, ImageDraw

from hid_proxy.utils.logging import get_logger

log = get_logger(__name__)


class SystemTray:
    """System tray icon manager with menu."""

    def __init__(self, app):
        self.app = app
        self._icon: Optional[pystray.Icon] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def _create_icon_image(self) -> Image.Image:
        """Create a simple tray icon image."""
        size = 64
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # Draw a simple HID-like icon: rectangle with USB symbol
        margin = 8
        draw.rounded_rectangle(
            [margin, margin, size - margin, size - margin],
            radius=8,
            fill=(0, 120, 212, 255),
            outline=(255, 255, 255, 255),
            width=2
        )
        # Draw "H" in center
        draw.text((size // 2 - 6, size // 2 - 10), "H", fill=(255, 255, 255, 255))
        return img

    def _create_menu(self) -> pystray.Menu:
        """Create the tray context menu."""
        return pystray.Menu(
            pystray.MenuItem("Show Settings", self._on_show_settings, default=True),
            pystray.MenuItem("Profiles", self._on_show_profiles),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Auto-connect",
                self._on_toggle_autoconnect,
                checked=lambda _: self.app.config.get("device.auto_connect", True)
            ),
            pystray.MenuItem(
                "Auto-start",
                self._on_toggle_autostart,
                checked=lambda _: self.app.autostart.is_enabled()
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", self._on_exit)
        )

    def _on_show_settings(self):
        from hid_proxy.ui.settings import SettingsWindow
        if not hasattr(self.app, '_settings_window') or self.app._settings_window is None:
            self.app._settings_window = SettingsWindow(self.app)
        self.app._settings_window.show()
        self.app._settings_window.raise_()
        self.app._settings_window.activateWindow()

    def _on_show_profiles(self):
        from hid_proxy.ui.profiles import ProfilesWindow
        if not hasattr(self.app, '_profiles_window') or self.app._profiles_window is None:
            self.app._profiles_window = ProfilesWindow(self.app)
        self.app._profiles_window.show()
        self.app._profiles_window.raise_()
        self.app._profiles_window.activateWindow()

    def _on_toggle_autoconnect(self):
        current = self.app.config.get("device.auto_connect", True)
        self.app.config.set("device.auto_connect", not current)
        self._update_tooltip()

    def _on_toggle_autostart(self):
        if self.app.autostart.is_enabled():
            self.app.autostart.disable()
        else:
            self.app.autostart.enable()
        self._update_tooltip()

    def _on_exit(self):
        self.app.shutdown()
        self.hide()

    def _update_tooltip(self):
        status = []
        if self.app.config.get("device.auto_connect", True):
            status.append("Auto-connect: ON")
        if self.app.autostart.is_enabled():
            status.append("Auto-start: ON")
        ports = self.app.device_manager.get_connected_ports()
        if ports:
            status.append(f"Connected: {', '.join(ports)}")
        else:
            status.append("No device")
        tooltip = "HID Proxy Controller\n" + "\n".join(status)
        if self._icon:
            self._icon.title = tooltip

    def show(self):
        """Show the tray icon."""
        if self._running:
            return
        self._running = True
        self._icon = pystray.Icon(
            "HIDProxyController",
            self._create_icon_image(),
            "HID Proxy Controller",
            self._create_menu()
        )
        self._thread = threading.Thread(target=self._icon.run, daemon=True, name="HID-Tray")
        self._thread.start()
        log.info("System tray started")
        # Update tooltip after a short delay
        threading.Timer(0.5, self._update_tooltip).start()

    def hide(self):
        """Hide the tray icon."""
        if self._icon:
            self._icon.stop()
            self._icon = None
        self._running = False
        log.info("System tray stopped")

    def set_tooltip(self, text: str):
        """Set tooltip text."""
        if self._icon:
            self._icon.title = text