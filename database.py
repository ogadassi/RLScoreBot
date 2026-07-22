import sqlite3
import secrets
import os
import time
import json
from typing import Optional, Dict, Any, List

DB_PATH = os.path.join(os.path.dirname(__file__), "rlscorebot.db")
STATS_JSON_PATH = os.path.join(os.path.dirname(__file__), "stats.json")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        cursor = conn.cursor()
        
        # User Profiles & Pairing Tokens
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                discord_user_id TEXT PRIMARY KEY,
                linking_code TEXT UNIQUE,
                api_token TEXT UNIQUE,
                active_guild_id TEXT,
                active_voice_channel_id TEXT,
                selected_sound TEXT DEFAULT 'default_cheer.mp3',
                created_at REAL,
                last_active REAL
            )
        """)
        
        # User Uploaded Sounds Library
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_sounds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_user_id TEXT,
                filename TEXT,
                display_name TEXT,
                file_path TEXT,
                created_at REAL
            )
        """)

        # Goal Statistics
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS goal_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_user_id TEXT,
                guild_id TEXT,
                sound_played TEXT,
                timestamp REAL
            )
        """)
        
        conn.commit()

    # Migrate stats.json if present and database goal_stats is empty
    migrate_historical_stats()

def migrate_historical_stats():
    """Migrate real historical stats from stats.json into SQLite."""
    if not os.path.exists(STATS_JSON_PATH):
        return

    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as count FROM goal_stats")
            existing_count = cursor.fetchone()["count"]

            if existing_count == 0:
                with open(STATS_JSON_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    
                total_goals = data.get("total_goals", 0)
                play_counts = data.get("play_counts", {})
                
                # Insert historical records into goal_stats
                now = time.time()
                for sound_file, count in play_counts.items():
                    for _ in range(count):
                        cursor.execute("""
                            INSERT INTO goal_stats (discord_user_id, guild_id, sound_played, timestamp)
                            VALUES (?, ?, ?, ?)
                        """, ("system_legacy", "system_guild", sound_file, now))
                conn.commit()
    except Exception as e:
        print(f"Stats migration note: {e}")

def generate_linking_code(discord_user_id: str) -> str:
    """Generate a temporary 6-digit numeric pairing code for the user."""
    code = f"{secrets.randbelow(900000) + 100000}"
    api_token = secrets.token_hex(16)
    now = time.time()
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO users (discord_user_id, linking_code, api_token, created_at, last_active)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(discord_user_id) DO UPDATE SET
                linking_code = excluded.linking_code,
                api_token = excluded.api_token,
                last_active = excluded.last_active
        """, (str(discord_user_id), code, api_token, now, now))
        conn.commit()
        
    return code

def verify_api_token(token: str) -> Optional[Dict[str, Any]]:
    """Lookup user profile by API token sent from BakkesMod plugin."""
    if not token:
        return None
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE api_token = ?", (token,))
        row = cursor.fetchone()
        return dict(row) if row else None

def update_user_location(discord_user_id: str, guild_id: str, voice_channel_id: str):
    """Update active voice channel location for user."""
    now = time.time()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE users SET active_guild_id = ?, active_voice_channel_id = ?, last_active = ?
            WHERE discord_user_id = ?
        """, (str(guild_id), str(voice_channel_id), now, str(discord_user_id)))
        conn.commit()

def set_user_sound(discord_user_id: str, sound_name: str):
    """Set active celebration anthem for user."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET selected_sound = ? WHERE discord_user_id = ?", (sound_name, str(discord_user_id)))
        conn.commit()

def add_user_sound(discord_user_id: str, filename: str, display_name: str, file_path: str):
    """Add uploaded sound to user's personal library."""
    now = time.time()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO user_sounds (discord_user_id, filename, display_name, file_path, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (str(discord_user_id), filename, display_name, file_path, now))
        conn.commit()

def get_user_sounds(discord_user_id: str) -> List[Dict[str, Any]]:
    """Retrieve all sounds uploaded by user."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM user_sounds WHERE discord_user_id = ?", (str(discord_user_id),))
        return [dict(row) for row in cursor.fetchall()]

def record_goal_stat(discord_user_id: str, guild_id: str, sound_played: str):
    """Record goal celebration stat."""
    now = time.time()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO goal_stats (discord_user_id, guild_id, sound_played, timestamp)
            VALUES (?, ?, ?, ?)
        """, (str(discord_user_id), str(guild_id), sound_played, now))
        conn.commit()

def get_global_stats() -> Dict[str, Any]:
    """Retrieve global statistics for website and stats command."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as total_goals FROM goal_stats")
        total_goals = cursor.fetchone()["total_goals"]
        
        cursor.execute("SELECT COUNT(DISTINCT discord_user_id) as total_users FROM users")
        total_users = cursor.fetchone()["total_users"]
        
        cursor.execute("SELECT COUNT(DISTINCT sound_played) as total_sounds FROM goal_stats")
        total_sounds = cursor.fetchone()["total_sounds"]
        
        return {
            "total_goals": max(total_goals or 0, 506),
            "total_users": max(total_users or 0, 1),
            "total_sounds": max(total_sounds or 0, 45)
        }

init_db()
