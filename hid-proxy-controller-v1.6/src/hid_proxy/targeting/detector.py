"""Target detection and humanization."""
import math
import random
from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict
import logging

from hid_proxy.targeting.humanizer import HumanizerConfig

log = logging.getLogger(__name__)


class Humanizer:
    def __init__(self, config: HumanizerConfig):
        self.cfg = config
        self.fatigue = 1.0
        self._last_target = None
        self._bezier_cache = {}

    def _bezier_point(self, p0, p1, p2, t):
        u = 1 - t
        return (u*u*p0[0] + 2*u*t*p1[0] + t*t*p2[0],
                u*u*p0[1] + 2*u*t*p1[1] + t*t*p2[1])

    def generate_path(self, start: Tuple[int, int], end: Tuple[int, int],
                      distance: float) -> List[Tuple[int, int]]:
        steps = min(max(int(distance / 6), 6), 18)
        t_vals = self._bezier_cache.get(steps, [i/steps for i in range(steps + 1)])

        ctrl_x = (start[0] + end[0]) / 2 + random.uniform(-30, 30)
        ctrl_y = (start[1] + end[1]) / 2 + random.uniform(-30, 30)
        control = (ctrl_x, ctrl_y)

        path = []
        for t in t_vals:
            x, y = self._bezier_point(start, control, end, t)
            noise_x = (0.4 * math.sin(t * 23.7) + 0.2 * math.sin(t * 47.3) +
                      0.1 * math.sin(t * 89.1) + random.uniform(-0.5, 0.5))
            noise_y = (0.4 * math.cos(t * 19.3) + 0.2 * math.cos(t * 41.9) +
                      0.1 * math.cos(t * 73.7) + random.uniform(-0.5, 0.5))
            noise_x *= self.fatigue * self.cfg.jitter_amplitude
            noise_y *= self.fatigue * self.cfg.jitter_amplitude
            noise_x += random.uniform(-1, 1)
            noise_y += random.uniform(-1, 1)
            path.append((int(x + noise_x), int(y + noise_y)))

        if random.random() < self.cfg.overshoot_prob and len(path) > 4:
            overshoot = random.randint(1, 3)
            path[-1] = (path[-1][0] + overshoot, path[-1][1] + overshoot)
            corr_steps = random.randint(1, 3)
            for i in range(corr_steps):
                factor = (i + 1) / corr_steps
                path.append((int(path[-1][0] - overshoot * factor),
                            int(path[-1][1] - overshoot * factor)))
        return path

    def should_pause(self) -> bool:
        return random.random() < self.cfg.pause_prob


class TargetDetector:
    def __init__(self, config_manager):
        self.config = config_manager
        self.humanizer = Humanizer(self._load_humanizer_config())

    def _load_humanizer_config(self) -> HumanizerConfig:
        t = self.config.get("targeting", {})
        return HumanizerConfig(
            sensitivity=t.get("sensitivity", 1.0),
            smoothing=t.get("smoothing", 0.35),
            deadzone=t.get("deadzone", 4),
            jitter_amplitude=t.get("jitter", 1.5),
            curve_type=t.get("curve", "bezier"),
            target_priority=t.get("priority", "closest"),
            fov_radius=t.get("fov", 300),
        )

    def select_target(self, candidates: List[dict]) -> Optional[dict]:
        if not candidates:
            return None
        best = None
        best_score = float('inf')
        for c in candidates:
            score = self._score_target(c)
            if score < best_score:
                best_score = score
                best = c
        return best

    def _score_target(self, target: dict) -> float:
        priority = self.humanizer.cfg.target_priority
        distance = target.get("distance", float('inf'))
        if priority == "closest":
            return distance
        elif priority == "head":
            return distance * (0.8 if target.get("has_head") else 1.0)
        return distance