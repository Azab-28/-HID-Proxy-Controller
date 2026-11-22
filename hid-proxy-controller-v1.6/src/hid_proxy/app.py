"""Application core — coordinates all subsystems with EventBus."""
import sys
from typing import Optional
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, QObject, Signal

from hid_proxy.config.manager import ConfigManager
from hid_proxy.config.profiles import ProfileManager
from hid_proxy.core.device import DeviceManager
from hid_proxy.core.monitor import ConnectionMonitor
from hid_proxy.core.dispatcher import (EventBus, get_event_bus, EventType, 
                                        emit_device_connected, emit_device_disconnected)
from hid_proxy.modules.registry import ModuleRegistry
from hid_proxy.targeting.detector import TargetDetector
from hid_proxy.ui.tray import SystemTray
from hid_proxy.system.autostart import AutoStartManager
from hid_proxy.system.validation import StartupValidator
from hid_proxy.system.process import ProcessEnumerator
from hid_proxy.utils.logging import get_logger

log = get_logger(__name__)


class Application(QObject):
    def __init__(self):
        super().__init__()
        self.config = ConfigManager()
        # Initialize profile manager
        self.config.profile_manager = ProfileManager(self.config)
        
        self.device_manager = DeviceManager(self.config)
        self.monitor = ConnectionMonitor(self.device_manager, self.config)
        self.event_bus = get_event_bus()
        self.module_registry = ModuleRegistry()
        self.detector = TargetDetector(self.config)
        self.autostart = AutoStartManager()
        self.process_enum = ProcessEnumerator()

        self._tray = None
        self._app = None
        self._running = False
        self._settings_window = None
        self._profiles_window = None
        self._targets_window = None
        
        # Subscribe to events
        self._subscribe_events()

    def _subscribe_events(self):
        """Subscribe to core events."""
        self.event_bus.subscribe(EventType.DEVICE_CONNECTED, self._on_device_connected)
        self.event_bus.subscribe(EventType.DEVICE_DISCONNECTED, self._on_device_disconnected)
        self.event_bus.subscribe(EventType.CONFIG_CHANGED, self._on_config_changed)

    def _on_device_connected(self, event):
        """Handle device connected event."""
        payload = event.payload
        log.info(f"Device connected: {payload.port} (ID: {payload.device_id})")
        # Update tray tooltip
        if self._tray:
            self._tray.update_tooltip()

    def _on_device_disconnected(self, event):
        """Handle device disconnected event."""
        payload = event.payload
        log.info(f"Device disconnected: {payload.port} ({payload.reason})")
        if self._tray:
            self._tray.update_tooltip()

    def _on_config_changed(self, event):
        """Handle config changes that need immediate propagation."""
        payload = event.payload
        if payload.key.startswith("targeting."):
            # Update detector config
            self.detector = TargetDetector(self.config)
        elif payload.key.startswith("modules."):
            # Module enable/disable changes
            self._update_module_states()

    def _update_module_states(self):
        """Sync module enabled state with config."""
        for module_name in self.module_registry.list_modules():
            module = self.module_registry.get(module_name)
            enabled = self.config.get(f"modules.{module_name}.enabled", True)
            if enabled and not module.is_enabled:
                module.enable()
            elif not enabled and module.is_enabled:
                module.disable()

    def run(self) -> int:
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setQuitOnLastWindowClosed(False)

        # Initialize modules
        self._init_modules()

        # Start device monitor
        self.monitor.start()

        # Auto-connect if configured
        if self.config.get("device.auto_connect"):
            self._auto_connect()

        # Setup system tray
        self._tray = SystemTray(self)
        self._tray.show()

        self._running = True
        exit_code = self._app.exec()

        # Cleanup after event loop ends
        self.shutdown()
        return exit_code

    def _init_modules(self):
        from hid_proxy.modules.mouse_emulator import MouseEmulator
        from hid_proxy.modules.keyboard_emulator import KeyboardEmulator
        from hid_proxy.modules.composite import CompositeModule

        self.module_registry.register("mouse", MouseEmulator(self.device_manager))
        self.module_registry.register("keyboard", KeyboardEmulator(self.device_manager))
        self.module_registry.register("composite", CompositeModule(self.device_manager))

        for module in self.module_registry.list_modules():
            self.module_registry.get(module).initialize()

    def _auto_connect(self):
        ports = self.device_manager.scan_ports()
        if ports:
            preferred = self.config.get("device.preferred_port")
            port = preferred if preferred in [p["port"] for p in ports] else ports[0]["port"]
            self.device_manager.connect(port, self.config.get("device.baudrate"))

    def shutdown(self):
        if not self._running:
            return
        log.info("Shutting down application...")
        self._running = False
        self.monitor.stop()
        self.device_manager.disconnect_all()
        for module in self.module_registry.list_modules():
            try:
                self.module_registry.get(module).shutdown()
            except Exception as e:
                log.error(f"Error shutting down module {module}: {e}")
        if self._tray:
            self._tray.hide()
        if self._settings_window:
            self._settings_window.close()
        if self._profiles_window:
            self._profiles_window.close()
        if self._targets_window:
            self._targets_window.close()

        # Ensure QApplication quits
        if self._app:
            self._app.quit()
        log.info("Shutdown complete")

    def request_shutdown(self):
        """Request shutdown from signal handler or tray."""
        if self._running:
            log.info("Shutdown requested")
            # Use QTimer to safely quit from event loop
            if self._app:
                QTimer.singleShot(0, self._app.quit)

    # ─────────────────────────────────────────────────────────────
    # Window Management
    # ─────────────────────────────────────────────────────────────

    def show_settings(self):
        if not self._settings_window:
            from hid_proxy.ui.settings import SettingsWindow
            self._settings_window = SettingsWindow(self)
        self._settings_window.show()
        self._settings_window.raise_()
        self._settings_window.activateWindow()

    def show_profiles(self):
        if not self._profiles_window:
            from hid_proxy.ui.profiles import ProfilesWindow
            self._profiles_window = ProfilesWindow(self)
        self._profiles_window.show()
        self._profiles_window.raise_()
        self._profiles_window.activateWindow()

    def show_targets(self):
        if not self._targets_window:
            from hid_proxy.ui.targets import TargetsWindow
            self._targets_window = TargetsWindow(self)
        self._targets_window.show()
        self._targets_window.raise_()
        self._targets_window.activateWindow()