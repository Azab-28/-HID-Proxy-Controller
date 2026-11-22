"""HID Proxy Controller — Main Entry Point"""
import sys
from hid_proxy.system.single_instance import SingleInstanceLock

def main() -> int:
    lock = SingleInstanceLock("Global\\HIDProxyControllerLock")
    if not lock.acquire():
        print("Application already running", file=sys.stderr)
        return 1
    
    try:
        from hid_proxy.app import Application
        from hid_proxy.utils.logging import setup_logging
        setup_logging()
        app = Application()
        return app.run()
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        return 1
    finally:
        lock.release()

if __name__ == "__main__":
    sys.exit(main())
