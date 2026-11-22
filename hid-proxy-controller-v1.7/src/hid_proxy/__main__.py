"""HID Proxy Controller — Main Entry Point."""
import signal
import sys
import threading

from hid_proxy.system.single_instance import SingleInstanceLock
from hid_proxy.utils.logging import get_logger, setup_logging

log = get_logger(__name__)

_app_instance = None
_shutdown_event = threading.Event()


def _signal_handler(signum, _frame) -> None:
    sig_name = signal.Signals(signum).name
    log.info(f"Received {sig_name}, initiating graceful shutdown...")
    _shutdown_event.set()
    if _app_instance:
        _app_instance.request_shutdown()


def _wakeup_timer() -> None:
    if _shutdown_event.is_set() and _app_instance:
        _app_instance.request_shutdown()


def main() -> int:
    global _app_instance

    lock = SingleInstanceLock("HIDProxyControllerLock")
    if not lock.acquire():
        print("Application already running", file=sys.stderr)
        return 1

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
        from hid_proxy.app import Application

        setup_logging()
        _qt_app = QApplication.instance() or QApplication(sys.argv)

        wakeup_timer = QTimer()
        wakeup_timer.timeout.connect(_wakeup_timer)
        wakeup_timer.start(200)

        app = Application()
        _app_instance = app
        exit_code = app.run()
        wakeup_timer.stop()
        return exit_code
    except Exception as e:
        log.exception(f"Fatal error: {e}")
        print(f"Fatal error: {e}", file=sys.stderr)
        return 1
    finally:
        _app_instance = None
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
