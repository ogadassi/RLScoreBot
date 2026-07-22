"""
logger.py
---------
Pretty, color-coded console logging for RLScoreBot.
Uses colorama for reliable ANSI support on Windows.
"""

import sys
import io
# Force UTF-8 output on Windows so box-drawing / emoji chars don't crash
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
from datetime import datetime
from colorama import init, Fore, Back, Style

# Initialize colorama — strip=False keeps colors even when piped
init(autoreset=True, strip=False)

# ── Palette ────────────────────────────────────────────────────────────────────
_DIM     = Style.DIM
_RESET   = Style.RESET_ALL
_BOLD    = Style.BRIGHT

_GREY    = Fore.WHITE   + Style.DIM
_CYAN    = Fore.CYAN    + Style.BRIGHT
_GREEN   = Fore.GREEN   + Style.BRIGHT
_YELLOW  = Fore.YELLOW  + Style.BRIGHT
_RED     = Fore.RED     + Style.BRIGHT
_MAGENTA = Fore.MAGENTA + Style.BRIGHT
_BLUE    = Fore.BLUE    + Style.BRIGHT
_WHITE   = Fore.WHITE   + Style.BRIGHT


def _ts() -> str:
    """Compact timestamp: HH:MM:SS"""
    return _GREY + datetime.now().strftime("%H:%M:%S") + _RESET


def _line(color: str, icon: str, label: str, msg: str) -> str:
    return f"  {_ts()}  {color}{icon}  {_BOLD}{label:<10}{_RESET}  {msg}"


# ── Public API ─────────────────────────────────────────────────────────────────

def banner():
    """Print the startup banner."""
    w = 54
    b = Fore.CYAN + Style.BRIGHT
    print()
    print(b + "  +" + "=" * w + "+")
    print(b + "  |" + " " * w + "|")
    print(b + "  |" + _WHITE + "         [*]  RLScoreBot  [*]         ".center(w) + b + "|")
    print(b + "  |" + _GREY  + "    Auto goal celebration for Rocket League   ".center(w) + b + "|")
    print(b + "  |" + " " * w + "|")
    print(b + "  +" + "=" * w + "+")
    print(_RESET)


def info(msg: str):
    print(_line(_CYAN, "●", "INFO", _WHITE + msg))


def success(msg: str):
    print(_line(_GREEN, "✔", "OK", _GREEN + msg))


def warn(msg: str):
    print(_line(_YELLOW, "▲", "WARN", _YELLOW + msg))


def error(msg: str):
    print(_line(_RED, "✖", "ERROR", _RED + msg))


def goal(score_before: int, score_after: int):
    """Fired when a goal is confirmed."""
    arrow = _WHITE + f"{score_before}  →  {score_after}"
    print()
    print(f"  {_ts()}  {_GREEN}{'━' * 50}")
    print(f"  {_ts()}  {_GREEN}⚽  {_BOLD}GOAL!{_RESET}   {_GREY}score {_RESET}{arrow}")
    print(f"  {_ts()}  {_GREEN}{'━' * 50}")
    print()


def playing(filename: str):
    """Fired when audio starts playing."""
    name = filename.rsplit(".", 1)[0]   # strip extension for cleaner display
    print(_line(_MAGENTA, "♪", "PLAYING", _MAGENTA + Style.BRIGHT + f'"{name}"'))


def detection(state: str, detail: str = ""):
    """Detection loop state changes."""
    print(_line(_BLUE, "◈", "DETECT", _GREY + state + (f"  {detail}" if detail else "")))


def sound_loaded(count: int):
    print(_line(_CYAN, "♫", "SOUNDS", _WHITE + f"{count} sounds loaded"))


def divider(label: str = ""):
    mid = f"  {label}  " if label else ""
    line = _GREY + "  " + ("─" * 4) + mid + ("─" * (46 - len(label))) + _RESET
    print(line)
