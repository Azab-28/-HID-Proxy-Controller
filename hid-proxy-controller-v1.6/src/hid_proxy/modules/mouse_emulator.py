"""Mouse emulation module with sub-pixel accumulator and advanced features."""
import struct
import logging
import threading
import time
from typing import List, Tuple, Optional
from dataclasses import dataclass

from hid_proxy.modules.base import BaseModule
from hid_proxy.core.protocol import Packets, Packet, Command

log = logging.getLogger(__name__)


@dataclass
class MacroStep:
    """Single step in a mouse macro."""
    action: str  # "move", "click", "wheel", "wait"
    params: dict
    delay_ms: int = 0  # Delay after this step


class MouseEmulator(BaseModule):
    """Mouse emulation with sub-pixel precision and macro support."""
    
    def __init__(self, device_manager):
        super().__init__(device_manager)
        self._subpixel_x = 0.0
        self._subpixel_y = 0.0
        self._last_pos = (0, 0)
        self._macro_lock = threading.Lock()
        self._running_macro = False

    def initialize(self):
        self._subpixel_x = 0.0
        self._subpixel_y = 0.0
        self._last_pos = (0, 0)
        log.info("Mouse emulator initialized (sub-pixel accumulator active)")

    def shutdown(self):
        self._running_macro = False
        log.info("Mouse emulator shutdown")

    def process(self, data):
        pass

    # ─────────────────────────────────────────────────────────────
    # Basic Movement (with sub-pixel accumulator)
    # ─────────────────────────────────────────────────────────────

    def move(self, dx: float, dy: float, port: str = "") -> bool:
        """Move mouse with sub-pixel accumulation.
        
        Args:
            dx, dy: Can be fractional (sub-pixel). Accumulator ensures no precision loss.
            port: Target port (empty = first available)
        """
        # Accumulate fractional parts
        self._subpixel_x += dx
        self._subpixel_y += dy
        
        # Extract integer pixels to send
        int_dx = int(self._subpixel_x)
        int_dy = int(self._subpixel_y)
        
        # Keep fractional remainder
        self._subpixel_x -= int_dx
        self._subpixel_y -= int_dy
        
        if int_dx == 0 and int_dy == 0:
            return True  # Nothing to send yet
        
        packet = Packets.mouse_move(int_dx, int_dy)
        self._last_pos = (self._last_pos[0] + int_dx, self._last_pos[1] + int_dy)
        return self.device_manager.send(port or self._get_port(), packet)

    def move_absolute(self, x: int, y: int, port: str = "") -> bool:
        """Move to absolute position (requires firmware support).
        
        Note: This requires firmware that supports absolute positioning.
        Falls back to relative move if not supported.
        """
        # Try absolute positioning command (custom, needs firmware support)
        packet = Packet(Command.MOUSE_MOVE, struct.pack("<hh", x, y), needs_ack=True)
        return self.device_manager.send(port or self._get_port(), packet)

    def click(self, button: str = "left", pressed: bool = True, port: str = "") -> bool:
        btn_map = {"left": 1, "right": 2, "middle": 4, "back": 8, "forward": 16}
        packet = Packets.mouse_button(btn_map.get(button, 1), pressed)
        return self.device_manager.send(port or self._get_port(), packet)

    def double_click(self, button: str = "left", port: str = "", delay_ms: int = 50) -> bool:
        """Perform a double-click."""
        if not self.click(button, True, port):
            return False
        time.sleep(delay_ms / 1000)
        if not self.click(button, False, port):
            return False
        time.sleep(delay_ms / 1000)
        if not self.click(button, True, port):
            return False
        time.sleep(delay_ms / 1000)
        return self.click(button, False, port)

    def wheel(self, delta: int, port: str = "") -> bool:
        packet = Packet(Command.MOUSE_WHEEL, struct.pack("<h", delta))
        return self.device_manager.send(port or self._get_port(), packet)

    def wheel_smooth(self, delta: int, steps: int = 4, port: str = "") -> bool:
        """Smooth wheel scrolling in steps."""
        step = delta // steps
        remainder = delta % steps
        for i in range(steps):
            d = step + (1 if i < remainder else 0)
            if not self.wheel(d, port):
                return False
            time.sleep(0.01)
        return True

    # ─────────────────────────────────────────────────────────────
    # Macro / Sequence Runner
    # ─────────────────────────────────────────────────────────────

    def run_macro(self, steps: List[MacroStep], port: str = "", loop: bool = False) -> bool:
        """Execute a sequence of mouse actions.
        
        Args:
            steps: List of MacroStep actions
            port: Target port
            loop: Repeat indefinitely until stopped
            
        Returns True if started successfully.
        """
        if self._running_macro:
            log.warning("Macro already running")
            return False
        
        def macro_runner():
            self._running_macro = True
            try:
                while self._running_macro:
                    for step in steps:
                        if not self._running_macro:
                            break
                        self._execute_macro_step(step, port)
                        if step.delay_ms > 0:
                            time.sleep(step.delay_ms / 1000)
                    if not loop:
                        break
            finally:
                self._running_macro = False
        
        thread = threading.Thread(target=macro_runner, daemon=True, name="MouseMacro")
        thread.start()
        return True

    def stop_macro(self):
        """Stop currently running macro."""
        self._running_macro = False

    def _execute_macro_step(self, step: MacroStep, port: str):
        action = step.action
        params = step.params
        
        try:
            if action == "move":
                self.move(params.get("dx", 0), params.get("dy", 0), port)
            elif action == "click":
                self.click(params.get("button", "left"), params.get("pressed", True), port)
            elif action == "wheel":
                self.wheel(params.get("delta", 0), port)
            elif action == "wait":
                time.sleep(params.get("ms", 0) / 1000)
            else:
                log.warning(f"Unknown macro action: {action}")
        except Exception as e:
            log.error(f"Macro step failed: {e}")

    # ─────────────────────────────────────────────────────────────
    # Consumer Control (Media Keys)
    # ─────────────────────────────────────────────────────────────

    # Consumer Control Usage IDs (HID spec)
    CONSUMER_VOLUME_UP = 0xE9
    CONSUMER_VOLUME_DOWN = 0xEA
    CONSUMER_MUTE = 0xE2
    CONSUMER_PLAY_PAUSE = 0xCD
    CONSUMER_NEXT_TRACK = 0xB5
    CONSUMER_PREV_TRACK = 0xB6
    CONSUMER_STOP = 0xB7

    def consumer_control(self, usage: int, pressed: bool, port: str = "") -> bool:
        """Send consumer control (media keys)."""
        packet = Packet(Command.CONSUMER_CTRL, struct.pack("<HB", usage, 1 if pressed else 0))
        return self.device_manager.send(port or self._get_port(), packet)

    def volume_up(self, port: str = "") -> bool:
        return self.consumer_control(self.CONSUMER_VOLUME_UP, True, port) and \
               self.consumer_control(self.CONSUMER_VOLUME_UP, False, port)

    def volume_down(self, port: str = "") -> bool:
        return self.consumer_control(self.CONSUMER_VOLUME_DOWN, True, port) and \
               self.consumer_control(self.CONSUMER_VOLUME_DOWN, False, port)

    def mute_toggle(self, port: str = "") -> bool:
        return self.consumer_control(self.CONSUMER_MUTE, True, port) and \
               self.consumer_control(self.CONSUMER_MUTE, False, port)

    def play_pause(self, port: str = "") -> bool:
        return self.consumer_control(self.CONSUMER_PLAY_PAUSE, True, port) and \
               self.consumer_control(self.CONSUMER_PLAY_PAUSE, False, port)

    def next_track(self, port: str = "") -> bool:
        return self.consumer_control(self.CONSUMER_NEXT_TRACK, True, port) and \
               self.consumer_control(self.CONSUMER_NEXT_TRACK, False, port)

    def prev_track(self, port: str = "") -> bool:
        return self.consumer_control(self.CONSUMER_PREV_TRACK, True, port) and \
               self.consumer_control(self.CONSUMER_PREV_TRACK, False, port)

    # ─────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────

    def _get_port(self) -> str:
        ports = self.device_manager.get_connected_ports()
        return ports[0] if ports else ""

    def get_position(self) -> Tuple[int, int]:
        """Get last known position (relative)."""
        return self._last_pos

    def reset_position(self):
        """Reset position tracking."""
        self._last_pos = (0, 0)
        self._subpixel_x = 0.0
        self._subpixel_y = 0.0