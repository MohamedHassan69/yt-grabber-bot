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
    abr: Optional[float]
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
    ext: str
    height: Optional[int]
    fps: Optional[float]
    filesize: Optional[int]
    vcodec: str
    acodec: str
    tbr: Optional[float]

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
    duration: Optional[int]
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
    status: str
    pct: float = 0.0
    speed: Optional[float] = None
    eta: Optional[int] = None
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
        "http_chunk_size": 10 * 1024 * 1024,
        "cookiefile": "m.youtube.com_cookies.txt",
    }


def _pick_best_formats(raw_formats: List[dict], max_filesize_bytes: int) -> Tuple[List[VideoFormat], List[AudioFormat]]:
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

        if ext in ("mhtml", "vtt") or f.get("format_note", "") == "storyboard":
            continue
        if filesize and filesize > max_filesize_bytes:
            continue

        if vcodec == "none" and acodec != "none":
            abr_val = abr or tbr or 0
            bucket = f"{ext}_{int(abr_val // 32) * 32}"
            existing = audio_formats.get(bucket)
            af = AudioFormat(format_id=fid, ext=ext, abr=abr_val, filesize=filesize, codec=acodec)
            if existing is None or af.sort_key > existing.sort_key:
                audio_formats[bucket] = af
            continue

        if vcodec != "none" and height:
            has_audio = acodec != "none"
            key = f"{height}_{ext}"
            existing = video_formats.get(key)
            vf = VideoFormat(format_id=fid, ext=ext, height=height, fps=fps, filesize=filesize, vcodec=vcodec, acodec=acodec, tbr=tbr)
            if existing is None:
                video_formats[key] = vf
            else:
                if (not existing.has_audio and has_audio) or ((tbr or 0) > (existing.tbr or 0)):
                    video_formats[key] = vf

    return sorted(video_formats.values(), key=lambda x: x.sort_key, reverse=True), sorted(audio_formats.values(), key=lambda x: x.sort_key, reverse=True)


# ─── Main service ──────────────────────────────────────────────────────────────

class YouTubeService:
    def __init__(self):
        self._semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_DOWNLOADS)

    async def get_video_info(self, url: str) -> VideoInfo:
        cache_key = f"info:{url}"
        cached = await video_cache.get(cache_key)
        if cached: return cached
        info = await asyncio.get_event_loop().run_in_executor(None, self._extract_info_sync, url)
        await video_cache.set(cache_key, info)
        return info

    def _extract_info_sync(self, url: str) -> VideoInfo:
        opts = {**_ydl_opts_base(), "noplaylist": True, "ignoreerrors": True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            raw = ydl.extract_info(url, download=False)
        if not raw: raise ValueError("Could not extract video info.")
        max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
        v_fmts, a_fmts = _pick_best_formats(raw.get("formats", []), max_bytes)
        return VideoInfo(url=url, video_id=raw.get("id", ""), title=raw.get("title", "Untitled"),
                         duration=raw.get("duration"), thumbnail=raw.get("thumbnail"), uploader=raw.get("uploader") or "Unknown",
                         view_count=raw.get("view_count"), upload_date=raw.get("upload_date"), description="",
                         video_formats=v_fmts, audio_formats=a_fmts, is_live=raw.get("is_live", False))

    async def get_playlist_info(self, url: str) -> PlaylistInfo:
        cache_key = f"playlist:{url}"
        cached = await video_cache.get(cache_key)
        if cached: return cached
        info = await asyncio.get_event_loop().run_in_executor(None, self._extract_playlist_sync, url)
        await video_cache.set(cache_key, info)
        return info

    def _extract_playlist_sync(self, url: str) -> PlaylistInfo:
        opts = {**_ydl_opts_base(), "noplaylist": False, "extract_flat": True, "playlistend": settings.MAX_PLAYLIST_ITEMS}
        with yt_dlp.YoutubeDL(opts) as ydl:
            raw = ydl.extract_info(url, download=False)
        if not raw: raise ValueError("Could not extract playlist info.")
        entries = [e for e in (raw.get("entries", []) or []) if e]
        return PlaylistInfo(url=url, playlist_id=raw.get("id", ""), title=raw.get("title", "Unknown"),
                            uploader=raw.get("uploader") or "Unknown", entry_count=len(entries),
                            entries=entries[:settings.MAX_PLAYLIST_ITEMS], thumbnail=raw.get("thumbnail"))

    async def download(self, url: str, format_spec: str, ext: str, on_progress: Optional[Callable] = None) -> Path:
        async with self._semaphore:
            return await asyncio.get_event_loop().run_in_executor(None, self._download_sync, url, format_spec, ext, on_progress)

    def _download_sync(self, url: str, format_spec: str, ext: str, on_progress: Optional[Callable]) -> Path:
        job_id = uuid.uuid4().hex[:8]
        out_template = str(settings.TMP_DIR / f"{job_id}.%(ext)s")
        
        # التصحيح السليم (السطر اللي كان عامل مشكلة)
        if ext in ("mp3", "m4a", "opus") or "audio" in format_spec:
            safe_format = f"{format_spec}/bestaudio/best"
        else:
            safe_format = f"{format_spec}/bestvideo+bestaudio/best"

        last_progress_time = [0.0]
        def _progress_hook(d: dict):
            if on_progress is None: return
            now = time.monotonic()
            if now - last_progress_time < 1.5 and d.get("status") == "downloading": return
            last_progress_time = now
            prog = DownloadProgress(status=d.get("status", "unknown"), pct=min(100.0, (d.get("downloaded_bytes", 0) / (d.get("total_bytes") or d.get("total_bytes_estimate") or 1)) * 100))
            loop = asyncio.get_event_loop()
            if loop.is_running(): asyncio.run_coroutine_threadsafe(self._call_progress(on_progress, prog), loop)

        opts = {**_ydl_opts_base(quiet=True), "format": safe_format, "outtmpl": out_template, "progress_hooks": [_progress_hook], "noplaylist": True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        for f in settings.TMP_DIR.iterdir():
            if f.stem == job_id: return f
        raise FileNotFoundError("Download file not found")

    @staticmethod
    async def _call_progress(callback: Callable, prog: DownloadProgress):
        try:
            if asyncio.iscoroutinefunction(callback): await callback(prog)
            else: callback(prog)
        except Exception as e: logger.debug(f"Progress error: {e}")

youtube_service = YouTubeService()
    
