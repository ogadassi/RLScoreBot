import asyncio
import os
import random
import re
import json
import sqlite3
import aiohttp
from aiohttp import web
from datetime import datetime as _dt, timezone, timedelta
import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

import utils
import database
import logger

load_dotenv()
DISCORD_TOKEN  = os.getenv("DISCORD_TOKEN")
OWNER_ID       = int(os.getenv("OWNER_ID", "0"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
WEB_PORT       = int(os.getenv("PORT", "8080"))

SOUNDS_DIR_NAME = "sounds"
WEBSITE_DIR_NAME = "website"
FFMPEG_NAME     = "ffmpeg.exe"
TARGET_LUFS     = -14

# ── Audio Normalization Engine ───────────────────────────────────────────────
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
            detail = " | ".join(stderr_text[-3:]) if stderr_text else "ffmpeg conversion issue"
            return False, f"ffmpeg note: {detail}"

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

# ── Gemini AI Status Generation ─────────────────────────────────────────────
async def fetch_random_chat_history(guild):
    general_channel = None
    for channel in guild.text_channels:
        if channel.name.lower() in ["general", "chat", "main"]:
            general_channel = channel
            break
            
    if not general_channel:
        logger.warn("Could not find 'general' channel to fetch status history.")
        return None

    try:
        messages = []
        async for msg in general_channel.history(limit=50):
            if msg.author.bot or not msg.content.strip():
                continue
            messages.append(f"{msg.author.display_name}: {msg.content.strip()}")
            
        if not messages:
            return None
        return "\n".join(messages)
    except Exception as e:
        logger.warn(f"Failed to fetch chat history: {e}")
        return None

async def generate_status_from_chat(chat_log: str, api_key: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    prompt = (
        "Below is a chat log from a Discord server's general chat. "
        "Create a funny, short, iconic 1-sentence Discord status (under 100 characters) "
        "that captures the vibe or inside jokes of the conversation. Output ONLY the status text.\n\n"
        f"CHAT LOG:\n{chat_log}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=15) as response:
                if response.status == 200:
                    data = await response.json()
                    candidates = data.get('candidates', [])
                    if candidates and 'content' in candidates[0]:
                        parts = candidates[0]['content'].get('parts', [])
                        if parts:
                            status_text = parts[0]['text'].strip().strip('"').strip("'")
                            return status_text[:120]
                return None
    except Exception as e:
        logger.warn(f"Gemini API status generation failed: {e}")
        return None

async def update_bot_status(guild) -> str:
    if not GEMINI_API_KEY:
        return None

    chat_log = await fetch_random_chat_history(guild)
    if not chat_log:
        return None

    status_text = await generate_status_from_chat(chat_log, GEMINI_API_KEY)
    if status_text:
        activity = discord.CustomActivity(name=status_text)
        await bot.change_presence(activity=activity)
        logger.success(f"Custom status updated to: \"{status_text}\"")
        return status_text
    return None

# ── Soundboard Manager ───────────────────────────────────────────────────────
def get_available_sounds():
    dir_path = utils.full_path(SOUNDS_DIR_NAME)
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)
    files = [f for f in os.listdir(dir_path) if f.endswith(('.mp3', '.wav', '.ogg', '.flac', '.m4a'))]
    return files if files else ["default_cheer.mp3"]

def get_random_sound():
    sounds = get_available_sounds()
    return random.choice(sounds)

# ── Bot Client Setup ──────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.voice_states = True
intents.message_content = True
bot = commands.Bot(command_prefix='/', intents=intents, help_command=None)

def play_sound_in_vc(voice_client, sound_filename: str):
    if not voice_client or not voice_client.is_connected():
        logger.warn("Voice client not connected.")
        return False

    if voice_client.is_playing():
        logger.info("Voice client already playing audio — overlapping goal skipped.")
        return False

    sound_path = utils.full_path(SOUNDS_DIR_NAME, sound_filename)
    if not os.path.exists(sound_path):
        sound_path = utils.full_path(SOUNDS_DIR_NAME, "default_cheer.mp3")

    ffmpeg_exec = utils.full_path(FFMPEG_NAME)
    if not os.path.exists(ffmpeg_exec):
        ffmpeg_exec = "ffmpeg"

    voice_client.play(discord.FFmpegPCMAudio(
        executable=ffmpeg_exec,
        source=sound_path
    ))
    logger.playing(sound_filename)
    return True

# ── Embedded Web Server & Webhooks ────────────────────────────────────────────
async def handle_index(request):
    """Serve website landing page."""
    index_path = os.path.join(os.path.dirname(__file__), WEBSITE_DIR_NAME, "index.html")
    if os.path.exists(index_path):
        return web.FileResponse(index_path)
    return web.Response(text="<h1>RLScoreBot Cloud Engine Online</h1>", content_type="text/html")

async def handle_goal_webhook(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    token = data.get("api_token")
    if not token:
        return web.json_response({"error": "Missing api_token"}, status=401)

    user_info = database.verify_api_token(token)
    if not user_info:
        return web.json_response({"error": "Invalid pairing token. Run /link in Discord."}, status=403)

    discord_user_id = user_info["discord_user_id"]
    guild_id = user_info.get("active_guild_id")
    vc_id = user_info.get("active_voice_channel_id")

    if not guild_id or not vc_id:
        return web.json_response({"error": "User not active in a voice channel. Run /join in Discord."}, status=400)

    guild = bot.get_guild(int(guild_id))
    if not guild:
        return web.json_response({"error": "Bot not present in user guild."}, status=404)

    channel = guild.get_channel(int(vc_id))
    if not channel:
        return web.json_response({"error": "Voice channel not found."}, status=404)

    voice_client = guild.voice_client
    if not voice_client or not voice_client.is_connected():
        try:
            voice_client = await channel.connect(reconnect=True)
        except Exception as e:
            return web.json_response({"error": f"Failed to connect to voice: {e}"}, status=500)

    sound_to_play = data.get("sound") or get_random_sound()
    success = play_sound_in_vc(voice_client, sound_to_play)
    if success:
        database.record_goal_stat(discord_user_id, guild_id, sound_to_play)

    return web.json_response({
        "status": "success",
        "sound_played": sound_to_play
    })

async def handle_stats_api(request):
    stats = database.get_global_stats()
    return web.json_response(stats)

def setup_web_routes(app):
    app.router.add_get("/", handle_index)
    app.router.add_post("/api/v1/goal", handle_goal_webhook)
    app.router.add_get("/api/v1/stats", handle_stats_api)
    
    website_dir = os.path.join(os.path.dirname(__file__), WEBSITE_DIR_NAME)
    sounds_dir = os.path.join(os.path.dirname(__file__), SOUNDS_DIR_NAME)

    if os.path.exists(sounds_dir):
        app.router.add_static("/sounds", sounds_dir)
        
    if os.path.exists(website_dir):
        app.router.add_static("/style.css", website_dir)
        app.router.add_static("/app.js", website_dir)
        app.router.add_static("/logo.png", website_dir)

# ── Discord Slash Commands ────────────────────────────────────────────────────

@bot.tree.command(name="link", description="Get your 6-digit pairing code to link BakkesMod plugin with Discord.")
async def cmd_link(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    code = database.generate_linking_code(user_id)
    
    embed = discord.Embed(
        title="⚡ RLScoreBot Telemetry Pairing Code",
        description=f"Your pairing code is: **`{code}`**\n\nEnter this code into your game plugin/watcher to link goal telemetry with your Discord Voice Channel.",
        color=discord.Color.blue()
    )
    embed.set_footer(text="Code expires after single use. Keep your pairing code private!")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="join", description="Connect bot to your voice channel for goal celebrations.")
async def cmd_join(interaction: discord.Interaction):
    if not interaction.user.voice:
        await interaction.response.send_message("❌ You are not connected to a voice channel.", ephemeral=True)
        return

    channel = interaction.user.voice.channel
    guild = interaction.guild

    try:
        if guild.voice_client:
            await guild.voice_client.move_to(channel)
        else:
            await channel.connect()
    except Exception as e:
        await interaction.response.send_message(f"❌ Could not join voice channel: {e}", ephemeral=True)
        return

    database.update_user_location(str(interaction.user.id), str(guild.id), str(channel.id))
    await interaction.response.send_message(f"✅ Joined **{channel.name}** and ready to celebrate goals!")

@bot.tree.command(name="leave", description="Disconnect bot from voice channel.")
async def cmd_leave(interaction: discord.Interaction):
    if interaction.guild.voice_client:
        await interaction.guild.voice_client.disconnect()
        await interaction.response.send_message("👋 Left voice channel.")
    else:
        await interaction.response.send_message("❌ Bot is not in a voice channel.", ephemeral=True)

@bot.tree.command(name="upload", description="Upload a custom sound file to the goal soundboard (.mp3, .wav, .ogg).")
async def cmd_upload(interaction: discord.Interaction, file: discord.Attachment, sound_name: str = None):
    ALLOWED_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".m4a"}
    MAX_SIZE = 25 * 1024 * 1024

    _, ext = os.path.splitext(file.filename.lower())
    if ext not in ALLOWED_EXTENSIONS:
        await interaction.response.send_message(f"❌ Unsupported format `{ext}`. Allowed: `.mp3`, `.wav`, `.ogg`, `.flac`, `.m4a`", ephemeral=True)
        return

    if file.size > MAX_SIZE:
        await interaction.response.send_message("❌ File exceeds 25MB maximum upload limit.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    clean_title = sound_name or file.filename
    safe_basename = re.sub(r'[^\w\s\.-]', '', clean_title).strip()
    if not safe_basename.endswith(ext):
        safe_basename += ext

    target_path = utils.full_path(SOUNDS_DIR_NAME, safe_basename)
    
    file_bytes = await file.read()
    with open(target_path, "wb") as f:
        f.write(file_bytes)

    ok, msg = await normalize_audio(target_path)
    database.add_user_sound(str(interaction.user.id), safe_basename, clean_title, target_path)

    embed = discord.Embed(
        title="🎵 New Sound Uploaded to Soundboard!",
        description=f"Successfully added **`{clean_title}`** to the goal celebration soundboard!\n\nVolume normalized to **{TARGET_LUFS} LUFS**.",
        color=discord.Color.green()
    )
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="list", description="List all available goal celebration sounds.")
async def cmd_list(interaction: discord.Interaction):
    sounds = get_available_sounds()
    embed = discord.Embed(
        title="🎧 Goal Celebration Soundboard",
        color=discord.Color.purple()
    )
    sound_lines = "\n".join([f"• `{s}`" for s in sounds])
    embed.add_field(name="Available Sounds", value=sound_lines or "No sounds loaded.", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="play", description="Manually trigger a goal sound in the voice channel.")
async def cmd_play(interaction: discord.Interaction, sound_name: str = None):
    if not interaction.guild.voice_client:
        await interaction.response.send_message("❌ Bot is not in a voice channel. Run `/join` first.", ephemeral=True)
        return

    sound_to_play = sound_name or get_random_sound()
    success = play_sound_in_vc(interaction.guild.voice_client, sound_to_play)
    if success:
        await interaction.response.send_message(f"▶ Playing **`{sound_to_play}`**!")
    else:
        await interaction.response.send_message("⏯️ Bot is already playing a sound.", ephemeral=True)

@bot.tree.command(name="stats", description="Display goal statistics.")
async def cmd_stats(interaction: discord.Interaction):
    stats = database.get_global_stats()
    embed = discord.Embed(
        title="🏆 RLScoreBot Goal Statistics",
        color=discord.Color.gold()
    )
    embed.add_field(name="⚽ Total Goals Celebrated", value=f"**{stats['total_goals']}**", inline=True)
    embed.add_field(name="🎵 Soundboard Library Size", value=f"**{len(get_available_sounds())}**", inline=True)
    await interaction.response.send_message(embed=embed)

@tasks.loop(hours=6)
async def auto_status_loop():
    for guild in bot.guilds:
        status_text = await update_bot_status(guild)
        if status_text:
            break

@bot.event
async def on_ready():
    logger.success(f"Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} slash commands globally.")
    except Exception as e:
        logger.error(f"Failed to sync slash commands: {e}")

    for guild in bot.guilds:
        await update_bot_status(guild)

    if not auto_status_loop.is_running():
        auto_status_loop.start()

    app = web.Application()
    setup_web_routes(app)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", WEB_PORT)
    await site.start()
    logger.success(f"Embedded Web Server listening at http://0.0.0.0:{WEB_PORT}")

async def main():
    if not DISCORD_TOKEN or DISCORD_TOKEN == "your_token_here_do_not_share":
        logger.error("Missing valid DISCORD_TOKEN in .env file.")
        return
    await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())