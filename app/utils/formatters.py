"""
Human-friendly formatting utilities.
"""
from typing import Optional


def format_size(bytes_val: Optional[int]) -> str:
    """Convert byte count to human-readable string."""
    if not bytes_val or bytes_val <= 0:
        return "~? MB"
    for unit in ("B", "KB", "MB", "GB"):
        if bytes_val < 1024:
            return f"~{bytes_val:.1f} {unit}"
        bytes_val /= 1024
    return f"~{bytes_val:.1f} GB"


def format_duration(seconds: Optional[int]) -> str:
    """Convert seconds to HH:MM:SS or MM:SS string."""
    if not seconds:
        return "?:??"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def format_progress_bar(pct: float, width: int = 10) -> str:
    """Return a Unicode progress bar string."""
    filled = int(width * pct / 100)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {pct:.0f}%"


def truncate(text: str, max_len: int = 60) -> str:
    """Truncate text with ellipsis."""
    if len(text) <= max_len:
        return text
    return text[:max_len - 1] + "…"


def escape_markdown(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    special = r"\_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in special else c for c in text)
