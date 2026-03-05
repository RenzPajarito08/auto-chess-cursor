"""
calibrate.py — Interactive calibration tool.

Workflow:
1. Takes a full-screen screenshot.
2. Opens it in a window and lets the user click the **top-left** and
   **bottom-right** corners of the chessboard.
3. Asks for the player colour (which colour is at the bottom).
4. Saves the calibration data to ``calibration.json``.
5. Extracts piece templates from the standard starting position and
   saves them to the ``templates/`` folder — both LIGHT and DARK square
   variants for each piece.

Run with:
    python calibrate.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import mss
import numpy as np

from config import Config

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
CALIBRATION_FILE = PROJECT_ROOT / "calibration.json"
TEMPLATES_DIR = PROJECT_ROOT / "templates"

# Starting position layout (from White's perspective, rank 8 at top):
# Row 0 = rank 8 (Black back rank)  …  Row 7 = rank 1 (White back rank)
STARTING_POSITION_WHITE = [
    ["bR", "bN", "bB", "bQ", "bK", "bB", "bN", "bR"],
    ["bP", "bP", "bP", "bP", "bP", "bP", "bP", "bP"],
    [None, None, None, None, None, None, None, None],
    [None, None, None, None, None, None, None, None],
    [None, None, None, None, None, None, None, None],
    [None, None, None, None, None, None, None, None],
    ["wP", "wP", "wP", "wP", "wP", "wP", "wP", "wP"],
    ["wR", "wN", "wB", "wQ", "wK", "wB", "wN", "wR"],
]

STARTING_POSITION_BLACK = [
    ["wR", "wN", "wB", "wK", "wQ", "wB", "wN", "wR"],
    ["wP", "wP", "wP", "wP", "wP", "wP", "wP", "wP"],
    [None, None, None, None, None, None, None, None],
    [None, None, None, None, None, None, None, None],
    [None, None, None, None, None, None, None, None],
    [None, None, None, None, None, None, None, None],
    ["bP", "bP", "bP", "bP", "bP", "bP", "bP", "bP"],
    ["bR", "bN", "bB", "bQ", "bK", "bB", "bN", "bR"],
]


def _square_color(row: int, col: int) -> str:
    """Return 'light' or 'dark' for a given row/col (0-indexed from screen top-left)."""
    # In chess, a8 (screen top-left when white at bottom) is a LIGHT square.
    # Light if (row + col) is even, dark if odd.
    return "light" if (row + col) % 2 == 0 else "dark"


# ---------------------------------------------------------------------------
# Click handler
# ---------------------------------------------------------------------------
class CornerPicker:
    """Collects two corner clicks from an OpenCV window."""

    def __init__(self) -> None:
        self.points: List[Tuple[int, int]] = []

    def on_click(self, event: int, x: int, y: int, flags: int, param: object) -> None:
        if event == cv2.EVENT_LBUTTONDOWN and len(self.points) < 2:
            self.points.append((x, y))
            print(f"  Corner {len(self.points)} selected: ({x}, {y})")


# ---------------------------------------------------------------------------
# Main calibration flow
# ---------------------------------------------------------------------------
def capture_screenshot() -> np.ndarray:
    """Grab the full screen and return as a BGR ndarray."""
    with mss.mss() as sct:
        mon = sct.monitors[0]
        raw = sct.grab(mon)
        img = np.array(raw)
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)


def pick_corners(screen: np.ndarray) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    """
    Display the screenshot and let the user click two corners.

    Returns (top_left, bottom_right).
    """
    picker = CornerPicker()

    # Resize for display if screen is very large
    h, w = screen.shape[:2]
    scale = 1.0
    if w > 1920:
        scale = 1920 / w
    display = cv2.resize(screen, None, fx=scale, fy=scale) if scale < 1.0 else screen.copy()

    win_name = "Click TOP-LEFT then BOTTOM-RIGHT of the chessboard (ESC to cancel)"
    cv2.namedWindow(win_name, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(win_name, picker.on_click)

    print("\n=== CALIBRATION ===")
    print("Click the TOP-LEFT corner of the chessboard, then the BOTTOM-RIGHT corner.")
    print("Press ESC to cancel.\n")

    while True:
        # Draw existing points
        vis = display.copy()
        for i, (px, py) in enumerate(picker.points):
            cv2.circle(vis, (px, py), 8, (0, 0, 255), 2)
            cv2.putText(vis, f"Corner {i+1}", (px + 12, py - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

        cv2.imshow(win_name, vis)
        key = cv2.waitKey(30)

        if key == 27:  # ESC
            cv2.destroyAllWindows()
            print("Calibration cancelled.")
            sys.exit(0)

        if len(picker.points) == 2:
            break

    cv2.destroyAllWindows()

    # Convert back to original scale
    p1 = (int(picker.points[0][0] / scale), int(picker.points[0][1] / scale))
    p2 = (int(picker.points[1][0] / scale), int(picker.points[1][1] / scale))

    # Ensure top-left / bottom-right ordering
    tl = (min(p1[0], p2[0]), min(p1[1], p2[1]))
    br = (max(p1[0], p2[0]), max(p1[1], p2[1]))

    return tl, br


def ask_site() -> str:
    """Ask the user which site they are calibrating for."""
    while True:
        print("\nWhich site are you calibrating for?")
        print("1. Chess.com")
        print("2. Lichess.org")
        choice = input("Choice (1/2): ").strip()
        if choice == "1":
            return "chess.com"
        if choice == "2":
            return "lichess.org"
        print("Please enter 1 or 2.")


def ask_player_color() -> str:
    """Ask the user which colour is at the bottom of the board."""
    while True:
        choice = input("\nWhich colour is at the BOTTOM of the board? (w)hite / (b)lack: ").strip().lower()
        if choice in ("w", "white"):
            return "white"
        if choice in ("b", "black"):
            return "black"
        print("Please enter 'w' or 'b'.")


def extract_templates(
    screen: np.ndarray,
    top_left: Tuple[int, int],
    bottom_right: Tuple[int, int],
    player_color: str,
    site: str,
) -> None:
    """
    Crop each square from the starting position and save piece templates
    to the ``templates/`` directory.

    For each piece type, saves BOTH a light-square and dark-square variant
    (e.g. ``wP_light.png`` and ``wP_dark.png``) so that template matching
    works regardless of the square colour the piece sits on.
    """
    cfg = Config.load()
    templates_dir = cfg.get_templates_dir(site)
    templates_dir.mkdir(parents=True, exist_ok=True)

    x1, y1 = top_left
    x2, y2 = bottom_right
    board_img = screen[y1:y2, x1:x2]

    h, w = board_img.shape[:2]
    sq_h = h // 8
    sq_w = w // 8

    layout = STARTING_POSITION_WHITE if player_color == "white" else STARTING_POSITION_BLACK

    # Track which (piece, square_color) combos we've already saved
    saved: set[str] = set()
    total = 0

    for row in range(8):
        for col in range(8):
            piece = layout[row][col]
            if piece is None:
                continue

            sq_color = _square_color(row, col)
            key = f"{piece}_{sq_color}"

            if key in saved:
                continue

            cy1 = row * sq_h
            cy2 = cy1 + sq_h
            cx1 = col * sq_w
            cx2 = cx1 + sq_w
            square_img = board_img[cy1:cy2, cx1:cx2]

            out_path = templates_dir / f"{key}.png"
            cv2.imwrite(str(out_path), square_img)
            saved.add(key)
            total += 1
            print(f"  Saved template: {key}  →  {out_path}")

    # Also save empty square templates (both colours)
    for row in range(2, 6):  # Rows 2-5 are empty in starting position
        for col in range(8):
            sq_color = _square_color(row, col)
            key = f"empty_{sq_color}"
            if key in saved:
                continue

            cy1 = row * sq_h
            cy2 = cy1 + sq_h
            cx1 = col * sq_w
            cx2 = cx1 + sq_w
            square_img = board_img[cy1:cy2, cx1:cx2]

            out_path = templates_dir / f"{key}.png"
            cv2.imwrite(str(out_path), square_img)
            saved.add(key)
            total += 1
            print(f"  Saved template: {key}  →  {out_path}")

    print(f"\n✓ {total} templates saved to {templates_dir}")


def save_calibration(
    top_left: Tuple[int, int],
    bottom_right: Tuple[int, int],
    player_color: str,
    site: str,
) -> None:
    """Update site-specific calibration in Config."""
    cfg = Config.load()
    cfg.update_site_config(site, top_left, bottom_right, player_color)
    print(f"\n✓ Calibration saved for {site}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    print("╔══════════════════════════════════════════╗")
    print("║   Chess Board Calibration Tool           ║")
    print("╚══════════════════════════════════════════╝")
    print("\nCapturing screen...")
    screen = capture_screenshot()
    print("Screenshot captured.\n")

    top_left, bottom_right = pick_corners(screen)
    print(f"\nBoard region: {top_left} → {bottom_right}")

    width = bottom_right[0] - top_left[0]
    height = bottom_right[1] - top_left[1]
    print(f"Board size: {width} × {height} px  |  Square: {width // 8} × {height // 8} px")

    site = ask_site()
    print(f"Calibrating for: {site}")

    player_color = ask_player_color()
    print(f"Player colour: {player_color}")

    save_calibration(top_left, bottom_right, player_color, site)

    print("\nExtracting piece templates from starting position...")
    print("(Make sure the board shows the STARTING POSITION!)\n")
    extract_templates(screen, top_left, bottom_right, player_color, site)

    print("\n" + "=" * 45)
    print("  Calibration complete!  You can now run:")
    print("    python main.py")
    print("=" * 45)


if __name__ == "__main__":
    main()
