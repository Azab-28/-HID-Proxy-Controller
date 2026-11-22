"""Humanizer configuration (shared with detector)."""
from dataclasses import dataclass

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
