"""Single instance enforcement using Windows named mutex."""
import ctypes
import ctypes.wintypes
import sys

ERROR_SUCCESS = 0
ERROR_ACCESS_DENIED = 5
ERROR_ALREADY_EXISTS = 183

if sys.platform == "win32":
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [
        ctypes.wintypes.LPVOID,
        ctypes.wintypes.BOOL,
        ctypes.wintypes.LPCWSTR,
    ]
    kernel32.CreateMutexW.restype = ctypes.wintypes.HANDLE
    kernel32.ReleaseMutex.argtypes = [ctypes.wintypes.HANDLE]
    kernel32.ReleaseMutex.restype = ctypes.wintypes.BOOL
    kernel32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
    kernel32.CloseHandle.restype = ctypes.wintypes.BOOL
else:
    kernel32 = None


class SingleInstanceLock:
    """Cross-process single instance lock using Windows named mutex."""

    def __init__(self, mutex_name: str):
        if not mutex_name.startswith(("Global\\", "Local\\")):
            mutex_name = "Local\\" + mutex_name
        self.mutex_name = mutex_name
        self.handle = None
        self._acquired = False

    def acquire(self) -> bool:
        if kernel32 is None:
            self._acquired = True
            return True

        handle = kernel32.CreateMutexW(None, True, self.mutex_name)
        if not handle:
            error = ctypes.get_last_error()
            if error == ERROR_ACCESS_DENIED:
                fallback_name = self.mutex_name.replace("Local\\", "", 1)
                handle = kernel32.CreateMutexW(None, True, fallback_name)
                if not handle:
                    return False
            else:
                return False

        error = ctypes.get_last_error()
        if error == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            self.handle = None
            self._acquired = False
            return False

        self.handle = handle
        self._acquired = error == ERROR_SUCCESS
        if not self._acquired:
            kernel32.CloseHandle(handle)
            self.handle = None
        return self._acquired

    def release(self) -> None:
        if kernel32 is not None and self.handle:
            if self._acquired:
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
