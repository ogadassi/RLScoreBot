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

    sounds_dir = os.path.dirname(file_path)
    if not os.path.exists(sounds_dir):
        os.makedirs(sounds_dir, exist_ok=True)

    tmp_fd, tmp_path = tempfile.mkstemp(
        suffix=".mp3",
        dir=sounds_dir
    )
    os.close(tmp_fd)

    try:
        ffmpeg_exec = utils.full_path(FFMPEG_NAME)
        if not os.path.exists(ffmpeg_exec):
            ffmpeg_exec = "ffmpeg"

        proc = await asyncio.create_subprocess_exec(
            ffmpeg_exec,
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

# ── Soundboard Manager (100% Server Guild Scoped) ───────────────────────────
def get_guild_sound_library(guild_id: str = None) -> list[str]:
    """
    Returns server-specific uploaded sounds combined with default starter sounds.
    Ensures sounds uploaded in Server A stay isolated to Server A!
    """
    default_sounds = ["default_cheer.mp3", "default_airhorn.mp3"]
    
    if not guild_id:
        dir_path = utils.full_path(SOUNDS_DIR_NAME)
        if os.path.exists(dir_path):
            files = [f for f in os.listdir(dir_path) if f.endswith(('.mp3', '.wav', '.ogg', '.flac', '.m4a'))]
            return files if files else default_sounds
        return default_sounds

    guild_records = database.get_guild_sounds(str(guild_id))
    guild_filenames = [r["filename"] for r in guild_records if r.get("filename")]

    # Combine server custom sounds + default starter sounds
    combined = list(dict.fromkeys(guild_filenames + default_sounds))
    return combined

def get_random_sound_for_guild(guild_id: str = None) -> str:
    sounds = get_guild_sound_library(guild_id)
    return random.choice(sounds)

def build_soundboard_embed(sounds: list[str], title_label: str) -> discord.Embed:
    """Builds a multi-column Discord Embed displaying the ENTIRE soundboard library without cutoffs."""
    embed = discord.Embed(title=title_label, color=discord.Color.purple())
    
    if not sounds:
        embed.description = "No custom sounds uploaded yet."
        return embed

    chunk_size = 20
    for i in range(0, len(sounds), chunk_size):
        chunk = sounds[i:i + chunk_size]
        field_name = f"Sounds ({i+1}–{min(i+chunk_size, len(sounds))} of {len(sounds)})"
        field_val = "\n".join([f"• `{s}`" for s in chunk])
        embed.add_field(name=field_name, value=field_val, inline=True)

    return embed

# ── Robust Gemini AI Status Generation Engine ───────────────────────────────
async def fetch_random_chat_history(guild):
    candidate_channels = [
        c for c in guild.text_channels 
        if c.permissions_for(guild.me).read_message_history and c.permissions_for(guild.me).read_messages
    ]

    if not candidate_channels:
        logger.warn("No accessible text channels found in guild.")
        return None, "No readable text channels found."

    random.shuffle(candidate_channels)

    for channel in candidate_channels:
        try:
            created_at = channel.created_at
            now = _dt.now(timezone.utc)
            delta_days = (now - created_at).days

            before_date = None
            if delta_days > 3:
                random_offset_days = random.randint(0, delta_days - 1)
                before_date = now - timedelta(days=random_offset_days)

            messages = []
            async for msg in channel.history(limit=50, before=before_date):
                if msg.author.bot or not msg.content.strip():
                    continue
                messages.append(f"{msg.author.display_name}: {msg.content.strip()}")
                
            if len(messages) >= 3:
                logger.info(f"Sampled {len(messages)} historical messages from #{channel.name}")
                sample_label = f"#{channel.name} ({'Random Archive' if before_date else 'Recent'})"
                return "\n".join(reversed(messages)), sample_label
        except Exception as e:
            logger.warn(f"Could not sample channel #{channel.name}: {e}")
            continue

    return None, "No text messages found in server history."

async def generate_status_from_chat(chat_log: str, api_key: str) -> tuple[str, str]:
    models_to_try = [
        "gemini-2.0-flash",
        "gemini-2.5-flash",
        "gemini-1.5-flash-latest",
        "gemini-1.5-pro-latest"
    ]

    prompt = (
        "Below is a chat log from a Discord server's conversation. "
        "Create a funny, short, iconic 1-sentence Discord status (under 100 characters) "
        "that captures the vibe, humor, or inside jokes of the conversation. Output ONLY the status text.\n\n"
        f"CHAT LOG:\n{chat_log}"
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }

    last_error = "Unknown error"
    async with aiohttp.ClientSession() as session:
        for model in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            try:
                async with session.post(url, json=payload, timeout=15) as response:
                    if response.status == 200:
                        data = await response.json()
                        candidates = data.get('candidates', [])
                        if candidates and 'content' in candidates[0]:
                            parts = candidates[0]['content'].get('parts', [])
                            if parts:
                                status_text = parts[0]['text'].strip().strip('"').strip("'")
                                return status_text[:120], f"Model {model}"
                    elif response.status == 429:
                        last_error = f"Gemini API rate limited (HTTP 429). Please wait before requesting again."
                        logger.warn(last_error)
                    else:
                        err_text = await response.text()
                        last_error = f"Gemini {model} HTTP {response.status}: {err_text[:100]}"
                        logger.error(last_error)
            except Exception as e:
                last_error = f"Gemini {model} exception: {e}"
                logger.warn(last_error)

    return None, last_error

_last_status_update_time = None

async def update_bot_status(guild) -> tuple[str, str]:
    global _last_status_update_time

    if not GEMINI_API_KEY:
        default_status = "Watching Rocket League ⚽ | /join or >join"
        activity = discord.CustomActivity(name=default_status)
        await bot.change_presence(activity=activity)
        return default_status, "GEMINI_API_KEY environment variable is missing on Render."

    chat_log, channel_info = await fetch_random_chat_history(guild)
    if not chat_log:
        default_status = "Watching Rocket League ⚽ | /join or >join"
        activity = discord.CustomActivity(name=default_status)
        await bot.change_presence(activity=activity)
        return default_status, f"Chat history unavailable: {channel_info}"

    status_text, gen_info = await generate_status_from_chat(chat_log, GEMINI_API_KEY)
    if status_text:
        activity = discord.CustomActivity(name=status_text)
        await bot.change_presence(activity=activity)
        _last_status_update_time = _dt.now(timezone.utc)
        logger.success(f"Custom status updated to: \"{status_text}\"")
        return status_text, f"Generated from {channel_info} via {gen_info}"

    default_status = "Watching Rocket League ⚽ | /join or >join"
    activity = discord.CustomActivity(name=default_status)
    await bot.change_presence(activity=activity)
    return default_status, f"AI generation fallback: {gen_info}"

# ── Bot Client Setup ──────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.voice_states = True
intents.message_content = True
bot = commands.Bot(command_prefix='>', intents=intents, help_command=None)

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
    index_path = os.path.join(os.path.dirname(__file__), WEBSITE_DIR_NAME, "index.html")
    if os.path.exists(index_path):
        return web.FileResponse(index_path)
    return web.Response(text="<h1>RLScoreBot Cloud Engine Online</h1>", content_type="text/html")

async def handle_style(request):
    css_path = os.path.join(os.path.dirname(__file__), WEBSITE_DIR_NAME, "style.css")
    if os.path.exists(css_path):
        return web.FileResponse(css_path)
    return web.Response(status=404)

async def handle_app_js(request):
    js_path = os.path.join(os.path.dirname(__file__), WEBSITE_DIR_NAME, "app.js")
    if os.path.exists(js_path):
        return web.FileResponse(js_path)
    return web.Response(status=404)

async def handle_logo(request):
    logo_path = os.path.join(os.path.dirname(__file__), WEBSITE_DIR_NAME, "logo.png")
    if os.path.exists(logo_path):
        return web.FileResponse(logo_path)
    return web.Response(status=404)

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
        return web.json_response({"error": "Invalid pairing token. Run >link in Discord."}, status=403)

    discord_user_id = user_info["discord_user_id"]
    guild_id = user_info.get("active_guild_id")
    vc_id = user_info.get("active_voice_channel_id")

    if not guild_id or not vc_id:
        return web.json_response({"error": "User not active in a voice channel. Run >join in Discord."}, status=400)

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

    # Play sound from the active server's soundboard library
    sound_to_play = data.get("sound") or get_random_sound_for_guild(guild_id)
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
    app.router.add_get("/style.css", handle_style)
    app.router.add_get("/app.js", handle_app_js)
    app.router.add_get("/logo.png", handle_logo)
    app.router.add_post("/api/v1/goal", handle_goal_webhook)
    app.router.add_get("/api/v1/stats", handle_stats_api)
    
    sounds_dir = os.path.join(os.path.dirname(__file__), SOUNDS_DIR_NAME)
    if os.path.exists(sounds_dir):
        app.router.add_static("/sounds", sounds_dir)

# ── Core Handlers ─────────────────────────────────────────────────────────────

async def do_link(user_id: str):
    code = database.generate_linking_code(user_id)
    embed = discord.Embed(
        title="⚡ RLScoreBot Telemetry Pairing Code",
        description=f"Your pairing code is: **`{code}`**\n\nEnter this code into your game plugin/watcher to link goal telemetry with your Discord Voice Channel.",
        color=discord.Color.blue()
    )
    embed.set_footer(text="Code expires after single use. Keep your pairing code private!")
    return embed

async def do_join(user, guild):
    if not user.voice or not user.voice.channel:
        return False, "❌ You are not connected to a voice channel. Please join a voice channel first!"

    channel = user.voice.channel
    try:
        if guild.voice_client:
            await guild.voice_client.move_to(channel)
        else:
            await channel.connect()
    except Exception as e:
        return False, f"❌ Could not join voice channel: {e}"

    database.update_user_location(str(user.id), str(guild.id), str(channel.id))
    return True, f"✅ Joined **{channel.name}** and ready to celebrate goals!"

async def do_leave(guild):
    if guild.voice_client:
        await guild.voice_client.disconnect()
        return True, "👋 Left voice channel."
    return False, "❌ Bot is not in a voice channel."

async def do_upload(user_id: str, guild_id: str, filename: str, file_bytes: bytes, sound_name: str = None):
    ALLOWED_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".m4a"}
    MAX_SIZE = 25 * 1024 * 1024

    _, ext = os.path.splitext(filename.lower())
    if ext not in ALLOWED_EXTENSIONS:
        return False, f"❌ Unsupported format `{ext}`. Allowed: `.mp3`, `.wav`, `.ogg`, `.flac`, `.m4a`"

    if len(file_bytes) > MAX_SIZE:
        return False, "❌ File exceeds 25MB maximum upload limit."

    clean_title = sound_name or filename
    safe_basename = re.sub(r'[^\w\s\.-]', '', clean_title).strip()
    if not safe_basename.endswith(ext):
        safe_basename += ext

    sounds_dir = utils.full_path(SOUNDS_DIR_NAME)
    if not os.path.exists(sounds_dir):
        os.makedirs(sounds_dir, exist_ok=True)

    target_path = os.path.join(sounds_dir, safe_basename)
    
    try:
        with open(target_path, "wb") as f:
            f.write(file_bytes)
    except Exception as exc:
        logger.error(f"Failed to write sound file: {exc}")
        return False, f"❌ Server file write error: {exc}"

    ok, msg = await normalize_audio(target_path)
    database.add_guild_sound(user_id, str(guild_id), safe_basename, clean_title, target_path)

    embed = discord.Embed(
        title="🎵 New Sound Uploaded to Server Soundboard!",
        description=f"Successfully added **`{clean_title}`** to this server's soundboard library!\n\nVolume normalized to **{TARGET_LUFS} LUFS**.",
        color=discord.Color.green()
    )
    return True, embed

# ── Slash Commands (UI Autocomplete Popups) ────────────────────────────────────

@bot.tree.command(name="link", description="Get your 6-digit pairing code to link BakkesMod plugin with Discord.")
async def slash_link(interaction: discord.Interaction):
    embed = await do_link(str(interaction.user.id))
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="join", description="Connect bot to your voice channel for goal celebrations.")
async def slash_join(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    ok, msg = await do_join(interaction.user, interaction.guild)
    await interaction.followup.send(msg, ephemeral=True)

@bot.tree.command(name="leave", description="Disconnect bot from voice channel.")
async def slash_leave(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    ok, msg = await do_leave(interaction.guild)
    await interaction.followup.send(msg, ephemeral=True)

@bot.tree.command(name="upload", description="Upload a custom sound file to this server's soundboard.")
@app_commands.describe(file="Select an audio file (.mp3, .wav, .ogg)", sound_name="Optional custom title")
async def slash_upload(interaction: discord.Interaction, file: discord.Attachment, sound_name: str = None):
    try:
        await interaction.response.defer(ephemeral=True)
        file_bytes = await file.read()
        ok, res = await do_upload(str(interaction.user.id), str(interaction.guild_id), file.filename, file_bytes, sound_name)
        if ok:
            await interaction.followup.send(embed=res, ephemeral=True)
        else:
            await interaction.followup.send(res, ephemeral=True)
    except Exception as e:
        logger.error(f"Slash upload failed: {e}")
        try:
            if interaction.response.is_done():
                await interaction.followup.send(f"❌ Upload failed: {e}", ephemeral=True)
            else:
                await interaction.response.send_message(f"❌ Upload failed: {e}", ephemeral=True)
        except Exception:
            pass

@bot.tree.command(name="list", description="List all sounds in this server's soundboard library.")
async def slash_list(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    sounds = get_guild_sound_library(str(interaction.guild_id))
    embed = build_soundboard_embed(sounds, "🎧 Server Goal Celebration Soundboard")
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="play", description="Manually trigger a goal sound in the voice channel.")
async def slash_play(interaction: discord.Interaction, sound_name: str = None):
    await interaction.response.defer()
    if not interaction.guild.voice_client:
        await interaction.followup.send("❌ Bot is not in a voice channel. Run `/join` or `>join` first.")
        return
    sound_to_play = sound_name or get_random_sound_for_guild(str(interaction.guild_id))
    success = play_sound_in_vc(interaction.guild.voice_client, sound_to_play)
    if success:
        await interaction.followup.send(f"▶ Playing **`{sound_to_play}`**!")
    else:
        await interaction.followup.send("⏯️ Bot is already playing a sound.")

# ── Prefix Commands (> Prefix Fallback) ───────────────────────────────────────

@bot.command(name="link", help="Get your 6-digit pairing code.")
async def cmd_link(ctx):
    embed = await do_link(str(ctx.author.id))
    await ctx.send(embed=embed)

@bot.command(name="join", help="Connect bot to your voice channel.")
async def cmd_join(ctx):
    ok, msg = await do_join(ctx.author, ctx.guild)
    await ctx.send(msg)

@bot.command(name="leave", help="Disconnect bot from voice channel.")
async def cmd_leave(ctx):
    ok, msg = await do_leave(ctx.guild)
    await ctx.send(msg)

@bot.command(name="upload", help="Upload custom sound file to this server's soundboard.")
async def cmd_upload(ctx, sound_name: str = None):
    if not ctx.message.attachments:
        await ctx.send("❌ Please attach an audio file to your message.")
        return
    attachment = ctx.message.attachments[0]
    file_bytes = await attachment.read()
    ok, res = await do_upload(str(ctx.author.id), str(ctx.guild.id), attachment.filename, file_bytes, sound_name)
    if ok:
        await ctx.send(embed=res)
    else:
        await ctx.send(res)

@bot.command(name="list", help="List available sounds in this server's soundboard.")
async def cmd_list(ctx):
    sounds = get_guild_sound_library(str(ctx.guild.id))
    embed = build_soundboard_embed(sounds, "🎧 Server Goal Celebration Soundboard")
    await ctx.send(embed=embed)

@bot.command(name="play", help="Manually trigger sound.")
async def cmd_play(ctx, sound_name: str = None):
    if not ctx.guild.voice_client:
        await ctx.send("❌ Bot is not in a voice channel. Run `>join` or `/join` first.")
        return
    sound_to_play = sound_name or get_random_sound_for_guild(str(ctx.guild.id))
    success = play_sound_in_vc(ctx.guild.voice_client, sound_to_play)
    if success:
        await ctx.send(f"▶ Playing **`{sound_to_play}`**!")
    else:
        await ctx.send("⏯️ Bot is already playing a sound.")

@bot.command(name="status_sync", help="Manually trigger an AI status sync (Owner & Admin Only).")
async def cmd_status_sync(ctx):
    is_owner = (ctx.author.id == OWNER_ID)
    is_admin = ctx.author.guild_permissions.administrator if ctx.guild else False

    if not (is_owner or is_admin):
        await ctx.send("❌ Permission denied. `>status_sync` is restricted to bot owner and server administrators.")
        return

    msg = await ctx.send("⏳ Sampling random historical chat history and calling Gemini AI...")
    status_text, diagnostic_info = await update_bot_status(ctx.guild)
    
    if status_text != "Watching Rocket League ⚽ | /join or >join":
        await msg.edit(content=f"✅ Status generated by Gemini: \"{status_text}\"\n*({diagnostic_info})*")
    else:
        await msg.edit(content=f"⚠️ Custom status set to fallback: \"{status_text}\"\n**Reason**: `{diagnostic_info}`")

@bot.command(name="stats", help="Display goal statistics.")
async def cmd_stats(ctx):
    stats = database.get_global_stats()
    embed = discord.Embed(title="🏆 RLScoreBot Goal Statistics", color=discord.Color.gold())
    embed.add_field(name="⚽ Total Goals Celebrated", value=f"**{stats['total_goals']}**", inline=True)
    embed.add_field(name="🎵 Soundboard Library Size", value=f"**{len(get_guild_sound_library(str(ctx.guild.id)))}**", inline=True)
    await ctx.send(embed=embed)

@tasks.loop(hours=6)
async def auto_status_loop():
    if bot.guilds:
        guild = random.choice(bot.guilds)
        await update_bot_status(guild)

@bot.event
async def on_ready():
    logger.success(f"Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} Slash Commands globally!")
    except Exception as e:
        logger.error(f"Failed to sync slash commands: {e}")

    if bot.guilds:
        await update_bot_status(bot.guilds[0])

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
    async with bot:
        await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())