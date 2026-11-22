"""Keyboard emulation module."""
import struct
import logging
from hid_proxy.modules.base import BaseModule
from hid_proxy.core.protocol import Packets

log = logging.getLogger(__name__)

class KeyboardEmulator(BaseModule):
    def initialize(self):
        self._pressed_keys = set()
        log.info("Keyboard emulator initialized")
    
    def shutdown(self):
        for key in self._pressed_keys:
            self.release(key)
        log.info("Keyboard emulator shutdown")
    
    def process(self, data):
        pass
    
    def press(self, keycode: int, port: str = "") -> bool:
        if keycode in self._pressed_keys:
            return True
        packet = Packets.keyboard_key(keycode, True)
        if self.device_manager.send(port or self._get_port(), packet):
            self._pressed_keys.add(keycode)
            return True
        return False
    
    def release(self, keycode: int, port: str = "") -> bool:
        if keycode not in self._pressed_keys:
            return True
        packet = Packets.keyboard_key(keycode, False)
        if self.device_manager.send(port or self._get_port(), packet):
            self._pressed_keys.discard(keycode)
            return True
        return False
    
    def type(self, text: str, port: str = "") -> bool:
        for char in text:
            keycode = self._char_to_keycode(char)
            if keycode:
                self.press(keycode, port)
                self.release(keycode, port)
        return True
    
    def _char_to_keycode(self, char: str) -> int:
        # Simplified mapping - extend as needed
        if 'a' <= char <= 'z':
            return ord(char) - ord('a') + 4
        if 'A' <= char <= 'Z':
            return ord(char) - ord('A') + 4
        if '1' <= char <= '9':
            return ord(char) - ord('1') + 30
        if char == '0':
            return 39
        return 0
    
    def _get_port(self) -> str:
        ports = self.device_manager.get_connected_ports()
        return ports[0] if ports else ""
