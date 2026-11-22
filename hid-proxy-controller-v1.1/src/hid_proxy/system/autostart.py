"""Auto-start management via Windows Registry."""
import winreg
import sys
import logging

log = logging.getLogger(__name__)

class AutoStartManager:
    REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
    APP_NAME = "HIDProxyController"
    
    def enable(self) -> bool:
        try:
            exe_path = sys.executable
            if exe_path.endswith("python.exe") or exe_path.endswith("pythonw.exe"):
                # Running from source - use the script path
                import hid_proxy
                script = hid_proxy.__file__.replace("__init__.py", "__main__.py")
                exe_path = f'"{sys.executable}" "{script}"'
            
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.REG_PATH, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, self.APP_NAME, 0, winreg.REG_SZ, exe_path)
            log.info("Auto-start enabled")
            return True
        except Exception as e:
            log.error(f"Enable auto-start failed: {e}")
            return False
    
    def disable(self) -> bool:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.REG_PATH, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, self.APP_NAME)
            log.info("Auto-start disabled")
            return True
        except FileNotFoundError:
            return True
        except Exception as e:
            log.error(f"Disable auto-start failed: {e}")
            return False
    
    def is_enabled(self) -> bool:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.REG_PATH, 0, winreg.KEY_READ) as key:
                winreg.QueryValueEx(key, self.APP_NAME)
            return True
        except FileNotFoundError:
            return False
        except Exception:
            return False
