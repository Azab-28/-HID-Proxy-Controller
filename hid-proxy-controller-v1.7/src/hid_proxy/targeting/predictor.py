"""Target movement prediction using smoothed velocity estimation (pure Python, no numpy)."""
from typing import List, Optional, Tuple


class TargetPredictor:
    def __init__(self, max_history: int = 10):
        self.max_history = max_history
        self.history: List[Tuple[float, float, float]] = []  # (x, y, timestamp)

    def update(self, x: float, y: float, timestamp: float) -> None:
        self.history.append((x, y, timestamp))
        if len(self.history) > self.max_history:
            self.history.pop(0)

    def predict(self, ahead_ms: float = 50.0) -> Optional[Tuple[float, float]]:
        if len(self.history) < 3:
            return None

        recent = self.history[-3:]
        t_diff = recent[-1][2] - recent[0][2]
        if t_diff <= 1e-6:
            return None

        vx = (recent[-1][0] - recent[0][0]) / t_diff
        vy = (recent[-1][1] - recent[0][1]) / t_diff

        horizon_s = ahead_ms / 1000.0
        pred_x = recent[-1][0] + vx * horizon_s
        pred_y = recent[-1][1] + vy * horizon_s
        return (pred_x, pred_y)

    def clear(self) -> None:
        self.history.clear()
