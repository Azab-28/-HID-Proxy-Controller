"""System tray icon implementation using QSystemTrayIcon (Qt native).

This replaces the pystray-based implementation to ensure thread-safety
(all UI operations on main thread).
"""
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import QSystemTrayIcon, QMenu, QApplication
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont
from PySide6.QtCore import QTimer, Qt, Slot

from hid_proxy.utils.logging import get_logger

log = get_logger(__name__)


class SystemTray(QSystemTrayIcon):
    """System tray icon manager using Qt's native QSystemTrayIcon."""

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setToolTip("HID Proxy Controller")
        
        # Create icon
        self._icon_pixmap = self._create_icon_pixmap()
        self.setIcon(QIcon(self._icon_pixmap))
        
        # Create context menu
        self._menu = self._create_menu()
        self.setContextMenu(self._menu)
        
        # Connect signals
        self.activated.connect(self._on_activated)
        
        # Tooltip update timer
        self._tooltip_timer = QTimer()
        self._tooltip_timer.setSingleShot(True)
        self._tooltip_timer.timeout.connect(self._update_tooltip)
        self._tooltip_timer.start(500)  # Initial update

    def _create_icon_pixmap(self) -> QPixmap:
        """Create tray icon pixmap."""
        size = 32
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Background circle
        margin = 2
        painter.setBrush(QColor(0, 120, 212))
        painter.setPen(QColor(255, 255, 255))
        painter.drawRoundedRect(margin, margin, size - 2*margin, size - 2*margin, 6, 6)
        
        # "H" letter
        painter.setPen(QColor(255, 255, 255))
        font = QFont("Arial", 14, QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "H")
        
        painter.end()
        return pixmap

    def _create_menu(self) -> QMenu:
        """Create the tray context menu."""
        menu = QMenu()
        
        # Show Settings
        action_settings = menu.addAction("Show Settings")
        action_settings.triggered.connect(self._on_show_settings)
        
        # Show Targets
        action_targets = menu.addAction("Targets")
        action_targets.triggered.connect(self._on_show_targets)
        
        # Profiles
        action_profiles = menu.addAction("Profiles")
        action_profiles.triggered.connect(self._on_show_profiles)
        
        menu.addSeparator()
        
        # Auto-connect
        self._action_autoconnect = menu.addAction("Auto-connect")
        self._action_autoconnect.setCheckable(True)
        self._action_autoconnect.setChecked(self.app.config.get("device.auto_connect", True))
        self._action_autoconnect.triggered.connect(self._on_toggle_autoconnect)
        
        # Auto-start
        self._action_autostart = menu.addAction("Auto-start")
        self._action_autostart.setCheckable(True)
        self._action_autostart.setChecked(self.app.autostart.is_enabled())
        self._action_autostart.triggered.connect(self._on_toggle_autostart)
        
        menu.addSeparator()
        
        # Exit
        action_exit = menu.addAction("Exit")
        action_exit.triggered.connect(self._on_exit)
        
        return menu

    @Slot()
    def _on_show_settings(self):
        self.app.show_settings()

    @Slot()
    def _on_show_targets(self):
        self.app.show_targets()

    @Slot()
    def _on_show_profiles(self):
        self.app.show_profiles()

    @Slot(bool)
    def _on_toggle_autoconnect(self, checked: bool):
        self.app.config.set("device.auto_connect", checked)
        self._action_autoconnect.setChecked(checked)
        self._schedule_tooltip_update()

    @Slot(bool)
    def _on_toggle_autostart(self, checked: bool):
        if checked:
            self.app.autostart.enable()
        else:
            self.app.autostart.disable()
        self._action_autostart.setChecked(checked)
        self._schedule_tooltip_update()

    @Slot()
    def _on_exit(self):
        self.app.request_shutdown()

    @Slot(QSystemTrayIcon.ActivationReason)
    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._on_show_settings()

    def _schedule_tooltip_update(self):
        """Schedule tooltip update (debounced)."""
        self._tooltip_timer.start(100)

    @Slot()
    def _update_tooltip(self):
        """Update tray tooltip with current status."""
        status_lines = ["HID Proxy Controller"]
        
        if self.app.config.get("device.auto_connect", True):
            status_lines.append("Auto-connect: ON")
        if self.app.autostart.is_enabled():
            status_lines.append("Auto-start: ON")
        
        ports = self.app.device_manager.get_connected_ports()
        if ports:
            status_lines.append(f"Connected: {', '.join(ports)}")
        else:
            status_lines.append("No device")
        
        self.setToolTip("\n".join(status_lines))

    def show(self):
        """Show the tray icon."""
        super().show()
        log.info("System tray started")
        self._schedule_tooltip_update()

    def hide(self):
        """Hide the tray icon."""
        super().hide()
        log.info("System tray stopped")

    def set_tooltip(self, text: str):
        """Set tooltip text."""
        self.setToolTip(text)