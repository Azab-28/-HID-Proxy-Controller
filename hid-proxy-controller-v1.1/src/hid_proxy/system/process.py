"""Process enumeration for target selection."""
import psutil
from typing import List, Dict


class ProcessEnumerator:
    def enumerate(self) -> List[Dict]:
        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'exe', 'username']):
            try:
                info = proc.info
                if info['name'] and info['exe']:
                    processes.append({
                        'pid': info['pid'],
                        'name': info['name'],
                        'path': info['exe'],
                        'user': info['username']
                    })
            except Exception:
                pass
        return processes

    def filter_games(self, processes: List[Dict]) -> List[Dict]:
        game_keywords = ['game', 'play', 'steam', 'epic', 'origin', 'battle', 'riot']
        return [p for p in processes if any(k in p['name'].lower() for k in game_keywords)]