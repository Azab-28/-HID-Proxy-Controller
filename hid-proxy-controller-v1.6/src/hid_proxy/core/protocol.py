"""Binary protocol for ESP32 communication with CRC-8 and streaming frame parser.

Frame Format (CRC-8):
[0xAA, 0x55, seq, cmd, length_lo, length_hi, payload..., crc8]

ACK Frame (for critical commands):
[0xAA, 0x55, seq, 0xFF, 0x00, 0x00, ack_seq, crc8]

Protocol Version Negotiation:
- Handshake includes version in payload
- Device responds with supported version
"""
import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional, List, Iterator
import itertools

# ─────────────────────────────────────────────────────────────
# CRC-8 (Dallas/Maxim polynomial 0x31)
# ─────────────────────────────────────────────────────────────

_CRC8_TABLE = tuple(
    (lambda c: c if c < 0x80 else c ^ 0x31)(c)  # Simplified - actual table below
    for c in range(256)
)

# Precomputed CRC-8 table (polynomial 0x31, init 0x00, no reflection)
_CRC8_TABLE = (
    0x00, 0x31, 0x62, 0x53, 0xC4, 0xF5, 0xA6, 0x97, 0xB9, 0x88, 0xDB, 0xEA, 0x7D, 0x4C, 0x1F, 0x2E,
    0x43, 0x72, 0x21, 0x10, 0x87, 0xB6, 0xE5, 0xD4, 0xFA, 0xCB, 0x98, 0xA9, 0x3E, 0x0F, 0x5C, 0x6D,
    0x86, 0xB7, 0xE4, 0xD5, 0x42, 0x73, 0x20, 0x11, 0x3F, 0x0E, 0x5D, 0x6C, 0xFB, 0xCA, 0x99, 0xA8,
    0xC5, 0xF4, 0xA7, 0x96, 0x01, 0x30, 0x63, 0x52, 0x7C, 0x4D, 0x1E, 0x2F, 0xB8, 0x89, 0xDA, 0xEB,
    0x3D, 0x0C, 0x5F, 0x6E, 0xF9, 0xC8, 0x9B, 0xAA, 0x84, 0xB5, 0xE6, 0xD7, 0x40, 0x71, 0x22, 0x13,
    0x7E, 0x4F, 0x1C, 0x2D, 0xBA, 0x8B, 0xD8, 0xE9, 0xC7, 0xF6, 0xA5, 0x94, 0x03, 0x32, 0x61, 0x50,
    0xBB, 0x8A, 0xD9, 0xE8, 0x7F, 0x4E, 0x1D, 0x2C, 0x02, 0x33, 0x60, 0x51, 0xC6, 0xF7, 0xA4, 0x95,
    0xF8, 0xC9, 0x9A, 0xAB, 0x3C, 0x0D, 0x5E, 0x6F, 0x41, 0x70, 0x23, 0x12, 0x85, 0xB4, 0xE7, 0xD6,
    0x7A, 0x4B, 0x18, 0x29, 0xBE, 0x8F, 0xDC, 0xED, 0xC3, 0xF2, 0xA1, 0x90, 0x07, 0x36, 0x65, 0x54,
    0x39, 0x08, 0x5B, 0x6A, 0xFD, 0xCC, 0x9F, 0xAE, 0x80, 0xB1, 0xE2, 0xD3, 0x44, 0x75, 0x26, 0x17,
    0xFC, 0xCD, 0x9E, 0xAF, 0x38, 0x09, 0x5A, 0x6B, 0x45, 0x74, 0x27, 0x16, 0x81, 0xB0, 0xE3, 0xD2,
    0xBF, 0x8E, 0xDD, 0xEC, 0x7B, 0x4A, 0x19, 0x28, 0x06, 0x37, 0x64, 0x55, 0xC2, 0xF3, 0xA0, 0x91,
    0x47, 0x76, 0x25, 0x14, 0x83, 0xB2, 0xE1, 0xD0, 0xFE, 0xCF, 0x9C, 0xAD, 0x3A, 0x0B, 0x58, 0x69,
    0x04, 0x35, 0x66, 0x57, 0xC0, 0xF1, 0xA2, 0x93, 0xBD, 0x8C, 0xDF, 0xEE, 0x79, 0x48, 0x1B, 0x2A,
    0xC1, 0xF0, 0xA3, 0x92, 0x05, 0x34, 0x67, 0x56, 0x78, 0x49, 0x1A, 0x2B, 0xBC, 0x8D, 0xDE, 0xEF,
    0x82, 0xB3, 0xE0, 0xD1, 0x46, 0x77, 0x24, 0x15, 0x3B, 0x0A, 0x59, 0x68, 0xFF, 0xCE, 0x9D, 0xAC,
)

def crc8(data: bytes) -> int:
    """Compute CRC-8 (Dallas/Maxim) over data."""
    crc = 0
    for b in data:
        crc = _CRC8_TABLE[crc ^ b]
    return crc


# ─────────────────────────────────────────────────────────────
# Commands & Responses
# ─────────────────────────────────────────────────────────────

class Command(IntEnum):
    # System
    PING = 0x01
    GET_INFO = 0x02
    RESET = 0x03
    
    # Config
    GET_CONFIG = 0x10
    SET_CONFIG = 0x11
    SAVE_CONFIG = 0x12
    LOAD_DEFAULTS = 0x13
    
    # HID - Mouse
    MOUSE_MOVE = 0x20
    MOUSE_BUTTON = 0x21
    MOUSE_WHEEL = 0x22
    
    # HID - Keyboard
    KEYBOARD_KEY = 0x23
    KEYBOARD_MOD = 0x24
    CONSUMER_CTRL = 0x25
    
    # Modules
    MODULE_ENABLE = 0x30
    MODULE_DISABLE = 0x31
    MODULE_CONFIG = 0x32
    
    # Status
    GET_STATUS = 0x40
    GET_STATS = 0x41
    
    # Protocol
    ACK = 0xFE
    VERSION = 0xFF


class Response(IntEnum):
    OK = 0x00
    ERROR = 0x01
    INVALID_CMD = 0x02
    INVALID_PARAM = 0x03
    NOT_READY = 0x04
    CHECKSUM_FAIL = 0x05
    BUSY = 0x06
    VERSION_MISMATCH = 0x07


# ─────────────────────────────────────────────────────────────
# Packet Dataclass
# ─────────────────────────────────────────────────────────────

@dataclass
class Packet:
    command: int
    payload: bytes = b""
    seq: int = 0          # Sequence number for ACK tracking
    needs_ack: bool = False  # Whether this packet requires ACK
    
    def encode(self) -> bytes:
        """Encode packet with CRC-8."""
        header = bytes([0xAA, 0x55])
        seq_byte = bytes([self.seq & 0xFF])
        cmd_byte = bytes([self.command])
        length = struct.pack("<H", len(self.payload))
        # Add flags byte: bit 7 = needs_ack
        flags = 0x80 if self.needs_ack else 0x00
        flags_byte = bytes([flags])
        to_checksum = seq_byte + cmd_byte + flags_byte + length + self.payload
        checksum = bytes([crc8(to_checksum)])
        return header + to_checksum + checksum

    @classmethod
    def decode(cls, data: bytes) -> Optional["Packet"]:
        """Decode single packet from complete frame."""
        if len(data) < 8 or data[0] != 0xAA or data[1] != 0x55:
            return None
        seq = data[2]
        command = data[3]
        flags = data[4]
        length = struct.unpack("<H", data[5:7])[0]
        if len(data) < 8 + length:
            return None
        payload = data[7:7+length]
        if data[7+length] != crc8(data[2:7+length]):
            return None
        return cls(command=command, payload=payload, seq=seq, needs_ack=bool(flags & 0x80))

    @staticmethod
    def _calc_checksum(data: bytes) -> int:
        return crc8(data)


# ─────────────────────────────────────────────────────────────
# Streaming Frame Parser (State Machine)
# ─────────────────────────────────────────────────────────────

class FrameParser:
    """Streaming frame parser using state machine.
    
    Handles: fragmented frames, multiple frames in one read, 
    garbage bytes between frames, oversized frames.
    """
    
    # States
    WAIT_HEADER1 = 0
    WAIT_HEADER2 = 1
    WAIT_SEQ = 2
    WAIT_CMD = 3
    WAIT_FLAGS = 4
    WAIT_LEN_LO = 5
    WAIT_LEN_HI = 6
    WAIT_PAYLOAD = 7
    WAIT_CRC = 8
    
    MAX_PAYLOAD = 1024  # Safety limit
    
    def __init__(self):
        self._state = self.WAIT_HEADER1
        self._buffer = bytearray()
        self._expected_len = 0
        self._seq = 0
        self._cmd = 0
        self._flags = 0
    
    def feed(self, data: bytes) -> Iterator[Packet]:
        """Feed bytes into parser, yield complete packets."""
        for byte in data:
            packet = self._process_byte(byte)
            if packet:
                yield packet
    
    def _process_byte(self, byte: int) -> Optional[Packet]:
        if self._state == self.WAIT_HEADER1:
            if byte == 0xAA:
                self._state = self.WAIT_HEADER2
        elif self._state == self.WAIT_HEADER2:
            if byte == 0x55:
                self._state = self.WAIT_SEQ
            else:
                self._state = self.WAIT_HEADER1 if byte != 0xAA else self.WAIT_HEADER2
        elif self._state == self.WAIT_SEQ:
            self._seq = byte
            self._state = self.WAIT_CMD
        elif self._state == self.WAIT_CMD:
            self._cmd = byte
            self._state = self.WAIT_FLAGS
        elif self._state == self.WAIT_FLAGS:
            self._flags = byte
            self._state = self.WAIT_LEN_LO
        elif self._state == self.WAIT_LEN_LO:
            self._expected_len = byte
            self._state = self.WAIT_LEN_HI
        elif self._state == self.WAIT_LEN_HI:
            self._expected_len |= (byte << 8)
            if self._expected_len > self.MAX_PAYLOAD:
                self._reset()
                return None
            self._buffer.clear()
            self._state = self.WAIT_PAYLOAD if self._expected_len > 0 else self.WAIT_CRC
        elif self._state == self.WAIT_PAYLOAD:
            self._buffer.append(byte)
            if len(self._buffer) >= self._expected_len:
                self._state = self.WAIT_CRC
        elif self._state == self.WAIT_CRC:
            received_crc = byte
            # Compute CRC over seq + cmd + flags + len_lo + len_hi + payload
            check_data = bytes([self._seq, self._cmd, self._flags, 
                               self._expected_len & 0xFF, (self._expected_len >> 8) & 0xFF]) + bytes(self._buffer)
            if crc8(check_data) == received_crc:
                packet = Packet(
                    command=self._cmd,
                    payload=bytes(self._buffer),
                    seq=self._seq,
                    needs_ack=bool(self._flags & 0x80)
                )
                self._reset()
                return packet
            else:
                self._reset()
        return None
    
    def _reset(self):
        self._state = self.WAIT_HEADER1
        self._buffer.clear()
        self._expected_len = 0


# ─────────────────────────────────────────────────────────────
# Packet Factory (Packets)
# ─────────────────────────────────────────────────────────────

_seq_counter = itertools.count(1)

def _next_seq() -> int:
    return next(_seq_counter) & 0xFF


class Packets:
    @staticmethod
    def ping(needs_ack: bool = False) -> bytes:
        return Packet(Command.PING, seq=_next_seq(), needs_ack=needs_ack).encode()
    
    @staticmethod
    def get_info(needs_ack: bool = False) -> bytes:
        return Packet(Command.GET_INFO, seq=_next_seq(), needs_ack=needs_ack).encode()
    
    @staticmethod
    def get_config(needs_ack: bool = False) -> bytes:
        return Packet(Command.GET_CONFIG, seq=_next_seq(), needs_ack=needs_ack).encode()
    
    @staticmethod
    def set_config(config_data: bytes, needs_ack: bool = True) -> bytes:
        return Packet(Command.SET_CONFIG, config_data, seq=_next_seq(), needs_ack=needs_ack).encode()
    
    @staticmethod
    def save_config(needs_ack: bool = True) -> bytes:
        return Packet(Command.SAVE_CONFIG, seq=_next_seq(), needs_ack=needs_ack).encode()
    
    @staticmethod
    def load_defaults(needs_ack: bool = True) -> bytes:
        return Packet(Command.LOAD_DEFAULTS, seq=_next_seq(), needs_ack=needs_ack).encode()
    
    @staticmethod
    def mouse_move(dx: int, dy: int) -> bytes:
        return Packet(Command.MOUSE_MOVE, struct.pack("<hh", dx, dy), seq=_next_seq()).encode()
    
    @staticmethod
    def mouse_button(buttons: int, pressed: bool) -> bytes:
        return Packet(Command.MOUSE_BUTTON, struct.pack("<BB", buttons, 1 if pressed else 0), seq=_next_seq()).encode()
    
    @staticmethod
    def mouse_wheel(delta: int) -> bytes:
        return Packet(Command.MOUSE_WHEEL, struct.pack("<h", delta), seq=_next_seq()).encode()
    
    @staticmethod
    def keyboard_key(keycode: int, pressed: bool) -> bytes:
        return Packet(Command.KEYBOARD_KEY, struct.pack("<HB", keycode, 1 if pressed else 0), seq=_next_seq()).encode()
    
    @staticmethod
    def keyboard_mod(modifiers: int) -> bytes:
        return Packet(Command.KEYBOARD_MOD, struct.pack("<B", modifiers), seq=_next_seq()).encode()
    
    @staticmethod
    def consumer_ctrl(usage: int, pressed: bool) -> bytes:
        return Packet(Command.CONSUMER_CTRL, struct.pack("<HB", usage, 1 if pressed else 0), seq=_next_seq()).encode()
    
    @staticmethod
    def module_enable(module_id: int, enabled: bool, needs_ack: bool = True) -> bytes:
        return Packet(Command.MODULE_ENABLE, struct.pack("<BB", module_id, 1 if enabled else 0), seq=_next_seq(), needs_ack=needs_ack).encode()
    
    @staticmethod
    def module_disable(module_id: int, needs_ack: bool = True) -> bytes:
        return Packet(Command.MODULE_DISABLE, struct.pack("<B", module_id), seq=_next_seq(), needs_ack=needs_ack).encode()
    
    @staticmethod
    def get_status(needs_ack: bool = False) -> bytes:
        return Packet(Command.GET_STATUS, seq=_next_seq(), needs_ack=needs_ack).encode()
    
    @staticmethod
    def get_stats(needs_ack: bool = False) -> bytes:
        return Packet(Command.GET_STATS, seq=_next_seq(), needs_ack=needs_ack).encode()
    
    @staticmethod
    def version(protocol_version: int = 1) -> bytes:
        return Packet(Command.VERSION, struct.pack("<B", protocol_version), seq=_next_seq(), needs_ack=True).encode()


# ─────────────────────────────────────────────────────────────
# ACK Handling Helpers
# ─────────────────────────────────────────────────────────────

class AckTracker:
    """Track pending ACKs with timeout and retry."""
    
    def __init__(self, timeout: float = 1.0, max_retries: int = 3):
        self._pending: Dict[int, tuple[Packet, float, int]] = {}  # seq -> (packet, sent_time, retries)
        self._timeout = timeout
        self._max_retries = max_retries
        self._lock = threading.Lock()
    
    def add(self, packet: Packet) -> None:
        if not packet.needs_ack:
            return
        with self._lock:
            self._pending[packet.seq] = (packet, time.time(), 0)
    
    def ack(self, seq: int) -> Optional[Packet]:
        with self._lock:
            return self._pending.pop(seq, None)
    
    def check_timeouts(self) -> List[Packet]:
        """Return packets that need retry."""
        now = time.time()
        with self._lock:
            retries = []
            for seq, (packet, sent_time, retries) in list(self._pending.items()):
                if now - sent_time > self._timeout:
                    if retries < 3:
                        self._pending[seq] = (packet, time.time(), retries + 1)
                        retries.append(packet)
                    else:
                        del self._pending[seq]
            return retries
    
    def clear(self) -> None:
        with self._lock:
            self._pending.clear()