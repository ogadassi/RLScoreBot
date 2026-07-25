"""
Jingle Creator — FastAPI Backend
Handles YouTube audio extraction and ffmpeg processing for RLScoreBot jingle creation.
"""

import os
import json
import time
import hashlib
import asyncio
import tempfile
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.background import BackgroundTasks
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# ─── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ─── Rate Limiter ────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=["100/hour"])

app = FastAPI(title="Jingle Creator API", version="1.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Static Files ─────────────────────────────────────────────────────────────
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ─── Audio Cache (in-memory, keyed by URL hash) ──────────────────────────────
# Maps url_hash -> (filepath, timestamp)
_audio_cache: dict[str, tuple[str, float]] = {}
CACHE_TTL = 600  # 10 minutes

CACHE_DIR = Path(tempfile.gettempdir()) / "jingle_cache"
CACHE_DIR.mkdir(exist_ok=True)


def cache_key(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


def get_cached_audio(url: str) -> Optional[str]:
    key = cache_key(url)
    if key in _audio_cache:
        path, ts = _audio_cache[key]
        if time.time() - ts < CACHE_TTL and os.path.exists(path):
            return path
        # Expired — clean up
        _audio_cache.pop(key, None)
        try:
            os.unlink(path)
        except OSError:
            pass
    return None


def store_cached_audio(url: str, path: str) -> None:
    _audio_cache[cache_key(url)] = (path, time.time())


# ─── ffmpeg Resolution ───────────────────────────────────────────────────────
def get_ffmpeg() -> str:
    """Return path to ffmpeg — prefers system ffmpeg on Railway (Linux)."""
    return "ffmpeg"


# ─── Core Async Helpers ──────────────────────────────────────────────────────
async def run_command(cmd: list[str], error_msg: str = "Command failed") -> tuple[bytes, bytes]:
    """Run a subprocess command asynchronously."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        log.error(f"{error_msg}: {stderr.decode()[:500]}")
        raise HTTPException(status_code=400, detail=f"{error_msg}: {stderr.decode()[:300]}")
    return stdout, stderr


async def fetch_video_info(url: str) -> dict:
    """Use yt-dlp --dump-json to get video metadata without downloading."""
    stdout, _ = await run_command(
        ["yt-dlp", "--dump-json", "--no-playlist", url],
        error_msg="Failed to fetch video info. Check the URL and try again"
    )
    try:
        info = json.loads(stdout.decode())
        return {
            "title": info.get("title", "Unknown"),
            "duration": info.get("duration", 0),
            "thumbnail": info.get("thumbnail", ""),
            "uploader": info.get("uploader", "Unknown"),
            "webpage_url": info.get("webpage_url", url),
        }
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Failed to parse video info")


async def download_audio(url: str) -> str:
    """Download audio from YouTube, caching by URL. Returns path to audio file."""
    cached = get_cached_audio(url)
    if cached:
        log.info(f"Cache hit for {url[:60]}")
        return cached

    log.info(f"Downloading audio: {url[:60]}")
    key = cache_key(url)
    output_template = str(CACHE_DIR / f"{key}.%(ext)s")

    await run_command(
        [
            "yt-dlp",
            "-x",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "-o", output_template,
            "--no-playlist",
            url,
        ],
        error_msg="Failed to download audio"
    )

    # Find the file yt-dlp created
    matches = list(CACHE_DIR.glob(f"{key}.*"))
    if not matches:
        raise HTTPException(status_code=500, detail="Audio download produced no file")

    path = str(matches[0])
    store_cached_audio(url, path)
    log.info(f"Downloaded and cached: {path}")
    return path


async def process_audio(
    input_path: str,
    output_path: str,
    start: float,
    end: float,
    fade_in: float,
    fade_out: float,
) -> None:
    """Trim audio and apply fade in/out via ffmpeg."""
    duration = end - start
    if duration <= 0:
        raise HTTPException(status_code=400, detail="End time must be greater than start time")
    if duration > 60:
        raise HTTPException(status_code=400, detail="Clip duration cannot exceed 60 seconds")

    # Build audio filter chain
    filters = []
    if fade_in > 0:
        filters.append(f"afade=t=in:st=0:d={fade_in:.3f}")
    if fade_out > 0:
        fade_start = max(0.0, duration - fade_out)
        filters.append(f"afade=t=out:st={fade_start:.3f}:d={fade_out:.3f}")
    filter_str = ",".join(filters) if filters else "anull"

    ffmpeg = get_ffmpeg()
    await run_command(
        [
            ffmpeg, "-y",
            "-ss", str(start),
            "-t", str(duration),
            "-i", input_path,
            "-af", filter_str,
            "-codec:a", "libmp3lame",
            "-q:a", "2",
            output_path,
        ],
        error_msg="Failed to process audio"
    )


# ─── Request Models ──────────────────────────────────────────────────────────
class FetchInfoRequest(BaseModel):
    url: str


class ProcessRequest(BaseModel):
    url: str
    start: float
    end: float
    fade_in: float = 0.0
    fade_out: float = 0.0
    filename: str = "jingle"


# ─── Routes ──────────────────────────────────────────────────────────────────
@app.get("/")
async def serve_index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/fetch-info")
@limiter.limit("30/hour")
async def api_fetch_info(request: Request, body: FetchInfoRequest):
    """Return YouTube video metadata (title, duration, thumbnail)."""
    if not body.url.strip():
        raise HTTPException(status_code=400, detail="URL is required")
    info = await fetch_video_info(body.url.strip())
    return info


@app.post("/api/process")
@limiter.limit("15/hour")
async def api_process(request: Request, body: ProcessRequest, background_tasks: BackgroundTasks):
    """
    Download (or use cached) audio, trim, apply fades, return MP3.
    Used for both preview (inline) and download (attachment) — frontend handles distinction.
    """
    if not body.url.strip():
        raise HTTPException(status_code=400, detail="URL is required")

    # Validate
    if body.start < 0:
        raise HTTPException(status_code=400, detail="Start time cannot be negative")
    if body.end <= body.start:
        raise HTTPException(status_code=400, detail="End must be after start")
    if body.fade_in < 0 or body.fade_in > 10:
        raise HTTPException(status_code=400, detail="Fade in must be 0–10 seconds")
    if body.fade_out < 0 or body.fade_out > 10:
        raise HTTPException(status_code=400, detail="Fade out must be 0–10 seconds")

    # Sanitize filename
    safe_name = "".join(c for c in body.filename if c.isalnum() or c in " _-").strip() or "jingle"

    # Get raw audio (cached)
    input_path = await download_audio(body.url.strip())

    # Process to a temp file
    tmp_file = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False, dir=CACHE_DIR)
    tmp_file.close()
    output_path = tmp_file.name

    try:
        await process_audio(input_path, output_path, body.start, body.end, body.fade_in, body.fade_out)
    except Exception:
        background_tasks.add_task(os.unlink, output_path)
        raise

    # Stream back to client
    file_size = os.path.getsize(output_path)

    def iterfile():
        try:
            with open(output_path, "rb") as f:
                while chunk := f.read(65536):
                    yield chunk
        finally:
            try:
                os.unlink(output_path)
            except OSError:
                pass

    return StreamingResponse(
        iterfile(),
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": f'inline; filename="{safe_name}.mp3"',
            "Content-Length": str(file_size),
            "Accept-Ranges": "bytes",
            "X-Filename": f"{safe_name}.mp3",
        },
    )
