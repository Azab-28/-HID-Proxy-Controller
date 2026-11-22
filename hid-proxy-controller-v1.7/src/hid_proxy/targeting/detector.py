"""Target selection and scoring."""
import logging
from typing import List, Optional

from hid_proxy.targeting.humanizer import Humanizer, HumanizerConfig

log = logging.getLogger(__name__)


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

    def reload_config(self) -> None:
        self.humanizer = Humanizer(self._load_humanizer_config())

    def select_target(self, candidates: List[dict]) -> Optional[dict]:
        if not candidates:
            return None
        fov = self.humanizer.cfg.fov_radius
        best = None
        best_score = float("inf")
        for c in candidates:
            dist = c.get("distance", float("inf"))
            if dist > fov:
                continue
            score = self._score_target(c)
            if score < best_score:
                best_score = score
                best = c
        return best

    def _score_target(self, target: dict) -> float:
        priority = self.humanizer.cfg.target_priority
        distance = target.get("distance", float("inf"))
        if priority == "head":
            return distance * (0.8 if target.get("has_head") else 1.0)
        return distance
