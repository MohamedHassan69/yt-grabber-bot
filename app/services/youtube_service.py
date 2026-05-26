"""
YouTube download service built on yt-dlp.
Handles info extraction, format listing, and actual downloading
with real-time progress reporting via asyncio queues.
"""
import asyncio
import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Tuple

import yt_dlp

from app.config import settings
from app.utils.cache import video_cache
from app.utils.formatters import format_size, format_duration
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


# ─── Data models ──────────────────────────────────────────────────────────────

@dataclass
class AudioFormat:
    format_id: str
    ext: str           # mp3, m4a, opus, webm
    abr: Optional[float]   # audio bitrate kbps
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
    ext: str           # mp4, webm
    height: Optional[int]
    fps: Optional[float]
    filesize: Optional[int]
    vcodec: str
    acodec: str        # 'none' if video-only
    tbr: Optional[float]   # total bitrate

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
    duration: Optional[int]    # seconds
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
    entries: List[dict] = field(default_factory=list)   # minimal info per entry
    thumbnail: Optional[str] = None


@dataclass
class DownloadProgress:
    status: str          # "downloading", "processing", "finished", "error"
    pct: float = 0.0
    speed: Optional[float] = None   # bytes/sec
    eta: Optional[int] = None       # seconds
    downloaded: Optional[int] = None
    total: Optional[int] = None
    filename: Optional[str] = None
    error: Optional[str] = None


# ─── Helper ────────────────────────────────────────────────────────────────────

def _ydl_opts_base(quiet: bool = True) -> dict:
    return {
        "quiet": quiet,
        "no_warnings": quiet,
        "noplaylist": True,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        "http_chunk_size": 10 * 1024 * 1024,  # 10 MB chunks
        "cookiefile": "m.youtube.com_cookies.txt",  # تمت إضافة ملف الكوكيز هنا
    }


def _pick_best_formats(
    raw_formats: List[dict],
    max_filesize_bytes: int,
) -> Tuple[List[VideoFormat], List[AudioFormat]]:
    """
    Parse raw yt-dlp format dicts into clean VideoFormat / AudioFormat objects,
    de-duplicated by resolution, preferring mp4 with audio.
    """
    video_formats: Dict[str, VideoFormat] = {}  # key: height+ext
    audio_formats: Dict[str, AudioFormat] = {}  # key: ext+abr_bucket

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

        # Skip manifests and storyboards
        if ext in ("mhtml", "vtt") or f.get("format_note", "") == "storyboard":
            continue

        # Skip anything that exceeds the configured max filesize
        if filesize and filesize > max_filesize_bytes:
            continue

        # ── Audio-only track ─────────────────────────────────────────────
        if vcodec == "none" and acodec != "none":
            abr_val = abr or tbr or 0
            bucket = f"{ext}_{int(abr_val // 32) * 32}"   # group by 32kbps steps
            existing = audio_formats.get(bucket)
            af = AudioFormat(
                format_id=fid, ext=ext, abr=abr_val,
                filesize=filesize, codec=acodec,
            )
            if existing is None or af.sort_key > existing.sort_key:
                audio_formats[bucket] = af
            continue

        # ── Video track (with or without audio) ──────────────────────────
        if vcodec != "none" and height:
            # Prefer mp4 with audio, fallback to webm, fallback to video-only
            has_audio = acodec != "none"
            key = f"{height}_{ext}"
            existing = video_formats.get(key)
            vf = VideoFormat(
                format_id=fid, ext=ext, height=height, fps=fps,
                filesize=filesize, vcodec=vcodec, acodec=acodec, tbr=tbr,
            )
            if existing is None:
                video_formats[key] = vf
            else:
                # Prefer: has_audio > higher bitrate > mp4
                existing_has_audio = existing.has_audio
                if (not existing_has_audio and has_audio) or \
                   (has_audio == existing_has_audio and (tbr or 0) > (existing.tbr or 0)):
                    video_formats[key] = vf

    # Sort results
    sorted_videos = sorted(video_formats.values(), key=lambda x: x.sort_key, reverse=True)
    sorted_audio = sorted(audio_formats.values(), key=lambda x: x.sort_key, reverse=True)

    return sorted_videos, sorted_audio


# ─── Main service ──────────────────────────────────────────────────────────────

class YouTubeService:
    """
    Async wrapper around yt-dlp providing:
      - Video/playlist info extraction
      - Format listing
      - Progress-reporting downloads
    """

    def __init__(self):
        self._semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_DOWNLOADS)

    # ── Info extraction ──────────────────────────────────────────────────────

    async def get_video_info(self, url: str) -> VideoInfo:
        """
        Fetch video metadata and available formats.
        Results are cached for CACHE_TTL_SECONDS.
        """
        cache_key = f"info:{url}"
        cached = await video_cache.get(cache_key)
        if cached:
            logger.debug(f"Cache hit for {url}")
            return cached

        logger.info(f"Fetching info: {url}")
        info = await asyncio.get_event_loop().run_in_executor(
            None, self._extract_info_sync, url
        )
        await video_cache.set(cache_key, info)
        return info

    def _extract_info_sync(self, url: str) -> VideoInfo:
        opts = {
            **_ydl_opts_base(),
            "noplaylist": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            raw = ydl.extract_info(url, download=False)

        if not raw:
            raise ValueError("Could not extract video info.")

        max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
        video_fmts, audio_fmts = _pick_best_formats(
            raw.get("formats", []), max_bytes
        )

        # Always add "best audio" virtual options (mp3 conversion)
        # These are handled specially during download via postprocessors
        mp3_size = None
        for af in audio_fmts:
            if af.ext in ("m4a", "webm", "opus"):
                # mp3 will be roughly similar size
                mp3_size = af.filesize
                break

        audio_fmts_final = []
        # Add MP3 conversion option
        audio_fmts_final.append(AudioFormat(
            format_id="bestaudio/best__mp3",
            ext="mp3",
            abr=192,
            filesize=mp3_size,
            codec="mp3",
        ))
        # Add M4A option
        for af in audio_fmts:
            if af.ext == "m4a":
                audio_fmts_final.append(af)
                break
        else:
            audio_fmts_final.append(AudioFormat(
                format_id="bestaudio/best__m4a",
                ext="m4a",
                abr=128,
                filesize=mp3_size,
                codec="aac",
            ))
        # Add best opus/webm audio
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
            description=raw.get("description", "")[:200] if raw.get("description") else "",
            video_formats=video_fmts,
            audio_formats=audio_fmts_final,
            is_live=raw.get("is_live", False),
        )

    async def get_playlist_info(self, url: str) -> PlaylistInfo:
        """Fetch playlist metadata (without downloading all videos)."""
        cache_key = f"playlist:{url}"
        cached = await video_cache.get(cache_key)
        if cached:
            return cached

        logger.info(f"Fetching playlist info: {url}")
        info = await asyncio.get_event_loop().run_in_executor(
            None, self._extract_playlist_sync, url
        )
        await video_cache.set(cache_key, info)
        return info

    def _extract_playlist_sync(self, url: str) -> PlaylistInfo:
        opts = {
            **_ydl_opts_base(),
            "noplaylist": False,
            "extract_flat": True,     # Fast: don't fetch individual video info
            "playlistend": settings.MAX_PLAYLIST_ITEMS,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            raw = ydl.extract_info(url, download=False)

        if not raw:
            raise ValueError("Could not extract playlist info.")

        entries = raw.get("entries", []) or []
        # Filter out None entries (private/deleted videos)
        entries = [e for e in entries if e]

        return PlaylistInfo(
            url=url,
            playlist_id=raw.get("id", ""),
            title=raw.get("title", "Unknown Playlist"),
            uploader=raw.get("uploader") or raw.get("channel") or "Unknown",
            entry_count=len(entries),
            entries=entries[:settings.MAX_PLAYLIST_ITEMS],
            thumbnail=raw.get("thumbnail"),
        )

    # ── Download ─────────────────────────────────────────────────────────────

    async def download(
        self,
        url: str,
        format_spec: str,
        ext: str,
        on_progress: Optional[Callable[[DownloadProgress], None]] = None,
    ) -> Path:
        """
        Download `url` using `format_spec`.
        Returns path to the downloaded file.
        `on_progress` is called with DownloadProgress updates.
        """
        async with self._semaphore:
            output_path = await asyncio.get_event_loop().run_in_executor(
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

        # ─── THE FIX: Bulletproof format selection ───
        # تنظيف الجودة المطلوبة لضمان عدم تعطل المكتبة
        clean_format = format_spec.split("__")
        if ext in ("mp3", "m4a", "opus") or "audio" in clean_format:
            safe_format = f"{clean_format}/bestaudio/best"
        else:
            # لو الجودة المطلوبة مش متوفرة، هينزل تلقائياً لأفضل جودة متاحة (فيديو وصوت)
            if "+" not in clean_format and clean_format != "best":
                safe_format = f"{clean_format}+bestaudio/bestvideo+bestaudio/best"
            else
    
