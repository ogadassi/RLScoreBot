import sqlite3
import secrets
import os
import time
from typing import Optional, Dict, Any, List

DB_PATH = os.path.join(os.path.dirname(__file__), "rlscorebot.db")

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
                created_at REAL,
                FOREIGN KEY(discord_user_id) REFERENCES users(discord_user_id)
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

def link_bakkesmod_code(code: str) -> Optional[Dict[str, Any]]:
    """Claim a 6-digit pairing code from BakkesMod plugin to retrieve API token."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE linking_code = ?", (code,))
        row = cursor.fetchone()
        if not row:
            return None
        
        user_data = dict(row)
        # Clear code after claiming so it cannot be reused
        cursor.execute("UPDATE users SET linking_code = NULL WHERE linking_code = ?", (code,))
        conn.commit()
        return user_data

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
        
        cursor.execute("SELECT COUNT(*) as total_sounds FROM user_sounds")
        total_sounds = cursor.fetchone()["total_sounds"]
        
        return {
            "total_goals": total_goals or 0,
            "total_users": total_users or 0,
            "total_sounds": total_sounds or 0
        }

# Initialize tables when imported
init_db()
