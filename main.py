"""
main.py — Chess automation orchestrator.

Runs the main game loop:
  connect to Chess.com via CDP → read move list → build FEN → query Stockfish → execute move

Usage:
    1. Launch Chrome with:  chrome.exe --remote-debugging-port=9222 --remote-allow-origins=*
    2. Navigate to Chess.com and start a game
    3. Run:  python main.py

    Ctrl+M  —  Pause / Resume
    Ctrl+Q  —  Quit
"""

from __future__ import annotations

import random
import sys
import threading
import time
from pathlib import Path

import keyboard

from automation.game_state_reader import GameStateReader
from automation.humanizer import Humanizer
from automation.mouse_controller import MouseController
from config import CALIBRATION_FILE, LOG_FILE, TEMPLATES_DIR, Config
from engine.stockfish import StockfishEngine
from utils.coordinates import SquareMapper
from utils.logger import get_logger, setup_logging


class ChessBot:
    """
    Main controller that ties every subsystem together.

    Parameters
    ----------
    config : Config
        Application configuration.
    """

    def __init__(self, config: Config) -> None:
        self.cfg = config
        self.paused = False
        self.running = True
        self.auto_next_game = False
        self.last_fen: str = ""
        self.move_count: int = 0
        self.consecutive_errors: int = 0
        self._last_total_moves: int = -1  # Total moves seen in the DOM (-1 = not yet started)
        self._game_over_detected_at: float = 0.0  # Timestamp when game-over button first seen
        self._game_over_delay: float = 0.0  # Random delay before clicking next game
        self._pending_color_detection: bool = True  # Start with True to detect on first game

        # --- Build subsystems ---
        self._validate_config()

        # CDP Game State Reader (primary FEN source)
        self.game_reader = GameStateReader(
            port=self.cfg.chrome_debug_port,
        )

        self.engine = StockfishEngine(
            path=self.cfg.stockfish_path,
            depth=self.cfg.stockfish_depth,
            time_limit=self.cfg.stockfish_time_limit,
            threads=self.cfg.stockfish_threads,
            hash_mb=self.cfg.stockfish_hash_mb,
            skill_level=self.cfg.stockfish_skill_level,
        )

        mapper = SquareMapper(
            top_left=self.cfg.board_top_left,  # type: ignore[arg-type]
            bottom_right=self.cfg.board_bottom_right,  # type: ignore[arg-type]
            player_color=self.cfg.player_color,
        )

        humanizer = Humanizer(
            think_delay_mean=self.cfg.think_delay_mean,
            think_delay_std=self.cfg.think_delay_std,
            think_delay_min=self.cfg.think_delay_min,
            think_delay_max=self.cfg.think_delay_max,
            move_duration_min=self.cfg.mouse_move_duration_min,
            move_duration_max=self.cfg.mouse_move_duration_max,
            jitter_px=self.cfg.coordinate_jitter_px,
            hesitation_prob=self.cfg.hesitation_probability,
            hesitation_min=self.cfg.hesitation_duration_min,
            hesitation_max=self.cfg.hesitation_duration_max,
            bezier_variance=self.cfg.bezier_curve_variance,
        )

        self.mouse = MouseController(
            square_mapper=mapper,
            humanizer=humanizer,
            use_drag=self.cfg.use_drag,
            site=self.cfg.detected_site,
        )

        self.log = get_logger("ChessBot")

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #
    def _validate_config(self, site: Optional[str] = None) -> None:
        """Ensure the bot has calibration/templates for the active site."""
        # If site is provided, we check that specific site's calibration
        if site:
            if not self.cfg.apply_site_config(site):
                print(
                    f"\n❌  No calibration found for {site}.\n"
                    f"    Run  python calibrate.py  and select {site} to set it up.\n"
                )
                sys.exit(1)
        else:
            # Initial check: just make sure we have AT LEAST ONE site calibrated
            # or the legacy calibration loaded.
            has_any = any(v.get("top_left") for v in self.cfg.site_configs.values())
            if not has_any and self.cfg.board_top_left is None:
                print(
                    "\n❌  No calibration found.\n"
                    "    Run  python calibrate.py  first to set up a chess site.\n"
                )
                sys.exit(1)

        if not Path(self.cfg.stockfish_path).exists():
            print(
                f"\n❌  Stockfish not found at: {self.cfg.stockfish_path}\n"
                "    Download from https://stockfishchess.org/download/\n"
                "    and update the path in config.json or config.py.\n"
            )
            sys.exit(1)

        # Templates check is site-dependent, we'll check it more thoroughly after connection
        templates_dir = self.cfg.get_templates_dir(site)
        if not templates_dir.exists() or not any(templates_dir.glob("*.png")):
            # Only warn if not using DOM reader (which doesn't need templates)
            if not self.cfg.use_dom_reader:
                print(
                    f"\n❌  No piece templates found for {site or 'current site'}.\n"
                    "    Run  python calibrate.py  to extract templates.\n"
                )
                sys.exit(1)

    # ------------------------------------------------------------------ #
    # Hotkeys
    # ------------------------------------------------------------------ #
    def _register_hotkeys(self) -> None:
        """Register pause and quit hotkeys."""
        keyboard.add_hotkey(self.cfg.pause_hotkey, self._toggle_pause)
        keyboard.add_hotkey(self.cfg.quit_hotkey, self._quit)
        keyboard.add_hotkey(self.cfg.bullet_hotkey, self._toggle_bullet_mode)
        keyboard.add_hotkey(self.cfg.auto_next_hotkey, self._toggle_auto_next_game)
        self.log.info(
            "Hotkeys registered — Pause: %s  |  Quit: %s  |  Bullet Mode: %s  |  Auto Next: %s",
            self.cfg.pause_hotkey,
            self.cfg.quit_hotkey,
            self.cfg.bullet_hotkey,
            self.cfg.auto_next_hotkey,
        )

    def _toggle_pause(self) -> None:
        self.paused = not self.paused
        state = "PAUSED" if self.paused else "RESUMED"
        self.log.info("⏸  Bot %s", state)

    def _quit(self) -> None:
        self.log.info("🛑  Quit hotkey pressed")
        self.running = False

    def _toggle_bullet_mode(self) -> None:
        """Toggle fast bullet mode."""
        self.mouse.human.bullet_mode = not self.mouse.human.bullet_mode
        state = "ENABLED" if self.mouse.human.bullet_mode else "DISABLED"
        icon = "🚀" if self.mouse.human.bullet_mode else "⚖️"
        self.log.info("%s  Bullet Mode %s", icon, state)

    def _toggle_auto_next_game(self) -> None:
        """Toggle automatic next game."""
        self.auto_next_game = not self.auto_next_game
        state = "ENABLED" if self.auto_next_game else "DISABLED"
        self.log.info("🔄 Auto Next Game %s", state)

    # ------------------------------------------------------------------ #
    # Main loop
    # ------------------------------------------------------------------ #
    # Configuration / Settings
    # ------------------------------------------------------------------ #
    def _detect_and_set_color(self) -> None:
        """Detect player color from DOM and update configuration/mapper."""
        detected_color = self.game_reader.detect_player_color()
        if detected_color:
            self.cfg.player_color = detected_color
            # Update square mapper with correct color
            self.mouse.mapper.player_color = detected_color
            self.log.info("Player color synchronized: %s", detected_color)
        else:
            self.log.warning("Could not detect color, using current: %s", self.cfg.player_color)

    def _handle_new_game(self) -> None:
        """Handle transition to a new game: reset state and flag color re-detection.

        Color detection is NOT done here because the DOM may still be showing
        the old game's board.  Instead we set a flag so that _tick() detects
        color once the new game's board is actually live.
        """
        self.log.info("New game transition (old_color=%s)", self.cfg.player_color)

        # Reset internal game state reader (board, move history)
        self.game_reader.reset_game_state()

        # Reset tracking so the first move of the new game is not skipped
        self._last_total_moves = -1
        self.last_fen = ""

        # Reset bullet mode counters for variety
        self.mouse.human.long_thought_count = 0
        self.mouse.human.max_long_thoughts = random.randint(6, 10)

        # Flag: detect color on the next tick that sees a fresh game board
        self._pending_color_detection = True

    # ------------------------------------------------------------------ #
    def run(self) -> None:
        """Start the bot main loop."""
        self._print_banner()
        self._register_hotkeys()

        # Connect to Chrome via CDP
        if not self.game_reader.connect():
            print(
                "\n❌  Cannot connect to Chrome.\n"
                "    Launch Chrome with:\n"
                "    chrome.exe --remote-debugging-port=9222 --remote-allow-origins=*\n"
                "    Then navigate to Chess.com or Lichess.org and start a game.\n"
            )
            return

        # Synchronize detected site and load corresponding calibration
        site = self.game_reader.site
        self.cfg.detected_site = site
        self.mouse.site = site
        self.log.info("Site detected: %s", site)

        # Load site-specific calibration
        if self.cfg.apply_site_config(site):
            self.log.info("Loaded calibration profile for %s", site)
            # Update subsystems with new coordinates
            self.mouse.mapper.update_corners(self.cfg.board_top_left, self.cfg.board_bottom_right)
            self.mouse.mapper.player_color = self.cfg.player_color
        else:
            self._validate_config(site) # This will exit if no calibration found for this site

        # Auto-detect player color and update mapper
        self._detect_and_set_color()
        self._pending_color_detection = True # Re-flag so it checks again once game starts

        # Read initial game state
        state = self.game_reader.get_game_state()
        if state:
            fen, total_moves, active = state
            # Initialize to -1 so that if it's our turn on move 0 (White) 
            # or move 1 (Black), we still trigger on the first tick.
            self._last_total_moves = -1 
            self.last_fen = fen
            self.log.info(
                "Initial state — %d moves played, FEN: %s, turn: %s",
                total_moves, fen, active,
            )

        # Start Stockfish
        self.engine.start()

        try:
            while self.running:
                # Pause check
                if self.paused:
                    time.sleep(0.2)
                    continue

                try:
                    self._tick()
                    self.consecutive_errors = 0
                except Exception as exc:
                    self.consecutive_errors += 1
                    self.log.error(
                        "Error in tick (%d/%d): %s",
                        self.consecutive_errors,
                        self.cfg.max_consecutive_errors,
                        exc,
                        exc_info=True,
                    )
                    if self.consecutive_errors >= self.cfg.max_consecutive_errors:
                        self.log.critical("Too many consecutive errors — stopping")
                        break
                    time.sleep(1.0)

                # Move check interval is shorter in bullet mode
                interval = 0.05 if self.mouse.human.bullet_mode else self.cfg.move_check_interval
                
                if self.auto_next_game:
                    if self.game_reader.is_next_arena_button_visible():
                        now = time.time()
                        if self._game_over_detected_at == 0.0:
                            # First time seeing the button — start the delay timer
                            self._game_over_delay = random.uniform(1.0, 2.0)
                            self._game_over_detected_at = now
                            self.log.info(
                                "Game over detected. Waiting %.1fs before clicking next...",
                                self._game_over_delay,
                            )
                        elif now - self._game_over_detected_at >= self._game_over_delay:
                            # Delay elapsed — click the button
                            if self.game_reader.click_next_arena_game():
                                self.log.info("Clicked Next Arena Game — handling transition...")
                                self._game_over_detected_at = 0.0
                                self._handle_new_game()
                    else:
                        # Button not visible — reset tracker
                        self._game_over_detected_at = 0.0
                
                time.sleep(interval)

        finally:
            self.engine.quit()
            self.game_reader.disconnect()
            keyboard.unhook_all()
            self.log.info("Bot stopped. Moves played: %d", self.move_count)

    def _tick(self) -> None:
        """One iteration: read move list → check turn → compute → execute."""
        # 1. Read the game state from Chess.com's DOM
        state = self.game_reader.get_game_state()
        if state is None:
            self.log.debug("Could not read game state — skipping tick")
            # Try to reconnect if connection was lost
            if not self.game_reader.is_connected():
                self.log.warning("CDP connection lost, attempting reconnect...")
                self.game_reader.connect()
            return

        fen, total_moves, active_color = state

        # 0. Deferred color detection for new game.
        #    We detect color HERE (on the live board) instead of during
        #    the game transition, because the old board may still be showing
        #    when _handle_new_game() runs.
        if self._pending_color_detection and (total_moves <= 1 or self._last_total_moves == -1):
            self.log.info(
                "Detecting/Synchronizing player color (Moves: %d)...",
                total_moves,
            )
            self._detect_and_set_color()
            self._pending_color_detection = False
            # If we just detected color at move 0/1, we should effectively "start" here
            return

        # 1.1 Check for game reset (new game started or page refreshed)
        # Only trigger on SIGNIFICANT drops — a fresh game has 0-2 moves.
        # Small fluctuations (e.g. 90→89) are DOM virtualization, NOT a new game.
        if (
            total_moves <= 2
            and self._last_total_moves > 5
        ):
            self.log.info(
                "New game detected in tick (Moves: %d -> %d). Handling transition...",
                self._last_total_moves, total_moves,
            )
            self._handle_new_game()
            return  # Let the next tick pick up the new game cleanly

        # 2. Check if it's our turn
        # Safety: if move count is 0 and we aren't sure of our color yet, wait.
        if total_moves == 0 and self.cfg.player_color is None:
            self.log.warning("Moves at 0 but color unknown - waiting for detection")
            return

        our_color = "w" if self.cfg.player_color == "white" else "b"
        
        # If it's not our turn, we skip.
        if active_color != our_color:
            # But we update the move counter so we know when the opponent HAS moved later.
            if total_moves > self._last_total_moves:
                if total_moves == 0:
                    self.log.info("Starting as Black - waiting for opponent's first move")
                else:
                    self.log.info(
                        "Opponent move detected (Total: %d). Waiting for %s...",
                        total_moves, "black" if our_color == "w" else "white"
                    )
                self._last_total_moves = total_moves
                self.last_fen = fen
            return

        # 3. It's our turn! Check if we've already acted on this move count.
        if total_moves <= self._last_total_moves:
            # We already played or the DOM hasn't updated after our move yet.
            return

        self.log.info(
            "Our turn (%s)! Total moves: %d — FEN: %s",
            our_color, total_moves, fen,
        )
        self._last_total_moves = total_moves
        self.last_fen = fen

        # 4. It's our turn! Get best move from Stockfish
        self.log.info("It's our turn (%s). Querying engine...", our_color)
        best_move = self.engine.get_best_move(fen)
        if best_move is None:
            self.log.warning("Engine returned no move — game may be over")
            return

        # 5. Execute the move
        self.log.info("Playing: %s (FEN: %s)", best_move, fen)
        self.mouse.execute_move(best_move, move_count=self.move_count)

        is_premove_executed = False
        if self.mouse.human.bullet_mode:
            premove = self._get_safe_premove(fen, best_move)
            if premove:
                self.log.info("Premoving recapture: %s", premove)
                self.mouse.execute_move(premove, is_premove=True)
                is_premove_executed = True

        # 6. Update state
        self.move_count += 1
        self.log.info("Move #%d complete (%s)", self.move_count, best_move)

        # Give the DOM a moment to update with our move
        if not is_premove_executed:
            delay = 0.1 if self.mouse.human.bullet_mode else 0.5
            time.sleep(delay)

        # Re-read game state to sync our tracking
        updated_state = self.game_reader.get_game_state()
        if updated_state:
            self.last_fen = updated_state[0]
            self._last_total_moves = updated_state[1]

    def _is_our_turn(self, active_color: str) -> bool:
        """Check if the active color matches our player color."""
        our = "w" if self.cfg.player_color == "white" else "b"
        return active_color == our

    def _get_safe_premove(self, fen: str, our_move: str) -> Optional[str]:
        """Determine if we can safely premove a recapture."""
        import chess
        try:
            board = chess.Board(fen)
            try:
                move_obj = chess.Move.from_uci(our_move)
                if move_obj not in board.legal_moves:
                    move_obj = board.parse_san(our_move) 
            except ValueError:
                return None
                
            board.push(move_obj)
            to_sq = move_obj.to_square
            
            # Find an opponent move that captures on to_sq
            for opp_move in list(board.legal_moves):
                if opp_move.to_square == to_sq:
                    board.push(opp_move)
                    # Use a very short time limit for premove calculation (30ms)
                    our_response = self.engine.get_best_move(board.fen(), depth=5, time_limit=0.03)
                    board.pop()
                    
                    if our_response:
                        response_obj = chess.Move.from_uci(our_response)
                        if response_obj.to_square == to_sq:
                            return our_response
            return None
        except Exception as exc:
            self.log.error("Error calculating premove: %s", exc)
            return None

    # ------------------------------------------------------------------ #
    # UI
    # ------------------------------------------------------------------ #
    @staticmethod
    def _print_banner() -> None:
        print("╔═══════════════════════════════════════════════╗")
        print("║     ♟  Auto Chess — Desktop Edition  ♟       ║")
        print("║                                               ║")
        print("║   Ctrl+M = Pause/Resume                       ║")
        print("║   Ctrl+Q = Quit                               ║")
        print("║   Ctrl+B = Bullet Mode (1m games)             ║")
        print("║   Ctrl+Y = Auto Next Game                     ║")
        print("╚═══════════════════════════════════════════════╝")
        print()


# -------------------------------------------------------------------------- #
# Entry point
# -------------------------------------------------------------------------- #
def main() -> None:
    config = Config.load()
    setup_logging(level=config.log_level, log_file=LOG_FILE if config.log_to_file else None)

    bot = ChessBot(config)
    bot.run()

if __name__ == "__main__":
    main()
