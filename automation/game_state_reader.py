"""
automation/game_state_reader.py — Read game state from Chess.com or Lichess.org via CDP.

Connects to a Chrome instance with ``--remote-debugging-port`` enabled,
reads the move list from site-specific web components or DOM elements,
and reconstructs the exact FEN using ``python-chess``.

This replaces unreliable vision-based FEN detection with a 100%
accurate game state derived from the DOM.
"""

from __future__ import annotations

import json
import re
import time
from typing import List, Optional, Tuple

import chess
import requests
import websocket  # websocket-client

from utils.logger import get_logger

log = get_logger(__name__)


class GameStateReader:
    """
    Reads the live game state from Chess.com by connecting to Chrome via CDP.

    Parameters
    ----------
    port : int
        Chrome DevTools Protocol debugging port (default 9222).
    """

    def __init__(self, port: int = 9222) -> None:
        self.port = port
        self._ws: Optional[websocket.WebSocket] = None
        self._ws_url: Optional[str] = None
        self._cmd_id = 0
        self._last_move_count = 0  # Track how many moves we've seen
        self._board = chess.Board()  # Tracks the true game state
        self._our_move_count = 0  # How many moves WE have played
        self.site = "chess.com"  # Default site

    # ------------------------------------------------------------------ #
    # Connection
    # ------------------------------------------------------------------ #
    def connect(self) -> bool:
        """
        Connect to Chrome's DevTools websocket.

        Returns True on success, False on failure.
        """
        try:
            # Get the list of debuggable pages
            resp = requests.get(
                f"http://localhost:{self.port}/json",
                timeout=5,
            )
            pages = resp.json()

            # Find a supported chess site page
            target = None
            for page in pages:
                url = page.get("url", "").lower()
                if "chess.com" in url:
                    target = page
                    self.site = "chess.com"
                    break
                elif "lichess.org" in url:
                    target = page
                    self.site = "lichess.org"
                    break

            if target is None:
                log.error(
                    "No supported chess tab (Chess.com or Lichess.org) found among %d pages.",
                    len(pages),
                )
                return False

            ws_url = target.get("webSocketDebuggerUrl")
            if not ws_url:
                log.error("No webSocketDebuggerUrl for Chess.com tab")
                return False

            self._ws_url = ws_url
            self._ws = websocket.create_connection(ws_url, timeout=10)
            log.info(
                "Connected to Chrome CDP — page: %s",
                target.get("title", target.get("url")),
            )
            return True

        except requests.ConnectionError:
            log.error(
                "Cannot connect to Chrome on port %d. "
                "Launch Chrome with: chrome.exe --remote-debugging-port=%d",
                self.port,
                self.port,
            )
            return False
        except Exception as exc:
            log.error("CDP connection error: %s", exc)
            return False

    def disconnect(self) -> None:
        """Close the websocket connection."""
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None
            log.info("CDP connection closed")

    def is_connected(self) -> bool:
        """Check if the websocket is still alive."""
        return self._ws is not None and self._ws.connected

    # ------------------------------------------------------------------ #
    # CDP Commands
    # ------------------------------------------------------------------ #
    def _send_command(self, method: str, params: Optional[dict] = None) -> dict:
        """Send a CDP command and return the result."""
        if not self._ws:
            raise RuntimeError("Not connected to Chrome")

        self._cmd_id += 1
        msg = {"id": self._cmd_id, "method": method}
        if params:
            msg["params"] = params

        self._ws.send(json.dumps(msg))

        # Wait for our response (skip events)
        while True:
            raw = self._ws.recv()
            data = json.loads(raw)
            if data.get("id") == self._cmd_id:
                return data
            # Ignore CDP events (they have no "id")

    def _evaluate_js(self, expression: str) -> Optional[str]:
        """Execute JavaScript in the page context and return the string result."""
        result = self._send_command(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True},
        )

        if "error" in result:
            log.error("JS evaluation error: %s", result["error"])
            return None

        value = result.get("result", {}).get("result", {}).get("value")
        return value

    # ------------------------------------------------------------------ #
    # Move List Reading
    # ------------------------------------------------------------------ #
    def read_move_list(self) -> Optional[List[str]]:
        """
        Read the move list from Chess.com's DOM.

        Returns a list of SAN moves like ``['d4', 'd5', 'Nc3', 'c6', ...]``
        or ``None`` on failure.
        """
        if self.site == "chess.com":
            js = r"""
            (() => {
                const moveList = document.querySelector('wc-simple-move-list, move-list');
                if (moveList) {
                    const plys = moveList.querySelectorAll('.node');
                    const moves = [];
                    for (const ply of plys) {
                        const figurine = ply.querySelector('[data-figurine]');
                        const figChar = figurine ? figurine.getAttribute('data-figurine') : '';
                        const textNode = ply.querySelector('.node-highlight-content');
                        const text = textNode ? textNode.textContent.trim() : '';
                        if (figChar || text) moves.push(figChar + text);
                    }
                    return JSON.stringify(moves);
                }
                const verticalMoves = document.querySelectorAll('.move-text-component, .move-node');
                if (verticalMoves.length > 0) {
                    const moves = [];
                    for (const node of verticalMoves) {
                        const fig = node.querySelector('[data-figurine]');
                        const figChar = fig ? fig.getAttribute('data-figurine') : '';
                        let text = node.textContent.trim();
                        moves.push(figChar + text);
                    }
                    return JSON.stringify(moves);
                }
                return null;
            })()
            """
        else: # lichess.org
            js = r"""
            (() => {
                // Lichess standard move list (handling obfuscated tags like kwdb)
                const moves = [];
                // Look for common Lichess move containers and tags
                const plys = document.querySelectorAll('l_move, .moves move, m2, kwdb, l4x > *');
                if (plys.length > 0) {
                    for (const ply of plys) {
                        // Skip move numbers (often tags like INDEX, i5z, or classes like index)
                        if (ply.tagName === 'INDEX' || 
                            ply.tagName === 'I5Z' || 
                            ply.classList.contains('index') ||
                            /^\d+\.?$/.test(ply.textContent.trim())) {
                            continue;
                        }
                        const text = ply.textContent.trim();
                        if (text && text.length <= 10) { // Safety check for SAN length
                            moves.push(text);
                        }
                    }
                    return JSON.stringify(moves);
                }
                
                // Fallback: If no plys but the board is visible, it's a new game (0 moves)
                if (document.querySelector('cg-board, .cg-wrap, .main-board')) {
                    return JSON.stringify([]);
                }
                
                return null;
            })()
            """

        raw = self._evaluate_js(js)
        if raw is None:
            return None

        try:
            moves = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

        cleaned = []
        for m in moves:
            san = self._clean_san(m)
            if san:
                cleaned.append(san)

        return cleaned

    @staticmethod
    def _clean_san(raw_move: str) -> Optional[str]:
        """
        Clean a raw SAN string. figurine chars are now handled by JS.
        """
        if not raw_move:
            return None

        # Strip whitespace, non-breaking spaces
        move = raw_move.strip().replace("\xa0", "").replace(" ", "")
        
        # Remove common annotations
        move = re.sub(r"[!?]+$", "", move)
        
        # Keep only standard notation chars
        move = re.sub(r"[^a-hA-H1-8KQRBNOxX+#=\-]", "", move)

        if not move:
            return None

        return move

    # ------------------------------------------------------------------ #
    # FEN Reconstruction
    # ------------------------------------------------------------------ #
    def get_game_state(self) -> Optional[Tuple[str, int, str]]:
        """
        Read the move list and reconstruct the current FEN.
        Uses a cached board to only process new moves.
        """
        moves = self.read_move_list()
        if moves is None:
            return None

        total_moves = len(moves)

        # Re-initialize or backtrack if the move list shrank or changed
        # (e.g. game restart or takeback)
        if total_moves < self._last_move_count:
            log.info("Move list shrank (%d -> %d), resetting board", self._last_move_count, total_moves)
            self._board = chess.Board()
            self._last_move_count = 0

        # Start from where we left off
        for i in range(self._last_move_count, total_moves):
            san = moves[i]
            try:
                self._board.push_san(san)
            except Exception:
                # Try to find nearest legal move
                recovered = self._try_recover_move(self._board, san)
                if recovered:
                    self._board.push(recovered)
                    log.info("Recovered move %d: '%s' → %s", i + 1, san, recovered)
                else:
                    log.error("Sync error at move %d: '%s'. Resetting board.", i + 1, san)
                    self._board = chess.Board()
                    self._last_move_count = 0
                    return None

        self._last_move_count = total_moves
        fen = self._board.fen()
        active = "w" if self._board.turn == chess.WHITE else "b"

        log.debug("Reconstructed FEN (%d moves): %s", total_moves, fen)
        return fen, total_moves, active

    @staticmethod
    def _try_recover_move(board: chess.Board, raw_san: str) -> Optional[chess.Move]:
        """
        Try various interpretations of a potentially malformed SAN move.

        Chess.com's figurine notation sometimes strips the piece letter,
        so 'c3' might actually be 'Nc3'. Try all piece prefixes.
        """
        # First try as-is
        for prefix in ["", "N", "B", "R", "Q", "K"]:
            candidate = prefix + raw_san
            try:
                return board.parse_san(candidate)
            except (chess.InvalidMoveError, chess.IllegalMoveError, chess.AmbiguousMoveError):
                continue

        # Try with 'x' for captures (e.g., "xg2" might be "Bxg2")
        if raw_san.startswith("x"):
            for prefix in ["N", "B", "R", "Q", "K"]:
                candidate = prefix + raw_san
                try:
                    return board.parse_san(candidate)
                except (chess.InvalidMoveError, chess.IllegalMoveError, chess.AmbiguousMoveError):
                    continue

        return None

    # ------------------------------------------------------------------ #
    # Turn Detection
    # ------------------------------------------------------------------ #
    def has_new_move(self) -> bool:
        """
        Check if a new move has been played since last check.

        This is the primary polling mechanism: call this in the main loop
        to detect when the opponent has moved.
        """
        moves = self.read_move_list()
        if moves is None:
            return False
        current_count = len(moves)
        return current_count > self._last_move_count

    def update_move_count(self, count: int) -> None:
        """Update the tracked move count after processing."""
        self._last_move_count = count

    # ------------------------------------------------------------------ #
    # Player Color Detection
    # ------------------------------------------------------------------ #
    def detect_player_color(self) -> Optional[str]:
        """
        Detect which color the player is by checking the board orientation.
        """
        if self.site == "chess.com":
            js = r"""
            (() => {
                const selectors = ['wc-chess-board', 'chess-board', '#board-layout-main', '.board', '[id^="board-"]', '.kb-board'];
                for (const sel of selectors) {
                    const board = document.querySelector(sel);
                    if (board) {
                        const isFlipped = board.classList.contains('flipped') || 
                                         board.classList.contains('is-flipped') ||
                                         board.classList.contains('flipped-board') ||
                                         board.getAttribute('flipped') === 'true';
                        return isFlipped ? 'black' : 'white';
                    }
                }
                return null;
            })()
            """
        else: # lichess.org
            js = r"""
            (() => {
                // 1. Primary check: status message (very reliable at start)
                const statusMsg = document.querySelector('.message, .announcement, .notification');
                if (statusMsg) {
                    const text = statusMsg.textContent.toLowerCase();
                    if (text.includes('you play the white')) return 'white';
                    if (text.includes('you play the black')) return 'black';
                }

                // 2. orientation class on wrap or board
                // Lichess uses 'orientation-black' or 'orientation-white'
                const orientationElem = document.querySelector('.orientation-black, .orientation-white, .cg-wrap, .cg-board, cg-container');
                if (orientationElem) {
                    if (orientationElem.classList.contains('orientation-black') || 
                        orientationElem.closest('.orientation-black')) {
                        return 'black';
                    }
                    if (orientationElem.classList.contains('orientation-white') || 
                        orientationElem.closest('.orientation-white')) {
                        return 'white';
                    }
                }

                // 3. coordinates
                const blackCoords = document.querySelector('coords.black, .coords.black');
                if (blackCoords) return 'black';
                
                const whiteCoords = document.querySelector('coords.white, .coords.white');
                if (whiteCoords) return 'white';

                // 4. Fallback: player status labels
                const blackBottom = document.querySelector('.player.black.bottom, .ruser-bottom.black, .player-bottom.black');
                if (blackBottom) return 'black';

                const whiteBottom = document.querySelector('.player.white.bottom, .ruser-bottom.white, .player-bottom.white');
                if (whiteBottom) return 'white';

                return null;
            })()
            """
        result = self._evaluate_js(js)
        if result:
            log.info("Detected board orientation on %s: %s", self.site, result)
        return result

    # ------------------------------------------------------------------ #
    # Context Manager
    # ------------------------------------------------------------------ #
    def __enter__(self) -> "GameStateReader":
        self.connect()
        return self

    def __exit__(self, *args: object) -> None:
        self.disconnect()
