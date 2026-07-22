import asyncio
import os
import random
import re
import json
import sqlite3
import aiohttp
from aiohttp import web
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

import utils
import database
import logger

load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID      = int(os.getenv("OWNER_ID", "0"))
WEB_PORT      = int(os.getenv("PORT", "8080"))

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

# ── Bot Client Setup ──────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.voice_states = True
bot = commands.Bot(command_prefix='/', intents=intents, help_command=None)

def play_sound_in_vc(voice_client, sound_filename: str):
    """Play specified audio file in Discord Voice Channel."""
    if not voice_client or not voice_client.is_connected():
        logger.warn("Voice client not connected.")
        return False

    if voice_client.is_playing():
        logger.info("Voice client already playing audio — overlapping goal skipped.")
        return False

    sound_path = utils.full_path(SOUNDS_DIR_NAME, sound_filename)
    if not os.path.exists(sound_path):
        # Fallback to default cheer sound if file not found
        sound_path = utils.full_path(SOUNDS_DIR_NAME, "default_cheer.mp3")

    ffmpeg_exec = utils.full_path(FFMPEG_NAME)
    if not os.path.exists(ffmpeg_exec):
        ffmpeg_exec = "ffmpeg" # System PATH fallback

    voice_client.play(discord.FFmpegPCMAudio(
        executable=ffmpeg_exec,
        source=sound_path
    ))
    logger.playing(sound_filename)
    return True

# ── Embedded Web Server & Webhooks ────────────────────────────────────────────
async def handle_index(request):
    """Serve website landing page."""
    index_path = utils.full_path(WEBSITE_DIR_NAME, "index.html")
    if os.path.exists(index_path):
        return web.FileResponse(index_path)
    return web.Response(text="RLScoreBot Cloud Engine Online.")

async def handle_goal_webhook(request):
    """API endpoint receiving BakkesMod goal pings."""
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
    selected_sound = user_info.get("selected_sound") or "default_cheer.mp3"

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

    # Trigger custom anthem!
    success = play_sound_in_vc(voice_client, selected_sound)
    if success:
        database.record_goal_stat(discord_user_id, guild_id, selected_sound)

    return web.json_response({
        "status": "success",
        "sound_played": selected_sound,
        "user_id": discord_user_id
    })

async def handle_stats_api(request):
    """API endpoint for website counters."""
    stats = database.get_global_stats()
    return web.json_response(stats)

def setup_web_routes(app):
    app.router.add_get("/", handle_index)
    app.router.add_post("/api/v1/goal", handle_goal_webhook)
    app.router.add_get("/api/v1/stats", handle_stats_api)
    
    # Static website assets & sounds
    website_path = utils.full_path(WEBSITE_DIR_NAME)
    sounds_path = utils.full_path(SOUNDS_DIR_NAME)
    
    if os.path.exists(website_path):
        app.router.add_static("/website", website_path)
        app.router.add_static("/style.css", website_path)
        app.router.add_static("/app.js", website_path)
    if os.path.exists(sounds_path):
        app.router.add_static("/sounds", sounds_path)

# ── Discord Slash Commands ────────────────────────────────────────────────────

@bot.tree.command(name="link", description="Get your 6-digit pairing code to link BakkesMod plugin with Discord.")
async def cmd_link(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    code = database.generate_linking_code(user_id)
    
    embed = discord.Embed(
        title="⚡ RLScoreBot BakkesMod Pairing Code",
        description=f"Your pairing code is: **`{code}`**\n\nEnter this code into the BakkesMod plugin menu in Rocket League to link your game telemetry.",
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

    # Update active location in database
    database.update_user_location(str(interaction.user.id), str(guild.id), str(channel.id))
    
    await interaction.response.send_message(f"✅ Joined **{channel.name}** and linked your goal celebrations!")

@bot.tree.command(name="leave", description="Disconnect bot from voice channel.")
async def cmd_leave(interaction: discord.Interaction):
    if interaction.guild.voice_client:
        await interaction.guild.voice_client.disconnect()
        await interaction.response.send_message("👋 Left voice channel.")
    else:
        await interaction.response.send_message("❌ Bot is not in a voice channel.", ephemeral=True)

@bot.tree.command(name="upload", description="Upload a custom goal celebration anthem (.mp3, .wav, .ogg).")
async def cmd_upload(interaction: discord.Interaction, file: discord.Attachment, display_name: str = None):
    ALLOWED_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".m4a"}
    MAX_SIZE = 25 * 1024 * 1024 # 25 MB

    _, ext = os.path.splitext(file.filename.lower())
    if ext not in ALLOWED_EXTENSIONS:
        await interaction.response.send_message(f"❌ Unsupported format `{ext}`. Allowed: `.mp3`, `.wav`, `.ogg`, `.flac`, `.m4a`", ephemeral=True)
        return

    if file.size > MAX_SIZE:
        await interaction.response.send_message("❌ File exceeds 25MB maximum upload limit.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    safe_basename = f"user_{interaction.user.id}_{int(asyncio.get_event_loop().time())}{ext}"
    target_path = utils.full_path(SOUNDS_DIR_NAME, safe_basename)
    
    # Download file bytes
    file_bytes = await file.read()
    with open(target_path, "wb") as f:
        f.write(file_bytes)

    # Normalize audio to -14 LUFS
    ok, msg = await normalize_audio(target_path)
    
    clean_name = display_name or file.filename
    database.add_user_sound(str(interaction.user.id), safe_basename, clean_name, target_path)
    database.set_user_sound(str(interaction.user.id), safe_basename)

    embed = discord.Embed(
        title="🎵 Custom Anthem Uploaded!",
        description=f"Successfully uploaded and set **`{clean_name}`** as your active goal celebration anthem!\n\nVolume normalized to **{TARGET_LUFS} LUFS**.",
        color=discord.Color.green()
    )
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="sound", description="Set your active goal anthem from your library or defaults.")
async def cmd_sound(interaction: discord.Interaction, sound_name: str):
    user_sounds = database.get_user_sounds(str(interaction.user.id))
    defaults = ["default_cheer.mp3", "default_airhorn.mp3"]

    # Check if matches user sound or default
    matched_file = None
    for s in user_sounds:
        if sound_name.lower() in s["display_name"].lower() or sound_name.lower() in s["filename"].lower():
            matched_file = s["filename"]
            break
            
    if not matched_file:
        for d in defaults:
            if sound_name.lower() in d.lower():
                matched_file = d
                break

    if not matched_file:
        await interaction.response.send_message(f"❌ Sound `{sound_name}` not found in your library. Use `/my_sounds` to view your sounds.", ephemeral=True)
        return

    database.set_user_sound(str(interaction.user.id), matched_file)
    await interaction.response.send_message(f"✅ Set **`{sound_name}`** as your active goal anthem!", ephemeral=True)

@bot.tree.command(name="my_sounds", description="List your uploaded custom goal anthems.")
async def cmd_my_sounds(interaction: discord.Interaction):
    user_sounds = database.get_user_sounds(str(interaction.user.id))
    
    embed = discord.Embed(
        title="🎧 Your Goal Anthem Library",
        color=discord.Color.purple()
    )
    
    embed.add_field(name="Default Starters", value="• `default_cheer.mp3` (Stadium Cheer)\n• `default_airhorn.mp3` (Hype Airhorn)", inline=False)
    
    if user_sounds:
        custom_lines = "\n".join([f"• **{s['display_name']}** (`{s['filename']}`)" for s in user_sounds])
        embed.add_field(name="Your Uploaded Anthems", value=custom_lines, inline=False)
    else:
        embed.add_field(name="Your Uploaded Anthems", value="*No custom anthems uploaded yet. Use `/upload` to add one!*", inline=False)
        
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="stats", description="Display server goal statistics and leaderboards.")
async def cmd_stats(interaction: discord.Interaction):
    stats = database.get_global_stats()
    embed = discord.Embed(
        title="🏆 RLScoreBot Global Statistics",
        color=discord.Color.gold()
    )
    embed.add_field(name="⚽ Total Goals Celebrated", value=f"**{stats['total_goals']}**", inline=True)
    embed.add_field(name="👤 Active Players", value=f"**{stats['total_users']}**", inline=True)
    embed.add_field(name="🎵 Custom Anthems", value=f"**{stats['total_sounds']}**", inline=True)
    await interaction.response.send_message(embed=embed)

@bot.event
async def on_ready():
    logger.success(f"Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} slash commands globally.")
    except Exception as e:
        logger.error(f"Failed to sync slash commands: {e}")

    # Start Embedded Web Server
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