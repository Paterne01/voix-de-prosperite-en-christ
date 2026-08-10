from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .config import absolute_path


def setup_logging(config: dict) -> logging.Logger:
    log_file = absolute_path(config["paths"]["logs"]) / "logs.txt"
    logger = logging.getLogger("voix")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(handler)
    return logger
