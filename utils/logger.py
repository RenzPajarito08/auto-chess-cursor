"""
utils/logger.py — Centralized logging configuration.

Provides a ``get_logger`` factory that returns named loggers sharing a
common format.  Output goes to both the console (coloured via level) and
an optional rotating log file.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional


_CONFIGURED = False  # module-level flag so we only configure once


def setup_logging(level: str = "INFO", log_file: Optional[Path] = None) -> None:
    """
    Configure the root logger once.

    Parameters
    ----------
    level : str
        Logging level name (DEBUG, INFO, WARNING, ERROR, CRITICAL).
    log_file : Path | None
        If provided, also write logs to this file.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    numeric_level = getattr(logging, level.upper(), logging.INFO)

    fmt = "[%(asctime)s] %(levelname)-8s | %(name)-28s | %(message)s"
    date_fmt = "%H:%M:%S"
    formatter = logging.Formatter(fmt, datefmt=date_fmt)

    root = logging.getLogger()
    root.setLevel(numeric_level)

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(numeric_level)
    console.setFormatter(formatter)
    root.addHandler(console)

    # File handler (optional)
    if log_file is not None:
        file_handler = logging.FileHandler(str(log_file), encoding="utf-8")
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """
    Return a named logger.

    Call ``setup_logging()`` first to configure handlers; if you forget,
    Python's default behaviour applies.
    """
    return logging.getLogger(name)
