# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

"""
normalize_sounds.py
-------------------
Batch-normalizes all audio files in the sounds/ folder to -14 LUFS
using ffmpeg's loudnorm filter.

Run this script once to fix existing sounds, or re-run anytime new
files are added outside of the bot's >upload command.

Usage:
    python normalize_sounds.py
    python normalize_sounds.py --lufs -16   (quieter)
    python normalize_sounds.py --lufs -10   (louder)
"""

import os
import sys
import subprocess
import tempfile
import argparse

# ── Config ────────────────────────────────────────────────────────────────────
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
SOUNDS_DIR   = os.path.join(SCRIPT_DIR, "sounds")
FFMPEG_PATH  = os.path.join(SCRIPT_DIR, "ffmpeg.exe")

SUPPORTED_EXTS = {".mp3", ".wav", ".ogg", ".flac", ".m4a"}

# ── Helpers ───────────────────────────────────────────────────────────────────

def normalize_file(file_path: str, target_lufs: float = -14.0) -> tuple[bool, str]:
    """
    Normalize a single audio file to target_lufs in-place.
    Returns (success: bool, message: str).
    """
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".mp3", dir=os.path.dirname(file_path))
    os.close(tmp_fd)

    try:
        result = subprocess.run(
            [
                FFMPEG_PATH,
                "-y",                          # overwrite temp without asking
                "-i", file_path,
                "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11",
                "-c:a", "libmp3lame",
                "-q:a", "2",                   # VBR ~190 kbps — good quality
                tmp_path,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

        if result.returncode != 0:
            err = result.stderr.decode(errors="replace").strip().splitlines()
            # Return last few lines of ffmpeg stderr for diagnosis
            detail = " | ".join(err[-3:]) if err else "unknown error"
            return False, f"ffmpeg error: {detail}"

        # Replace original with normalized copy
        os.replace(tmp_path, file_path)
        return True, "OK"

    except Exception as exc:
        return False, str(exc)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def main():
    parser = argparse.ArgumentParser(description="Normalize all sounds to a target loudness.")
    parser.add_argument("--lufs", type=float, default=-14.0,
                        help="Target loudness in LUFS (default: -14)")
    args = parser.parse_args()

    target = args.lufs

    # ── Sanity checks ─────────────────────────────────────────────────────────
    if not os.path.isfile(FFMPEG_PATH):
        print(f"[ERROR] ffmpeg.exe not found at: {FFMPEG_PATH}")
        sys.exit(1)

    if not os.path.isdir(SOUNDS_DIR):
        print(f"[ERROR] sounds/ directory not found at: {SOUNDS_DIR}")
        sys.exit(1)

    files = [
        f for f in sorted(os.listdir(SOUNDS_DIR))
        if os.path.splitext(f)[1].lower() in SUPPORTED_EXTS
    ]

    if not files:
        print("No supported audio files found in sounds/")
        sys.exit(0)

    print(f"Target loudness : {target} LUFS")
    print(f"Files to process: {len(files)}")
    print("-" * 50)

    ok_count  = 0
    err_count = 0

    for i, filename in enumerate(files, 1):
        path = os.path.join(SOUNDS_DIR, filename)
        label = f"[{i:>2}/{len(files)}] {filename}"
        print(f"{label:<55}", end="", flush=True)

        success, msg = normalize_file(path, target)

        if success:
            print("OK")
            ok_count += 1
        else:
            print(f"FAIL  {msg}")
            err_count += 1

    print("-" * 50)
    print(f"Done — {ok_count} normalized, {err_count} failed.")

    if err_count:
        sys.exit(1)


if __name__ == "__main__":
    main()
