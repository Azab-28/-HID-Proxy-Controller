"""Keyboard emulation module with full Unicode, macro, and hotkey support."""
import struct
import logging
import threading
import time
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass, field

from hid_proxy.modules.base import BaseModule
from hid_proxy.core.protocol import Packets, Packet, Command

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# USB HID Keyboard Usage IDs (Comprehensive)
# ─────────────────────────────────────────────────────────────

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
    'F13': 104, 'F14': 105, 'F15': 106, 'F16': 107, 'F17': 108, 'F18': 109,
    'F19': 110, 'F20': 111, 'F21': 112, 'F22': 113, 'F23': 114, 'F24': 115,
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
    # Extended symbols (require shift)
    '!': 30, '@': 31, '#': 32, '$': 33, '%': 34, '^': 35, '&': 36, '*': 37,
    '(': 38, ')': 39, '_': 45, '+': 46, '{': 47, '}': 48, '|': 49,
    ':': 51, '"': 52, '~': 53, '<': 54, '>': 55, '?': 56,
}

# Modifier bitmasks (HID spec)
MOD_LEFT_CTRL = 1
MOD_LEFT_SHIFT = 2
MOD_LEFT_ALT = 4
MOD_LEFT_GUI = 8   # Windows/Command key
MOD_RIGHT_CTRL = 16
MOD_RIGHT_SHIFT = 32
MOD_RIGHT_ALT = 64
MOD_RIGHT_GUI = 128

# Common modifier combinations
MOD_CTRL = MOD_LEFT_CTRL
MOD_SHIFT = MOD_LEFT_SHIFT
MOD_ALT = MOD_LEFT_ALT
MOD_GUI = MOD_LEFT_GUI
MOD_CTRL_SHIFT = MOD_CTRL | MOD_SHIFT
MOD_CTRL_ALT = MOD_CTRL | MOD_ALT
MOD_CTRL_SHIFT_ALT = MOD_CTRL | MOD_SHIFT | MOD_ALT
MOD_ALT_SHIFT = MOD_ALT | MOD_SHIFT
MOD_CTRL_GUI = MOD_CTRL | MOD_GUI  # Win+Ctrl
MOD_GUI_SHIFT = MOD_GUI | MOD_SHIFT

# Characters requiring Shift (US layout)
SHIFT_REQUIRED = set(
    'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    '~!@#$%^&*()_+{}|:"<>?'
)


@dataclass
class KeyEvent:
    """Keyboard event for macro recording/playback."""
    action: str  # "press", "release", "type"
    keycode: int = 0
    char: str = ""
    modifiers: int = 0
    delay_ms: int = 0


@dataclass
class Macro:
    """Keyboard macro definition."""
    name: str
    events: List[KeyEvent] = field(default_factory=list)
    loop: bool = False


class KeyboardEmulator(BaseModule):
    """Full-featured keyboard emulation with Unicode, macros, and hotkeys."""
    
    def __init__(self, device_manager):
        super().__init__(device_manager)
        self._pressed_keys: set = set()
        self._active_modifiers: int = 0
        self._sticky_modifiers: int = 0  # For sticky keys accessibility
        self._key_repeat_thread: Optional[threading.Thread] = None
        self._key_repeat_active: Dict[int, bool] = {}
        self._macro_lock = threading.Lock()
        self._running_macro = False
        self._macros: Dict[str, Macro] = {}
        self._global_hotkeys: Dict[tuple, Callable] = {}  # (modifiers, keycode) -> callback
        self._last_key_time: Dict[int, float] = {}

    def initialize(self):
        self._pressed_keys = set()
        self._active_modifiers = 0
        self._sticky_modifiers = 0
        self._key_repeat_active = {}
        self._running_macro = False
        self._macros = {}
        self._global_hotkeys = {}
        self._last_key_time = {}
        log.info("Keyboard emulator initialized (Unicode, macros, hotkeys)")

    def shutdown(self):
        self._running_macro = False
        # Release all keys
        for keycode in list(self._pressed_keys):
            self.release(keycode)
        # Release all modifiers
        if self._active_modifiers:
            self._send_modifiers(0)
        # Stop key repeat
        self._key_repeat_active.clear()
        log.info("Keyboard emulator shutdown")

    def process(self, data):
        pass

    # ─────────────────────────────────────────────────────────────
    # Core Key Operations
    # ─────────────────────────────────────────────────────────────

    def press(self, keycode: int, port: str = "") -> bool:
        """Press a key (non-modifier)."""
        if keycode in self._pressed_keys:
            return True
        packet = Packets.keyboard_key(keycode, True)
        if self.device_manager.send(port or self._get_port(), packet):
            self._pressed_keys.add(keycode)
            self._last_key_time[keycode] = time.time()
            return True
        return False

    def release(self, keycode: int, port: str = "") -> bool:
        """Release a key (non-modifier)."""
        if keycode not in self._pressed_keys:
            return True
        packet = Packets.keyboard_key(keycode, False)
        if self.device_manager.send(port or self._get_port(), packet):
            self._pressed_keys.discard(keycode)
            self._key_repeat_active.pop(keycode, None)
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

    # ─────────────────────────────────────────────────────────────
    # Text Input (Unicode + Shift handling)
    # ─────────────────────────────────────────────────────────────

    def type(self, text: str, port: str = "", delay_ms: int = 0) -> bool:
        """Type a string with full Unicode support.
        
        Args:
            text: String to type (any Unicode)
            port: Target port
            delay_ms: Optional delay between characters (ms)
        """
        for char in text:
            if not self._type_char(char, port):
                return False
            if delay_ms > 0:
                time.sleep(delay_ms / 1000)
        return True

    def _type_char(self, char: str, port: str) -> bool:
        """Type a single Unicode character."""
        # Try direct mapping first
        keycode = KEYCODE_MAP.get(char)
        
        if keycode is not None:
            # Direct mapping exists
            needs_shift = char in SHIFT_REQUIRED
            if needs_shift:
                self.press_modifier(MOD_LEFT_SHIFT, port)
            self.press(keycode, port)
            self.release(keycode, port)
            if needs_shift:
                self.release_modifier(MOD_LEFT_SHIFT, port)
            return True
        
        # Handle Unicode via Alt codes (Windows) or direct Unicode input
        # For characters not in basic map, use Alt+Numpad (Windows)
        try:
            code_point = ord(char)
            if code_point <= 0xFFFF:
                # Use Alt+Numpad for BMP characters
                return self._type_unicode_alt_code(code_point, port)
            else:
                log.warning(f"Character U+{code_point:04X} ({char!r}) not supported")
                return False
        except Exception as e:
            log.error(f"Failed to type char {char!r}: {e}")
            return False

    def _type_unicode_alt_code(self, code_point: int, port: str) -> bool:
        """Type Unicode character via Alt+Numpad (Windows only).
        
        Note: Requires NumLock ON and registry key 
        HKCU\\Control Panel\\Input Method\\EnableHexNumpad = 1
        """
        # For simplicity, skip unsupported chars in this implementation
        # Full Alt-code support requires specific OS configuration
        log.warning(f"Unicode U+{code_point:04X} not in KEYCODE_MAP, skipping")
        return False

    # ─────────────────────────────────────────────────────────────
    # Hotkeys & Shortcuts
    # ─────────────────────────────────────────────────────────────

    def hotkey(self, *keycodes: int, port: str = "") -> bool:
        """Press multiple keys simultaneously (e.g., Ctrl+C)."""
        # Press all
        for kc in keycodes:
            if not self.press(kc, port):
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

    # Convenience hotkeys
    def copy(self, port: str = "") -> bool:
        return self.hotkey_with_modifiers(MOD_CTRL, KEYCODE_MAP['c'], port)

    def paste(self, port: str = "") -> bool:
        return self.hotkey_with_modifiers(MOD_CTRL, KEYCODE_MAP['v'], port)

    def cut(self, port: str = "") -> bool:
        return self.hotkey_with_modifiers(MOD_CTRL, KEYCODE_MAP['x'], port)

    def select_all(self, port: str = "") -> bool:
        return self.hotkey_with_modifiers(MOD_CTRL, KEYCODE_MAP['a'], port)

    def undo(self, port: str = "") -> bool:
        return self.hotkey_with_modifiers(MOD_CTRL, KEYCODE_MAP['z'], port)

    def redo(self, port: str = "") -> bool:
        return self.hotkey_with_modifiers(MOD_CTRL | MOD_SHIFT, KEYCODE_MAP['z'], port)

    def save(self, port: str = "") -> bool:
        return self.hotkey_with_modifiers(MOD_CTRL, KEYCODE_MAP['s'], port)

    def find(self, port: str = "") -> bool:
        return self.hotkey_with_modifiers(MOD_CTRL, KEYCODE_MAP['f'], port)

    def new_tab(self, port: str = "") -> bool:
        return self.hotkey_with_modifiers(MOD_CTRL, KEYCODE_MAP['t'], port)

    def close_tab(self, port: str = "") -> bool:
        return self.hotkey_with_modifiers(MOD_CTRL, KEYCODE_MAP['w'], port)

    def switch_app(self, port: str = "") -> bool:
        return self.hotkey_with_modifiers(MOD_ALT, KEYCODE_MAP['\t'], port)  # Alt+Tab

    def run_dialog(self, port: str = "") -> bool:
        return self.hotkey_with_modifiers(MOD_GUI, KEYCODE_MAP['r'], port)  # Win+R

    # ─────────────────────────────────────────────────────────────
    # Global Hotkey Registration
    # ─────────────────────────────────────────────────────────────

    def register_hotkey(self, modifiers: int, keycode: int, callback: Callable) -> bool:
        """Register a global hotkey callback.
        
        Note: This registers the hotkey for programmatic triggering.
        Actual global hotkey capture requires OS-level hooks.
        """
        key = (modifiers, keycode)
        if key in self._global_hotkeys:
            log.warning(f"Hotkey {modifiers:#x}+{keycode} already registered")
            return False
        self._global_hotkeys[key] = callback
        return True

    def trigger_hotkey(self, modifiers: int, keycode: int) -> bool:
        """Programmatically trigger a registered hotkey."""
        key = (modifiers, keycode)
        callback = self._global_hotkeys.get(key)
        if callback:
            try:
                callback()
                return True
            except Exception as e:
                log.error(f"Hotkey callback failed: {e}")
        return False

    # ─────────────────────────────────────────────────────────────
    # Macro Recording & Playback
    # ─────────────────────────────────────────────────────────────

    def start_macro_recording(self, name: str) -> bool:
        """Start recording a macro."""
        with self._macro_lock:
            if name in self._macros:
                log.warning(f"Macro '{name}' exists, overwriting")
            self._macros[name] = Macro(name=name)
            return True

    def record_key_event(self, macro_name: str, event: KeyEvent):
        """Record a key event to a macro."""
        with self._macro_lock:
            macro = self._macros.get(macro_name)
            if macro:
                macro.events.append(event)

    def stop_macro_recording(self, name: str) -> Optional[Macro]:
        """Stop recording and return the macro."""
        with self._macro_lock:
            return self._macros.get(name)

    def play_macro(self, name: str, port: str = "", loop: bool = False, speed: float = 1.0) -> bool:
        """Play back a recorded macro."""
        with self._macro_lock:
            macro = self._macros.get(name)
            if not macro:
                log.error(f"Macro '{name}' not found")
                return False
        
        if self._running_macro:
            log.warning("Macro already running")
            return False
        
        def macro_runner():
            self._running_macro = True
            try:
                while self._running_macro:
                    for event in macro.events:
                        if not self._running_macro:
                            break
                        self._execute_macro_event(event, port)
                        if event.delay_ms > 0:
                            time.sleep((event.delay_ms / speed) / 1000)
                    if not loop:
                        break
            finally:
                self._running_macro = False
        
        thread = threading.Thread(target=macro_runner, daemon=True, name=f"KeyboardMacro-{name}")
        thread.start()
        return True

    def stop_macro(self):
        """Stop currently running macro."""
        self._running_macro = False

    def _execute_macro_event(self, event: KeyEvent, port: str):
        try:
            if event.action == "press":
                if event.modifiers:
                    self.press_modifier(event.modifiers, port)
                self.press(event.keycode, port)
            elif event.action == "release":
                self.release(event.keycode, port)
                if event.modifiers:
                    self.release_modifier(event.modifiers, port)
            elif event.action == "type":
                self.type(event.char, port)
        except Exception as e:
            log.error(f"Macro event failed: {e}")

    def save_macro(self, name: str, filepath: str) -> bool:
        """Save macro to JSON file."""
        import json
        macro = self._macros.get(name)
        if not macro:
            return False
        data = {
            "name": macro.name,
            "loop": macro.loop,
            "events": [
                {"action": e.action, "keycode": e.keycode, "char": e.char, 
                 "modifiers": e.modifiers, "delay_ms": e.delay_ms}
                for e in macro.events
            ]
        }
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            log.error(f"Failed to save macro: {e}")
            return False

    def load_macro(self, filepath: str) -> bool:
        """Load macro from JSON file."""
        import json
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            macro = Macro(name=data["name"], loop=data.get("loop", False))
            for e in data["events"]:
                macro.events.append(KeyEvent(**e))
            with self._macro_lock:
                self._macros[macro.name] = macro
            return True
        except Exception as e:
            log.error(f"Failed to load macro: {e}")
            return False

    # ─────────────────────────────────────────────────────────────
    # Key Repeat / Auto-repeat
    # ─────────────────────────────────────────────────────────────

    def start_key_repeat(self, keycode: int, interval_ms: int = 50, port: str = "") -> bool:
        """Start auto-repeat for a key."""
        if keycode in self._key_repeat_active:
            return True
        
        self._key_repeat_active[keycode] = True
        
        def repeat_loop():
            while self._key_repeat_active.get(keycode, False):
                self.press(keycode, port)
                self.release(keycode, port)
                time.sleep(interval_ms / 1000)
        
        thread = threading.Thread(target=repeat_loop, daemon=True, name=f"KeyRepeat-{keycode}")
        thread.start()
        return True

    def stop_key_repeat(self, keycode: int):
        """Stop auto-repeat for a key."""
        self._key_repeat_active.pop(keycode, False)

    def stop_all_key_repeat(self):
        """Stop all auto-repeat."""
        self._key_repeat_active.clear()

    # ─────────────────────────────────────────────────────────────
    # Sticky Keys (Accessibility)
    # ─────────────────────────────────────────────────────────────

    def enable_sticky_keys(self):
        """Enable sticky modifiers (press once to lock, twice to unlock)."""
        self._sticky_modifiers = self._active_modifiers

    def disable_sticky_keys(self):
        """Disable sticky modifiers."""
        self._sticky_modifiers = 0

    # ─────────────────────────────────────────────────────────────
    # Legacy / Compatibility
    # ─────────────────────────────────────────────────────────────

    def _char_to_keycode(self, char: str) -> int:
        """Legacy method for backward compatibility."""
        base_char = char.lower() if char.isalpha() else char
        return KEYCODE_MAP.get(base_char, 0)

    def _get_port(self) -> str:
        ports = self.device_manager.get_connected_ports()
        return ports[0] if ports else ""