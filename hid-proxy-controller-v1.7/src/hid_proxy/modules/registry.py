"""Module registry for managing modules."""
from typing import Dict, List, Optional
from hid_proxy.modules.base import BaseModule


class ModuleRegistry:
    def __init__(self):
        self._modules: Dict[str, BaseModule] = {}

    def register(self, name: str, module: BaseModule) -> None:
        self._modules[name] = module

    def unregister(self, name: str) -> None:
        self._modules.pop(name, None)

    def get(self, name: str) -> Optional[BaseModule]:
        return self._modules.get(name)

    def list_modules(self) -> List[str]:
        return list(self._modules.keys())

    def get_enabled(self) -> List[BaseModule]:
        return [m for m in self._modules.values() if m.is_enabled]
