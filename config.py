"""
config.py — Central configuration for the chess automation system.

All tunable parameters live here: engine paths, timing, humanization,
hotkeys, and vision thresholds.  Values are loaded from an optional
``config.json`` in the project root; anything missing falls back to the
defaults defined in ``DEFAULT_CONFIG``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
CALIBRATION_FILE = PROJECT_ROOT / "calibration.json"
TEMPLATES_DIR = PROJECT_ROOT / "templates"
CONFIG_JSON = PROJECT_ROOT / "config.json"
LOG_FILE = PROJECT_ROOT / "auto_chess.log"


# ---------------------------------------------------------------------------
# Configuration dataclass
# ---------------------------------------------------------------------------
@dataclass
class Config:
    """Immutable(ish) bag of every tuneable knob in the system."""

    # -- Stockfish --------------------------------------------------------
    stockfish_path: str = r"C:\stockfish\stockfish-windows-x86-64-avx2.exe"
    stockfish_depth: int = 12
    stockfish_time_limit: float = 2.0          # seconds per move
    stockfish_threads: int = 1
    stockfish_hash_mb: int = 16
    stockfish_skill_level: int = 6             # 0-20

    # -- Player -----------------------------------------------------------
    player_color: str = "white"                # "white" or "black"

    # -- Vision -----------------------------------------------------------
    template_match_threshold: float = 0.70     # min confidence for a match
    board_detect_interval: float = 0.5         # seconds between scans
    screenshot_monitor: int = 0                # 0 = primary monitor

    # -- Humanization -----------------------------------------------------
    think_delay_mean: float = 0.8              # seconds
    think_delay_std: float = 0.4
    think_delay_min: float = 0.2
    think_delay_max: float = 3.0
    mouse_move_duration_min: float = 0.15      # seconds
    mouse_move_duration_max: float = 0.45
    coordinate_jitter_px: int = 4              # max random offset in pixels
    hesitation_probability: float = 0.15       # chance to pause mid-move
    hesitation_duration_min: float = 0.05
    hesitation_duration_max: float = 0.25
    bezier_curve_variance: float = 60.0        # px – control-point spread
    use_drag: bool = True                      # True = drag, False = click-click

    # -- Hotkeys ----------------------------------------------------------
    pause_hotkey: str = "ctrl+m"
    quit_hotkey: str = "ctrl+q"
    bullet_hotkey: str = "ctrl+b"
    emergency_corner_size: int = 5             # px – top-left corner zone

    # -- Logging ----------------------------------------------------------
    log_level: str = "INFO"
    log_to_file: bool = True

    # -- Loop control -----------------------------------------------------
    move_check_interval: float = 0.3           # seconds between FEN polls
    max_consecutive_errors: int = 10

    # -- CDP (Chrome DevTools Protocol) ------------------------------------
    chrome_debug_port: int = 9222              # Chrome remote debugging port
    use_dom_reader: bool = True                # Use DOM reader instead of vision

    # -- Calibration (populated at runtime) --------------------------------
    board_top_left: Optional[tuple[int, int]] = None
    board_bottom_right: Optional[tuple[int, int]] = None

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @property
    def board_region(self) -> Optional[tuple[int, int, int, int]]:
        """Return (x, y, w, h) or None if uncalibrated."""
        if self.board_top_left and self.board_bottom_right:
            x1, y1 = self.board_top_left
            x2, y2 = self.board_bottom_right
            return (x1, y1, x2 - x1, y2 - y1)
        return None

    @property
    def square_size(self) -> Optional[int]:
        """Pixel size of one square (assumes a perfect square board)."""
        region = self.board_region
        if region:
            return region[2] // 8
        return None

    def save(self, path: Optional[Path] = None) -> None:
        """Persist current config to JSON."""
        path = path or CONFIG_JSON
        data = {k: v for k, v in self.__dict__.items() if not k.startswith("_")}
        # Convert tuples to lists for JSON
        for key in ("board_top_left", "board_bottom_right"):
            if data.get(key) is not None:
                data[key] = list(data[key])
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Config":
        """Load from JSON, falling back to defaults for missing keys."""
        path = path or CONFIG_JSON
        cfg = cls()
        if path.exists():
            with open(path, "r", encoding="utf-8") as fh:
                data: dict = json.load(fh)
            for key, value in data.items():
                if hasattr(cfg, key):
                    # Convert lists back to tuples for coordinate fields
                    if key in ("board_top_left", "board_bottom_right") and value is not None:
                        value = tuple(value)
                    setattr(cfg, key, value)
        # Also try to load calibration data
        if CALIBRATION_FILE.exists() and cfg.board_top_left is None:
            with open(CALIBRATION_FILE, "r", encoding="utf-8") as fh:
                cal = json.load(fh)
            cfg.board_top_left = tuple(cal["top_left"])
            cfg.board_bottom_right = tuple(cal["bottom_right"])
            cfg.player_color = cal.get("player_color", cfg.player_color)
        return cfg
