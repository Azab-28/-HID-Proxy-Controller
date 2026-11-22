"""Target movement prediction."""
from typing import List, Tuple, Optional
import numpy as np

class TargetPredictor:
    def __init__(self, max_history: int = 10):
        self.max_history = max_history
        self.history: List[Tuple[float, float, float]] = []  # (x, y, timestamp)
    
    def update(self, x: float, y: float, timestamp: float):
        self.history.append((x, y, timestamp))
        if len(self.history) > self.max_history:
            self.history.pop(0)
    
    def predict(self, ahead_ms: float = 50) -> Optional[Tuple[float, float]]:
        if len(self.history) < 3:
            return None
        
        # Simple linear prediction based on recent velocity
        recent = self.history[-3:]
        t_diff = recent[-1][2] - recent[0][2]
        if t_diff <= 0:
            return None
        
        vx = (recent[-1][0] - recent[0][0]) / t_diff
        vy = (recent[-1][1] - recent[0][1]) / t_diff
        
        pred_x = recent[-1][0] + vx * (ahead_ms / 1000)
        pred_y = recent[-1][1] + vy * (ahead_ms / 1000)
        
        return (pred_x, pred_y)
    
    def clear(self):
        self.history.clear()
