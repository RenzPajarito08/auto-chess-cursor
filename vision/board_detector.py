"""
vision/board_detector.py — Chessboard detection and screenshot capture.

Uses ``mss`` for fast screen capture and the calibrated board region
from ``calibration.json``.  A fallback auto-detection path using OpenCV
contour analysis is included for initial setup.
"""

from __future__ import annotations

from typing import Optional, Tuple

import cv2
import mss
import numpy as np
from PIL import Image

from utils.logger import get_logger

log = get_logger(__name__)


class BoardDetector:
    """
    Captures the screen and extracts the chessboard region.

    Parameters
    ----------
    board_region : tuple[int, int, int, int] | None
        Pre-calibrated (x, y, w, h) of the board.  If ``None``, the
        detector attempts to find the board automatically.
    monitor : int
        ``mss`` monitor index (0 = all monitors stitched).
    """

    def __init__(
        self,
        board_region: Optional[Tuple[int, int, int, int]] = None,
        monitor: int = 0,
    ) -> None:
        self.board_region = board_region
        self.monitor = monitor
        self._sct = mss.mss()
        log.info("BoardDetector ready — region=%s", board_region)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def capture_screen(self) -> np.ndarray:
        """
        Grab a full-screen screenshot and return it as a BGR ``ndarray``.
        """
        mon = self._sct.monitors[self.monitor]
        raw = self._sct.grab(mon)
        img = np.array(raw)
        # mss gives BGRA; drop alpha channel
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

    def capture_board(self) -> Optional[np.ndarray]:
        """
        Return just the chessboard portion of the screen as a BGR image.

        If a calibrated region is set it is used directly; otherwise
        ``auto_detect_board`` is tried.
        """
        screen = self.capture_screen()

        if self.board_region:
            x, y, w, h = self.board_region
            board = screen[y : y + h, x : x + w]
            return board

        # Fallback: auto-detect
        region = self.auto_detect_board(screen)
        if region is not None:
            self.board_region = region
            x, y, w, h = region
            log.info("Auto-detected board at (%d, %d, %d, %d)", x, y, w, h)
            return screen[y : y + h, x : x + w]

        log.warning("Board not found on screen")
        return None

    def capture_board_region(self) -> Optional[np.ndarray]:
        """
        Capture *only* the board region directly (faster than full screen).
        Requires a calibrated region.
        """
        if not self.board_region:
            return self.capture_board()

        x, y, w, h = self.board_region
        region = {"left": x, "top": y, "width": w, "height": h}
        raw = self._sct.grab(region)
        img = np.array(raw)
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

    # ------------------------------------------------------------------ #
    # Auto-detection fallback
    # ------------------------------------------------------------------ #
    @staticmethod
    def auto_detect_board(screen: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
        """
        Try to find the chessboard by looking for the largest roughly-square
        rectangular contour with a grid pattern.

        Returns (x, y, w, h) or ``None``.
        """
        gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        edges = cv2.dilate(edges, kernel, iterations=2)

        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        best: Optional[Tuple[int, int, int, int]] = None
        best_area = 0

        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            area = w * h
            aspect = w / h if h > 0 else 0

            # Board should be roughly square and large enough
            if 0.85 < aspect < 1.15 and area > 40000 and area > best_area:
                best = (x, y, w, h)
                best_area = area

        return best

    # ------------------------------------------------------------------ #
    # Utility
    # ------------------------------------------------------------------ #
    def get_square_image(
        self, board_img: np.ndarray, row: int, col: int
    ) -> np.ndarray:
        """
        Extract the image of a single square (row 0 = top of screen).

        Parameters
        ----------
        board_img : ndarray
            The cropped board image.
        row, col : int
            Zero-indexed row/column (0,0 = top-left on screen).

        Returns
        -------
        ndarray
            Cropped square image.
        """
        h, w = board_img.shape[:2]
        sq_h = h // 8
        sq_w = w // 8
        y1 = row * sq_h
        y2 = y1 + sq_h
        x1 = col * sq_w
        x2 = x1 + sq_w
        return board_img[y1:y2, x1:x2]
