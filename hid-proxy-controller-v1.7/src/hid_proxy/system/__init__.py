"""System package."""

from .autostart import AutoStartManager, AutoStartManager as AutoStart
from .process import ProcessEnumerator, ProcessEnumerator as ProcessManager
from .single_instance import SingleInstanceLock, SingleInstanceLock as SingleInstance
from .validation import StartupValidator, StartupValidator as Validator

__all__ = [
    "AutoStartManager",
    "AutoStart",
    "ProcessEnumerator",
    "ProcessManager",
    "StartupValidator",
    "Validator",
    "SingleInstanceLock",
    "SingleInstance",
]
