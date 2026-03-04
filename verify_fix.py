"""
verify_fix.py — Dry run verification for chess bot fixes.
"""
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parent))

from config import Config
from vision.board_detector import BoardDetector
from vision.piece_detector import PieceDetector
from vision.fen_builder import FenBuilder
from engine.stockfish import StockfishEngine

def verify():
    print("=== Verification Start ===")
    cfg = Config.load()
    
    # 1. Test FEN Builder Validation
    print("\n[1] Testing FEN Builder Validation...")
    builder = FenBuilder(player_color=cfg.player_color)
    invalid_fen = "8/8/8/8/8/8/8/8 w KQkq - 0 1" # No kings
    valid, msg = builder.validate_fen(invalid_fen)
    print(f"  Invalid FEN test: {valid} (Message: {msg})")
    
    standard_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    valid, msg = builder.validate_fen(standard_fen)
    print(f"  Standard FEN test: {valid} (Message: {msg})")

    # 2. Test Engine
    print("\n[2] Testing Stockfish Engine...")
    engine = StockfishEngine(path=cfg.stockfish_path)
    try:
        engine.start()
        move = engine.get_best_move(standard_fen)
        print(f"  Best move from start: {move}")
    except Exception as e:
        print(f"  Engine error: {e}")
    finally:
        engine.quit()

    print("\n=== Verification Complete ===")

if __name__ == "__main__":
    verify()
