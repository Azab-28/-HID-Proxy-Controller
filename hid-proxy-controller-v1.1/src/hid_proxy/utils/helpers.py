"""Helper functions."""
import math
import random
from typing import Tuple

def clamp(value: float, min_val: float, max_val: float) -> float:
    return max(min_val, min(value, max_val))

def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t

def distance(p1: Tuple[int, int], p2: Tuple[int, int]) -> float:
    return math.hypot(p2[0] - p1[0], p2[1] - p1[1])

def smooth_step(t: float) -> float:
    return t * t * (3 - 2 * t)

def random_jitter(amplitude: float) -> Tuple[float, float]:
    return (random.uniform(-amplitude, amplitude), random.uniform(-amplitude, amplitude))
