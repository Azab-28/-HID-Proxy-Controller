"""Single instance enforcement using Windows named mutex."""
import ctypes
from ctypes import wintypes

kernel32 = ctypes.windll.kernel32

class SingleInstanceLock:
    def __init__(self, mutex_name: str):
        self.mutex_name = mutex_name
        self.handle = None
        self._acquired = False
    
    def acquire(self) -> bool:
        self.handle = kernel32.CreateMutexW(None, True, self.mutex_name)
        if not self.handle:
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
