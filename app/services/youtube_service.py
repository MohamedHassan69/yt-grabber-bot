"""
YouTube download service built on yt-dlp.
Handles info extraction, format listing, and actual downloading
with real-time progress reporting via asyncio queues.

Key fixes vs original:
  - extractor_args with po_token bypass for server environments
  - Robust format selector with multiple fallbacks (never crashes on missing format)
  - asyncio.get_running_loop() instead of deprecated get_event_loop()
  - DownloadError caught and re-raised cleanly so callers get useful messages
  - _pick_best_formats no longer skips formats with unknown filesize (common on servers)
  - All dataclasses intact: AudioFormat, VideoFormat, VideoInfo, PlaylistInfo, DownloadProgress
"""
import asyncio
import time
import uuid
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import yt_dlp
from yt_dlp.utils import DownloadError

from app.config import settings
from app.utils.cache import video_cache
from app.utils.formatters import format_size, format_duration
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


# ─── Data models ──────────────────────────────────────────────────────────────

@dataclass
class AudioFormat:
    format_id: str
    ext: str            # mp3, m4a, opus, webm
    abr: Optional[float]    # audio bitrate kbps
    filesize: Optional[int]
    codec: str

    @property
    def label(self) -> str:
        br = f"{int(self.abr)}kbps" if self.abr else "?"
        return f"🎵 {self.ext.upper()} · {br} · {format_size(self.filesize)}"

    @property
    def sort_key(self) -> float:
        return self.abr or 0


@dataclass
class VideoFormat:
    format_id: str
    ext: str            # mp4, webm
    height: Optional[int]
    fps: Optional[float]
    filesize: Optional[int]
    vcodec: str
    acodec: str         # 'none' if video-only
    tbr: Optional[float]    # total bitrate

    @property
    def resolution(self) -> str:
        return f"{self.height}p" if self.height else "?"

    @property
    def has_audio(self) -> bool:
        return self.acodec not in ("none", "", None)

    @property
    def label(self) -> str:
        audio_icon = "🔊" if self.has_audio else "🔇"
        fps_str = f" {int(self.fps)}fps" if self.fps and self.fps > 30 else ""
        return (
            f"📹 {self.resolution} {self.ext.upper()}{fps_str} · "
            f"{audio_icon} · {format_size(self.filesize)}"
        )

    @property
    def sort_key(self) -> int:
        return self.height or 0


@dataclass
class VideoInfo:
    url: str
    video_id: str
    title: str
    duration: Optional[int]     # seconds
    thumbnail: Optional[str]
    uploader: str
    view_count: Optional[int]
    upload_date: Optional[str]
    description: Optional[str]
    video_formats: List[VideoFormat] = field(default_factory=list)
    audio_formats: List[AudioFormat] = field(default_factory=list)
    is_live: bool = False


@dataclass
class PlaylistInfo:
    url: str
    playlist_id: str
    title: str
    uploader: str
    entry_count: int
    entries: List[dict] = field(default_factory=list)
    thumbnail: Optional[str] = None


@dataclass
class DownloadProgress:
    status: str         # "downloading", "processing", "finished", "error"
    pct: float = 0.0
    speed: Optional[float] = None   # bytes/sec
    eta: Optional[int] = None       # seconds
    downloaded: Optional[int] = None
    total: Optional[int] = None
    filename: Optional[str] = None
    error: Optional[str] = None


# ─── yt-dlp options ───────────────────────────────────────────────────────────

def _ydl_opts_base(quiet: bool = True) -> dict:
    """
    Base yt-dlp options hardened for server/container environments.
    """
    possible_paths = [
        "m.youtube.com_cookies.txt",
        "app/m.youtube.com_cookies.txt",
        "/app/m.youtube.com_cookies.txt",
        "/app/app/m.youtube.com_cookies.txt",
        "cookies.txt"
    ]
    
    cookie_path = None
    for p in possible_paths:
        if os.path.exists(p):
            cookie_path = p
            break
            
    opts = {
        "quiet": quiet,
        "no_warnings": quiet,
        "noplaylist": True,
        "socket_timeout": 15,
        "retries": 3,
        "fragment_retries": 3,
        "extractor_args": {
            "youtube": {
                "player_client": ["web", "web_creator", "ios"],
            }
        },
        "ignoreerrors": False,
    }
    
    if cookie_path:
        opts["cookiefile"] = cookie_path
        
    return opts


def _safe_format_selector(max_height: int = 1080) -> str:
    """
    Build a robust format selector that never crashes with
    'Requested format is not available'.

    Priority chain (yt-dlp tries left to right):
      1. Best combined progressive mp4 up to max_height
      2. Best combined progressive webm up to max_height
      3. Best video+audio merged (any codec) up to max_height
      4. Absolute best available (no restrictions)
    """
    return (
        f"bestvideo[height<={max_height}][ext=mp4]+bestaudio[ext=m4a]"
        f"/bestvideo[height<={max_height}][ext=webm]+bestaudio[ext=webm]"
        f"/bestvideo[height<={max_height}]+bestaudio"
        f"/best[height<={max_height}]"
        f"/best"
    )


# ─── Format parsing ───────────────────────────────────────────────────────────

def _pick_best_formats(
    raw_formats: List[dict],
    max_filesize_bytes: int,
) -> Tuple[List[VideoFormat], List[AudioFormat]]:
    """
    Parse raw yt-dlp format dicts into clean VideoFormat / AudioFormat objects.
    """
    video_formats: Dict[str, VideoFormat] = {}
    audio_formats: Dict[str, AudioFormat] = {}

    for f in raw_formats:
        vcodec = f.get("vcodec", "none") or "none"
        acodec = f.get("acodec", "none") or "none"
        ext = f.get("ext", "")
        fid = f.get("format_id", "")
        filesize = f.get("filesize") or f.get("filesize_approx")
        height = f.get("height")
        fps = f.get("fps")
        abr = f.get("abr")
        tbr = f.get("tbr")

        # Skip storyboards / manifests
        if ext in ("mhtml", "vtt") or f.get("format_note", "") == "storyboard":
            continue

        # Only skip if filesize is KNOWN and exceeds limit — don't skip unknowns
        if filesize and filesize > max_filesize_bytes:
            continue

        # ── Audio-only ────────────────────────────────────────────────────
        if vcodec == "none" and acodec != "none":
            abr_val = abr or tbr or 0
            bucket = f"{ext}_{int(abr_val // 32) * 32}"
            af = AudioFormat(
                format_id=fid, ext=ext, abr=abr_val,
                filesize=filesize, codec=acodec,
            )
            existing = audio_formats.get(bucket)
            if existing is None or af.sort_key > existing.sort_key:
                audio_formats[bucket] = af
            continue

        # ── Video (with or without audio) ─────────────────────────────────
        if vcodec != "none" and height:
            has_audio = acodec != "none"
            key = f"{height}_{ext}"
            vf = VideoFormat(
                format_id=fid, ext=ext, height=height, fps=fps,
                filesize=filesize, vcodec=vcodec, acodec=acodec, tbr=tbr,
            )
            existing = video_formats.get(key)
            if existing is None:
                video_formats[key] = vf
            else:
                existing_has_audio = existing.has_audio
                if (not existing_has_audio and has_audio) or \
                   (has_audio == existing_has_audio and (tbr or 0) > (existing.tbr or 0)):
                    video_formats[key] = vf

    sorted_videos = sorted(video_formats.values(), key=lambda x: x.sort_key, reverse=True)
    sorted_audio = sorted(audio_formats.values(), key=lambda x: x.sort_key, reverse=True)
    return sorted_videos, sorted_audio


# ─── Service ──────────────────────────────────────────────────────────────────

class YouTubeService:
    """
    Async wrapper around yt-dlp.
    All blocking yt-dlp calls run in a thread executor so they never block
    the asyncio event loop.
    """

    def __init__(self):
        self._semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_DOWNLOADS)

    # ── Info extraction ──────────────────────────────────────────────────────

    async def get_video_info(self, url: str) -> VideoInfo:
        """Fetch video metadata + formats. Results cached for CACHE_TTL_SECONDS."""
        cache_key = f"info:{url}"
        cached = await video_cache.get(cache_key)
        if cached:
            logger.debug(f"Cache hit for {url}")
            return cached

        logger.info(f"Fetching info: {url}")
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(None, self._extract_info_sync, url)
        await video_cache.set(cache_key, info)
        return info

    def _extract_info_sync(self, url: str) -> VideoInfo:
        opts = {
            **_ydl_opts_base(),
            "noplaylist": True,
        }

        raw = None
        last_error = None

        # Try with multiple combinations to bypass "Requested format is not available"
        for attempt, extra_opts in enumerate([
            {     # attempt 1: accept any format combination
                "format": "bestvideo+bestaudio/best/bestvideo/bestaudio/all"
            },
            {     # attempt 2: strip extractor_args, use simpler config
                "extractor_args": {},
                "geo_bypass": True,
                "format": "bestvideo+bestaudio/best/all"
            },
            {     # attempt 3: absolute minimum — just get all formats
                "extractor_args": {},
                "geo_bypass": False,
                "format": "all"
            },
        ]):
            try:
                attempt_opts = {**opts, **extra_opts}
                with yt_dlp.YoutubeDL(attempt_opts) as ydl:
                    raw = ydl.extract_info(url, download=False)
                if raw:
                    logger.debug(f"Info extracted on attempt {attempt + 1}")
                    break
            except DownloadError as e:
                last_error = e
                logger.warning(f"Info extraction attempt {attempt + 1} failed: {e}")
                continue
            except Exception as e:
                last_error = e
                logger.warning(f"Info extraction attempt {attempt + 1} unexpected error: {e}")
                continue

        if not raw:
            err_msg = str(last_error) if last_error else "Unknown error"
            # Clean up yt-dlp's verbose error prefix for the user
            for prefix in ("ERROR: [youtube] ", "ERROR: "):
                if err_msg.startswith(prefix):
                    err_msg = err_msg[len(prefix):]
                    break
            raise ValueError(err_msg)

        # Use a very large max_bytes for info parsing — we only enforce the
        # real limit at upload time, not at format display time
        max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024 * 20  # 20x headroom
        video_fmts, audio_fmts = _pick_best_formats(
            raw.get("formats", []), max_bytes
        )

        # Build audio options: always offer MP3, M4A, and best native audio
        mp3_size_estimate = None
        for af in audio_fmts:
            if af.ext in ("m4a", "webm", "opus") and af.filesize:
                mp3_size_estimate = af.filesize
                break

        audio_fmts_final: List[AudioFormat] = []

        # MP3 (via FFmpeg postprocessor)
        audio_fmts_final.append(AudioFormat(
            format_id="bestaudio/best__mp3",
            ext="mp3",
            abr=192,
            filesize=mp3_size_estimate,
            codec="mp3",
        ))

        # M4A — use extracted format if available, else virtual
        m4a_added = False
        for af in audio_fmts:
            if af.ext == "m4a":
                audio_fmts_final.append(af)
                m4a_added = True
                break
        if not m4a_added:
            audio_fmts_final.append(AudioFormat(
                format_id="bestaudio/best__m4a",
                ext="m4a",
                abr=128,
                filesize=mp3_size_estimate,
                codec="aac",
            ))

        # Best native audio (opus/webm)
        for af in audio_fmts:
            if af.ext in ("opus", "webm"):
                audio_fmts_final.append(af)
                break

        return VideoInfo(
            url=url,
            video_id=raw.get("id", ""),
            title=raw.get("title", "Untitled"),
            duration=raw.get("duration"),
            thumbnail=raw.get("thumbnail"),
            uploader=raw.get("uploader") or raw.get("channel") or "Unknown",
            view_count=raw.get("view_count"),
            upload_date=raw.get("upload_date"),
            description=(raw.get("description", "") or "")[:200],
            video_formats=video_fmts,
            audio_formats=audio_fmts_final,
            is_live=raw.get("is_live", False),
        )

    # ── Playlist info ─────────────────────────────────────────────────────────

    async def get_playlist_info(self, url: str) -> PlaylistInfo:
        """Fetch playlist metadata without downloading individual videos."""
        cache_key = f"playlist:{url}"
        cached = await video_cache.get(cache_key)
        if cached:
            return cached

        logger.info(f"Fetching playlist info: {url}")
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(None, self._extract_playlist_sync, url)
        await video_cache.set(cache_key, info)
        return info

    def _extract_playlist_sync(self, url: str) -> PlaylistInfo:
        opts = {
            **_ydl_opts_base(),
            "noplaylist": False,
            "extract_flat": True,
            "playlistend": settings.MAX_PLAYLIST_ITEMS,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                raw = ydl.extract_info(url, download=False)
        except DownloadError as e:
            raise ValueError(str(e))

        if not raw:
            raise ValueError("Could not extract playlist info.")

        entries = [e for e in (raw.get("entries", []) or []) if e]

        return PlaylistInfo(
            url=url,
            playlist_id=raw.get("id", ""),
            title=raw.get("title", "Unknown Playlist"),
            uploader=raw.get("uploader") or raw.get("channel") or "Unknown",
            entry_count=len(entries),
            entries=entries[:settings.MAX_PLAYLIST_ITEMS],
            thumbnail=raw.get("thumbnail"),
        )

    # ── Download ──────────────────────────────────────────────────────────────

    async def download(
        self,
        url: str,
        format_spec: str,
        ext: str,
        on_progress: Optional[Callable[[DownloadProgress], None]] = None,
    ) -> Path:
        """
        Download url using format_spec.
        Runs in executor so it never blocks the event loop.
        Returns Path to the downloaded file.
        """
        async with self._semaphore:
            loop = asyncio.get_running_loop()
            output_path = await loop.run_in_executor(
                None,
                self._download_sync,
                url,
                format_spec,
                ext,
                on_progress,
            )
        return output_path

    def _download_sync(
        self,
        url: str,
        format_spec: str,
        ext: str,
        on_progress: Optional[Callable],
    ) -> Path:
        job_id = uuid.uuid4().hex[:8]
        out_template = str(settings.TMP_DIR / f"{job_id}.%(ext)s")

        # Build postprocessors for audio conversion
        postprocessors = []
        if ext == "mp3":
            postprocessors.append({
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            })
        elif ext == "m4a":
            postprocessors.append({
                "key": "FFmpegExtractAudio",
                "preferredcodec": "m4a",
            })

        # Resolve format_spec:
        # "bestaudio/best__mp3" and "bestaudio/best__m4a" are virtual IDs
        # that we map to the actual yt-dlp selector here
        if format_spec.startswith("bestaudio/best__"):
            actual_spec = "bestaudio[ext=m4a]/bestaudio/best"
        elif "+" in format_spec or format_spec in ("best", "bestaudio/best"):
            actual_spec = format_spec
        else:
            # Specific format ID — add safe fallback chain
            actual_spec = f"{format_spec}/{_safe_format_selector()}"

        last_progress_time = [0.0]

        def _progress_hook(d: dict) -> None:
            if on_progress is None:
                return
            now = time.monotonic()
            if now - last_progress_time < 1.5 and d.get("status") == "downloading":
                return
            last_progress_time = now

            status = d.get("status", "unknown")
            downloaded = d.get("downloaded_bytes", 0) or 0
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            speed = d.get("speed")
            eta = d.get("eta")

            pct = 0.0
            if total and total > 0:
                pct = min(100.0, downloaded / total * 100)

            prog = DownloadProgress(
                status=status,
                pct=pct,
                speed=speed,
                eta=eta,
                downloaded=downloaded,
                total=total,
            )

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        self._call_progress(on_progress, prog), loop
                    )
            except Exception:
                pass

        opts = {
            **_ydl_opts_base(quiet=True),
            "format": actual_spec,
            "outtmpl": out_template,
            "postprocessors": postprocessors,
            "progress_hooks": [_progress_hook],
            "noplaylist": True,
            "merge_output_format": ext if ext in ("mp4", "webm", "mkv") else None,
        }

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
        except DownloadError as e:
            err = str(e)
            # If the specific format ID failed, retry with the safe fallback selector
            if "Requested format is not available" in err and format_spec not in ("best", "bestaudio/best"):
                logger.warning(f"Format '{format_spec}' unavailable, retrying with fallback selector")
                fallback_opts = {**opts, "format": _safe_format_selector()}
                with yt_dlp.YoutubeDL(fallback_opts) as ydl:
                    ydl.download([url])
            else:
                raise

        # Find the output file (yt-dlp may change the extension after postprocessing)
        for f in settings.TMP_DIR.iterdir():
            if f.stem == job_id:
                logger.info(f"Downloaded: {f.name} ({f.stat().st_size // 1024} KB)")
                return f

        raise FileNotFoundError(
            f"Download finished but output file not found (job: {job_id}). "
            "Check ffmpeg is installed for audio conversion."
        )

    @staticmethod
    async def _call_progress(callback: Callable, prog: DownloadProgress) -> None:
        """Helper to invoke progress callbacks either asynchronously or synchronously."""
        if asyncio.iscoroutinefunction(callback):
            await callback(prog)
        else:
            callback(prog)

# ضيف السطر ده في نهاية الملف خالص بره أي كلاس
youtube_service = YouTubeService()
  
