"""
vision/piece_detector.py — Chess piece identification via template matching.

Uses OpenCV ``matchTemplate`` to compare each of the 64 board squares
against a library of piece templates stored in the ``templates/`` folder.

Templates are named ``{piece}_{sqcolor}.png`` — e.g. ``wP_light.png``,
``wP_dark.png`` — so each piece has variants for both square colours.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from utils.logger import get_logger

log = get_logger(__name__)

# Standard piece characters used throughout the system.
# Uppercase = white, lowercase = black, '.' = empty.
PIECE_CHARS = {
    "wP": "P", "wN": "N", "wB": "B", "wR": "R", "wQ": "Q", "wK": "K",
    "bP": "p", "bN": "n", "bB": "b", "bR": "r", "bQ": "q", "bK": "k",
}

# Reverse map for display
CHAR_NAMES: Dict[str, str] = {v: k for k, v in PIECE_CHARS.items()}

# Pattern for template filenames: e.g. "wP_light", "bK_dark", or legacy "wP"
_TEMPLATE_RE = re.compile(r"^((?:w|b)[PNBRQK])(?:_(light|dark))?$")


class PieceDetector:
    """
    Identifies chess pieces on each square of a board image.

    Templates can be named either:
    - ``wP_light.png`` / ``wP_dark.png``  (preferred — square-colour aware)
    - ``wP.png``  (legacy single-template fallback)

    Parameters
    ----------
    templates_dir : Path
        Directory containing piece template images.
    threshold : float
        Minimum ``matchTemplate`` score to accept a match.
    """

    def __init__(self, templates_dir: Path, threshold: float = 0.75) -> None:
        self.templates_dir = templates_dir
        self.threshold = threshold
        # Maps piece_char → list of template images (may have 1 or 2)
        self.templates: Dict[str, List[np.ndarray]] = {}
        # Empty-square templates for "is this square occupied?" check
        self.empty_templates: List[np.ndarray] = []
        self._load_templates()

    # ------------------------------------------------------------------ #
    # Template loading
    # ------------------------------------------------------------------ #
    def _load_templates(self) -> None:
        """Load all ``*.png`` templates from the templates directory."""
        if not self.templates_dir.exists():
            log.warning("Templates directory does not exist: %s", self.templates_dir)
            return

        piece_count = 0
        for path in sorted(self.templates_dir.glob("*.png")):
            stem = path.stem  # e.g. "wP_light", "bK_dark", "empty_light"

            # Handle empty square templates
            if stem.startswith("empty"):
                img = cv2.imread(str(path), cv2.IMREAD_COLOR)
                if img is not None:
                    self.empty_templates.append(img)
                    log.debug("Loaded empty template: %s", stem)
                continue

            m = _TEMPLATE_RE.match(stem)
            if not m:
                continue

            piece_name = m.group(1)  # e.g. "wP"
            if piece_name not in PIECE_CHARS:
                continue

            img = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if img is None:
                continue

            char = PIECE_CHARS[piece_name]
            if char not in self.templates:
                self.templates[char] = []
            self.templates[char].append(img)
            piece_count += 1
            log.debug("Loaded template: %s → '%s'  (%dx%d)", stem, char, img.shape[1], img.shape[0])

        total_pieces = len(self.templates)
        log.info(
            "Loaded %d template images for %d piece types (+%d empty) from %s",
            piece_count,
            total_pieces,
            len(self.empty_templates),
            self.templates_dir,
        )

    def reload_templates(self) -> None:
        """Re-read templates from disk (useful after re-calibration)."""
        self.templates.clear()
        self.empty_templates.clear()
        self._load_templates()

    # ------------------------------------------------------------------ #
    # Detection
    # ------------------------------------------------------------------ #
    def detect_piece(self, square_img: np.ndarray) -> Tuple[str, float]:
        """
        Identify the piece in a single square image.

        Compares against ALL template variants (light + dark) for each
        piece and picks the best match overall.

        Returns
        -------
        (piece_char, confidence) : (str, float)
            ``piece_char`` is one of ``PNBRQKpnbrqk`` or ``'.'`` for empty.
        """
        if not self.templates:
            return (".", 0.0)

        best_char = "."
        best_score = 0.0

        sq_h, sq_w = square_img.shape[:2]

        # Check against all piece templates (including light/dark variants)
        for char, tmpl_list in self.templates.items():
            for tmpl in tmpl_list:
                tmpl_resized = cv2.resize(tmpl, (sq_w, sq_h), interpolation=cv2.INTER_AREA)
                result = cv2.matchTemplate(square_img, tmpl_resized, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, _ = cv2.minMaxLoc(result)

                if max_val > best_score:
                    best_score = max_val
                    best_char = char

        # Also check empty templates — if empty matches better, it's empty
        for tmpl in self.empty_templates:
            tmpl_resized = cv2.resize(tmpl, (sq_w, sq_h), interpolation=cv2.INTER_AREA)
            result = cv2.matchTemplate(square_img, tmpl_resized, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(result)

            if max_val > best_score:
                best_score = max_val
                best_char = "."

        if best_score < self.threshold:
            return (".", best_score)

        return (best_char, best_score)

    def detect_board(self, board_img: np.ndarray) -> List[List[str]]:
        """
        Scan all 64 squares and return an 8×8 matrix of piece characters.

        ``board[0][0]`` corresponds to the top-left square *on screen*
        (a8 for white-at-bottom, a1 for black-at-bottom).

        Parameters
        ----------
        board_img : ndarray
            The full cropped board image (8×8 squares).

        Returns
        -------
        list[list[str]]
            8 rows × 8 cols of piece characters.
        """
        board, scores = self.detect_board_with_confidence(board_img)
        
        # Log the piece matrix and scores for debugging
        log.debug("Detected board matrix:\n%s", self._matrix_to_string(board))
        log.debug("Detection confidence scores:\n%s", self._matrix_to_string(scores))
        
        return board

    @staticmethod
    def _matrix_to_string(matrix: List[List[object]]) -> str:
        """Helper to format a matrix for logging."""
        return "\n".join(" ".join(f"{str(item):>5}" for item in row) for row in matrix)

    def detect_board_with_confidence(
        self, board_img: np.ndarray
    ) -> Tuple[List[List[str]], List[List[float]]]:
        """
        Like ``detect_board`` but also returns a confidence matrix.
        """
        h, w = board_img.shape[:2]
        sq_h = h // 8
        sq_w = w // 8

        board: List[List[str]] = []
        scores: List[List[float]] = []
        for row in range(8):
            rank_pieces: List[str] = []
            rank_scores: List[float] = []
            for col in range(8):
                y1 = row * sq_h
                y2 = y1 + sq_h
                x1 = col * sq_w
                x2 = x1 + sq_w
                square_img = board_img[y1:y2, x1:x2]

                piece, confidence = self.detect_piece(square_img)
                rank_pieces.append(piece)
                rank_scores.append(round(confidence, 3))
            board.append(rank_pieces)
            scores.append(rank_scores)

        return board, scores
