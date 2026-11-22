"""Settings window with Device, Targeting, UI, and Security tabs."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from hid_proxy.utils.logging import get_logger

log = get_logger(__name__)


class SettingsWindow(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setWindowTitle("HID Proxy Controller - Settings")
        self.resize(600, 520)
        self._pending_saves: dict = {}
        self._setup_ui()
        self._load_values()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        tabs = QTabWidget()

        # Device tab
        device_tab = QWidget()
        device_layout = QFormLayout(device_tab)

        port_layout = QHBoxLayout()
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(220)
        self.port_combo.currentIndexChanged.connect(self._on_port_combo_changed)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_ports)
        port_layout.addWidget(self.port_combo)
        port_layout.addWidget(refresh_btn)
        device_layout.addRow("Detected Port:", port_layout)

        self.baudrate_combo = QComboBox()
        self.baudrate_combo.addItems(["115200", "921600", "2000000"])
        self.baudrate_combo.currentTextChanged.connect(
            lambda v: self._queue_save("device.baudrate", int(v))
        )
        device_layout.addRow("Baudrate:", self.baudrate_combo)

        self.auto_connect = QCheckBox("Auto-connect on startup")
        self.auto_connect.toggled.connect(lambda v: self._queue_save("device.auto_connect", v))
        device_layout.addRow(self.auto_connect)

        self.preferred_port = QLineEdit()
        self.preferred_port.setPlaceholderText("e.g. COM3 (leave empty for auto-detect)")
        self.preferred_port.textChanged.connect(
            lambda v: self._queue_save("device.preferred_port", v.strip())
        )
        device_layout.addRow("Preferred Port:", self.preferred_port)
        tabs.addTab(device_tab, "Device")

        # Targeting tab
        targeting_tab = QWidget()
        targeting_layout = QFormLayout(targeting_tab)

        self.sensitivity = QDoubleSpinBox()
        self.sensitivity.setRange(0.1, 5.0)
        self.sensitivity.setSingleStep(0.1)
        self.sensitivity.valueChanged.connect(lambda v: self._queue_save("targeting.sensitivity", v))

        self.smoothing = QDoubleSpinBox()
        self.smoothing.setRange(0.0, 1.0)
        self.smoothing.setSingleStep(0.05)
        self.smoothing.valueChanged.connect(lambda v: self._queue_save("targeting.smoothing", v))

        self.deadzone = QSpinBox()
        self.deadzone.setRange(0, 50)
        self.deadzone.valueChanged.connect(lambda v: self._queue_save("targeting.deadzone", v))

        self.jitter = QDoubleSpinBox()
        self.jitter.setRange(0.0, 10.0)
        self.jitter.setSingleStep(0.1)
        self.jitter.valueChanged.connect(lambda v: self._queue_save("targeting.jitter", v))

        self.curve = QComboBox()
        self.curve.addItems(["bezier", "linear", "catmull"])
        self.curve.currentTextChanged.connect(lambda v: self._queue_save("targeting.curve", v))

        self.priority = QComboBox()
        self.priority.addItems(["closest", "head"])
        self.priority.currentTextChanged.connect(lambda v: self._queue_save("targeting.priority", v))

        self.fov = QSpinBox()
        self.fov.setRange(50, 1000)
        self.fov.valueChanged.connect(lambda v: self._queue_save("targeting.fov", v))

        targeting_layout.addRow("Sensitivity:", self.sensitivity)
        targeting_layout.addRow("Smoothing:", self.smoothing)
        targeting_layout.addRow("Deadzone:", self.deadzone)
        targeting_layout.addRow("Jitter:", self.jitter)
        targeting_layout.addRow("Curve Type:", self.curve)
        targeting_layout.addRow("Priority:", self.priority)
        targeting_layout.addRow("FOV Radius:", self.fov)
        tabs.addTab(targeting_tab, "Targeting")

        # UI tab
        ui_tab = QWidget()
        ui_layout = QFormLayout(ui_tab)

        self.theme = QComboBox()
        self.theme.addItems(["dark", "light", "system"])
        self.theme.currentTextChanged.connect(self._on_theme_changed)
        ui_layout.addRow("Theme:", self.theme)

        self.minimize_tray = QCheckBox("Minimize to tray")
        self.minimize_tray.toggled.connect(lambda v: self._queue_save("ui.minimize_to_tray", v))
        ui_layout.addRow(self.minimize_tray)

        self.notifications = QCheckBox("Show notifications")
        self.notifications.toggled.connect(lambda v: self._queue_save("ui.show_notifications", v))
        ui_layout.addRow(self.notifications)
        tabs.addTab(ui_tab, "UI")

        # Security tab
        security_tab = QWidget()
        security_layout = QFormLayout(security_tab)

        self.encrypt_config = QCheckBox("Encrypt configuration file")
        self.encrypt_config.toggled.connect(self._on_encrypt_toggled)
        security_layout.addRow(self.encrypt_config)

        pwd_layout = QHBoxLayout()
        self.encryption_password = QLineEdit()
        self.encryption_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.encryption_password.setPlaceholderText("Enter encryption password")
        pwd_layout.addWidget(self.encryption_password)

        self.show_password = QCheckBox("Show")
        self.show_password.toggled.connect(self._toggle_password_visibility)
        pwd_layout.addWidget(self.show_password)
        security_layout.addRow("Password:", pwd_layout)

        self.save_to_keyring = QCheckBox("Save password in Windows Credential Manager")
        self.save_to_keyring.setChecked(True)
        security_layout.addRow(self.save_to_keyring)

        sec_btn_layout = QHBoxLayout()
        self.btn_set_password = QPushButton("Set / Change Password")
        self.btn_set_password.clicked.connect(self._set_encryption_password)
        sec_btn_layout.addWidget(self.btn_set_password)

        self.btn_remove_encryption = QPushButton("Remove Encryption")
        self.btn_remove_encryption.clicked.connect(self._remove_encryption)
        sec_btn_layout.addWidget(self.btn_remove_encryption)
        security_layout.addRow(sec_btn_layout)

        self.encryption_status = QLabel("")
        self.encryption_status.setWordWrap(True)
        security_layout.addRow("Status:", self.encryption_status)
        tabs.addTab(security_tab, "Security")

        # Bottom action buttons
        footer_layout = QHBoxLayout()
        save_btn = QPushButton("Save All")
        save_btn.clicked.connect(self._flush_saves)
        cancel_btn = QPushButton("Close")
        cancel_btn.clicked.connect(self.hide)
        footer_layout.addStretch()
        footer_layout.addWidget(cancel_btn)
        footer_layout.addWidget(save_btn)

        main_layout.addWidget(tabs)
        main_layout.addLayout(footer_layout)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._load_values()

    def closeEvent(self, event) -> None:
        event.ignore()
        self.hide()

    def _load_values(self) -> None:
        c = self.app.config
        widgets = [
            self.port_combo,
            self.baudrate_combo,
            self.auto_connect,
            self.preferred_port,
            self.sensitivity,
            self.smoothing,
            self.deadzone,
            self.jitter,
            self.curve,
            self.priority,
            self.fov,
            self.theme,
            self.minimize_tray,
            self.notifications,
            self.encrypt_config,
        ]
        for w in widgets:
            w.blockSignals(True)
        try:
            self._refresh_ports()
            preferred = c.get("device.preferred_port", "")
            self.preferred_port.setText(preferred)
            if preferred:
                idx = self.port_combo.findData(preferred)
                if idx >= 0:
                    self.port_combo.setCurrentIndex(idx)

            self.baudrate_combo.setCurrentText(str(c.get("device.baudrate", 2000000)))
            self.auto_connect.setChecked(bool(c.get("device.auto_connect", True)))

            self.sensitivity.setValue(float(c.get("targeting.sensitivity", 1.0)))
            self.smoothing.setValue(float(c.get("targeting.smoothing", 0.35)))
            self.deadzone.setValue(int(c.get("targeting.deadzone", 4)))
            self.jitter.setValue(float(c.get("targeting.jitter", 1.5)))
            self.curve.setCurrentText(str(c.get("targeting.curve", "bezier")))
            self.priority.setCurrentText(str(c.get("targeting.priority", "closest")))
            self.fov.setValue(int(c.get("targeting.fov", 300)))

            self.theme.setCurrentText(str(c.get("ui.theme", "dark")))
            self.minimize_tray.setChecked(bool(c.get("ui.minimize_to_tray", True)))
            self.notifications.setChecked(bool(c.get("ui.show_notifications", True)))

            enc = bool(c.get("security.encrypt_config", False))
            self.encrypt_config.setChecked(enc)
            self._sync_encryption_widgets(enc)
            self._update_encryption_status()
            self._pending_saves.clear()
        finally:
            for w in widgets:
                w.blockSignals(False)

    def _refresh_ports(self) -> None:
        current = self.port_combo.currentData()
        self.port_combo.clear()
        self.port_combo.addItem("Auto-detect", "")
        for p in self.app.device_manager.scan_ports():
            self.port_combo.addItem(f"{p['port']} - {p['description']}", p["port"])
        if current:
            idx = self.port_combo.findData(current)
            if idx >= 0:
                self.port_combo.setCurrentIndex(idx)

    def _on_port_combo_changed(self, _index: int) -> None:
        port_data = self.port_combo.currentData() or ""
        self.preferred_port.setText(port_data)

    def _queue_save(self, key: str, value) -> None:
        self._pending_saves[key] = value

    def _flush_saves(self) -> None:
        if self._pending_saves:
            self.app.config.update_many(self._pending_saves)
            self._pending_saves.clear()
        self.hide()

    def _on_theme_changed(self, theme: str) -> None:
        self._queue_save("ui.theme", theme)
        self.apply_theme(theme)

    @classmethod
    def apply_theme(cls, theme: str) -> None:
        app = QApplication.instance()
        if not app:
            return
        if theme == "dark":
            app.setStyleSheet(cls._dark_stylesheet())
        elif theme == "light":
            app.setStyleSheet(cls._light_stylesheet())
        else:
            app.setStyleSheet("")

    @staticmethod
    def _dark_stylesheet() -> str:
        return """
        QWidget { background-color: #1e1e1e; color: #d4d4d4; }
        QTabWidget::pane { border: 1px solid #3c3c3c; background: #1e1e1e; }
        QTabBar::tab { background: #2d2d2d; color: #d4d4d4; padding: 8px 16px; border: 1px solid #3c3c3c; }
        QTabBar::tab:selected { background: #0e639c; color: white; }
        QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {
            background: #2d2d2d; color: #d4d4d4; border: 1px solid #3c3c3c; padding: 4px;
        }
        QPushButton { background: #0e639c; color: white; border: none; padding: 8px 16px; border-radius: 4px; }
        QPushButton:hover { background: #1177bb; }
        QMenu { background: #1e1e1e; color: #d4d4d4; border: 1px solid #3c3c3c; }
        """

    @staticmethod
    def _light_stylesheet() -> str:
        return """
        QWidget { background-color: #ffffff; color: #333333; }
        QTabWidget::pane { border: 1px solid #cccccc; background: #ffffff; }
        QTabBar::tab { background: #f0f0f0; color: #333333; padding: 8px 16px; border: 1px solid #cccccc; }
        QTabBar::tab:selected { background: #0078d4; color: white; }
        QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {
            background: #ffffff; color: #333333; border: 1px solid #cccccc; padding: 4px;
        }
        QPushButton { background: #0078d4; color: white; border: none; padding: 8px 16px; border-radius: 4px; }
        QPushButton:hover { background: #106ebe; }
        """

    def _sync_encryption_widgets(self, enabled: bool) -> None:
        self.encryption_password.setEnabled(enabled)
        self.show_password.setEnabled(enabled)
        self.btn_set_password.setEnabled(enabled)
        self.btn_remove_encryption.setEnabled(enabled)
        self.save_to_keyring.setEnabled(enabled)

    def _on_encrypt_toggled(self, checked: bool) -> None:
        self._sync_encryption_widgets(checked)
        if not checked and self.app.config.get("security.encrypt_config", False):
            self._remove_encryption()
        self._update_encryption_status()

    def _toggle_password_visibility(self, checked: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        self.encryption_password.setEchoMode(mode)

    def _set_encryption_password(self) -> None:
        password = self.encryption_password.text()
        if not password:
            QMessageBox.warning(self, "Empty Password", "Please enter a password first.")
            return
        if self.app.config.set_encryption_password(password, self.save_to_keyring.isChecked()):
            QMessageBox.information(self, "Success", "Encryption password set successfully.")
            self.encryption_password.clear()
            self._update_encryption_status()
        else:
            QMessageBox.critical(self, "Error", "Failed to set encryption password.")

    def _remove_encryption(self) -> None:
        reply = QMessageBox.question(
            self,
            "Remove Encryption",
            "This will decrypt the config file and remove the password.\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            if self.app.config.remove_encryption():
                self.encrypt_config.blockSignals(True)
                self.encrypt_config.setChecked(False)
                self.encrypt_config.blockSignals(False)
                self._sync_encryption_widgets(False)
                self._update_encryption_status()
                QMessageBox.information(self, "Success", "Encryption removed.")

    def _update_encryption_status(self) -> None:
        if self.app.config.get("security.encrypt_config", False):
            self.encryption_status.setText("Config is encrypted (AES-256-GCM)")
            self.encryption_status.setStyleSheet("color: #4ec9b0;")
        else:
            self.encryption_status.setText("Config is not encrypted")
            self.encryption_status.setStyleSheet("color: #999999;")
