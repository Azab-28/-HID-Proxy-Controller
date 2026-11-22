"""Native Qt SystemTrayIcon implementation (100% GUI main-thread safe)."""
from PySide6.QtCore import QTimer, Qt, Slot
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from hid_proxy.utils.logging import get_logger

log = get_logger(__name__)


class SystemTray(QSystemTrayIcon):
    """System tray icon manager using Qt's native QSystemTrayIcon."""

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setToolTip("HID Proxy Controller")

        self._icon_pixmap = self._create_icon_pixmap()
        self.setIcon(QIcon(self._icon_pixmap))

        self._menu = self._create_menu()
        self.setContextMenu(self._menu)
        self.activated.connect(self._on_activated)

        self._tooltip_timer = QTimer(self)
        self._tooltip_timer.setSingleShot(True)
        self._tooltip_timer.timeout.connect(self.update_tooltip)
        self._tooltip_timer.start(300)

    def _create_icon_pixmap(self) -> QPixmap:
        size = 32
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        margin = 2
        painter.setBrush(QColor(0, 120, 212))
        painter.setPen(QColor(255, 255, 255))
        painter.drawRoundedRect(margin, margin, size - 2 * margin, size - 2 * margin, 6, 6)

        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "H")
        painter.end()
        return pixmap

    def _create_menu(self) -> QMenu:
        menu = QMenu()
        menu.aboutToShow.connect(self._sync_menu_states)

        action_settings = menu.addAction("Show Settings")
        action_settings.triggered.connect(self._on_show_settings)

        action_targets = menu.addAction("Targets")
        action_targets.triggered.connect(self._on_show_targets)

        action_profiles = menu.addAction("Profiles")
        action_profiles.triggered.connect(self._on_show_profiles)

        menu.addSeparator()

        self._action_autoconnect = menu.addAction("Auto-connect")
        self._action_autoconnect.setCheckable(True)
        self._action_autoconnect.setChecked(self.app.config.get("device.auto_connect", True))
        self._action_autoconnect.triggered.connect(self._on_toggle_autoconnect)

        self._action_autostart = menu.addAction("Auto-start")
        self._action_autostart.setCheckable(True)
        self._action_autostart.setChecked(self.app.autostart.is_enabled())
        self._action_autostart.triggered.connect(self._on_toggle_autostart)

        menu.addSeparator()

        action_exit = menu.addAction("Exit")
        action_exit.triggered.connect(self._on_exit)
        return menu

    @Slot()
    def _sync_menu_states(self) -> None:
        self._action_autoconnect.setChecked(bool(self.app.config.get("device.auto_connect", True)))
        self._action_autostart.setChecked(self.app.autostart.is_enabled())

    @Slot()
    def _on_show_settings(self) -> None:
        self.app.show_settings()

    @Slot()
    def _on_show_targets(self) -> None:
        self.app.show_targets()

    @Slot()
    def _on_show_profiles(self) -> None:
        self.app.show_profiles()

    @Slot(bool)
    def _on_toggle_autoconnect(self, checked: bool) -> None:
        self.app.config.set("device.auto_connect", checked)
        self.schedule_tooltip_update()

    @Slot(bool)
    def _on_toggle_autostart(self, checked: bool) -> None:
        if checked:
            self.app.autostart.enable()
        else:
            self.app.autostart.disable()
        self._action_autostart.setChecked(self.app.autostart.is_enabled())
        self.schedule_tooltip_update()

    @Slot()
    def _on_exit(self) -> None:
        self.app.request_shutdown()

    @Slot(QSystemTrayIcon.ActivationReason)
    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._on_show_settings()

    def schedule_tooltip_update(self) -> None:
        self._tooltip_timer.start(100)

    @Slot()
    def update_tooltip(self) -> None:
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

    def show(self) -> None:
        super().show()
        log.info("System tray started")
        self.schedule_tooltip_update()

    def hide(self) -> None:
        super().hide()
        log.info("System tray stopped")

    def set_tooltip(self, text: str) -> None:
        self.setToolTip(text)
