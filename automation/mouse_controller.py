"""
automation/mouse_controller.py — Physical mouse automation for chess moves.

Performs drag-and-drop (or click-click) moves using ``pyautogui`` with
human-like movement provided by ``Humanizer``.
"""

from __future__ import annotations

import time
from typing import Tuple

import pyautogui

from automation.humanizer import Humanizer
from utils.coordinates import SquareMapper
from utils.logger import get_logger

log = get_logger(__name__)

# Safety: disable pyautogui's fail-safe (we implement our own)
pyautogui.FAILSAFE = False
# Reduce pyautogui's built-in pause — we handle timing ourselves
pyautogui.PAUSE = 0.02


class MouseController:
    """
    Executes chess moves by controlling the real mouse cursor.

    Parameters
    ----------
    square_mapper : SquareMapper
        Translates algebraic squares to screen coordinates.
    humanizer : Humanizer
        Provides realistic timing and movement patterns.
    use_drag : bool
        If ``True``, use drag-and-drop.  If ``False``, click source then
        click destination.
    site : str
        The chess site being used ("chess.com" or "lichess.org").
    """

    def __init__(
        self,
        square_mapper: SquareMapper,
        humanizer: Humanizer,
        use_drag: bool = True,
        site: str = "chess.com",
    ) -> None:
        self.mapper = square_mapper
        self.human = humanizer
        self.use_drag = use_drag
        self.site = site
        log.info("MouseController ready — site=%s mode=%s", site, "drag" if use_drag else "click-click")

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def execute_move(self, uci_move: str, move_count: int = 0, is_premove: bool = False) -> None:
        """
        Execute a chess move given in UCI notation (e.g. ``'e2e4'``).

        The full sequence is:
        1. Think delay.
        2. Move cursor to source square (with Bézier curve).
        3. Pick up piece (mouseDown / click).
        4. Optional hesitation.
        5. Move cursor to destination square (with Bézier curve).
        6. Release piece (mouseUp / click).

        For promotion moves (5 chars like ``'e7e8q'``), the promotion
        piece selection is attempted automatically.
        """
        from_sq = uci_move[:2]
        to_sq = uci_move[2:4]
        promotion = uci_move[4] if len(uci_move) > 4 else None

        from_pos = self.mapper.square_to_screen(from_sq)
        to_pos = self.mapper.square_to_screen(to_sq)

        # Add jitter
        from_pos = self.human.jitter(*from_pos)
        to_pos = self.human.jitter(*to_pos)

        log.info(
            "Executing move %s → %s  screen (%d,%d)→(%d,%d)%s" + (" (PREMOVE)" if is_premove else ""),
            from_sq,
            to_sq,
            from_pos[0],
            from_pos[1],
            to_pos[0],
            to_pos[1],
            f" promo={promotion}" if promotion else "",
        )

        # Step 1: Think
        if not is_premove:
            self.human.think_delay(move_count)

        if self.use_drag:
            self._drag_move(from_pos, to_pos, is_premove=is_premove)
        else:
            self._click_click_move(from_pos, to_pos, is_premove=is_premove)

        # Handle promotion if needed
        if promotion:
            if not is_premove:
                time.sleep(0.3)
            self._handle_promotion(promotion, to_pos)

        log.info("Move %s executed", uci_move)

    # ------------------------------------------------------------------ #
    # Move implementations
    # ------------------------------------------------------------------ #
    def _drag_move(
        self, from_pos: Tuple[int, int], to_pos: Tuple[int, int], is_premove: bool = False
    ) -> None:
        """Perform a drag-and-drop move."""
        # Move to source via Bézier curve
        current = pyautogui.position()
        self._smooth_move(current, from_pos, is_premove=is_premove)
        
        if not self.human.bullet_mode and not is_premove:
            time.sleep(0.05)

        # Pick up
        pyautogui.mouseDown(button="left")
        
        if not (self.human.bullet_mode or is_premove):
            time.sleep(random_small())

        # Optional hesitation
        if not is_premove:
            self.human.maybe_hesitate()

        # Drag to destination via Bézier curve
        self._smooth_move(from_pos, to_pos, is_premove=is_premove)
        
        if not (self.human.bullet_mode or is_premove):
            time.sleep(random_small())

        # Release
        pyautogui.mouseUp(button="left")

    def _click_click_move(
        self, from_pos: Tuple[int, int], to_pos: Tuple[int, int], is_premove: bool = False
    ) -> None:
        """Perform a click-source then click-destination move."""
        current = pyautogui.position()

        # Click source
        self._smooth_move(current, from_pos, is_premove=is_premove)
        if not (self.human.bullet_mode or is_premove):
            time.sleep(0.05)
        pyautogui.click(from_pos[0], from_pos[1])

        # Brief pause between clicks
        if not (self.human.bullet_mode or is_premove):
            time.sleep(0.1 + random_small())
        elif not is_premove:
            time.sleep(0.02)

        # Optional hesitation
        if not is_premove:
            self.human.maybe_hesitate()

        # Click destination
        self._smooth_move(from_pos, to_pos, is_premove=is_premove)
        if not (self.human.bullet_mode or is_premove):
            time.sleep(0.05)
        pyautogui.click(to_pos[0], to_pos[1])

    # ------------------------------------------------------------------ #
    # Smooth mouse movement along Bézier curve
    # ------------------------------------------------------------------ #
    def _smooth_move(
        self, start: Tuple[int, int], end: Tuple[int, int], is_premove: bool = False
    ) -> None:
        """
        Move the mouse cursor from ``start`` to ``end`` along a smooth
        Bézier curve, with realistic speed variation.
        """
        # Bullet/Premove: fewer points, much faster
        points_count = 10 if (self.human.bullet_mode or is_premove) else 25
        path = self.human.bezier_path(start, end, num_points=points_count)
        
        duration = self.human.move_duration()
        if is_premove:
            duration *= 0.5 # Premoves are lightning fast

        # Speed profile
        for i, (x, y) in enumerate(path):
            t = i / max(len(path) - 1, 1)
            smoothed = t * t * (3.0 - 2.0 * t)
            delay = duration / len(path)

            speed_factor = 0.5 + 1.5 * (1.0 - abs(2.0 * smoothed - 1.0))
            adjusted_delay = delay * speed_factor

            pyautogui.moveTo(x, y, _pause=False)
            time.sleep(max(0.0005, adjusted_delay))

    # ------------------------------------------------------------------ #
    # Promotion handling
    # ------------------------------------------------------------------ #
    def _handle_promotion(self, piece: str, pos: Tuple[int, int]) -> None:
        """
        Attempt to select a promotion piece.
        """
        sq_size = self.mapper.square_h
        piece_lower = piece.lower()
        
        # Promotion menu offsets (multiples of square size)
        # Queen, Knight, Rook, Bishop
        offsets = {"q": 0, "n": 1, "r": 2, "b": 3}
        offset_idx = offsets.get(piece_lower, 0)

        promo_x = pos[0]
        
        if self.site == "chess.com":
            # Chess.com: vertical menu below the promotion square
            promo_y = pos[1] + int(offset_idx * sq_size)
        else:
            # Lichess.org: vertical menu, but direction depends on color/orientation
            # Typically, it expands towards the middle of the board.
            direction = 1 if pos[1] < self.mapper.top_left[1] + self.mapper.board_height / 2 else -1
            promo_y = pos[1] + int(offset_idx * sq_size * direction)

        log.info("Selecting promotion piece '%s' at (%d, %d) on %s", piece, promo_x, promo_y, self.site)
        self._smooth_move(pos, (promo_x, promo_y))
        
        if not self.human.bullet_mode:
            time.sleep(0.1)
            
        pyautogui.click(promo_x, promo_y)

    # ------------------------------------------------------------------ #
    # Safety
    # ------------------------------------------------------------------ #
    @staticmethod
    def check_emergency_stop(corner_size: int = 5) -> bool:
        """
        Return ``True`` if the mouse is in the top-left corner — the
        user has triggered an emergency stop.
        """
        x, y = pyautogui.position()
        return x <= corner_size and y <= corner_size


# -------------------------------------------------------------------------- #
# Helpers
# -------------------------------------------------------------------------- #
def random_small() -> float:
    """Small random delay (20–80 ms)."""
    import random
    return random.uniform(0.02, 0.08)
