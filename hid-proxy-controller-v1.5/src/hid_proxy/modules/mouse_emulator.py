"""Mouse emulation module."""
import struct
import logging
from hid_proxy.modules.base import BaseModule
from hid_proxy.core.protocol import Packets

log = logging.getLogger(__name__)

class MouseEmulator(BaseModule):
    def initialize(self):
        self._last_pos = (0, 0)
        log.info("Mouse emulator initialized")
    
    def shutdown(self):
        log.info("Mouse emulator shutdown")
    
    def process(self, data):
        pass
    
    def move(self, dx: int, dy: int, port: str = "") -> bool:
        packet = Packets.mouse_move(dx, dy)
        return self.device_manager.send(port or self._get_port(), packet)
    
    def click(self, button: str = "left", pressed: bool = True, port: str = "") -> bool:
        btn_map = {"left": 1, "right": 2, "middle": 4}
        packet = Packets.mouse_button(btn_map.get(button, 1), pressed)
        return self.device_manager.send(port or self._get_port(), packet)
    
    def wheel(self, delta: int, port: str = "") -> bool:
        from hid_proxy.core.protocol import Packet, Command
        packet = Packet(Command.MOUSE_WHEEL, struct.pack("<h", delta))
        return self.device_manager.send(port or self._get_port(), packet)
    
    def _get_port(self) -> str:
        ports = self.device_manager.get_connected_ports()
        return ports[0] if ports else ""
