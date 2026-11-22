"""Command dispatcher for routing commands to modules."""
import logging
from typing import Dict, Callable, Any, List

log = logging.getLogger(__name__)

class CommandDispatcher:
    def __init__(self, device_manager):
        self.device_manager = device_manager
        self._handlers: Dict[str, List[Callable]] = {}
        self._default_port: str = ""
    
    def register(self, command: str, handler: Callable) -> None:
        if command not in self._handlers:
            self._handlers[command] = []
        self._handlers[command].append(handler)
    
    def unregister(self, command: str, handler: Callable) -> None:
        if command in self._handlers:
            self._handlers[command].remove(handler)
    
    def dispatch(self, command: str, *args, **kwargs) -> List[Any]:
        results = []
        for handler in self._handlers.get(command, []):
            try:
                results.append(handler(*args, **kwargs))
            except Exception as e:
                log.error(f"Dispatch error ({command}): {e}")
        return results
    
    def set_default_port(self, port: str) -> None:
        self._default_port = port
    
    def send_to_device(self, packet) -> bool:
        if not self._default_port:
            ports = self.device_manager.get_connected_ports()
            if not ports:
                return False
            self._default_port = ports[0]
        return self.device_manager.send(self._default_port, packet)
