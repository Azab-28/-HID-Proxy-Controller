"""Application core — coordinates all subsystems with Qt Signals & EventBus."""
import sys
from typing import Optional

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from hid_proxy.config.manager import ConfigManager
from hid_proxy.config.profiles import ProfileManager
from hid_proxy.core.device import DeviceManager
from hid_proxy.core.dispatcher import EventType, get_event_bus
from hid_proxy.core.monitor import ConnectionMonitor
from hid_proxy.modules.registry import ModuleRegistry
from hid_proxy.system.autostart import AutoStartManager
from hid_proxy.system.process import ProcessEnumerator
from hid_proxy.system.validation import StartupValidator
from hid_proxy.targeting.detector import TargetDetector
from hid_proxy.ui.settings import SettingsWindow
from hid_proxy.ui.tray import SystemTray
from hid_proxy.utils.logging import get_logger

log = get_logger(__name__)


class Application(QObject):
    """Main application coordinator. Marshals background events onto the Qt GUI thread."""

    _sig_device_connected = Signal(str, str)
    _sig_device_disconnected = Signal(str, str)
    _sig_config_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setQuitOnLastWindowClosed(False)

        self.config = ConfigManager()
        self.config.profile_manager = ProfileManager(self.config)

        self.device_manager = DeviceManager(self.config)
        self.monitor = ConnectionMonitor(self.device_manager, self.config)
        self.event_bus = get_event_bus()
        self.module_registry = ModuleRegistry()
        self.detector = TargetDetector(self.config)
        self.autostart = AutoStartManager()
        self.process_enum = ProcessEnumerator()
        self.validator = StartupValidator(self.config, self.device_manager)

        self._tray: Optional[SystemTray] = None
        self._running = False
        self._settings_window = None
        self._profiles_window = None
        self._targets_window = None
        self._unsubscribers = []

        self._sig_device_connected.connect(self._handle_device_connected_ui)
        self._sig_device_disconnected.connect(self._handle_device_disconnected_ui)
        self._sig_config_changed.connect(self._handle_config_changed_ui)
        self._subscribe_events()

    def _subscribe_events(self) -> None:
        self._unsubscribers.append(
            self.event_bus.subscribe(
                EventType.DEVICE_CONNECTED,
                lambda ev: self._sig_device_connected.emit(ev.payload.port, ev.payload.device_id),
            )
        )
        self._unsubscribers.append(
            self.event_bus.subscribe(
                EventType.DEVICE_DISCONNECTED,
                lambda ev: self._sig_device_disconnected.emit(ev.payload.port, ev.payload.reason),
            )
        )
        self._unsubscribers.append(
            self.event_bus.subscribe(
                EventType.CONFIG_CHANGED,
                lambda ev: self._sig_config_changed.emit(ev.payload.key),
            )
        )

    def _handle_device_connected_ui(self, port: str, device_id: str) -> None:
        log.info(f"Device connected: {port} (ID: {device_id})")
        if self._tray:
            self._tray.update_tooltip()

    def _handle_device_disconnected_ui(self, port: str, reason: str) -> None:
        log.info(f"Device disconnected: {port} ({reason})")
        if self._tray:
            self._tray.update_tooltip()

    def _handle_config_changed_ui(self, key: str) -> None:
        if key.startswith("targeting.") or key == "profile.loaded":
            self.detector.reload_config()
        if key.startswith("modules.") or key == "profile.loaded":
            self._update_module_states()
        if key in ("ui.theme", "profile.loaded"):
            SettingsWindow.apply_theme(self.config.get("ui.theme", "dark"))

    def _update_module_states(self) -> None:
        for module_name in self.module_registry.list_modules():
            module = self.module_registry.get(module_name)
            if not module:
                continue
            enabled = bool(self.config.get(f"modules.{module_name}.enabled", True))
            if enabled and not module.is_enabled:
                module.enable()
            elif not enabled and module.is_enabled:
                module.disable()

    def run(self) -> int:
        is_ok, errors, warnings = self.validator.validate_all()
        for w in warnings:
            log.warning(f"Startup check: {w}")
        if not is_ok:
            for err in errors:
                log.error(f"Startup validation error: {err}")
            return 1

        SettingsWindow.apply_theme(self.config.get("ui.theme", "dark"))
        self._init_modules()
        self._update_module_states()

        # ConnectionMonitor handles initial scan + auto-connect without race conditions
        self.monitor.start()

        self._tray = SystemTray(self)
        self._tray.show()

        self._running = True
        exit_code = self._app.exec()
        self.shutdown()
        return exit_code

    def _init_modules(self) -> None:
        from hid_proxy.modules.composite import CompositeModule
        from hid_proxy.modules.keyboard_emulator import KeyboardEmulator
        from hid_proxy.modules.mouse_emulator import MouseEmulator

        self.module_registry.register("mouse", MouseEmulator(self.device_manager))
        self.module_registry.register("keyboard", KeyboardEmulator(self.device_manager))
        self.module_registry.register("composite", CompositeModule(self.device_manager))

        for module_name in self.module_registry.list_modules():
            module = self.module_registry.get(module_name)
            if module:
                module.initialize()

    def shutdown(self) -> None:
        if not self._running:
            return
        log.info("Shutting down application...")
        self._running = False

        for unsub in self._unsubscribers:
            try:
                unsub()
            except Exception:
                pass
        self._unsubscribers.clear()

        self.monitor.stop()
        self.device_manager.disconnect_all()
        for module_name in self.module_registry.list_modules():
            module = self.module_registry.get(module_name)
            if module:
                try:
                    module.shutdown()
                except Exception as e:
                    log.error(f"Error shutting down module {module_name}: {e}")

        for win in (self._settings_window, self._profiles_window, self._targets_window):
            if win:
                win.hide()
                win.deleteLater()

        if self._tray:
            self._tray.hide()

        if self._app:
            self._app.quit()
        log.info("Shutdown complete")

    def request_shutdown(self) -> None:
        if self._running:
            log.info("Shutdown requested")
            if self._app:
                QTimer.singleShot(0, self._app.quit)

    def show_settings(self) -> None:
        if not self._settings_window:
            self._settings_window = SettingsWindow(self)
        self._settings_window.show()
        self._settings_window.raise_()
        self._settings_window.activateWindow()

    def show_profiles(self) -> None:
        if not self._profiles_window:
            from hid_proxy.ui.profiles import ProfilesWindow
            self._profiles_window = ProfilesWindow(self)
        self._profiles_window.show()
        self._profiles_window.raise_()
        self._profiles_window.activateWindow()

    def show_targets(self) -> None:
        if not self._targets_window:
            from hid_proxy.ui.targets import TargetsWindow
            self._targets_window = TargetsWindow(self)
        self._targets_window.show()
        self._targets_window.raise_()
        self._targets_window.activateWindow()
