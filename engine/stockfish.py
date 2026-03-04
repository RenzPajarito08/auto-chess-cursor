"""
engine/stockfish.py — Stockfish UCI wrapper.

Wraps ``python-chess``'s ``SimpleEngine`` to provide a clean interface
for obtaining the best move from a given FEN position.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import chess
import chess.engine

from utils.logger import get_logger

log = get_logger(__name__)


class StockfishEngine:
    """
    Manages a Stockfish UCI process.

    Parameters
    ----------
    path : str | Path
        Filesystem path to the Stockfish executable.
    depth : int
        Default search depth.
    time_limit : float
        Default time limit in seconds per move.
    threads : int
        Number of CPU threads for Stockfish.
    hash_mb : int
        Hash table size in MB.
    """

    def __init__(
        self,
        path: str | Path,
        depth: int = 12,
        time_limit: float = 2.0,
        threads: int = 1,
        hash_mb: int = 16,
    ) -> None:
        self.path = Path(path)
        self.depth = depth
        self.time_limit = time_limit
        self._engine: Optional[chess.engine.SimpleEngine] = None
        self._threads = threads
        self._hash_mb = hash_mb

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        """Launch the Stockfish process."""
        if self._engine is not None:
            log.warning("Engine already running")
            return

        if not self.path.exists():
            raise FileNotFoundError(
                f"Stockfish executable not found at {self.path}. "
                "Download it from https://stockfishchess.org/download/"
            )

        log.info("Starting Stockfish at %s", self.path)
        self._engine = chess.engine.SimpleEngine.popen_uci(str(self.path))

        # Configure engine options
        self._engine.configure({
            "Threads": self._threads,
            "Hash": self._hash_mb,
        })
        log.info(
            "Stockfish ready — threads=%d  hash=%dMB  depth=%d  time=%.1fs",
            self._threads,
            self._hash_mb,
            self.depth,
            self.time_limit,
        )

    def quit(self) -> None:
        """Gracefully terminate the engine process."""
        if self._engine is not None:
            try:
                self._engine.quit()
            except Exception:
                pass
            self._engine = None
            log.info("Stockfish stopped")

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def get_best_move(
        self,
        fen: str,
        depth: Optional[int] = None,
        time_limit: Optional[float] = None,
    ) -> Optional[str]:
        """
        Query Stockfish for the best move in UCI notation (e.g. ``'e2e4'``).

        Parameters
        ----------
        fen : str
            Full FEN string of the current position.
        depth : int | None
            Override the default depth.
        time_limit : float | None
            Override the default time limit.

        Returns
        -------
        str | None
            Best move in UCI format, or ``None`` on failure.
        """
        if self._engine is None:
            log.error("Engine not started — call start() first")
            return None

        d = depth or self.depth
        t = time_limit or self.time_limit

        try:
            board = chess.Board(fen)
            if not board.is_valid():
                log.warning("Invalid FEN: %s", fen)
                # Try to play anyway — Stockfish is lenient
        except ValueError as exc:
            log.error("FEN parse error: %s — %s", fen, exc)
            return None

        try:
            limit = chess.engine.Limit(depth=d, time=t)
            result = self._engine.play(board, limit)
            if result.move is None:
                log.warning("Stockfish returned no move (game over?)")
                return None
            move_uci = result.move.uci()
            log.info("Stockfish best move: %s  (depth=%d, time=%.1fs)", move_uci, d, t)
            return move_uci
        except chess.engine.EngineTerminatedError:
            log.error("Stockfish process terminated unexpectedly")
            self._engine = None
            return None
        except Exception as exc:
            log.error("Engine error: %s", exc)
            return None

    def get_evaluation(self, fen: str, depth: Optional[int] = None) -> Optional[str]:
        """
        Get the centipawn evaluation or mate score for a position.

        Returns a human-readable string like ``"+1.23"`` or ``"#3"``.
        """
        if self._engine is None:
            return None

        d = depth or self.depth
        try:
            board = chess.Board(fen)
            info = self._engine.analyse(board, chess.engine.Limit(depth=d))
            score = info.get("score")
            if score is None:
                return None
            pov = score.white()
            if pov.is_mate():
                return f"#{pov.mate()}"
            cp = pov.score()
            if cp is not None:
                return f"{cp / 100:+.2f}"
            return None
        except Exception as exc:
            log.error("Evaluation error: %s", exc)
            return None

    # ------------------------------------------------------------------ #
    # Context manager
    # ------------------------------------------------------------------ #
    def __enter__(self) -> "StockfishEngine":
        self.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.quit()
