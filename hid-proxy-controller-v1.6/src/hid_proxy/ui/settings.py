"""Settings window with Security tab and live theme switching."""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QTabWidget, QFormLayout,
                               QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox,
                               QCheckBox, QPushButton, QLabel, QGroupBox,
                               QHBoxLayout, QMessageBox, QInputDialog)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

from hid_proxy.utils.logging import get_logger

log = get_logger(__name__)


class SettingsWindow(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setWindowTitle("HID Proxy Controller - Settings")
        self.resize(600, 550)
        self._pending_saves = {}  # Batch config changes
        self._setup_ui()
        self._load_values()
        self._refresh_ports()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        tabs = QTabWidget()

        # Device tab
        device_tab = QWidget()
        device_layout = QFormLayout(device_tab)
        
        # Port selection with refresh
        port_layout = QHBoxLayout()
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(200)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_ports)
        port_layout.addWidget(self.port_combo)
        port_layout.addWidget(refresh_btn)
        device_layout.addRow("Port:", port_layout)
        
        self.baudrate_combo = QComboBox()
        self.baudrate_combo.addItems(["115200", "921600", "2000000"])
        device_layout.addRow("Baudrate:", self.baudrate_combo)
        
        self.auto_connect = QCheckBox("Auto-connect on startup")
        device_layout.addRow(self.auto_connect)
        
        self.preferred_port = QLineEdit()
        self.preferred_port.setPlaceholderText("Leave empty for auto-detect")
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

        # Security tab (NEW)
        security_tab = QWidget()
        security_layout = QFormLayout(security_tab)
        
        self.encrypt_config = QCheckBox("Encrypt configuration file")
        self.encrypt_config.toggled.connect(self._on_encrypt_toggled)
        security_layout.addRow(self.encrypt_config)
        
        # Encryption password
        pwd_layout = QHBoxLayout()
        self.encryption_password = QLineEdit()
        self.encryption_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.encryption_password.setPlaceholderText("Enter encryption password")
        self.encryption_password.textChanged.connect(self._on_password_changed)
        pwd_layout.addWidget(self.encryption_password)
        
        self.show_password = QCheckBox("Show")
        self.show_password.toggled.connect(self._toggle_password_visibility)
        pwd_layout.addWidget(self.show_password)
        security_layout.addRow("Password:", pwd_layout)
        
        # Save to keyring
        self.save_to_keyring = QCheckBox("Save password in Windows Credential Manager")
        self.save_to_keyring.setChecked(True)
        security_layout.addRow(self.save_to_keyring)
        
        # Encryption buttons
        btn_layout = QHBoxLayout()
        self.btn_set_password = QPushButton("Set / Change Password")
        self.btn_set_password.clicked.connect(self._set_encryption_password)
        btn_layout.addWidget(self.btn_set_password)
        
        self.btn_remove_encryption = QPushButton("Remove Encryption")
        self.btn_remove_encryption.clicked.connect(self._remove_encryption)
        btn_layout.addWidget(self.btn_remove_encryption)
        security_layout.addRow(btn_layout)
        
        # Encryption status
        self.encryption_status = QLabel("")
        self.encryption_status.setWordWrap(True)
        security_layout.addRow("Status:", self.encryption_status)
        
        tabs.addTab(security_tab, "Security")

        # Buttons
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("Save All")
        save_btn.clicked.connect(self._flush_saves)
        btn_layout.addStretch()
        btn_layout.addWidget(save_btn)
        
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addLayout(btn_layout)

    def _load_values(self):
        c = self.app.config
        
        # Device
        self._refresh_ports()
        preferred = c.get("device.preferred_port", "")
        if preferred:
            self.port_combo.setCurrentText(preferred)
        self.baudrate_combo.setCurrentText(str(c.get("device.baudrate", 2000000)))
        self.auto_connect.setChecked(c.get("device.auto_connect", True))
        self.preferred_port.setText(preferred)
        
        # Targeting
        self.sensitivity.blockSignals(True)
        self.sensitivity.setValue(c.get("targeting.sensitivity", 1.0))
        self.smoothing.blockSignals(True)
        self.smoothing.setValue(c.get("targeting.smoothing", 0.35))
        self.deadzone.blockSignals(True)
        self.deadzone.setValue(c.get("targeting.deadzone", 4))
        self.jitter.blockSignals(True)
        self.jitter.setValue(c.get("targeting.jitter", 1.5))
        self.priority.blockSignals(True)
        self.priority.setCurrentText(c.get("targeting.priority", "closest"))
        self.fov.blockSignals(True)
        self.fov.setValue(c.get("targeting.fov", 300))
        
        self.sensitivity.blockSignals(False)
        self.smoothing.blockSignals(False)
        self.deadzone.blockSignals(False)
        self.jitter.blockSignals(False)
        self.priority.blockSignals(False)
        
        # UI
        self.theme.blockSignals(True)
        self.theme.setCurrentText(c.get("ui.theme", "dark"))
        self.minimize_tray.blockSignals(True)
        self.minimize_tray.setChecked(c.get("ui.minimize_to_tray", True))
        self.notifications.blockSignals(True)
        self.notifications.setChecked(c.get("ui.show_notifications", True))
        self.theme.blockSignals(False)
        self.minimize_tray.blockSignals(False)
        self.notifications.blockSignals(False)
        
        # Security
        self.encrypt_config.blockSignals(True)
        self.encrypt_config.setChecked(c.get("security.encrypt_config", False))
        self._on_encrypt_toggled(self.encrypt_config.isChecked())
        self.encrypt_config.blockSignals(False)
        
        self.save_to_keyring.blockSignals(True)
        self.save_to_keyring.setChecked(True)  # Default
        self.save_to_keyring.blockSignals(False)
        
        self._update_encryption_status()

    def _refresh_ports(self):
        """Refresh available serial ports."""
        current = self.port_combo.currentText()
        self.port_combo.clear()
        self.port_combo.addItem("Auto-detect", "")
        
        ports = self.app.device_manager.scan_ports()
        for p in ports:
            self.port_combo.addItem(f"{p['port']} - {p['description']}", p['port'])
        
        if current:
            index = self.port_combo.findText(current)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)

    def _queue_save(self, key: str, value):
        """Queue a config change for batch saving."""
        self._pending_saves[key] = value

    def _flush_saves(self):
        """Apply all pending config changes at once."""
        c = self.app.config
        for key, value in self._pending_saves.items():
            c.set(key, value)
        self._pending_saves.clear()
        
        # Save port preference
        port_data = self.port_combo.currentData()
        if port_data:
            c.set("device.preferred_port", port_data)
        else:
            c.set("device.preferred_port", "")
        
        self.close()

    def _refresh_ports(self):
        """Refresh available serial ports."""
        current = self.port_combo.currentData()
        self.port_combo.clear()
        self.port_combo.addItem("Auto-detect", "")
        
        ports = self.app.device_manager.scan_ports()
        for p in ports:
            self.port_combo.addItem(f"{p['port']} - {p['description']}", p['port'])
        
        if current:
            index = self.port_combo.findData(current)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)

    def _on_theme_changed(self, theme: str):
        """Apply theme change immediately."""
        self._queue_save("ui.theme", theme)
        self._apply_theme(theme)

    def _apply_theme(self, theme: str):
        """Apply Qt theme to entire application."""
        app = QApplication.instance()
        if not app:
            return
        
        if theme == "dark":
            app.setStyleSheet(self._dark_stylesheet())
        elif theme == "light":
            app.setStyleSheet(self._light_stylesheet())
        else:  # system
            app.setStyleSheet("")

    def _dark_stylesheet(self) -> str:
        return """
            QWidget { background-color: #1e1e1e; color: #d4d4d4; }
            QTabWidget::pane { border: 1px solid #3c3c3c; background: #1e1e1e; }
            QTabBar::tab { background: #2d2d2d; color: #d4d4d4; padding: 8px 16px; border: 1px solid #3c3c3c; }
            QTabBar::tab:selected { background: #0e639c; color: white; }
            QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit { 
                background: #2d2d2d; color: #d4d4d4; border: 1px solid #3c3c3c; padding: 4px; 
            }
            QCheckBox { color: #d4d4d4; }
            QGroupBox { border: 1px solid #3c3c3c; margin-top: 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; color: #d4d4d4; }
            QPushButton { background: #0e639c; color: white; border: none; padding: 8px 16px; border-radius: 4px; }
            QPushButton:hover { background: #1177bb; }
            QMenu { background: #1e1e1e; color: #d4d4d4; border: 1px solid #3c3c3c; }
            QScrollBar:vertical { background: #2d2d2d; width: 10px; }
            QScrollBar::handle:vertical { background: #3c3c3c; min-height: 20px; }
        """

    def _light_stylesheet(self) -> str:
        return """
            QWidget { background-color: #ffffff; color: #333333; }
            QTabWidget::pane { border: 1px solid #cccccc; background: #ffffff; }
            QTabBar::tab { background: #f0f0f0; color: #333333; padding: 8px 16px; border: 1px solid #cccccc; }
            QTabBar::tab:selected { background: #0078d4; color: white; }
            QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit { 
                background: #ffffff; color: #333333; border: 1px solid #cccccc; padding: 4px; 
            }
            QCheckBox { color: #333333; }
            QGroupBox { border: 1px solid #cccccc; margin-top: 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; color: #333333; }
            QPushButton { background: #0078d4; color: white; border: none; padding: 8px 16px; border-radius: 4px; }
            QPushButton:hover { background: #106ebe; }
        """

    def _on_encrypt_toggled(self, checked: bool):
        self._queue_save("security.encrypt_config", checked)
        self.encryption_password.setEnabled(checked)
        self.show_password.setEnabled(checked)
        self.btn_set_password.setEnabled(checked)
        self.btn_remove_encryption.setEnabled(checked)
        self.save_to_keyring.setEnabled(checked)
        self._update_encryption_status()

    def _toggle_password_visibility(self, checked: bool):
        mode = QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        self.encryption_password.setEchoMode(mode)

    def _on_password_changed(self, text: str):
        # Don't auto-save password, only on explicit button click
        pass

    def _set_encryption_password(self):
        password = self.encryption_password.text()
        if not password:
            QMessageBox.warning(self, "Empty Password", "Please enter a password first.")
            return
        
        save_to_keyring = self.save_to_keyring.isChecked()
        if self.app.config.set_encryption_password(password, save_to_keyring):
            QMessageBox.information(self, "Success", "Encryption password set successfully.")
            self.encryption_password.clear()
            self._update_encryption_status()
        else:
            QMessageBox.critical(self, "Error", "Failed to set encryption password.")

    def _remove_encryption(self):
        reply = QMessageBox.question(
            self, "Remove Encryption",
            "This will decrypt the config file and remove the password.\nContinue?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            if self.app.config.remove_encryption():
                self.encrypt_config.setChecked(False)
                self._on_encrypt_toggled(False)
                QMessageBox.information(self, "Success", "Encryption removed.")
            else:
                QMessageBox.critical(self, "Error", "Failed to remove encryption.")

    def _update_encryption_status(self):
        c = self.app.config
        if c.get("security.encrypt_config", False):
            self.encryption_status.setText("✓ Config is encrypted")
            self.encryption_status.setStyleSheet("color: #4ec9b0;")
        else:
            self.encryption_status.setText("○ Config is not encrypted")
            self.encryption_status.setStyleSheet("color: #cccccc;")