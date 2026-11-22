"""Binary protocol for ESP32 communication.
Frame: [0xAA, 0x55, cmd, length_lo, length_hi, payload..., checksum]
"""
import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional

class Command(IntEnum):
    PING = 0x01
    GET_INFO = 0x02
    RESET = 0x03
    GET_CONFIG = 0x10
    SET_CONFIG = 0x11
    SAVE_CONFIG = 0x12
    LOAD_DEFAULTS = 0x13
    MOUSE_MOVE = 0x20
    MOUSE_BUTTON = 0x21
    MOUSE_WHEEL = 0x22
    KEYBOARD_KEY = 0x23
    KEYBOARD_MOD = 0x24
    CONSUMER_CTRL = 0x25
    MODULE_ENABLE = 0x30
    MODULE_DISABLE = 0x31
    MODULE_CONFIG = 0x32
    GET_STATUS = 0x40
    GET_STATS = 0x41

class Response(IntEnum):
    OK = 0x00
    ERROR = 0x01
    INVALID_CMD = 0x02
    INVALID_PARAM = 0x03
    NOT_READY = 0x04
    CHECKSUM_FAIL = 0x05
    BUSY = 0x06

@dataclass
class Packet:
    command: int
    payload: bytes = b""
    
    def encode(self) -> bytes:
        header = bytes([0xAA, 0x55])
        cmd_byte = bytes([self.command])
        length = struct.pack("<H", len(self.payload))
        checksum = self._calc_checksum(cmd_byte + length + self.payload)
        return header + cmd_byte + length + self.payload + bytes([checksum])
    
    @classmethod
    def decode(cls, data: bytes) -> Optional["Packet"]:
        if len(data) < 6 or data[0] != 0xAA or data[1] != 0x55:
            return None
        command = data[2]
        length = struct.unpack("<H", data[3:5])[0]
        if len(data) < 6 + length:
            return None
        payload = data[5:5+length]
        if data[5+length] != cls._calc_checksum_static(data[2:5+length]):
            return None
        return cls(command=command, payload=payload)
    
    @staticmethod
    def _calc_checksum(data: bytes) -> int:
        checksum = 0
        for b in data:
            checksum ^= b
        return checksum
    
    _calc_checksum_static = staticmethod(_calc_checksum)

class Packets:
    @staticmethod
    def ping() -> bytes:
        return Packet(Command.PING).encode()
    
    @staticmethod
    def get_info() -> bytes:
        return Packet(Command.GET_INFO).encode()
    
    @staticmethod
    def get_config() -> bytes:
        return Packet(Command.GET_CONFIG).encode()
    
    @staticmethod
    def set_config(config_data: bytes) -> bytes:
        return Packet(Command.SET_CONFIG, config_data).encode()
    
    @staticmethod
    def mouse_move(dx: int, dy: int) -> bytes:
        return Packet(Command.MOUSE_MOVE, struct.pack("<hh", dx, dy)).encode()
    
    @staticmethod
    def mouse_button(buttons: int, pressed: bool) -> bytes:
        return Packet(Command.MOUSE_BUTTON, struct.pack("<BB", buttons, 1 if pressed else 0)).encode()
    
    @staticmethod
    def keyboard_key(keycode: int, pressed: bool) -> bytes:
        return Packet(Command.KEYBOARD_KEY, struct.pack("<HB", keycode, 1 if pressed else 0)).encode()
    
    @staticmethod
    def module_enable(module_id: int, enabled: bool) -> bytes:
        return Packet(Command.MODULE_ENABLE, struct.pack("<BB", module_id, 1 if enabled else 0)).encode()
