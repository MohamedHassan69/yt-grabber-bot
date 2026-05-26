"""
YouTube URL detection and validation helpers.
"""
import re
from enum import Enum
from typing import Optional, Tuple
from urllib.parse import urlparse, parse_qs


class URLType(Enum):
    UNKNOWN = "unknown"
    VIDEO = "video"
    PLAYLIST = "playlist"
    SHORT = "short"


# Patterns for various YouTube URL forms
_YT_DOMAINS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "music.youtube.com"}

_PLAYLIST_RE = re.compile(r"[?&]list=([A-Za-z0-9_\-]+)")
_VIDEO_ID_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?.*v=|embed/|v/|shorts/)|youtu\.be/)([A-Za-z0-9_\-]{11})"
)

# Full regex to quickly detect if a string looks like a YouTube URL
YOUTUBE_URL_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.|m\.)?(?:youtube(?:-nocookie)?\.com|youtu\.be)/"
    r"(?:watch\?.*v=|embed/|v/|shorts/|playlist\?|[A-Za-z0-9_\-]{11})",
    re.IGNORECASE,
)


def is_youtube_url(text: str) -> bool:
    """Return True if `text` appears to be a YouTube URL."""
    text = text.strip()
    return bool(YOUTUBE_URL_PATTERN.search(text))


def classify_url(url: str) -> Tuple[URLType, Optional[str]]:
    """
    Classify a YouTube URL as VIDEO, PLAYLIST, SHORT, or UNKNOWN.
    Returns (URLType, extracted_id_or_list_id).
    """
    url = url.strip()
    parsed = urlparse(url if "://" in url else "https://" + url)
    domain = parsed.netloc.lower().lstrip("www.").lstrip("m.")

    if domain not in _YT_DOMAINS and "youtube" not in domain and "youtu.be" not in domain:
        return URLType.UNKNOWN, None

    qs = parse_qs(parsed.query)

    # Detect shorts
    if "/shorts/" in parsed.path:
        vid_match = re.search(r"/shorts/([A-Za-z0-9_\-]{11})", parsed.path)
        return URLType.SHORT, vid_match.group(1) if vid_match else None

    # Detect playlist-only URL (no video ID)
    if "list" in qs and "v" not in qs:
        return URLType.PLAYLIST, qs["list"][0]

    # Detect playlist+video (treat as playlist)
    if "list" in qs and "v" in qs:
        return URLType.PLAYLIST, qs["list"][0]

    # youtu.be short links
    if "youtu.be" in parsed.netloc:
        vid_id = parsed.path.lstrip("/")[:11]
        return URLType.VIDEO, vid_id

    # Standard watch URL
    if "v" in qs:
        return URLType.VIDEO, qs["v"][0]

    return URLType.UNKNOWN, None


def extract_url_from_text(text: str) -> Optional[str]:
    """Extract the first YouTube URL found in arbitrary text."""
    match = YOUTUBE_URL_PATTERN.search(text)
    if not match:
        return None
    # Find full URL by scanning from match start
    start = match.start()
    # Walk back to find http/https if not included in match
    for i in range(start, max(0, start - 10), -1):
        if text[i:i+4] == "http":
            start = i
            break
    end = start
    while end < len(text) and text[end] not in (" ", "\n", "\t", ">", '"', "'"):
        end += 1
    return text[start:end]
