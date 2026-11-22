"""Logging setup."""
import logging
import sys
from pathlib import Path

def setup_logging(level: int = logging.INFO):
    log_dir = Path.home() / "AppData" / "Local" / "HIDProxyController" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "hid_proxy.log"
    
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout)
        ]
    )

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
