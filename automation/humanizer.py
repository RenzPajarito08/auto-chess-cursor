"""
automation/humanizer.py — Human-like behaviour patterns.

Generates realistic timing, mouse movement curves, and small
imperfections to make the automation appear natural.
"""

from __future__ import annotations

import random
import time
from typing import List, Tuple

from utils.logger import get_logger

log = get_logger(__name__)


class Humanizer:
    """
    Produces human-like delays, cursor paths, and coordinate jitter.

    Parameters
    ----------
    think_delay_mean, think_delay_std : float
        Normal-distribution parameters for pre-move "thinking" time.
    think_delay_min, think_delay_max : float
        Clamp range for the thinking delay.
    move_duration_min, move_duration_max : float
        Range for how long a mouse drag takes (seconds).
    jitter_px : int
        Maximum random pixel offset added to click targets.
    hesitation_prob : float
        Probability (0–1) of a brief hesitation mid-move.
    hesitation_min, hesitation_max : float
        Duration range for a mid-move hesitation.
    bezier_variance : float
        Spread (in pixels) of Bézier control points — higher values
        produce more curved paths.
    """

    def __init__(
        self,
        think_delay_mean: float = 0.8,
        think_delay_std: float = 0.4,
        think_delay_min: float = 0.2,
        think_delay_max: float = 3.0,
        move_duration_min: float = 0.15,
        move_duration_max: float = 0.45,
        jitter_px: int = 4,
        hesitation_prob: float = 0.15,
        hesitation_min: float = 0.05,
        hesitation_max: float = 0.25,
        bezier_variance: float = 60.0,
    ) -> None:
        self.think_delay_mean = think_delay_mean
        self.think_delay_std = think_delay_std
        self.think_delay_min = think_delay_min
        self.think_delay_max = think_delay_max
        self.move_duration_min = move_duration_min
        self.move_duration_max = move_duration_max
        self.jitter_px = jitter_px
        self.hesitation_prob = hesitation_prob
        self.hesitation_min = hesitation_min
        self.hesitation_max = hesitation_max
        self.bezier_variance = bezier_variance
        self.bullet_mode = False
        
        # Bullet mode optimizations
        self.long_thought_count = 0
        self.max_long_thoughts = random.randint(6, 10)
        self.last_game_id = None  # To reset counts between games if needed

    # ------------------------------------------------------------------ #
    # Timing
    # ------------------------------------------------------------------ #
    def think_delay(self, move_count: int = 0) -> float:
        """
        Return a random 'thinking' delay and sleep for that duration.

        The delay follows a normal distribution clamped to
        ``[think_delay_min, think_delay_max]``.
        """
        if self.bullet_mode:
            # Bullet mode timing
            # If it's early (opening), play fast but not too fast
            if move_count <= 10:
                delay = random.uniform(0.1, 0.4)
            else:
                # Mid/End game logic:
                # 85% chance of a very fast move (0.05s - 0.2s)
                # 15% chance of a "longer" thought (1.0s - 3.5s) if we have credits left
                if self.long_thought_count < self.max_long_thoughts and random.random() < 0.15:
                    delay = random.uniform(1.0, 3.5)
                    self.long_thought_count += 1
                else:
                    delay = random.uniform(0.05, 0.2)
        else:
            delay = random.gauss(self.think_delay_mean, self.think_delay_std)
            delay = max(self.think_delay_min, min(self.think_delay_max, delay))
            
        log.debug("Thinking for %.2fs (Bullet: %s, Move: %d, Long pauses: %d/%d)", 
                  delay, self.bullet_mode, move_count, self.long_thought_count, self.max_long_thoughts)
        time.sleep(delay)
        return delay

    def move_duration(self) -> float:
        """Return a random duration for a mouse move (not including pauses)."""
        if self.bullet_mode:
            # Bullet mode: fast movement (0.08s to 0.15s)
            return random.uniform(0.08, 0.15)
        return random.uniform(self.move_duration_min, self.move_duration_max)

    def maybe_hesitate(self) -> bool:
        """
        Randomly pause mid-move (simulating hesitation).

        Returns ``True`` if a hesitation actually occurred.
        """
        if self.bullet_mode:
            return False
            
        if random.random() < self.hesitation_prob:
            pause = random.uniform(self.hesitation_min, self.hesitation_max)
            log.debug("Hesitating for %.2fs", pause)
            time.sleep(pause)
            return True
        return False

    # ------------------------------------------------------------------ #
    # Coordinate jitter
    # ------------------------------------------------------------------ #
    def jitter(self, x: int, y: int) -> Tuple[int, int]:
        """
        Add a small random offset to ``(x, y)``.

        The offset is drawn uniformly from ``[-jitter_px, +jitter_px]``
        on each axis.
        """
        dx = random.randint(-self.jitter_px, self.jitter_px)
        dy = random.randint(-self.jitter_px, self.jitter_px)
        return (x + dx, y + dy)

    # ------------------------------------------------------------------ #
    # Bézier curve path generation
    # ------------------------------------------------------------------ #
    def bezier_path(
        self,
        start: Tuple[int, int],
        end: Tuple[int, int],
        num_points: int = 30,
    ) -> List[Tuple[int, int]]:
        """
        Generate a smooth Bézier curve between ``start`` and ``end``.

        Uses a cubic Bézier with two random control points offset
        perpendicular to the line between start and end.

        Parameters
        ----------
        start, end : (int, int)
            Pixel coordinates.
        num_points : int
            Number of intermediate waypoints on the curve.

        Returns
        -------
        list[(int, int)]
            Ordered pixel coordinates along the curve.
        """
        sx, sy = start
        ex, ey = end

        # Midpoint
        mx = (sx + ex) / 2
        my = (sy + ey) / 2

        # Perpendicular direction
        dx = ex - sx
        dy = ey - sy
        length = (dx ** 2 + dy ** 2) ** 0.5 or 1.0
        perp_x = -dy / length
        perp_y = dx / length

        # Two control points spread around the midpoint
        v = self.bezier_variance
        offset1 = random.gauss(0, v * 0.5)
        offset2 = random.gauss(0, v * 0.5)

        # Shift control points along the line at ~1/3 and ~2/3
        c1x = sx + dx * 0.3 + perp_x * offset1
        c1y = sy + dy * 0.3 + perp_y * offset1
        c2x = sx + dx * 0.7 + perp_x * offset2
        c2y = sy + dy * 0.7 + perp_y * offset2

        points: List[Tuple[int, int]] = []
        for i in range(num_points + 1):
            t = i / num_points
            inv = 1.0 - t
            # Cubic Bézier formula
            bx = (
                inv ** 3 * sx
                + 3 * inv ** 2 * t * c1x
                + 3 * inv * t ** 2 * c2x
                + t ** 3 * ex
            )
            by = (
                inv ** 3 * sy
                + 3 * inv ** 2 * t * c1y
                + 3 * inv * t ** 2 * c2y
                + t ** 3 * ey
            )
            points.append((int(bx), int(by)))

        return points

    # ------------------------------------------------------------------ #
    # Pre-move "warm-up" — small random drift before picking up the piece
    # ------------------------------------------------------------------ #
    def pre_move_drift(self, target: Tuple[int, int]) -> Tuple[int, int]:
        """
        Return a point slightly off from ``target`` to move to first,
        simulating the mouse drifting toward the square before settling.
        """
        drift_px = random.randint(5, 15)
        angle = random.uniform(0, 6.283)
        import math

        dx = int(drift_px * math.cos(angle))
        dy = int(drift_px * math.sin(angle))
        return (target[0] + dx, target[1] + dy)
