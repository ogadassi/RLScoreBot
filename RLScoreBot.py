import asyncio
import os
import random
import re
import json
import time
import sqlite3
import aiohttp
import functools
import cv2
import numpy as np
from PIL import ImageGrab
from datetime import datetime as _dt, timezone
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

import utils
import logger
import score_detector

load_dotenv()
DISCORD_TOKEN  = os.getenv("DISCORD_TOKEN")
OWNER_ID       = int(os.getenv("OWNER_ID", "0"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

SOUNDS_DIR_NAME = "sounds"
FFMPEG_NAME     = "ffmpeg.exe"

_bot_start_time = _dt.now()
_session_goals  = 0
_session_plays  = 0

_stats_path = utils.full_path("stats.json")

def load_stats():
    if os.path.isfile(_stats_path):
        try:
            with open(_stats_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"total_goals": 0, "play_counts": {}}

def save_stats(data):
    try:
        with open(_stats_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to save stats.json: {e}")

_stats = load_stats()

def record_goal():
    global _session_goals, _stats
    _session_goals += 1
    _stats["total_goals"] = _stats.get("total_goals", 0) + 1
    save_stats(_stats)

def record_play(sound_filename):
    global _session_plays, _stats
    _session_plays += 1
    counts = _stats.setdefault("play_counts", {})
    counts[sound_filename] = counts.get(sound_filename, 0) + 1
    save_stats(_stats)

def normalize_name(s):
    base, _ = os.path.splitext(s.lower())
    return re.sub(r'[\s_\-]+', '', base)

def scan_sounds():
    dir_path = utils.full_path(SOUNDS_DIR_NAME)
    if not os.path.isdir(dir_path):
        logger.error(f"Sounds directory missing at: {dir_path}")
        return {}
    sound_map = {}
    for filename in os.listdir(dir_path):
        if filename.endswith(".mp3"):
            norm = normalize_name(filename)
            sound_map[norm] = filename
    return sound_map

sounds = scan_sounds()

def random_sound():
    if not sounds:
        return None
    return random.choice(list(sounds.values()))

def play_sound(voice_client, sound_filename):
    if not voice_client or not voice_client.is_connected():
        logger.warn("Voice client not connected.")
        return
    if not sound_filename:
        logger.warn("No sound available to play.")
        return
    if voice_client.is_playing():
        logger.info("Already playing audio — goal skipped.")
        return
    sound_path = utils.full_path(SOUNDS_DIR_NAME, sound_filename)
    if not os.path.isfile(sound_path):
        logger.error(f"Sound file missing: {sound_path}")
        return
    ffmpeg_path = utils.full_path(FFMPEG_NAME)
    if not os.path.isfile(ffmpeg_path):
        ffmpeg_path = "ffmpeg"

    record_play(sound_filename)
    voice_client.play(discord.FFmpegPCMAudio(
        executable=ffmpeg_path,
        source=sound_path,
    ))
    logger.playing(sound_filename)

intents = discord.Intents.default()
intents.voice_states    = True
intents.message_content = True

bot = commands.Bot(command_prefix=">", intents=intents, help_command=None)

def is_rl_running():
    try:
        cmd = 'tasklist /FI "IMAGENAME eq RocketLeague.exe" /FO CSV /NH'
        out = os.popen(cmd).read()
        return "RocketLeague.exe" in out
    except Exception as e:
        logger.error(f"Error checking RL process: {e}")
        return False

def owner_only():
    async def predicate(ctx):
        if not OWNER_ID:
            await ctx.send("❌ `OWNER_ID` not set in `.env`. Owner commands disabled.")
            return False
        if ctx.author.id != OWNER_ID:
            await ctx.send("❌ Permission denied. Owner-only command.")
            return False
        return True
    return commands.check(predicate)

# ── Prefix Commands ───────────────────────────────────────────────────────────

@bot.command(name="help", help="Show all available commands")
async def help_cmd(ctx):
    embed = discord.Embed(
        title="🎮 RLScoreBot — Commands",
        description="Auto goal celebration bot for Rocket League",
        color=discord.Color.from_str("#5865F2"),
    )
    embed.add_field(
        name=">join",
        value="Join your current voice channel & start goal detection",
        inline=False,
    )
    embed.add_field(
        name=">leave",
        value="Leave the voice channel & stop goal detection",
        inline=False,
    )
    embed.add_field(
        name=">play [sound]",
        value="Play a specific sound or a random sound if no name given",
        inline=False,
    )
    embed.add_field(
        name=">list",
        value="List all available sound files in the library",
        inline=False,
    )
    embed.add_field(
        name=">stats",
        value="Show goal counts & play statistics",
        inline=False,
    )
    embed.add_field(
        name=">upload [sound_name]",
        value="Upload an MP3 sound file to the sound library",
        inline=False,
    )
    embed.add_field(
        name=">refresh",
        value="[Owner] Reload sounds from disk without restarting",
        inline=False,
    )
    embed.add_field(
        name=">status_sync",
        value="[Owner] Manually trigger custom status sync from chat history",
        inline=False,
    )
    embed.add_field(
        name=">test",
        value="[Owner] Run diagnostic self-test",
        inline=False,
    )
    embed.set_footer(text="Prefix: >  |  RLScoreBot v2.0")
    await ctx.send(embed=embed)


@bot.command(name="join", help="Join your voice channel and start score detection")
async def join_cmd(ctx):
    bot._manual_leave = False
    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.send("❌ You need to be in a voice channel first!")
        return

    channel = ctx.author.voice.channel
    voice_client = ctx.guild.voice_client

    if voice_client and voice_client.is_connected():
        await voice_client.move_to(channel)
        logger.info(f"Moved to voice channel: {channel.name}")
    else:
        await channel.connect()
        logger.info(f"Joined voice channel: {channel.name}")

    if not check_goal.is_running():
        check_goal.start(ctx.guild)
        logger.info("Goal detection loop started manually.")

    await ctx.send(f"✅ Joined **{channel.name}**! Score detection active.")


@bot.command(name="leave", help="Leave the voice channel and stop score detection")
async def leave_cmd(ctx):
    bot._manual_leave = True
    voice_client = ctx.guild.voice_client

    if check_goal.is_running():
        check_goal.stop()
        logger.info("Goal detection loop stopped.")

    if voice_client and voice_client.is_connected():
        await voice_client.disconnect()
        logger.info("Disconnected from voice channel.")
        await ctx.send("👋 Disconnected from voice channel.")
    else:
        await ctx.send("⚠️ I'm not in a voice channel.")


@bot.command(name="play", help="Play a sound by name or random if omitted")
async def play_cmd(ctx, *, sound_name: str = None):
    voice_client = ctx.guild.voice_client
    if not voice_client or not voice_client.is_connected():
        await ctx.send("❌ I'm not in a voice channel! Use `>join` first.")
        return

    if sound_name is None:
        chosen = random_sound()
        if not chosen:
            await ctx.send("❌ Sound library is empty.")
            return
        play_sound(voice_client, chosen)
        await ctx.send(f"🎵 Playing random sound: **`{chosen}`**")
        return

    norm = normalize_name(sound_name)
    if norm in sounds:
        play_sound(voice_client, sounds[norm])
        await ctx.send(f"🎵 Playing: **`{sounds[norm]}`**")
    else:
        matched_file = None
        for key, val in sounds.items():
            if norm in key:
                matched_file = val
                break

        if matched_file:
            play_sound(voice_client, matched_file)
            await ctx.send(f"🎵 Playing closest match: **`{matched_file}`**")
        else:
            await ctx.send(f"❌ Sound `'{sound_name}'` not found. Use `>list` to see available sounds.")


@bot.command(name="list", help="List all available sound files")
async def list_cmd(ctx):
    if not sounds:
        await ctx.send("❌ Sound library is empty.")
        return

    sound_names = sorted(sounds.values())
    list_str = "\n".join(f"`{i+1}.` {os.path.splitext(s)[0]}" for i, s in enumerate(sound_names))

    if len(list_str) > 1900:
        pages = []
        current = ""
        for line in list_str.split("\n"):
            if len(current) + len(line) + 1 > 1900:
                pages.append(current)
                current = line
            else:
                current += f"\n{line}" if current else line
        if current:
            pages.append(current)

        for idx, page in enumerate(pages):
            embed = discord.Embed(
                title=f"🎵 Sound Library ({idx+1}/{len(pages)})",
                description=page,
                color=discord.Color.from_str("#5865F2"),
            )
            await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title=f"🎵 Sound Library ({len(sounds)} sounds)",
            description=list_str,
            color=discord.Color.from_str("#5865F2"),
        )
        await ctx.send(embed=embed)


@bot.command(name="upload", help="Upload a new sound file (.mp3)")
async def upload_cmd(ctx, *, custom_name: str = None):
    if not ctx.message.attachments:
        await ctx.send("❌ Please attach an `.mp3` file to your message!")
        return

    attachment = ctx.message.attachments[0]
    filename = attachment.filename

    if not filename.lower().endswith(".mp3"):
        await ctx.send("❌ Only `.mp3` files are supported!")
        return

    if custom_name:
        safe_name = re.sub(r'[\s_\-]+', '_', custom_name.strip()).lower()
        if not safe_name.endswith(".mp3"):
            safe_name += ".mp3"
        save_filename = safe_name
    else:
        save_filename = filename

    sounds_dir = utils.full_path(SOUNDS_DIR_NAME)
    if not os.path.exists(sounds_dir):
        os.makedirs(sounds_dir, exist_ok=True)

    dest_path = os.path.join(sounds_dir, save_filename)
    await attachment.save(dest_path)

    global sounds
    sounds = scan_sounds()

    logger.success(f"Sound uploaded and saved to: {dest_path}")

    embed = discord.Embed(
        title="✅ Sound Uploaded!",
        description=f"Saved as: **`{save_filename}`**\nTotal sounds: **{len(sounds)}**",
        color=discord.Color.green(),
    )
    embed.add_field(name="How to play it", value=f"`>play {os.path.splitext(save_filename)[0]}`", inline=False)
    await ctx.send(embed=embed)


@bot.command(name="refresh", help="Reload sound files from disk")
@owner_only()
async def refresh_cmd(ctx):
    global sounds
    sounds = scan_sounds()
    logger.success(f"Sound library refreshed: {len(sounds)} sounds loaded")
    await ctx.send(f"✅ Sound library reloaded! **{len(sounds)}** sounds active.")


@bot.command(name="test", help="Run diagnostic self-test")
@owner_only()
async def test_cmd(ctx):
    logger.divider()
    logger.info("Running self-test diagnostics...")

    status_msg = await ctx.send("🔬 Running self-test diagnostics...")
    results = []

    if sounds:
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


# ── Goal Detection Loop ───────────────────────────────────────────────────────

prev_img = None
img = None
consecutive_frames  = 0
last_detected_idx   = -1
current_game_score  = -1

@tasks.loop(seconds=0.1)
async def check_goal(guild):
    global prev_img, img, consecutive_frames, last_detected_idx, current_game_score

    voice_client = guild.voice_client
    if not voice_client or not voice_client.is_connected():
        return

    try:
        raw_screen = ImageGrab.grab()
        screen_np   = np.array(raw_screen)
        screen_bgr  = cv2.cvtColor(screen_np, cv2.COLOR_RGB2BGR)

        h, w = screen_bgr.shape[:2]
        crop_h = int(h * 0.15)
        crop_w = int(w * 0.30)
        start_x = int((w - crop_w) / 2)

        cropped = screen_bgr[0:crop_h, start_x:start_x + crop_w]
        img = score_detector.process_image(cropped)

        if prev_img is None:
            prev_img = img
            return

        diff_score = score_detector.calculate_image_difference(img, prev_img)

        if diff_score > 0.05:
            best_match = -1.0
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
                    if current_game_score == -1:
                        current_game_score = best_match_idx
                        logger.detection("Initialized", f"score = {current_game_score}")
                        prev_img = img
                        return

                    if best_match_idx == 0:
                        if current_game_score != 0:
                            logger.detection("Game reset", "score → 0")
                            current_game_score = 0
                        prev_img = img
                        return

                    if best_match_idx == current_game_score + 1:
                        logger.goal(current_game_score, best_match_idx)
                        current_game_score = best_match_idx
                        record_goal()
                        play_sound(voice_client, random_sound())
                        consecutive_frames = 0
                        prev_img = img
                        return

                    if best_match_idx == current_game_score:
                        prev_img = img
                        return

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
    general_channel = None
    for channel in guild.text_channels:
        if channel.name.lower() == "general":
            general_channel = channel
            break
            
    if not general_channel:
        logger.warn("Could not find 'general' channel to fetch status history.")
        return None

    try:
        start_date = general_channel.created_at
        now = _dt.now(timezone.utc)
        
        delta = now - start_date
        if delta.total_seconds() <= 0:
            logger.warn("General channel has no valid age/history.")
            return None
            
        random_seconds = random.randint(0, max(1, int(delta.total_seconds())))
        random_time = start_date + timedelta(seconds=random_seconds)

        messages = []
        async for msg in general_channel.history(limit=50, after=random_time):
            if msg.author.bot or not msg.content.strip():
                continue
            messages.append(f"{msg.author.display_name}: {msg.content.strip()}")
            
        if not messages:
            async for msg in general_channel.history(limit=50):
                if msg.author.bot or not msg.content.strip():
                    continue
                messages.append(f"{msg.author.display_name}: {msg.content.strip()}")
            messages.reverse()
                
        return "\n".join(messages)
    except Exception as e:
        logger.error(f"Error fetching random chat history: {e}")
        return None


async def generate_status_from_chat(chat_text: str, api_key: str) -> str:
    if not api_key:
        logger.warn("Gemini API key is missing. Cannot generate status.")
        return None

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key={api_key}"
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
                        logger.warn("Gemini returned no status candidates.")
                        return None
                        
                    candidate = candidates[0]
                    content = candidate.get('content')
                    if not content or not content.get('parts'):
                        return None
                        
                    status_text = content['parts'][0]['text'].strip()
                    lines = [l.strip().lstrip('*').lstrip('>').strip() for l in status_text.splitlines() if l.strip()]
                    clean_text = lines[0] if lines else status_text
                    if (clean_text.startswith('"') and clean_text.endswith('"')) or (clean_text.startswith("'") and clean_text.endswith("'")):
                        clean_text = clean_text[1:-1].strip()
                    return clean_text[:120]
                else:
                    err = await response.text()
                    logger.error(f"Gemini API returned status {response.status}: {err[:150]}")
                    return None
    except Exception as e:
        logger.error(f"Error calling Gemini API: {e}")
        return None


async def update_bot_status(guild):
    if not GEMINI_API_KEY:
        logger.warn("GEMINI_API_KEY not found in .env. Custom status disabled.")
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
                try:
                    await voice_client.disconnect(force=True)
                except Exception:
                    pass
            await asyncio.sleep(0.5)
            await bot.close()
            import sys
            sys.exit(2)
    else:
        monitor_game_status._seen_running = True
        
        if not getattr(bot, "_manual_leave", False) and not getattr(monitor_game_status, "_is_connecting", False):
            if not any(vc.is_connected() for vc in bot.voice_clients):
                for guild in bot.guilds:
                    owner = guild.get_member(OWNER_ID)
                    if owner and owner.voice and owner.voice.channel:
                        monitor_game_status._is_connecting = True
                        try:
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

@bot.event
async def on_voice_state_update(member, before, after):
    """Auto-disconnect from voice channel if no human members remain."""
    for vc in bot.voice_clients:
        if vc.channel:
            human_members = [m for m in vc.channel.members if not m.bot]
            if len(human_members) == 0:
                logger.info(f"Voice channel #{vc.channel.name} is empty. Disconnecting...")
                try:
                    await vc.disconnect()
                except Exception as e:
                    logger.error(f"Disconnect error: {e}")


@bot.command(name="status_sync", help="Manually trigger an LLM-generated status update from random general chat history")
@owner_only()
async def status_sync_cmd(ctx):
    await ctx.send("⏳ Sampling random historical chat history and calling Gemini AI...")
    status_text = await update_bot_status(ctx.guild)
    if status_text:
        await ctx.send(f"✅ Status updated to: \"{status_text}\"")
    else:
        await ctx.send("❌ Failed to update status. Check bot console logs for details.")


@bot.event
async def on_ready():
    logger.success(f"Connected to Discord as {bot.user}")
    logger.divider()

    if not auto_status_loop.is_running():
        auto_status_loop.start()
        logger.info("Custom status auto-update loop started.")

    if not monitor_game_status.is_running():
        monitor_game_status.start()
        logger.info("Game status monitor loop started.")

async def main():
    if not DISCORD_TOKEN:
        logger.error("DISCORD_TOKEN is missing! Please set it in your .env file.")
        return
    async with bot:
        await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())