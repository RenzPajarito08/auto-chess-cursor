"""
main.py — Chess automation orchestrator.

Runs the main game loop:
  connect to Chess.com via CDP → read move list → build FEN → query Stockfish → execute move

Usage:
    1. Launch Chrome with:  chrome.exe --remote-debugging-port=9222 --remote-allow-origins=*
    2. Navigate to Chess.com and start a game
    3. Run:  python main.py

Hotkeys (while running):
    Ctrl+M  —  Pause / Resume
    Ctrl+Q  —  Quit
    Mouse to top-left corner  —  Emergency stop
"""

from __future__ import annotations

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
        self.last_fen: str = ""
        self.move_count: int = 0
        self.consecutive_errors: int = 0
        self._last_total_moves: int = 0  # Total moves seen in the DOM

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
    def _validate_config(self) -> None:
        if self.cfg.board_top_left is None or self.cfg.board_bottom_right is None:
            print(
                "\n❌  No calibration found.\n"
                "    Run  python calibrate.py  first to set up the board region.\n"
            )
            sys.exit(1)

        if not Path(self.cfg.stockfish_path).exists():
            print(
                f"\n❌  Stockfish not found at: {self.cfg.stockfish_path}\n"
                "    Download from https://stockfishchess.org/download/\n"
                "    and update the path in config.json or config.py.\n"
            )
            sys.exit(1)

        if not TEMPLATES_DIR.exists() or not any(TEMPLATES_DIR.glob("*.png")):
            print(
                "\n❌  No piece templates found.\n"
                "    Run  python calibrate.py  with the board in starting position.\n"
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
        self.log.info(
            "Hotkeys registered — Pause: %s  |  Quit: %s  |  Bullet Mode: %s",
            self.cfg.pause_hotkey,
            self.cfg.quit_hotkey,
            self.cfg.bullet_hotkey,
        )

    def _toggle_pause(self) -> None:
        self.paused = not self.paused
        state = "PAUSED" if self.paused else "RESUMED"
        self.log.info("⏸  Bot %s", state)
        print(f"\n{'⏸ ' if self.paused else '▶ '} Bot {state}")

    def _quit(self) -> None:
        self.log.info("🛑  Quit hotkey pressed")
        self.running = False

    def _toggle_bullet_mode(self) -> None:
        """Toggle fast bullet mode."""
        self.mouse.human.bullet_mode = not self.mouse.human.bullet_mode
        state = "ENABLED" if self.mouse.human.bullet_mode else "DISABLED"
        icon = "🚀" if self.mouse.human.bullet_mode else "⚖️"
        self.log.info("%s  Bullet Mode %s", icon, state)
        print(f"\n{icon} Bullet Mode {state}")

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

        # Synchronize detected site
        self.cfg.detected_site = self.game_reader.site
        self.mouse.site = self.game_reader.site
        self.log.info("Site detected: %s", self.cfg.detected_site)
        print(f"✅  Connected to {self.cfg.detected_site}")

        # Auto-detect player color and update mapper
        self._detect_and_set_color()

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
                # Emergency stop check
                if MouseController.check_emergency_stop(self.cfg.emergency_corner_size):
                    self.log.warning("🚨  Emergency stop triggered — mouse in corner")
                    print("\n🚨  Emergency stop! Mouse moved to top-left corner.")
                    break

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
        
        # 1.1 Check for game reset (new game started or page refreshed)
        # If the move count drops significantly or is 0 while we had a high count, it's a new game.
        if total_moves < self._last_total_moves:
            self.log.info("New game detected (Moves: %d -> %d). Re-detecting color...", self._last_total_moves, total_moves)
            self._detect_and_set_color()
            self._last_total_moves = -1 # Reset so we act on the first move correctly

        # 2. Check if it's our turn
        our_color = "w" if self.cfg.player_color == "white" else "b"
        
        # If it's not our turn, we skip.
        if active_color != our_color:
            # But we update the move counter so we know when the opponent HAS moved later.
            if total_moves > self._last_total_moves:
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
            "Game state update (Our Turn: %s)! Total moves: %s — FEN: %s",
            active_color, total_moves, fen,
        )
        self._last_total_moves = total_moves
        self.last_fen = fen

        # 3. Check if it's our turn
        our_color = "w" if self.cfg.player_color == "white" else "b"
        if active_color != our_color:
            self.log.info(
                "It's %s's turn (opponent). Waiting...",
                "black" if our_color == "w" else "white",
            )
            return

        # 4. It's our turn! Get best move from Stockfish
        self.log.info("It's our turn (%s). Querying engine...", our_color)
        best_move = self.engine.get_best_move(fen)
        if best_move is None:
            self.log.warning("Engine returned no move — game may be over")
            return

        # 5. Execute the move
        self.log.info("Playing: %s (FEN: %s)", best_move, fen)
        self.mouse.execute_move(best_move)

        # 6. Update state
        self.move_count += 1
        self.log.info("Move #%d complete (%s)", self.move_count, best_move)

        # Give the DOM a moment to update with our move
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
        print("║   Mouse → top-left corner = Emergency stop    ║")
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
