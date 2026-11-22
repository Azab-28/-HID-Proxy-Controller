"""Application core — coordinates all subsystems."""
import sys
from typing import Optional
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, QObject, Signal

from hid_proxy.config.manager import ConfigManager
from hid_proxy.core.device import DeviceManager
from hid_proxy.core.monitor import ConnectionMonitor
from hid_proxy.core.dispatcher import CommandDispatcher
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
        self.device_manager = DeviceManager(self.config)
        self.monitor = ConnectionMonitor(self.device_manager, self.config)
        self.dispatcher = CommandDispatcher(self.device_manager)
        self.module_registry = ModuleRegistry()
        self.detector = TargetDetector(self.config)
        self.autostart = AutoStartManager()
        self.process_enum = ProcessEnumerator()

        self._tray = None
        self._app = None
        self._running = False
        self._settings_window = None
        self._profiles_window = None

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
        log.info("Shutdown complete")