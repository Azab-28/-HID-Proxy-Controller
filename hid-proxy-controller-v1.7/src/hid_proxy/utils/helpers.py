"""Helper functions."""
import math
import random
from typing import Tuple


def clamp(value: float, min_val: float, max_val: float) -> float:
    return max(min_val, min(value, max_val))


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def distance(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    return math.hypot(p2[0] - p1[0], p2[1] - p1[1])


def smooth_step(t: float) -> float:
    t = clamp(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def random_jitter(amplitude: float) -> Tuple[float, float]:
    return (random.uniform(-amplitude, amplitude), random.uniform(-amplitude, amplitude))
