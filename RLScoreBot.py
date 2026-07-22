import asyncio
import os
import random
import discord
import requests
from discord.ext import commands, tasks
from itertools import count, filterfalse
from dotenv import load_dotenv

import utils
import score_detector
import logger

import aiohttp

load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID      = int(os.getenv("OWNER_ID", "0"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ── Constants ─────────────────────────────────────────────────────────────────
SOUNDS_DIR_NAME = "sounds"
FFMPEG_NAME     = "ffmpeg.exe"
TARGET_LUFS     = -14

def is_rl_running():
    """Check if Rocket League is running. Uses fast Win32 window check first, falling back to tasklist."""
    import win32gui
    if win32gui.FindWindow(None, "Rocket League") != 0:
        return True

    import subprocess
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq RocketLeague.exe", "/NH"],
        capture_output=True,
        text=True,
        creationflags=0x08000000, # CREATE_NO_WINDOW
    )
    return "rocketleague.exe" in result.stdout.lower()

# ── Owner-only check ──────────────────────────────────────────────────────────
def owner_only():
    """Command check that restricts usage to the bot owner."""
    async def predicate(ctx):
        if ctx.author.id != OWNER_ID:
            await ctx.send("🔒 You don't have permission to use that command.")
            return False
        return True
    return commands.check(predicate)

sounds = {}

intents = discord.Intents().all()
bot = commands.Bot(command_prefix='>', intents=intents, help_command=None)

# ── Sound loading ─────────────────────────────────────────────────────────────

# ── Stats ─────────────────────────────────────────────────────────────────────
import json
from datetime import datetime as _dt, timezone, timedelta

STATS_FILE = utils.full_path("stats.json")

# Persistent (written to stats.json)
_stats: dict = {"total_goals": 0, "play_counts": {}}
# Session-only (reset each run)
_session_goals  = 0
_session_plays  = 0
_bot_start_time = _dt.now()

def load_stats():
    global _stats
    if os.path.isfile(STATS_FILE):
        try:
            with open(STATS_FILE, encoding="utf-8") as f:
                _stats = json.load(f)
            _stats.setdefault("total_goals", 0)
            _stats.setdefault("play_counts", {})
            total_plays = sum(_stats["play_counts"].values())
            logger.info(f"Stats loaded: {_stats['total_goals']} goals, {total_plays} sound plays recorded all-time.")
        except Exception as e:
            logger.warn(f"Failed to load stats: {e}. Starting fresh.")
            _stats = {"total_goals": 0, "play_counts": {}}
    else:
        logger.info("No stats.json found, starting with empty statistics.")
        _stats = {"total_goals": 0, "play_counts": {}}

def save_stats():
    try:
        with open(STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(_stats, f, indent=2)
    except Exception as e:
        logger.warn(f"Could not save stats: {e}")

def record_play(sound_file: str):
    global _session_plays
    _session_plays += 1
    _stats["play_counts"][sound_file] = _stats["play_counts"].get(sound_file, 0) + 1
    save_stats()

def record_goal():
    global _session_goals
    _session_goals += 1
    _stats["total_goals"] += 1
    save_stats()

# ── Sound loading ─────────────────────────────────────────────────────────────

def load_sounds():
    global sounds
    sounds = {}
    dir_path = utils.full_path(SOUNDS_DIR_NAME)

    sound_id = 1

    if not os.path.exists(dir_path):
        logger.warn(f"Sounds directory missing — creating at {dir_path}")
        os.makedirs(dir_path)

    for filename in sorted(os.listdir(dir_path)):
        sounds[sound_id] = filename
        sound_id += 1

    logger.sound_loaded(len(sounds))


def random_sound():
    if not sounds:
        return None
    return random.choice(list(sounds.values()))


def play_sound(voice_client, sound_file):
    if not sound_file:
        logger.warn("play_sound called with no sound file.")
        return

    if not voice_client or not voice_client.is_connected():
        logger.warn("Attempted to play sound but voice client is not connected.")
        return

    if voice_client.is_playing():
        logger.info("Already playing — skipped.")
        return

    voice_client.play(discord.FFmpegPCMAudio(
        executable=utils.full_path(FFMPEG_NAME),
        source=utils.full_path(SOUNDS_DIR_NAME, sound_file)
    ))
    logger.playing(sound_file)
    record_play(sound_file)

# ── Audio normalization ───────────────────────────────────────────────────────

async def normalize_audio(file_path: str, target_lufs: float = TARGET_LUFS) -> tuple[bool, str]:
    import tempfile

    tmp_fd, tmp_path = tempfile.mkstemp(
        suffix=".mp3",
        dir=os.path.dirname(file_path)
    )
    os.close(tmp_fd)

    try:
        proc = await asyncio.create_subprocess_exec(
            utils.full_path(FFMPEG_NAME),
            "-y",
            "-i", file_path,
            "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11",
            "-c:a", "libmp3lame",
            "-q:a", "2",
            tmp_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr_bytes = await proc.communicate()

        if proc.returncode != 0:
            stderr_text = stderr_bytes.decode(errors="replace").strip().splitlines()
            detail = " | ".join(stderr_text[-3:]) if stderr_text else "unknown error"
            return False, f"ffmpeg error: {detail}"

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

# ── Upload security ──────────────────────────────────────────────────────────
import re as _re

ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".m4a"}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024   # 50 MB
_SAFE_NAME = _re.compile(r'^[\w\s\-()\[\].]+$')  # letters, digits, spaces, - _ ( ) [ ] .

# ── Commands ──────────────────────────────────────────────────────────────────

@bot.command(name='upload', help='Upload a new audio file. Allowed: .mp3 .wav .ogg .flac .m4a (max 50 MB).')
async def upload(ctx, name: str = None):
    if not ctx.message.attachments:
        await ctx.send("Please attach a sound file.")
        return

    attachment = ctx.message.attachments[0]

    # Resolve filename and extension
    _, attach_ext = os.path.splitext(attachment.filename.lower())
    if not name:
        name = attachment.filename
    else:
        _, name_ext = os.path.splitext(name)
        if not name_ext:
            name = name + attach_ext

    # 1. Block path traversal ─────────────────────────────────────────────────
    safe_name = os.path.basename(name)
    if safe_name != name or ".." in name or "/" in name or "\\" in name:
        await ctx.send("❌ Invalid filename.")
        logger.warn(f"Upload blocked (path traversal): {name!r} by {ctx.author}")
        return

    # 2. Safe character set ───────────────────────────────────────────────────
    if not _SAFE_NAME.match(safe_name):
        await ctx.send("❌ Filename contains invalid characters. Use letters, numbers, spaces, `-` and `_` only.")
        logger.warn(f"Upload blocked (bad chars): {safe_name!r} by {ctx.author}")
        return

    # 3. Extension whitelist ──────────────────────────────────────────────────
    _, ext = os.path.splitext(safe_name)
    if ext.lower() not in ALLOWED_AUDIO_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_AUDIO_EXTENSIONS))
        await ctx.send(f"❌ `{ext}` is not an allowed audio format. Accepted: {allowed}")
        logger.warn(f"Upload blocked (bad extension {ext!r}): {safe_name} by {ctx.author}")
        return

    # 4. Content-type check removed because Discord MIME types can be unreliable

    # 5. Size cap ─────────────────────────────────────────────────────────────
    if attachment.size > MAX_UPLOAD_BYTES:
        mb = attachment.size / 1024 / 1024
        await ctx.send(f"❌ File too large ({mb:.1f} MB). Maximum is {MAX_UPLOAD_BYTES // 1024 // 1024} MB.")
        logger.warn(f"Upload blocked (too large {mb:.1f} MB): {safe_name} by {ctx.author}")
        return

    # 6. Name collision ───────────────────────────────────────────────────────
    file_path = utils.full_path(SOUNDS_DIR_NAME, safe_name)
    if os.path.isfile(file_path):
        await ctx.send(f"A file named `{safe_name}` already exists.")
        return

    # 7. Download & save (Asynchronously) ─────────────────────────────────────
    file_bytes = await attachment.read()
    with open(file_path, "wb") as f:
        f.write(file_bytes)

    # 8. Normalize ────────────────────────────────────────────────────────────
    status_msg = await ctx.send(f"⏳ Normalizing `{safe_name}` to {TARGET_LUFS} LUFS…")
    logger.info(f"Normalizing upload: {safe_name} (from {ctx.author})")
    ok, msg = await normalize_audio(file_path)

    # Reload all sounds from disk to ensure memory matches disk and IDs are sorted
    load_sounds()
    new_sound_id = next((sid for sid, name in sounds.items() if name == safe_name), None)
    if new_sound_id is None:
        new_sound_id = next(filterfalse(set(sounds.keys()).__contains__, count(1)))
        sounds[new_sound_id] = safe_name

    if ok:
        logger.success(f"Uploaded + normalized: {safe_name} (ID {new_sound_id}) by {ctx.author}")
        await status_msg.edit(content=(
            f"✅ Uploaded and normalized `{safe_name}` → ID **{new_sound_id}** "
            f"(volume matched to {TARGET_LUFS} LUFS)"
        ))
    else:
        logger.warn(f"Uploaded {safe_name} (normalization failed): {msg}")
        await status_msg.edit(content=(
            f"⚠️ Uploaded `{safe_name}` → ID **{new_sound_id}** "
            f"(normalization failed: {msg})"
        ))


@bot.command(name='normalize', help=f'Normalize all sounds in the folder to {TARGET_LUFS} LUFS.')
@owner_only()
async def normalize_cmd(ctx):
    if not sounds:
        await ctx.send("No sounds loaded. Use `>refresh` first.")
        return

    status_msg = await ctx.send(f"⏳ Normalizing **{len(sounds)}** sounds to {TARGET_LUFS} LUFS…")
    logger.divider("NORMALIZE")
    logger.info(f"Normalizing {len(sounds)} sounds to {TARGET_LUFS} LUFS…")

    ok_list   = []
    fail_list = []

    for sound_id in sorted(sounds.keys()):
        filename  = sounds[sound_id]
        file_path = utils.full_path(SOUNDS_DIR_NAME, filename)

        if not os.path.isfile(file_path):
            logger.warn(f"File not found on disk: {filename}")
            fail_list.append(f"`{filename}` — file not found on disk")
            continue

        ok, msg = await normalize_audio(file_path)
        if ok:
            logger.success(f"Normalized: {filename}")
            ok_list.append(filename)
        else:
            logger.error(f"Failed: {filename} — {msg}")
            fail_list.append(f"`{filename}` — {msg}")

    logger.divider()

    embed = discord.Embed(
        title="🎚️ Normalization Complete",
        color=discord.Color.green() if not fail_list else discord.Color.orange(),
    )
    embed.add_field(
        name=f"✅ Normalized ({len(ok_list)})",
        value="\n".join(f"• {f}" for f in ok_list) or "None",
        inline=False,
    )
    if fail_list:
        embed.add_field(
            name=f"❌ Failed ({len(fail_list)})",
            value="\n".join(f"• {f}" for f in fail_list),
            inline=False,
        )
    embed.set_footer(text=f"Target: {TARGET_LUFS} LUFS  •  TP=-1.5  •  LRA=11")

    await status_msg.delete()
    await ctx.send(embed=embed)


@bot.command(name='refresh', help='Reloads all sounds from the folder')
async def refresh_sounds(ctx):
    load_sounds()
    await ctx.send(f"🔄 Reloaded **{len(sounds)}** sounds from disk.")


@bot.command(name='delete', help='Delete a sound by its ID')
@owner_only()
async def delete_sound(ctx, sound_id):
    try:
        sound_id = int(sound_id)
    except ValueError:
        await ctx.send(f"`{sound_id}` is not a valid ID.")
        return

    if sound_id not in sounds:
        await ctx.send(f"No sound with ID `{sound_id}` exists.")
        return

    sound_name = sounds[sound_id]
    os.remove(utils.full_path(SOUNDS_DIR_NAME, sound_name))
    sounds.pop(sound_id)
    logger.info(f"Deleted sound {sound_id}: {sound_name}")
    await ctx.send(f"🗑️ Deleted sound **{sound_id}** (`{sound_name}`)")


@bot.command(name="list", help="List all sounds currently loaded")
async def list_sounds(ctx):
    if not sounds:
        await ctx.send("No sounds loaded.")
        return

    lines = [f"`{sid}` — {sounds[sid]}" for sid in sorted(sounds.keys())]
    chunk = ""
    for line in lines:
        if len(chunk) + len(line) + 1 > 1900:
            await ctx.send(chunk)
            chunk = ""
        chunk += line + "\n"
    if chunk:
        await ctx.send(chunk)


@bot.command(name="play", help="Play a sound. Optional: provide an ID from >list to play a specific one.")
async def play(ctx, sound_id: int = None):
    voice_client = ctx.message.guild.voice_client
    if not voice_client or not voice_client.is_connected():
        await ctx.send("❌ The bot is not connected to a voice channel. Use `>join` first.")
        return
    if voice_client.is_playing():
        await ctx.send("⏯️ Already playing a sound.")
        return

    if sound_id is not None:
        if sound_id not in sounds:
            await ctx.send(f"❌ No sound with ID `{sound_id}`. Use `>list` to see available sounds.")
            return
        play_sound(voice_client, sounds[sound_id])
    else:
        play_sound(voice_client, random_sound())


@bot.command(name='join', help='Join your current voice channel and start goal detection')
async def join(ctx):
    voice = discord.utils.get(bot.voice_clients, guild=ctx.guild)

    if not ctx.message.author.voice:
        await ctx.send(f"❌ {ctx.message.author.name} is not in a voice channel.")
        return

    if voice:
        await ctx.send("✅ Already connected to a voice channel.")
        return

    channel = ctx.message.author.voice.channel
    try:
        await channel.connect(reconnect=False)
    except TimeoutError:
        await ctx.send("❌ Timed out connecting to voice. Try again in a moment.")
        return
    except Exception as e:
        await ctx.send(f"❌ Failed to connect to voice: {e}")
        return

    logger.success(f"Joined voice channel: {channel.name}")

    bot._manual_leave = False
    if not check_goal.is_running():
        check_goal.start(ctx.guild)
        logger.info("Goal detection loop started.")

    await ctx.send(f"✅ Joined **{channel.name}** and started goal detection.")


@bot.command(name='leave', help='Leave the voice channel and stop goal detection')
async def leave(ctx):
    bot._manual_leave = True
    voice_client = ctx.message.guild.voice_client
    if voice_client and voice_client.is_connected():
        if check_goal.is_running():
            check_goal.stop()
            logger.info("Goal detection loop stopped.")
        await voice_client.disconnect()
        logger.info("Left voice channel.")
        await ctx.send("👋 Left the voice channel.")
    else:
        await ctx.send("❌ Not connected to a voice channel.")


@bot.command(name='restart', help='Restart the bot (auto-relaunches via watcher)')
@owner_only()
async def restart(ctx):
    await ctx.send("🔄 Restarting…")
    logger.warn("Restart requested by user.")
    try:
        if check_goal.is_running():
            check_goal.stop()
        voice_client = ctx.message.guild.voice_client
        if voice_client and voice_client.is_connected():
            await asyncio.wait_for(voice_client.disconnect(), timeout=2.0)
        await asyncio.wait_for(bot.close(), timeout=2.0)
    except Exception as e:
        logger.error(f"Error during graceful restart shutdown: {e}")
    finally:
        os._exit(0)


@bot.command(name="commands", aliases=["cmds", "help"], help="Show all available bot commands")
async def commands_list(ctx):
    embed = discord.Embed(
        title="🎮 RLScoreBot — Commands",
        description=f"Prefix: `>` — e.g. `>join`",
        color=discord.Color.from_str("#5865F2"),
    )
    embed.add_field(
        name="🔊 Voice & Detection",
        value=(
            "`>join` — Join your voice channel and start goal detection\n"
            "`>leave` — Leave the voice channel and stop detection\n"
            "`>play [id]` — Play a random sound or specify a sound by ID\n"
            "🔒 `>restart` — Restart the bot (owner only)"
        ),
        inline=False,
    )
    embed.add_field(
        name="🎵 Sound Management",
        value=(
            "`>list` — List all loaded sounds with their IDs\n"
            "`>upload <name>` — Upload a new sound (attach audio) — auto-normalizes\n"
            "🔒 `>delete <id>` — Delete a sound by its ID (owner only)\n"
            "`>refresh` — Reload sounds from disk\n"
            f"🔒 `>normalize` — Normalize all sounds to {TARGET_LUFS} LUFS (owner only)"
        ),
        inline=False,
    )
    embed.add_field(
        name="🛠️ Utilities",
        value=(
            "`>commands` / `>cmds` / `>help` — Show this command list\n"
            "`>stats` — Goals scored, sounds played, top 10 leaderboard\n"
            "🔒 `>status_sync` — Sync custom status to Gemini generation (owner only)\n"
            "🔒 `>test` — Run a full self-test and show pass/fail report (owner only)"
        ),
        inline=False,
    )
    embed.set_footer(text=f"Sounds loaded: {len(sounds)}  •  Volume: {TARGET_LUFS} LUFS  •  🔒 = Owner Only")
    await ctx.send(embed=embed)


@bot.command(name="test", help="Run a self-test of all bot systems")
@owner_only()
async def test_cmd(ctx):
    status_msg = await ctx.send("🔬 Running self-test…")
    logger.divider("TEST")

    results = []

    if sounds:
        logger.success(f"Sounds loaded: {len(sounds)}")
        results.append(("✅", "Sounds loaded", f"{len(sounds)} sounds in memory"))
    else:
        logger.warn("No sounds loaded")
        results.append(("❌", "Sounds loaded", "No sounds — try `>refresh`"))

    ffmpeg_path = utils.full_path(FFMPEG_NAME)
    if os.path.isfile(ffmpeg_path):
        logger.success(f"FFmpeg found: {ffmpeg_path}")
        results.append(("✅", "FFmpeg found", ffmpeg_path))
    else:
        logger.error(f"FFmpeg missing: {ffmpeg_path}")
        results.append(("❌", "FFmpeg found", f"Missing at `{ffmpeg_path}`"))

    sounds_dir = utils.full_path(SOUNDS_DIR_NAME)
    if os.path.isdir(sounds_dir):
        disk_files = os.listdir(sounds_dir)
        results.append(("✅", "Sounds directory", f"{len(disk_files)} files on disk"))
    else:
        results.append(("❌", "Sounds directory", "Directory not found"))

    missing = [
        name for name in sounds.values()
        if not os.path.isfile(utils.full_path(SOUNDS_DIR_NAME, name))
    ]
    if not missing:
        results.append(("✅", "File integrity", "All registered sounds exist on disk"))
    else:
        logger.warn(f"Missing files: {missing}")
        results.append(("⚠️", "File integrity", f"{len(missing)} missing: {', '.join(missing[:5])}"))

    if DISCORD_TOKEN:
        results.append(("✅", "Discord token", "Token loaded from .env"))
    else:
        logger.error("DISCORD_TOKEN not set")
        results.append(("❌", "Discord token", "DISCORD_TOKEN not set in .env"))

    # Stats file check
    stats_path = utils.full_path("stats.json")
    if os.path.isfile(stats_path):
        try:
            with open(stats_path, encoding="utf-8") as f:
                loaded_stats = json.load(f)
            goals = loaded_stats.get("total_goals", 0)
            plays = sum(loaded_stats.get("play_counts", {}).values())
            results.append(("✅", "Stats file (stats.json)", f"Found and readable ({goals} goals, {plays} plays recorded)"))
        except Exception as e:
            results.append(("❌", "Stats file (stats.json)", f"Found but corrupted: {e}"))
    else:
        results.append(("⚠️", "Stats file (stats.json)", "Not found (will be created automatically)"))

    # Owner ID check
    if OWNER_ID:
        results.append(("✅", "Owner ID configuration", f"Configured ID: `{OWNER_ID}`"))
    else:
        results.append(("⚠️", "Owner ID configuration", "OWNER_ID not set in .env. Owner-only commands disabled."))

    voice_client = ctx.guild.voice_client
    if voice_client and voice_client.is_connected():
        results.append(("✅", "Voice connection", f"Connected to **{voice_client.channel.name}**"))
        loop_state = "running" if check_goal.is_running() else "stopped"
        results.append(("✅" if check_goal.is_running() else "⚠️", "Goal detection loop", loop_state))
    else:
        results.append(("⚠️", "Voice connection", "Not in a voice channel (use `>join`)"))
        results.append(("⚠️", "Goal detection loop", "Not started — joins automatically on `>join`"))

    if voice_client and voice_client.is_connected() and sounds:
        if voice_client.is_playing():
            results.append(("⚠️", "Audio playback", "Already playing — skipped live test"))
        else:
            test_sound = random_sound()
            play_sound(voice_client, test_sound)
            results.append(("✅", "Audio playback", f"Playing `{test_sound}` now — can you hear it?"))
    else:
        results.append(("⏭️", "Audio playback", "Skipped — join a voice channel to test audio"))

    logger.divider()

    all_pass = all(e[0] == "✅" for e in results)
    embed = discord.Embed(
        title="🔬 Self-Test Report",
        color=discord.Color.green() if all_pass else discord.Color.orange(),
    )
    for emoji, label, detail in results:
        embed.add_field(name=f"{emoji} {label}", value=detail, inline=False)

    pass_count = sum(1 for e in results if e[0] == "✅")
    embed.set_footer(text=f"{pass_count}/{len(results)} checks passed")

    await status_msg.delete()
    await ctx.send(embed=embed)


# ── Goal detection loop ───────────────────────────────────────────────────────

prev_img = None
img = None
consecutive_frames  = 0
last_detected_idx   = -1
current_game_score  = -1

@tasks.loop(seconds=0.2)
async def check_goal(guild):
    global prev_img, img, consecutive_frames, last_detected_idx, current_game_score

    voice_client = guild.voice_client
    if not voice_client or not voice_client.is_connected():
        return

    try:
        img = score_detector.get_score_img()
    except RuntimeError:
        return

    if not prev_img:
        prev_img = img

    try:
        if score_detector.compare_images(img, prev_img) < score_detector.DIFFERENCE_SIMILARITY_THRESHOLD:
            best_match     = 0
            best_match_idx = -1

            for i, saved_img in enumerate(score_detector.SAVED_IMAGES):
                score = score_detector.compare_images(img, saved_img)
                if score > best_match:
                    best_match     = score
                    best_match_idx = i

            if best_match > score_detector.SAVED_IMAGE_SIMILARITY_THRESHOLD:
                if best_match_idx == last_detected_idx:
                    consecutive_frames += 1
                else:
                    consecutive_frames = 1
                    last_detected_idx  = best_match_idx

                if consecutive_frames >= 3:
                    # Case 1: Initialization
                    if current_game_score == -1:
                        current_game_score = best_match_idx
                        logger.detection("Initialized", f"score = {current_game_score}")
                        prev_img = img
                        return

                    # Case 2: Game Reset
                    if best_match_idx == 0:
                        if current_game_score != 0:
                            logger.detection("Game reset", "score → 0")
                            current_game_score = 0
                        prev_img = img
                        return

                    # Case 3: Goal Scored
                    if best_match_idx == current_game_score + 1:
                        logger.goal(current_game_score, best_match_idx)
                        current_game_score = best_match_idx
                        record_goal()
                        play_sound(voice_client, random_sound())
                        consecutive_frames = 0
                        prev_img = img
                        return

                    # Case 4: Same Score
                    if best_match_idx == current_game_score:
                        prev_img = img
                        return

                    # Case 5: Illogical jump (noise)
                    consecutive_frames = 0
                    prev_img = img
            else:
                consecutive_frames = 0
                last_detected_idx  = -1

    except Exception as e:
        logger.error(f"Detection loop: {e}")


@bot.command(name="stats", help="Show play stats and goal counts")
async def stats_cmd(ctx):
    uptime = _dt.now() - _bot_start_time
    h, rem = divmod(int(uptime.total_seconds()), 3600)
    m, s   = divmod(rem, 60)
    uptime_str = f"{h}h {m}m {s}s" if h else f"{m}m {s}s"

    # Top 10 most played (all-time)
    top = sorted(_stats["play_counts"].items(), key=lambda x: x[1], reverse=True)[:10]

    embed = discord.Embed(
        title="📊 RLScoreBot — Stats",
        color=discord.Color.from_str("#5865F2"),
    )
    embed.add_field(
        name="🎯 Goals",
        value=(
            f"This session: **{_session_goals}**\n"
            f"All-time: **{_stats['total_goals']}**"
        ),
        inline=True,
    )
    embed.add_field(
        name="🎵 Sounds Played",
        value=(
            f"This session: **{_session_plays}**\n"
            f"Sounds loaded: **{len(sounds)}**"
        ),
        inline=True,
    )
    embed.add_field(name="⏱️ Uptime", value=uptime_str, inline=True)

    if top:
        leaderboard = "\n".join(
            f"`{i+1}.` {os.path.splitext(name)[0]} — **{count}** plays"
            for i, (name, count) in enumerate(top)
        )
        embed.add_field(name="🏆 Most Played (All-Time)", value=leaderboard, inline=False)
    else:
        embed.add_field(name="🏆 Most Played", value="No plays recorded yet.", inline=False)

    embed.set_footer(text="Stats persist across restarts  •  Session resets on each launch")
    await ctx.send(embed=embed)


# ── Gemini Status Sync ─────────────────────────────────────────────────────────

async def fetch_random_chat_history(guild):
    """Finds a text channel named 'general' in the guild, picks a random day, and returns up to 50 messages formatted as a chat log."""
    general_channel = None
    for channel in guild.text_channels:
        if channel.name.lower() == "general":
            general_channel = channel
            break
            
    if not general_channel:
        logger.warn("Could not find 'general' channel to fetch status history.")
        return None

    try:
        start_date = general_channel.created_at # UTC timezone-aware
        now = _dt.now(timezone.utc)
        
        delta = now - start_date
        if delta.total_seconds() <= 0:
            logger.warn("General channel has no valid age/history.")
            return None
            
        random_seconds = random.randint(0, max(1, int(delta.total_seconds())))
        random_time = start_date + timedelta(seconds=random_seconds)

        messages = []
        # Fetch up to 50 messages starting after the random time
        async for msg in general_channel.history(limit=50, after=random_time):
            if msg.author.bot or not msg.content.strip():
                continue
            messages.append(f"{msg.author.display_name}: {msg.content.strip()}")
            
        if not messages:
            # Fallback: just fetch the latest 50 messages if the random date was empty
            async for msg in general_channel.history(limit=50):
                if msg.author.bot or not msg.content.strip():
                    continue
                messages.append(f"{msg.author.display_name}: {msg.content.strip()}")
            # Reverse fallback messages to restore chronological order (newest to oldest by default)
            messages.reverse()
                
        return "\n".join(messages)
    except Exception as e:
        logger.error(f"Error fetching random chat history: {e}")
        return None


async def generate_status_from_chat(chat_text: str, api_key: str) -> str:
    """Sends chat text to the Gemini API and generates a funny custom status."""
    if not api_key:
        logger.warn("Gemini API key is missing. Cannot generate status.")
        return None

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{
            "parts": [{
                "text": (
                    "Below is a segment of chat history from a Discord channel.\n"
                    "Generate a funny, concise custom status for a bot based on this chat.\n"
                    "Requirements:\n"
                    "1. Must be under 128 characters (extremely short and punchy).\n"
                    "2. Must sound like a custom status message (e.g. an activity, a funny quote, or a dry joke).\n"
                    "3. Absolutely do NOT wrap in quotation marks or prefix with 'Status:' or anything similar.\n"
                    "4. Output only the status text itself.\n\n"
                    f"Chat History:\n{chat_text}"
                )
            }]
        }]
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    candidates = data.get('candidates', [])
                    if not candidates:
                        logger.warn("Gemini returned no status candidates (possibly filtered).")
                        return None
                        
                    candidate = candidates[0]
                    finish_reason = candidate.get('finishReason')
                    if finish_reason == 'SAFETY':
                        logger.warn("Gemini blocked status generation due to safety settings (flagged content).")
                        return None
                        
                    content = candidate.get('content')
                    if not content or not content.get('parts'):
                        logger.warn(f"Gemini response structure is missing content/parts. Finish reason: {finish_reason}")
                        return None
                        
                    status_text = content['parts'][0]['text'].strip()
                    if (status_text.startswith('"') and status_text.endswith('"')) or (status_text.startswith("'") and status_text.endswith("'")):
                        status_text = status_text[1:-1].strip()
                    return status_text[:120]  # truncate to safe limit
                else:
                    err_body = await response.text()
                    logger.error(f"Gemini API returned status {response.status}: {err_body}")
                    return None
    except Exception as e:
        import traceback
        tb_str = "".join(traceback.format_exception(type(e), e, e.__traceback__))
        logger.error(f"Failed to generate status from Gemini ({type(e).__name__}):\n{tb_str}")
        return None


async def update_bot_status(guild) -> str:
    """Orchestrates fetching history, calling Gemini, and setting the bot's custom status."""
    if not GEMINI_API_KEY:
        logger.warn("GEMINI_API_KEY not configured in environment. Custom status sync skipped.")
        return None

    logger.info("Syncing custom status with random chat history...")
    chat_log = await fetch_random_chat_history(guild)
    if not chat_log:
        logger.warn("No chat log fetched. Skipping status sync.")
        return None

    status_text = await generate_status_from_chat(chat_log, GEMINI_API_KEY)
    if not status_text:
        logger.warn("Could not generate status from chat history.")
        return None

    activity = discord.CustomActivity(name=status_text)
    await bot.change_presence(activity=activity)
    logger.success(f"Custom status updated to: \"{status_text}\"")
    return status_text


@tasks.loop(hours=6)
async def auto_status_loop():
    for guild in bot.guilds:
        status_text = await update_bot_status(guild)
        if status_text:
            break


@tasks.loop(seconds=1)
async def monitor_game_status():
    """Gracefully shuts down the bot if Rocket League isn't running (with a 60s startup grace period)."""
    if not is_rl_running():
        now = _dt.now()
        uptime = now - _bot_start_time
        if getattr(monitor_game_status, "_seen_running", False) or uptime.total_seconds() > 60:
            logger.warn("Rocket League is not running. Shutting down bot gracefully...")
            voice_client = discord.utils.get(bot.voice_clients)
            if voice_client and voice_client.is_connected():
                await voice_client.disconnect()
            await bot.close()
            os._exit(2)
    else:
        monitor_game_status._seen_running = True
        
        if not getattr(bot, "_manual_leave", False) and not getattr(monitor_game_status, "_is_connecting", False):
            if not any(vc.is_connected() for vc in bot.voice_clients):
                for guild in bot.guilds:
                    owner = guild.get_member(OWNER_ID)
                    if owner and owner.voice and owner.voice.channel:
                        monitor_game_status._is_connecting = True
                        try:
                            # Using asyncio.create_task to not block the loop, but since connect() blocks, 
                            # we can just await it directly as the loop handles it
                            await owner.voice.channel.connect(reconnect=False)
                            logger.success(f"Auto-joined voice channel: {owner.voice.channel.name}")
                            if not check_goal.is_running():
                                check_goal.start(guild)
                                logger.info("Goal detection loop started automatically.")
                        except Exception as e:
                            logger.error(f"Failed to auto-join: {e}")
                        finally:
                            monitor_game_status._is_connecting = False
                        break


@bot.command(name="status_sync", help="Manually trigger an LLM-generated status update from random general chat history")
@owner_only()
async def status_sync_cmd(ctx):
    status_msg = await ctx.send("⏳ Fetching chat history and generating custom status...")
    status_text = await update_bot_status(ctx.guild)
    if status_text:
        await status_msg.edit(content=f"✅ Custom status updated to: \"{status_text}\"")
    else:
        await status_msg.edit(content="❌ Failed to update custom status. Check console logs for details.")


# ── Events ────────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    logger.success(f"Connected to Discord as {bot.user}")
    logger.divider("READY")
    if not auto_status_loop.is_running():
        auto_status_loop.start()
        logger.info("Custom status auto-update loop started.")
    if not monitor_game_status.is_running():
        monitor_game_status.start()
        logger.info("Game status monitor loop started.")


@bot.event
async def on_message(message):
    await bot.process_commands(message)


# ── Entry point ───────────────────────────────────────────────────────────────

async def main():
    async with bot:
        await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    import traceback as _tb

    CRASH_LOG = utils.full_path("crash.log")

    def write_crash(exc: BaseException):
        """Append a crash report to crash.log."""
        timestamp = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
        sep = "=" * 60
        report = (
            f"\n{sep}\n"
            f"CRASH  {timestamp}\n"
            f"{sep}\n"
            f"Exception : {type(exc).__name__}: {exc}\n"
            f"Uptime    : {_dt.now() - _bot_start_time}\n"
            f"Sounds    : {len(sounds)} loaded\n"
            f"Session goals : {_session_goals}\n"
            f"\nTraceback:\n"
            f"{_tb.format_exc()}\n"
            f"{sep}\n"
        )
        try:
            with open(CRASH_LOG, "a", encoding="utf-8") as f:
                f.write(report)
            logger.error(f"Crash written to crash.log")
        except Exception:
            pass

    logger.banner()
    load_sounds()
    load_stats()

    if not DISCORD_TOKEN:
        logger.error("DISCORD_TOKEN not found. Create a .env file with your token.")
    elif not os.path.exists(utils.full_path(FFMPEG_NAME)):
        logger.error(f"{FFMPEG_NAME} not found. Place ffmpeg.exe in the project folder.")
    else:
        logger.info("Starting bot…")
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            logger.warn("Bot stopped by user.")
        except Exception as e:
            logger.error(f"Fatal crash: {type(e).__name__}: {e}")
            write_crash(e)
            logger.warn("Window closing in 10 seconds — check crash.log for details")
            import time as _time; _time.sleep(10)