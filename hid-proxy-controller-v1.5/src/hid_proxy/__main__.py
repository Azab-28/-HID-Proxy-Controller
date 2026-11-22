"""HID Proxy Controller — Main Entry Point"""
import sys
import signal
import threading
from hid_proxy.system.single_instance import SingleInstanceLock
from hid_proxy.utils.logging import setup_logging, get_logger

log = get_logger(__name__)

# Global reference for signal handler
_app_instance = None
_shutdown_event = threading.Event()


def _signal_handler(signum, frame):
    """Handle SIGINT/SIGTERM gracefully."""
    sig_name = signal.Signals(signum).name
    log.info(f"Received {sig_name}, initiating graceful shutdown...")
    _shutdown_event.set()
    if _app_instance:
        # Use request_shutdown which safely posts quit to Qt event loop
        _app_instance.request_shutdown()


def _wakeup_timer():
    """Timer callback to allow Python signal handlers to run in Qt event loop.
    
    Qt's event loop blocks Python signal handlers. A periodic timer
    (every 200ms) gives Python a chance to process signals.
    """
    if _shutdown_event.is_set() and _app_instance:
        _app_instance.request_shutdown()


def main() -> int:
    global _app_instance

    # Use Local namespace (no admin required) instead of Global
    lock = SingleInstanceLock("HIDProxyControllerLock")
    if not lock.acquire():
        print("Application already running", file=sys.stderr)
        return 1

    # Register signal handlers
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    try:
        from hid_proxy.app import Application
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
        
        setup_logging()
        
        # Create QApplication early for timer
        qt_app = QApplication.instance() or QApplication(sys.argv)
        
        # Timer to allow signal processing (200ms interval)
        wakeup_timer = QTimer()
        wakeup_timer.timeout.connect(_wakeup_timer)
        wakeup_timer.start(200)
        
        app = Application()
        _app_instance = app
        
        # Run the application
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