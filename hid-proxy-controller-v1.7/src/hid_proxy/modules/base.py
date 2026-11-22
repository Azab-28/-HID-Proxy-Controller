"""Base module interface."""
from abc import ABC, abstractmethod
from typing import Any


class BaseModule(ABC):
    def __init__(self, device_manager):
        self.device_manager = device_manager
        self._enabled = False

    @abstractmethod
    def initialize(self) -> None:
        pass

    @abstractmethod
    def shutdown(self) -> None:
        pass

    @abstractmethod
    def process(self, data: Any) -> None:
        pass

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False

    @property
    def is_enabled(self) -> bool:
        return self._enabled
