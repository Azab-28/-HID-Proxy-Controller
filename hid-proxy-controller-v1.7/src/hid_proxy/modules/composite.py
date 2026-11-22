"""Composite module for combining multiple modules."""
from hid_proxy.modules.base import BaseModule


class CompositeModule(BaseModule):
    def __init__(self, device_manager):
        super().__init__(device_manager)
        self._modules: list[BaseModule] = []

    def add_module(self, module: BaseModule) -> None:
        self._modules.append(module)

    def initialize(self) -> None:
        for m in self._modules:
            m.initialize()

    def shutdown(self) -> None:
        for m in self._modules:
            m.shutdown()

    def process(self, data) -> None:
        if not self._enabled:
            return
        for m in self._modules:
            if m.is_enabled:
                m.process(data)

    def enable(self) -> None:
        super().enable()
        for m in self._modules:
            m.enable()

    def disable(self) -> None:
        super().disable()
        for m in self._modules:
            m.disable()
