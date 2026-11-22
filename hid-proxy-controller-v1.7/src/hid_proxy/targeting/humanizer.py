"""Humanizer configuration and natural trajectory generator."""
import math
import random
from dataclasses import dataclass
from typing import Dict, List, Tuple


@dataclass
class HumanizerConfig:
    sensitivity: float = 1.0
    smoothing: float = 0.35
    deadzone: int = 4
    jitter_amplitude: float = 1.5
    curve_type: str = "bezier"
    target_priority: str = "closest"
    fov_radius: int = 300
    pause_prob: float = 0.02
    overshoot_prob: float = 0.15


class Humanizer:
    """Generates human-like cursor trajectories without endpoint drift or overshoot accumulation."""

    def __init__(self, config: HumanizerConfig):
        self.cfg = config
        self.fatigue = 1.0
        self._last_target = None
        self._t_cache: Dict[int, List[float]] = {}

    def _get_t_values(self, steps: int) -> List[float]:
        if steps not in self._t_cache:
            # Ease-in-out timing distribution (smooth acceleration & deceleration)
            raw = [i / steps for i in range(steps + 1)]
            self._t_cache[steps] = [t * t * (3.0 - 2.0 * t) for t in raw]
        return self._t_cache[steps]

    @staticmethod
    def _bezier_point(
        p0: Tuple[float, float], p1: Tuple[float, float], p2: Tuple[float, float], t: float
    ) -> Tuple[float, float]:
        u = 1.0 - t
        return (
            u * u * p0[0] + 2.0 * u * t * p1[0] + t * t * p2[0],
            u * u * p0[1] + 2.0 * u * t * p1[1] + t * t * p2[1],
        )

    def generate_path(
        self, start: Tuple[int, int], end: Tuple[int, int], distance: float
    ) -> List[Tuple[int, int]]:
        if distance <= self.cfg.deadzone:
            return [end]

        steps = min(max(int(distance / 6), 6), 18)
        t_vals = self._get_t_values(steps)

        dx = end[0] - start[0]
        dy = end[1] - start[1]
        perp_x = -dy / max(distance, 1.0)
        perp_y = dx / max(distance, 1.0)

        if self.cfg.curve_type == "linear":
            arc_offset = 0.0
        else:
            max_arc = min(30.0, distance * 0.25)
            arc_offset = random.uniform(-max_arc, max_arc)

        control = (
            (start[0] + end[0]) / 2.0 + perp_x * arc_offset,
            (start[1] + end[1]) / 2.0 + perp_y * arc_offset,
        )

        path: List[Tuple[int, int]] = []
        for idx, t in enumerate(t_vals):
            if idx == 0:
                path.append(start)
                continue
            if idx == len(t_vals) - 1:
                path.append(end)
                continue

            x, y = self._bezier_point(start, control, end, t)
            # Envelope tapers noise smoothly to 0 at start (t=0) and end (t=1)
            envelope = math.sin(math.pi * t)
            noise_x = (
                0.4 * math.sin(t * 23.7)
                + 0.2 * math.sin(t * 47.3)
                + 0.1 * math.sin(t * 89.1)
                + random.uniform(-0.5, 0.5)
            )
            noise_y = (
                0.4 * math.cos(t * 19.3)
                + 0.2 * math.cos(t * 41.9)
                + 0.1 * math.cos(t * 73.7)
                + random.uniform(-0.5, 0.5)
            )
            scale = envelope * self.fatigue * self.cfg.jitter_amplitude
            path.append((int(round(x + noise_x * scale)), int(round(y + noise_y * scale))))

        # Proportional overshoot along travel direction, then smooth return to exact end
        if random.random() < self.cfg.overshoot_prob and len(path) > 4 and distance > 15:
            overshoot_dist = random.uniform(2.0, min(6.0, distance * 0.1))
            ux = dx / distance
            uy = dy / distance
            peak_x = end[0] + ux * overshoot_dist
            peak_y = end[1] + uy * overshoot_dist
            path[-1] = (int(round(peak_x)), int(round(peak_y)))

            corr_steps = random.randint(1, 3)
            for i in range(corr_steps):
                factor = (i + 1) / corr_steps
                cx = peak_x + (end[0] - peak_x) * factor
                cy = peak_y + (end[1] - peak_y) * factor
                path.append((int(round(cx)), int(round(cy))))

        return path

    def should_pause(self) -> bool:
        return random.random() < self.cfg.pause_prob
