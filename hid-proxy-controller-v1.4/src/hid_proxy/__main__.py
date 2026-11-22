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
        setup_logging()
        app = Application()
        _app_instance = app
        return app.run()
    except Exception as e:
        log.exception(f"Fatal error: {e}")
        print(f"Fatal error: {e}", file=sys.stderr)
        return 1
    finally:
        _app_instance = None
        lock.release()


if __name__ == "__main__":
    sys.exit(main())