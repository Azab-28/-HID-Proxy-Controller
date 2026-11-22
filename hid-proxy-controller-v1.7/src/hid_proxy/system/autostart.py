"""Auto-start management via Windows Registry (HKCU Run)."""
import logging
import sys

log = logging.getLogger(__name__)


class AutoStartManager:
    REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
    APP_NAME = "HIDProxyController"

    def enable(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            import winreg

            exe_path = sys.executable
            if exe_path.lower().endswith(("python.exe", "pythonw.exe")):
                import hid_proxy
                script = hid_proxy.__file__.replace("__init__.py", "__main__.py")
                exe_path = f'"{sys.executable}" "{script}"'
            else:
                exe_path = f'"{exe_path}"'

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, self.REG_PATH, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.SetValueEx(key, self.APP_NAME, 0, winreg.REG_SZ, exe_path)
            log.info("Auto-start enabled")
            return True
        except Exception as e:
            log.error(f"Enable auto-start failed: {e}")
            return False

    def disable(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, self.REG_PATH, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.DeleteValue(key, self.APP_NAME)
            log.info("Auto-start disabled")
            return True
        except FileNotFoundError:
            return True
        except Exception as e:
            log.error(f"Disable auto-start failed: {e}")
            return False

    def is_enabled(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, self.REG_PATH, 0, winreg.KEY_READ
            ) as key:
                winreg.QueryValueEx(key, self.APP_NAME)
            return True
        except FileNotFoundError:
            return False
        except Exception as e:
            log.debug(f"Error checking auto-start status: {e}")
            return False
