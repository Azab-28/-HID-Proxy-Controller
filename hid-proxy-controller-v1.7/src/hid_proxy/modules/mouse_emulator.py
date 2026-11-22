"""Mouse emulation module with sub-pixel accumulator and macro runner."""
import logging
import struct
import threading
import time
from dataclasses import dataclass
from typing import List, Tuple

from hid_proxy.core.protocol import Command, Packet, Packets
from hid_proxy.modules.base import BaseModule

log = logging.getLogger(__name__)


@dataclass
class MacroStep:
    action: str  # "move", "click", "wheel", "wait"
    params: dict
    delay_ms: int = 0


class MouseEmulator(BaseModule):
    """Mouse emulation with sub-pixel precision and macro support."""

    CONSUMER_VOLUME_UP = 0xE9
    CONSUMER_VOLUME_DOWN = 0xEA
    CONSUMER_MUTE = 0xE2
    CONSUMER_PLAY_PAUSE = 0xCD
    CONSUMER_NEXT_TRACK = 0xB5
    CONSUMER_PREV_TRACK = 0xB6
    CONSUMER_STOP = 0xB7

    def __init__(self, device_manager):
        super().__init__(device_manager)
        self._subpixel_x = 0.0
        self._subpixel_y = 0.0
        self._last_pos = (0, 0)
        self._macro_lock = threading.Lock()
        self._running_macro = False

    def initialize(self) -> None:
        self._subpixel_x = 0.0
        self._subpixel_y = 0.0
        self._last_pos = (0, 0)
        log.info("Mouse emulator initialized")

    def shutdown(self) -> None:
        self._running_macro = False
        log.info("Mouse emulator shutdown")

    def process(self, data) -> None:
        if isinstance(data, dict) and "dx" in data and "dy" in data:
            self.move(data["dx"], data["dy"], data.get("port", ""))

    def move(self, dx: float, dy: float, port: str = "") -> bool:
        self._subpixel_x += dx
        self._subpixel_y += dy

        int_dx = int(self._subpixel_x)
        int_dy = int(self._subpixel_y)

        self._subpixel_x -= int_dx
        self._subpixel_y -= int_dy

        if int_dx == 0 and int_dy == 0:
            return True

        packet = Packets.mouse_move(int_dx, int_dy)
        self._last_pos = (self._last_pos[0] + int_dx, self._last_pos[1] + int_dy)
        return self.device_manager.send(port or self._get_port(), packet)

    def click(self, button: str = "left", pressed: bool = True, port: str = "") -> bool:
        btn_map = {"left": 1, "right": 2, "middle": 4, "back": 8, "forward": 16}
        packet = Packets.mouse_button(btn_map.get(button, 1), pressed)
        return self.device_manager.send(port or self._get_port(), packet)

    def double_click(self, button: str = "left", port: str = "", delay_ms: int = 50) -> bool:
        if not self.click(button, True, port):
            return False
        time.sleep(delay_ms / 1000.0)
        if not self.click(button, False, port):
            return False
        time.sleep(delay_ms / 1000.0)
        if not self.click(button, True, port):
            return False
        time.sleep(delay_ms / 1000.0)
        return self.click(button, False, port)

    def wheel(self, delta: int, port: str = "") -> bool:
        packet = Packets.mouse_wheel(delta)
        return self.device_manager.send(port or self._get_port(), packet)

    def wheel_smooth(self, delta: int, steps: int = 4, port: str = "") -> bool:
        if steps <= 0:
            return self.wheel(delta, port)
        sign = 1 if delta >= 0 else -1
        abs_delta = abs(delta)
        step = abs_delta // steps
        remainder = abs_delta % steps
        for i in range(steps):
            d = sign * (step + (1 if i < remainder else 0))
            if d != 0 and not self.wheel(d, port):
                return False
            time.sleep(0.01)
        return True

    def run_macro(self, steps: List[MacroStep], port: str = "", loop: bool = False) -> bool:
        with self._macro_lock:
            if self._running_macro:
                log.warning("Macro already running")
                return False
            self._running_macro = True

        def macro_runner() -> None:
            try:
                while self._running_macro:
                    for step in steps:
                        if not self._running_macro:
                            break
                        self._execute_macro_step(step, port)
                        if step.delay_ms > 0:
                            time.sleep(step.delay_ms / 1000.0)
                    if not loop:
                        break
            finally:
                self._running_macro = False

        threading.Thread(target=macro_runner, daemon=True, name="MouseMacro").start()
        return True

    def stop_macro(self) -> None:
        self._running_macro = False

    def _execute_macro_step(self, step: MacroStep, port: str) -> None:
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
                time.sleep(params.get("ms", 0) / 1000.0)
        except Exception as e:
            log.error(f"Macro step failed: {e}")

    def consumer_control(self, usage: int, pressed: bool, port: str = "") -> bool:
        packet = Packets.consumer_ctrl(usage, pressed)
        return self.device_manager.send(port or self._get_port(), packet)

    def volume_up(self, port: str = "") -> bool:
        return self.consumer_control(self.CONSUMER_VOLUME_UP, True, port) and self.consumer_control(
            self.CONSUMER_VOLUME_UP, False, port
        )

    def volume_down(self, port: str = "") -> bool:
        return self.consumer_control(self.CONSUMER_VOLUME_DOWN, True, port) and self.consumer_control(
            self.CONSUMER_VOLUME_DOWN, False, port
        )

    def mute_toggle(self, port: str = "") -> bool:
        return self.consumer_control(self.CONSUMER_MUTE, True, port) and self.consumer_control(
            self.CONSUMER_MUTE, False, port
        )

    def play_pause(self, port: str = "") -> bool:
        return self.consumer_control(self.CONSUMER_PLAY_PAUSE, True, port) and self.consumer_control(
            self.CONSUMER_PLAY_PAUSE, False, port
        )

    def next_track(self, port: str = "") -> bool:
        return self.consumer_control(self.CONSUMER_NEXT_TRACK, True, port) and self.consumer_control(
            self.CONSUMER_NEXT_TRACK, False, port
        )

    def prev_track(self, port: str = "") -> bool:
        return self.consumer_control(self.CONSUMER_PREV_TRACK, True, port) and self.consumer_control(
            self.CONSUMER_PREV_TRACK, False, port
        )

    def _get_port(self) -> str:
        ports = self.device_manager.get_connected_ports()
        return ports[0] if ports else ""

    def get_position(self) -> Tuple[int, int]:
        return self._last_pos

    def reset_position(self) -> None:
        self._last_pos = (0, 0)
        self._subpixel_x = 0.0
        self._subpixel_y = 0.0
