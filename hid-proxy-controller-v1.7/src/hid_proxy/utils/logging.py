"""Logging setup with rotating file handler and safe console stream."""
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


def setup_logging(level: int = logging.INFO, log_dir: Optional[Path] = None) -> None:
    """Configure root logger with rotation and GUI-safe stdout handling."""
    if log_dir is None:
        try:
            from platformdirs import user_log_dir
            log_dir = Path(user_log_dir("HIDProxyController", appauthor=False))
        except ImportError:
            log_dir = Path.home() / "AppData" / "Local" / "HIDProxyController" / "logs"

    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "hid_proxy.log"

    root = logging.getLogger()
    root.setLevel(level)

    # Clear existing handlers to avoid duplicate logs on re-init
    for h in list(root.handlers):
        root.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # In Nuitka --windows-console-mode=disable, sys.stdout can be None
    if sys.stdout is not None:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
