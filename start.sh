#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
#  YTGrabBot — Universal start script
#  Works on: local machine, Docker, Koyeb, Render, Railway
# ─────────────────────────────────────────────────────────────────
set -euo pipefail

echo "=============================================="
echo "  YTGrabBot — Starting up"
echo "=============================================="

# ── Load .env if present and not running inside Docker ────────────
if [ -f ".env" ] && [ -z "${DOCKER_ENV:-}" ]; then
    echo "[*] Loading .env file..."
    set -a
    source .env
    set +a
fi

# ── Validate required env ──────────────────────────────────────────
if [ -z "${BOT_TOKEN:-}" ]; then
    echo "[ERROR] BOT_TOKEN is not set!"
    echo "        Copy .env.example to .env and fill in your token."
    exit 1
fi

# ── Create required directories ───────────────────────────────────
mkdir -p tmp logs

# ── Check Python version ──────────────────────────────────────────
PYTHON=$(command -v python3 || command -v python)
PY_VERSION=$($PYTHON --version 2>&1)
echo "[*] Python: $PY_VERSION"

# ── Install / update dependencies ────────────────────────────────
echo "[*] Installing dependencies..."
$PYTHON -m pip install --quiet --upgrade pip
$PYTHON -m pip install --quiet -r requirements.txt

# ── Update yt-dlp to latest (important — YouTube changes frequently) ──
echo "[*] Updating yt-dlp..."
$PYTHON -m pip install --quiet --upgrade yt-dlp || true

# ── Check FFmpeg ──────────────────────────────────────────────────
if command -v ffmpeg &>/dev/null; then
    echo "[*] FFmpeg: $(ffmpeg -version 2>&1 | head -1)"
else
    echo "[WARN] FFmpeg not found. MP3/M4A conversion may not work."
    echo "       Install with: sudo apt-get install ffmpeg"
fi

# ── Launch the bot ────────────────────────────────────────────────
echo "=============================================="
echo "[*] Launching YTGrabBot..."
echo "=============================================="
exec $PYTHON main.py
