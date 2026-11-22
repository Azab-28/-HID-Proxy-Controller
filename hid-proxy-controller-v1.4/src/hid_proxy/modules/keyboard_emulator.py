"""Keyboard emulation module with modifier and Unicode support."""
import struct
import logging
from hid_proxy.modules.base import BaseModule
from hid_proxy.core.protocol import Packets, Packet, Command

log = logging.getLogger(__name__)

# USB HID Keyboard Usage IDs (subset)
KEYCODE_MAP = {
    # Letters
    'a': 4, 'b': 5, 'c': 6, 'd': 7, 'e': 8, 'f': 9, 'g': 10, 'h': 11,
    'i': 12, 'j': 13, 'k': 14, 'l': 15, 'm': 16, 'n': 17, 'o': 18, 'p': 19,
    'q': 20, 'r': 21, 's': 22, 't': 23, 'u': 24, 'v': 25, 'w': 26, 'x': 27,
    'y': 28, 'z': 29,
    # Numbers
    '1': 30, '2': 31, '3': 32, '4': 33, '5': 34, '6': 35, '7': 36, '8': 37, '9': 38, '0': 39,
    # Special keys
    '\n': 40,  # Enter
    '\t': 43,  # Tab
    ' ': 44,   # Space
    '-': 45, '=': 46, '[': 47, ']': 48, '\\': 49, '#': 50, ';': 51, "'": 52,
    '`': 53, ',': 54, '.': 55, '/': 56,
    # Function keys
    'F1': 58, 'F2': 59, 'F3': 60, 'F4': 61, 'F5': 62, 'F6': 63,
    'F7': 64, 'F8': 65, 'F9': 66, 'F10': 67, 'F11': 68, 'F12': 69,
    # Modifiers (handled separately via keyboard_mod)
    # Navigation
    'Home': 74, 'End': 77, 'PageUp': 75, 'PageDown': 78,
    'Left': 80, 'Right': 79, 'Up': 82, 'Down': 81,
    'Insert': 73, 'Delete': 76,
    # Lock keys
    'CapsLock': 57, 'NumLock': 83, 'ScrollLock': 71,
    # Numpad
    'Numpad0': 98, 'Numpad1': 89, 'Numpad2': 90, 'Numpad3': 91,
    'Numpad4': 92, 'Numpad5': 93, 'Numpad6': 94, 'Numpad7': 95,
    'Numpad8': 96, 'Numpad9': 97,
    'NumpadEnter': 88, 'Numpad+': 87, 'Numpad-': 86, 'Numpad*': 85, 'Numpad/': 84,
    'Numpad.': 99,
}

# Modifier bitmasks
MOD_LEFT_CTRL = 1
MOD_LEFT_SHIFT = 2
MOD_LEFT_ALT = 4
MOD_LEFT_GUI = 8  # Windows/Command key
MOD_RIGHT_CTRL = 16
MOD_RIGHT_SHIFT = 32
MOD_RIGHT_ALT = 64
MOD_RIGHT_GUI = 128

SHIFT_REQUIRED = set('ABCDEFGHIJKLMNOPQRSTUVWXYZ~!@#$%^&*()_+{}|:"<>?')


class KeyboardEmulator(BaseModule):
    def initialize(self):
        self._pressed_keys = set()      # Set of keycodes currently held
        self._active_modifiers = 0      # Current modifier bitmask
        log.info("Keyboard emulator initialized")

    def shutdown(self):
        # Release all keys and modifiers
        for keycode in list(self._pressed_keys):
            self.release(keycode)
        if self._active_modifiers:
            self._send_modifiers(0)
        log.info("Keyboard emulator shutdown")

    def process(self, data):
        pass

    def press(self, keycode: int, port: str = "") -> bool:
        """Press a key (non-modifier)."""
        if keycode in self._pressed_keys:
            return True
        packet = Packets.keyboard_key(keycode, True)
        if self.device_manager.send(port or self._get_port(), packet):
            self._pressed_keys.add(keycode)
            return True
        return False

    def release(self, keycode: int, port: str = "") -> bool:
        """Release a key (non-modifier)."""
        if keycode not in self._pressed_keys:
            return True
        packet = Packets.keyboard_key(keycode, False)
        if self.device_manager.send(port or self._get_port(), packet):
            self._pressed_keys.discard(keycode)
            return True
        return False

    def press_modifier(self, modifier: int, port: str = "") -> bool:
        """Press a modifier key (Ctrl, Shift, Alt, Gui)."""
        if self._active_modifiers & modifier:
            return True
        self._active_modifiers |= modifier
        return self._send_modifiers(self._active_modifiers, port)

    def release_modifier(self, modifier: int, port: str = "") -> bool:
        """Release a modifier key."""
        if not (self._active_modifiers & modifier):
            return True
        self._active_modifiers &= ~modifier
        return self._send_modifiers(self._active_modifiers, port)

    def _send_modifiers(self, modifiers: int, port: str = "") -> bool:
        """Send keyboard modifier report."""
        packet = Packet(Command.KEYBOARD_MOD, struct.pack("<B", modifiers))
        return self.device_manager.send(port or self._get_port(), packet)

    def type(self, text: str, port: str = "") -> bool:
        """Type a string, handling modifiers for uppercase/symbols."""
        for char in text:
            if not self._type_char(char, port):
                return False
        return True

    def _type_char(self, char: str, port: str) -> bool:
        """Type a single character with proper modifier handling."""
        # Check if shift is needed
        needs_shift = char in SHIFT_REQUIRED

        # Get base keycode (lowercase for letters)
        base_char = char.lower() if char.isalpha() else char
        keycode = KEYCODE_MAP.get(base_char)

        if keycode is None:
            log.warning(f"No keycode mapping for character: {repr(char)}")
            return False

        # Handle shift
        if needs_shift:
            self.press_modifier(MOD_LEFT_SHIFT, port)

        # Press and release the key
        self.press(keycode, port)
        self.release(keycode, port)

        # Release shift
        if needs_shift:
            self.release_modifier(MOD_LEFT_SHIFT, port)

        return True

    def hotkey(self, *keycodes: int, port: str = "") -> bool:
        """Press multiple keys simultaneously (e.g., Ctrl+C)."""
        # Press all
        for kc in keycodes:
            if not self.press(kc, port):
                # Release any already pressed
                for kc2 in keycodes:
                    if kc2 in self._pressed_keys:
                        self.release(kc2, port)
                return False
        # Release all in reverse order
        for kc in reversed(keycodes):
            self.release(kc, port)
        return True

    def hotkey_with_modifiers(self, modifiers: int, keycode: int, port: str = "") -> bool:
        """Press key with modifiers (e.g., Ctrl+Shift+V)."""
        self.press_modifier(modifiers, port)
        self.press(keycode, port)
        self.release(keycode, port)
        self.release_modifier(modifiers, port)
        return True

    def _char_to_keycode(self, char: str) -> int:
        """Legacy method for backward compatibility."""
        base_char = char.lower() if char.isalpha() else char
        return KEYCODE_MAP.get(base_char, 0)

    def _get_port(self) -> str:
        ports = self.device_manager.get_connected_ports()
        return ports[0] if ports else ""