"""
utils/coordinates.py — Chess-square ↔ screen-pixel mapping.

``SquareMapper`` takes the calibrated board corners and computes the
centre pixel for any algebraic square (a1–h8), respecting whether the
player is White (a1 bottom-left) or Black (a1 top-right).
"""

from __future__ import annotations

from typing import Tuple

from utils.logger import get_logger

log = get_logger(__name__)


class SquareMapper:
    """
    Converts algebraic chess notation to screen pixel coordinates.

    Parameters
    ----------
    top_left : tuple[int, int]
        Screen pixel of the board's top-left corner.
    bottom_right : tuple[int, int]
        Screen pixel of the board's bottom-right corner.
    player_color : str
        ``"white"`` means rank-8 is at the top of the screen (standard).
        ``"black"`` means rank-1 is at the top.
    """

    FILES = "abcdefgh"
    RANKS = "12345678"

    def __init__(
        self,
        top_left: Optional[Tuple[int, int]],
        bottom_right: Optional[Tuple[int, int]],
        player_color: str = "white",
    ) -> None:
        self.top_left = top_left
        self.bottom_right = bottom_right
        self.player_color = player_color.lower()
        self.board_width = 0
        self.board_height = 0
        self.square_w = 0.0
        self.square_h = 0.0

        if top_left and bottom_right:
            self._update_dimensions()

        log.debug(
            "SquareMapper initialised — board %s→%s  sq=%.1f×%.1f  color=%s",
            top_left,
            bottom_right,
            self.square_w,
            self.square_h,
            self.player_color,
        )

    def _update_dimensions(self) -> None:
        """Update square dimensions from corners."""
        if self.top_left and self.bottom_right:
            self.board_width = self.bottom_right[0] - self.top_left[0]
            self.board_height = self.bottom_right[1] - self.top_left[1]
            self.square_w = self.board_width / 8
            self.square_h = self.board_height / 8

    def update_corners(self, top_left: Tuple[int, int], bottom_right: Tuple[int, int]) -> None:
        """Update the board corners at runtime."""
        self.top_left = top_left
        self.bottom_right = bottom_right
        self._update_dimensions()
        log.info("SquareMapper updated: %s -> %s", top_left, bottom_right)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def square_to_screen(self, square: str) -> Tuple[int, int]:
        """
        Convert an algebraic square like ``'e4'`` to a screen ``(x, y)``
        pixel at the centre of that square.
        """
        file_idx = self.FILES.index(square[0])  # 0..7
        rank_idx = int(square[1]) - 1            # 0..7

        if self.player_color == "white":
            col = file_idx
            row = 7 - rank_idx       # rank 8 is row 0 on screen
        else:
            col = 7 - file_idx
            row = rank_idx           # rank 1 is row 0 on screen

        x = int(self.top_left[0] + col * self.square_w + self.square_w / 2)
        y = int(self.top_left[1] + row * self.square_h + self.square_h / 2)
        return (x, y)

    def screen_to_square(self, x: int, y: int) -> str:
        """
        Convert screen (x, y) back to an algebraic square.
        """
        col = int((x - self.top_left[0]) / self.square_w)
        row = int((y - self.top_left[1]) / self.square_h)
        col = max(0, min(7, col))
        row = max(0, min(7, row))

        if self.player_color == "white":
            file_idx = col
            rank_idx = 7 - row
        else:
            file_idx = 7 - col
            rank_idx = row

        return f"{self.FILES[file_idx]}{rank_idx + 1}"

    def square_pixel_region(self, square: str) -> Tuple[int, int, int, int]:
        """
        Return the bounding box (x1, y1, x2, y2) of a square on screen.
        """
        cx, cy = self.square_to_screen(square)
        half_w = int(self.square_w / 2)
        half_h = int(self.square_h / 2)
        return (cx - half_w, cy - half_h, cx + half_w, cy + half_h)
