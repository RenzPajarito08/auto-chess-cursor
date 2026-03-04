"""
vision/fen_builder.py — Convert an 8×8 piece matrix to FEN notation.

The matrix is in *screen* order (row 0 = top of screen).  For a white-
at-bottom board that means row 0 corresponds to rank 8.
"""

from __future__ import annotations

from typing import List

import chess
from typing import List

from utils.logger import get_logger

log = get_logger(__name__)


class FenBuilder:
    """
    Translates an 8×8 board matrix into a FEN string.

    Parameters
    ----------
    player_color : str
        ``"white"`` or ``"black"`` — controls how the matrix rows map to
        chess ranks.
    """

    def __init__(self, player_color: str = "white") -> None:
        self.player_color = player_color.lower()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def build(
        self,
        board: List[List[str]],
        active_color: str = "w",
        castling: str = "KQkq",
        en_passant: str = "-",
        halfmove: int = 0,
        fullmove: int = 1,
    ) -> str:
        """
        Build a full FEN string from the board matrix.

        Parameters
        ----------
        board : list[list[str]]
            8×8 matrix where ``board[0][0]`` is the top-left square
            visible on screen.
        active_color : str
            ``"w"`` or ``"b"`` — side to move.
        castling, en_passant : str
            Standard FEN fields (usually guessed / defaulted).
        halfmove, fullmove : int
            Move counters.

        Returns
        -------
        str
            Complete FEN string, e.g.
            ``"rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"``.
        """
        rows: List[str] = []

        # If playing as white, screen row 0 = rank 8 (already correct
        # FEN order).  If playing as black, screen row 0 = rank 1, so
        # we need to reverse.
        ordered = board if self.player_color == "white" else list(reversed(board))

        for rank in ordered:
            # Also reverse columns when playing black
            cols = rank if self.player_color == "white" else list(reversed(rank))
            rows.append(self._rank_to_fen(cols))

        piece_placement = "/".join(rows)
        fen = f"{piece_placement} {active_color} {castling} {en_passant} {halfmove} {fullmove}"
        
        valid, msg = self.validate_fen(fen)
        if not valid:
            log.warning("FEN validation warning: %s (FEN: %s)", msg, fen)
            
        log.debug("Built FEN: %s", fen)
        return fen

    @staticmethod
    def validate_fen(fen: str) -> Tuple[bool, str]:
        """
        Perform basic sanity checks on a FEN string.
        Returns (is_valid, message).
        """
        try:
            board = chess.Board(fen)
            if not board.is_valid():
                # Check for specific common vision errors
                pieces = fen.split(" ")[0]
                if "K" not in pieces:
                    return False, "White king missing"
                if "k" not in pieces:
                    return False, "Black king missing"
                return False, "Invalid piece placement or multiple kings"
            return True, "OK"
        except Exception as exc:
            return False, str(exc)

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #
    @staticmethod
    def _rank_to_fen(rank: List[str]) -> str:
        """
        Convert one rank (list of 8 piece chars) to the FEN rank string.

        Empty squares ``'.'`` are collapsed into digit counts.
        """
        fen_rank = ""
        empty_count = 0

        for char in rank:
            if char == ".":
                empty_count += 1
            else:
                if empty_count > 0:
                    fen_rank += str(empty_count)
                    empty_count = 0
                fen_rank += char

        if empty_count > 0:
            fen_rank += str(empty_count)

        return fen_rank

    # ------------------------------------------------------------------ #
    # Convenience
    # ------------------------------------------------------------------ #
    @staticmethod
    def board_to_string(board: List[List[str]]) -> str:
        """Pretty-print the board for debugging."""
        lines = []
        for row in board:
            lines.append(" ".join(piece if piece != "." else "·" for piece in row))
        return "\n".join(lines)
