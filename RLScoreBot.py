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

# ── Randomized Historical Gemini AI Status Generation Engine ───────────────
async def fetch_random_chat_history(guild):
    """
    Randomized historical chat sampler:
    Picks a random text channel and samples 50 messages from a random point in time
    (ranging from channel creation to present) to unearth old classic inside jokes.
    """
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

            # Pick a random point in time if channel has history > 3 days
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
        "gemini-1.5-pro-latest",
        "gemini-pro"
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
                    else:
                        err_text = await response.text()
                        last_error = f"Gemini {model} HTTP {response.status}: {err_text[:100]}"
                        logger.error(last_error)
            except Exception as e:
                last_error = f"Gemini {model} exception: {e}"
                logger.warn(last_error)

    return None, last_error

async def update_bot_status(guild) -> tuple[str, str]:
    if not GEMINI_API_KEY:
        default_status = "Watching Rocket League ⚽ | >join"
        activity = discord.CustomActivity(name=default_status)
        await bot.change_presence(activity=activity)
        return default_status, "GEMINI_API_KEY environment variable is missing on Render."

    chat_log, channel_info = await fetch_random_chat_history(guild)
    if not chat_log:
        default_status = "Watching Rocket League ⚽ | >join"
        activity = discord.CustomActivity(name=default_status)
        await bot.change_presence(activity=activity)
        return default_status, f"Chat history unavailable: {channel_info}"

    status_text, gen_info = await generate_status_from_chat(chat_log, GEMINI_API_KEY)
    if status_text:
        activity = discord.CustomActivity(name=status_text)
        await bot.change_presence(activity=activity)
        logger.success(f"Custom status updated to: \"{status_text}\"")
        return status_text, f"Generated from {channel_info} via {gen_info}"

    default_status = "Watching Rocket League ⚽ | >join"
    activity = discord.CustomActivity(name=default_status)
    await bot.change_presence(activity=activity)
    return default_status, f"AI generation error: {gen_info}"

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
    """Serve website landing page."""
    index_path = os.path.join(os.path.dirname(__file__), WEBSITE_DIR_NAME, "index.html")
    if os.path.exists(index_path):
        return web.FileResponse(index_path)
    return web.Response(text="<h1>RLScoreBot Cloud Engine Online</h1>", content_type="text/html")

async def handle_style(request):
    """Serve style.css directly with text/css content type."""
    css_path = os.path.join(os.path.dirname(__file__), WEBSITE_DIR_NAME, "style.css")
    if os.path.exists(css_path):
        return web.FileResponse(css_path)
    return web.Response(status=404)

async def handle_app_js(request):
    """Serve app.js directly with application/javascript content type."""
    js_path = os.path.join(os.path.dirname(__file__), WEBSITE_DIR_NAME, "app.js")
    if os.path.exists(js_path):
        return web.FileResponse(js_path)
    return web.Response(status=404)

async def handle_logo(request):
    """Serve logo.png directly."""
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
    app.router.add_get("/style.css", handle_style)
    app.router.add_get("/app.js", handle_app_js)
    app.router.add_get("/logo.png", handle_logo)
    app.router.add_post("/api/v1/goal", handle_goal_webhook)
    app.router.add_get("/api/v1/stats", handle_stats_api)
    
    sounds_dir = os.path.join(os.path.dirname(__file__), SOUNDS_DIR_NAME)
    if os.path.exists(sounds_dir):
        app.router.add_static("/sounds", sounds_dir)

# ── Discord Commands (Prefix >) ───────────────────────────────────────────────

@bot.command(name="link", help="Get your 6-digit pairing code to link BakkesMod plugin with Discord.")
async def cmd_link(ctx):
    code = database.generate_linking_code(str(ctx.author.id))
    embed = discord.Embed(
        title="⚡ RLScoreBot Telemetry Pairing Code",
        description=f"Your pairing code is: **`{code}`**\n\nEnter this code into your game plugin/watcher to link goal telemetry with your Discord Voice Channel.",
        color=discord.Color.blue()
    )
    embed.set_footer(text="Code expires after single use. Keep your pairing code private!")
    await ctx.send(embed=embed)

@bot.command(name="join", help="Connect bot to your voice channel for goal celebrations.")
async def cmd_join(ctx):
    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.send("❌ You are not connected to a voice channel. Please join a voice channel first!")
        return

    channel = ctx.author.voice.channel
    guild = ctx.guild

    try:
        if guild.voice_client:
            await guild.voice_client.move_to(channel)
        else:
            await channel.connect()
    except Exception as e:
        await ctx.send(f"❌ Could not join voice channel: {e}")
        return

    database.update_user_location(str(ctx.author.id), str(guild.id), str(channel.id))
    await ctx.send(f"✅ Joined **{channel.name}** and ready to celebrate goals!")

@bot.command(name="leave", help="Disconnect bot from voice channel.")
async def cmd_leave(ctx):
    if ctx.guild.voice_client:
        await ctx.guild.voice_client.disconnect()
        await ctx.send("👋 Left voice channel.")
    else:
        await ctx.send("❌ Bot is not in a voice channel.")

@bot.command(name="upload", help="Upload a custom sound file to the goal soundboard (.mp3, .wav, .ogg).")
async def cmd_upload(ctx, sound_name: str = None):
    if not ctx.message.attachments:
        await ctx.send("❌ Please attach an audio file to your message.")
        return

    attachment = ctx.message.attachments[0]
    ALLOWED_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".m4a"}
    MAX_SIZE = 25 * 1024 * 1024

    _, ext = os.path.splitext(attachment.filename.lower())
    if ext not in ALLOWED_EXTENSIONS:
        await ctx.send(f"❌ Unsupported format `{ext}`. Allowed: `.mp3`, `.wav`, `.ogg`, `.flac`, `.m4a`")
        return

    if attachment.size > MAX_SIZE:
        await ctx.send("❌ File exceeds 25MB maximum upload limit.")
        return

    clean_title = sound_name or attachment.filename
    safe_basename = re.sub(r'[^\w\s\.-]', '', clean_title).strip()
    if not safe_basename.endswith(ext):
        safe_basename += ext

    target_path = utils.full_path(SOUNDS_DIR_NAME, safe_basename)
    
    file_bytes = await attachment.read()
    with open(target_path, "wb") as f:
        f.write(file_bytes)

    ok, msg = await normalize_audio(target_path)
    database.add_user_sound(str(ctx.author.id), safe_basename, clean_title, target_path)

    embed = discord.Embed(
        title="🎵 New Sound Uploaded to Soundboard!",
        description=f"Successfully added **`{clean_title}`** to the goal celebration soundboard!\n\nVolume normalized to **{TARGET_LUFS} LUFS**.",
        color=discord.Color.green()
    )
    await ctx.send(embed=embed)

@bot.command(name="list", help="List all available goal celebration sounds.")
async def cmd_list(ctx):
    sounds = get_available_sounds()
    embed = discord.Embed(
        title="🎧 Goal Celebration Soundboard",
        color=discord.Color.purple()
    )
    sound_lines = "\n".join([f"• `{s}`" for s in sounds[:30]])
    embed.add_field(name=f"Available Sounds ({len(sounds)})", value=sound_lines or "No sounds loaded.", inline=False)
    await ctx.send(embed=embed)

@bot.command(name="play", help="Manually trigger a goal sound in the voice channel.")
async def cmd_play(ctx, sound_name: str = None):
    if not ctx.guild.voice_client:
        await ctx.send("❌ Bot is not in a voice channel. Run `>join` first.")
        return

    sound_to_play = sound_name or get_random_sound()
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
    
    if status_text != "Watching Rocket League ⚽ | >join":
        await msg.edit(content=f"✅ Status generated by Gemini: \"{status_text}\"\n*({diagnostic_info})*")
    else:
        await msg.edit(content=f"⚠️ Custom status set to fallback: \"{status_text}\"\n**Reason**: `{diagnostic_info}`")

@bot.command(name="stats", help="Display goal statistics.")
async def cmd_stats(ctx):
    stats = database.get_global_stats()
    embed = discord.Embed(
        title="🏆 RLScoreBot Goal Statistics",
        color=discord.Color.gold()
    )
    embed.add_field(name="⚽ Total Goals Celebrated", value=f"**{stats['total_goals']}**", inline=True)
    embed.add_field(name="🎵 Soundboard Library Size", value=f"**{len(get_available_sounds())}**", inline=True)
    await ctx.send(embed=embed)

@tasks.loop(hours=6)
async def auto_status_loop():
    for guild in bot.guilds:
        status_text, _ = await update_bot_status(guild)
        if status_text != "Watching Rocket League ⚽ | >join":
            break

@bot.event
async def on_ready():
    logger.success(f"Logged in as {bot.user} (ID: {bot.user.id})")

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
    async with bot:
        await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())