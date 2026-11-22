"""Composite module for combining multiple modules."""
from hid_proxy.modules.base import BaseModule

class CompositeModule(BaseModule):
    def __init__(self, device_manager):
        super().__init__(device_manager)
        self._modules = []
    
    def add_module(self, module: BaseModule):
        self._modules.append(module)
    
    def initialize(self):
        for m in self._modules:
            m.initialize()
    
    def shutdown(self):
        for m in self._modules:
            m.shutdown()
    
    def process(self, data):
        for m in self._modules:
            m.process(data)
    
    def enable(self):
        super().enable()
        for m in self._modules:
            m.enable()
    
    def disable(self):
        super().disable()
        for m in self._modules:
            m.disable()
