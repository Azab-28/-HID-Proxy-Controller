"""Settings window."""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QTabWidget, QFormLayout,
                               QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox,
                               QCheckBox, QPushButton, QLabel, QGroupBox)
from PySide6.QtCore import Qt

class SettingsWindow(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setWindowTitle("HID Proxy Controller - Settings")
        self.resize(600, 500)
        self._setup_ui()
        self._load_values()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        
        # Device tab
        device_tab = QWidget()
        device_layout = QFormLayout(device_tab)
        self.port_combo = QComboBox()
        self.baudrate_combo = QComboBox()
        self.baudrate_combo.addItems(["115200", "921600", "2000000"])
        self.auto_connect = QCheckBox("Auto-connect on startup")
        device_layout.addRow("Port:", self.port_combo)
        device_layout.addRow("Baudrate:", self.baudrate_combo)
        device_layout.addRow(self.auto_connect)
        tabs.addTab(device_tab, "Device")
        
        # Targeting tab
        targeting_tab = QWidget()
        targeting_layout = QFormLayout(targeting_tab)
        self.sensitivity = QDoubleSpinBox()
        self.sensitivity.setRange(0.1, 5.0)
        self.sensitivity.setSingleStep(0.1)
        self.smoothing = QDoubleSpinBox()
        self.smoothing.setRange(0.0, 1.0)
        self.smoothing.setSingleStep(0.05)
        self.deadzone = QSpinBox()
        self.deadzone.setRange(0, 50)
        self.jitter = QDoubleSpinBox()
        self.jitter.setRange(0.0, 10.0)
        self.jitter.setSingleStep(0.1)
        self.priority = QComboBox()
        self.priority.addItems(["closest", "head"])
        self.fov = QSpinBox()
        self.fov.setRange(50, 1000)
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
        self.minimize_tray = QCheckBox("Minimize to tray")
        self.notifications = QCheckBox("Show notifications")
        ui_layout.addRow("Theme:", self.theme)
        ui_layout.addRow(self.minimize_tray)
        ui_layout.addRow(self.notifications)
        tabs.addTab(ui_tab, "UI")
        
        # Buttons
        btn_layout = QVBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._save)
        btn_layout.addWidget(save_btn)
        
        layout.addWidget(tabs)
        layout.addLayout(btn_layout)
    
    def _load_values(self):
        c = self.app.config
        self.baudrate_combo.setCurrentText(str(c.get("device.baudrate", 2000000)))
        self.auto_connect.setChecked(c.get("device.auto_connect", True))
        self.sensitivity.setValue(c.get("targeting.sensitivity", 1.0))
        self.smoothing.setValue(c.get("targeting.smoothing", 0.35))
        self.deadzone.setValue(c.get("targeting.deadzone", 4))
        self.jitter.setValue(c.get("targeting.jitter", 1.5))
        self.priority.setCurrentText(c.get("targeting.priority", "closest"))
        self.fov.setValue(c.get("targeting.fov", 300))
        self.theme.setCurrentText(c.get("ui.theme", "dark"))
        self.minimize_tray.setChecked(c.get("ui.minimize_to_tray", True))
        self.notifications.setChecked(c.get("ui.show_notifications", True))
    
    def _save(self):
        c = self.app.config
        c.set("device.baudrate", int(self.baudrate_combo.currentText()))
        c.set("device.auto_connect", self.auto_connect.isChecked())
        c.set("targeting.sensitivity", self.sensitivity.value())
        c.set("targeting.smoothing", self.smoothing.value())
        c.set("targeting.deadzone", self.deadzone.value())
        c.set("targeting.jitter", self.jitter.value())
        c.set("targeting.priority", self.priority.currentText())
        c.set("targeting.fov", self.fov.value())
        c.set("ui.theme", self.theme.currentText())
        c.set("ui.minimize_to_tray", self.minimize_tray.isChecked())
        c.set("ui.show_notifications", self.notifications.isChecked())
        self.close()
