# ♟ Auto Chess — Desktop Edition

A premium Python desktop automation system that plays chess with 100% accuracy. It synchronized with your browser's game state via **Chrome DevTools Protocol (CDP)**, consults Stockfish for the best move, and executes it with realistic **human-like mouse movements**.

**No computer vision lag, no piece detection errors** — pure DOM-to-Desktop synchronization.

---

## Key Features

- **100% Accurate State**: Reads the move list directly from Chess.com's DOM via CDP.
- **Auto-Color Detection**: Automatically detects if you are playing as White or Black based on board orientation.
- **Multi-Game Support**: Seamlessly transitions to new games without manual restarts.
- **Human-Like Automation**: Simulates realistic mouse paths, thinking delays, and "hesitations" using `Humanizer`.
- **Anti-Detection**: Uses CDP to bypass Selenium/WebDriver detection methods.

---

## Quick Start

### 1. Launch Chrome with Debugging

Close all Chrome windows and launch it from the terminal/command prompt with the debugging port enabled:

```bash
chrome.exe --remote-debugging-port=9222 --remote-allow-origins=*
```

Shortcut:
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\temp\chrome_bot_profile"

### 2. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 3. Install Stockfish

Download Stockfish from [stockfishchess.org/download](https://stockfishchess.org/download/).
Update `config.py` or create a `config.json` with the path:

```json
{
  "stockfish_path": "C:\\stockfish\\stockfish-windows-x86-64-avx2.exe"
}
```

### 4. Calibrate the Board

Open Chess.com in the debugging Chrome window, then run:

```bash
python calibrate.py
```

- Click the **top-left** corner and **bottom-right** corner of the board when prompted.
- This maps the screen coordinates to the chess squares.

### 5. Run the Bot

```bash
python main.py
```

The bot will now automatically:

1. Connect to your active Chess.com tab.
2. Detect your color and board orientation.
3. Play moves automatically when it's your turn.
4. Reset and re-detect for every new game.

---

## Controls

| Hotkey                  | Action         |
| ----------------------- | -------------- |
| `Ctrl+P`                | Pause / Resume |
| `Ctrl+Q`                | Quit           |
| Mouse → top-left corner | Emergency stop |

---

## Configuration

Create a `config.json` to customize the "personality" of the bot:

```json
{
  "stockfish_path": "C:\\stockfish\\stockfish.exe",
  "stockfish_depth": 14,
  "think_delay_mean": 1.2,
  "coordinate_jitter_px": 5,
  "hesitation_probability": 0.2,
  "use_drag": true
}
```

---

## Troubleshooting

| Issue                       | Solution                                                              |
| --------------------------- | --------------------------------------------------------------------- |
| "Cannot connect to Chrome"  | Ensure Chrome is running with `--remote-debugging-port=9222`.         |
| "No Chess.com tab found"    | Make sure Chess.com is open in the active Chrome profile.             |
| Moves land on wrong squares | Re-run `python calibrate.py` and click the board corners precisely.   |
| Bot doesn't move when Black | Check if the board is fully loaded; the bot auto-detects orientation. |
| Stockfish errors            | Verify the `stockfish_path` in your config is correct.                |

---

## Requirements

- Python 3.11+
- Chrome Browser
- Stockfish Engine
- Windows (Recommended)
