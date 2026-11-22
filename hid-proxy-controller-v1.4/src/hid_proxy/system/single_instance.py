"""Single instance enforcement using Windows named mutex."""
import ctypes
from ctypes import wintypes
import sys

kernel32 = ctypes.windll.kernel32


class SingleInstanceLock:
    """Cross-process single instance lock using Windows named mutex.

    Uses Local namespace by default (no admin required). For Global namespace,
    prefix mutex_name with "Global\\" (requires SeCreateGlobalPrivilege).
    """

    def __init__(self, mutex_name: str):
        # Ensure it's a Local mutex unless explicitly Global
        if not mutex_name.startswith(("Global\\", "Local\\")):
            mutex_name = "Local\\" + mutex_name
        self.mutex_name = mutex_name
        self.handle = None
        self._acquired = False

    def acquire(self) -> bool:
        self.handle = kernel32.CreateMutexW(None, True, self.mutex_name)
        if not self.handle:
            error = kernel32.GetLastError()
            if error == 5:  # ERROR_ACCESS_DENIED
                # Try without Local prefix as fallback
                fallback_name = self.mutex_name.replace("Local\\", "", 1)
                self.handle = kernel32.CreateMutexW(None, True, fallback_name)
                if not self.handle:
                    return False
            else:
                return False
        self._acquired = (kernel32.GetLastError() == 0)
        return self._acquired

    def release(self) -> None:
        if self.handle and self._acquired:
            kernel32.ReleaseMutex(self.handle)
            kernel32.CloseHandle(self.handle)
            self.handle = None
            self._acquired = False

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()

    @property
    def is_acquired(self) -> bool:
        return self._acquired


def is_windows() -> bool:
    return sys.platform == "win32"