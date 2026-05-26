# 📥 YTGrabBot — Professional Telegram YouTube Downloader

[![Python](https://img.shields.io/badge/Python-3.11+-blue)](https://python.org)
[![yt-dlp](https://img.shields.io/badge/yt--dlp-Latest-orange)](https://github.com/yt-dlp/yt-dlp)
[![python-telegram-bot](https://img.shields.io/badge/python--telegram--bot-21.x-blue)](https://python-telegram-bot.org)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED)](https://docker.com)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

A production-ready, SnapTube-like Telegram bot for downloading YouTube videos and playlists in any quality — built for free hosting platforms.

---

## ✨ Features

| Feature | Details |
|---|---|
| 📹 **Video Formats** | 144p → 1080p+ (MP4, WebM), with audio/video-only detection |
| 🎵 **Audio Formats** | MP3 (192kbps), M4A, Opus — all with file sizes shown |
| 📋 **Playlist Support** | Browse, pick, or bulk-download up to 50 videos |
| 📊 **Progress Bars** | Real download + upload progress in Telegram |
| ⚡ **Async Architecture** | Full async/await, download queue, semaphore limiting |
| 🛡 **Rate Limiting** | Per-user token bucket, auto-cooldown on violation |
| 🔁 **Smart Caching** | TTL-based metadata cache reduces yt-dlp calls by ~80% |
| 🧹 **Auto Cleanup** | Temp files deleted after upload automatically |
| 🐳 **Docker Ready** | Multi-stage Dockerfile, docker-compose included |
| ☁️ **Cloud Ready** | Koyeb · Render · Railway · any Docker host |

---

## 📁 Project Structure

```
ytgrabbot/
├── main.py                    # Entry point
├── app/
│   ├── config.py              # All settings via env vars
│   ├── handlers/
│   │   ├── command_handlers.py  # /start /help /cancel /stats
│   │   ├── message_handlers.py  # URL detection + format menu
│   │   └── callback_handlers.py # Button presses + download flow
│   ├── services/
│   │   ├── youtube_service.py   # yt-dlp wrapper, format extraction
│   │   ├── queue_service.py     # Async download queue
│   │   ├── cleanup_service.py   # Temp file management
│   │   └── ui_builder.py        # All keyboards and message templates
│   └── utils/
│       ├── cache.py             # TTL in-memory cache
│       ├── rate_limiter.py      # Token bucket rate limiter
│       ├── url_validator.py     # YouTube URL detection
│       ├── formatters.py        # Human-readable sizes/durations
│       └── logger.py            # Rotating file + console logger
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── start.sh
├── Procfile
├── runtime.txt
├── koyeb.yaml
└── README.md
```

---

## 🚀 Quick Start (Local)

### Prerequisites
- Python 3.11+
- FFmpeg installed (`sudo apt install ffmpeg` / `brew install ffmpeg`)
- A Telegram bot token from [@BotFather](https://t.me/BotFather)

```bash
# 1. Clone
git clone https://github.com/YOUR_USERNAME/ytgrabbot.git
cd ytgrabbot

# 2. Configure
cp .env.example .env
nano .env     # Set BOT_TOKEN at minimum

# 3. Start
chmod +x start.sh
./start.sh
```

Or manually:
```bash
pip install -r requirements.txt
python main.py
```

---

## 📱 Mobile-Only Deployment Tutorial

> **No laptop needed.** Deploy from your phone using only the apps below.

### Tools You Need (all free)
- **Telegram** — to create your bot
- **GitHub app** — to store your code
- **Koyeb / Render / Railway** — to host (choose one)

---

### Step 1 — Create Your Bot Token

1. Open Telegram → search **@BotFather**
2. Send `/newbot`
3. Follow prompts, give your bot a name and username
4. Copy the **HTTP API token** (looks like `123456789:ABCdef...`)

---

### Step 2 — Fork the Repository

1. Open this GitHub repository in your phone's browser
2. Tap the **Fork** button (top right)
3. Select your account → **Create fork**

You now have your own copy at `github.com/YOUR_USERNAME/ytgrabbot`

---

### Step 3 — Add Your Bot Token as a Secret

> Do this **before** deploying so your token is never in the code.

**On GitHub (mobile browser):**
1. Go to your forked repo
2. Tap **Settings** → **Secrets and variables** → **Actions**
3. Tap **New repository secret**
4. Name: `BOT_TOKEN`, Value: your token from Step 1
5. Tap **Add secret**

---

### Option A — Deploy to Koyeb (Recommended for free)

Koyeb offers a **free nano instance** with no credit card required.

1. Open [koyeb.com](https://app.koyeb.com) on your phone browser
2. Sign up / log in
3. Tap **Create App**
4. Select **GitHub** as source → choose your fork → branch: `main`
5. **Build method**: Dockerfile (auto-detected)
6. **Port**: `8080`
7. Under **Environment Variables**, add:
   ```
   BOT_TOKEN = your_token_here
   WEBHOOK_URL = (leave empty for now, fill after first deploy)
   PORT = 8080
   ENVIRONMENT = production
   ```
8. Tap **Deploy**
9. Once deployed, copy the **public URL** (e.g. `https://my-app-xyz.koyeb.app`)
10. Go back to environment variables, set:
    ```
    WEBHOOK_URL = https://my-app-xyz.koyeb.app
    ```
11. Tap **Redeploy** (or it redeploys automatically)

✅ Your bot is live! Test it on Telegram.

**To stop/start:** In Koyeb dashboard → your app → Pause / Resume

---

### Option B — Deploy to Render

1. Open [render.com](https://render.com) → Sign up
2. Tap **New** → **Web Service**
3. Connect GitHub → select your fork
4. Settings:
   - **Environment**: Docker
   - **Dockerfile path**: `./Dockerfile`
   - **Plan**: Free
5. Add environment variables (same as Koyeb above)
6. Tap **Create Web Service**
7. After deploy, copy your URL and set `WEBHOOK_URL`

⚠️ Note: Render's free plan sleeps after 15 min of inactivity. Use a cron ping service like [cron-job.org](https://cron-job.org) to keep it awake, **or** run in polling mode (leave `WEBHOOK_URL` empty).

---

### Option C — Deploy to Railway

1. Open [railway.app](https://railway.app) → Sign up with GitHub
2. Tap **New Project** → **Deploy from GitHub repo**
3. Select your fork
4. Railway auto-detects the Dockerfile
5. Go to **Variables** tab, add all env vars
6. Set `WEBHOOK_URL` to your Railway public URL after first deploy

Railway provides **$5/month free credits** — enough for ~500 hours.

---

### Option D — Docker (VPS / Any Server)

```bash
# On your server
git clone https://github.com/YOUR_USERNAME/ytgrabbot.git
cd ytgrabbot
cp .env.example .env
# Edit .env with your values
docker-compose up -d
# View logs
docker-compose logs -f
```

---

## ⚙️ Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `BOT_TOKEN` | **required** | Telegram bot token |
| `WEBHOOK_URL` | *(empty)* | Public URL for webhook mode. Empty = polling |
| `WEBHOOK_SECRET` | *(empty)* | Secret token to secure webhook |
| `PORT` | `8080` | Port for webhook server |
| `MAX_FILE_SIZE_MB` | `45` | Max upload size (Telegram limit: 50MB) |
| `MAX_DURATION_SECONDS` | `1800` | Max video length (30 min) |
| `MAX_PLAYLIST_ITEMS` | `50` | Max playlist videos |
| `MAX_CONCURRENT_DOWNLOADS` | `3` | Simultaneous downloads across all users |
| `RATE_LIMIT_CALLS` | `5` | Requests per period per user |
| `RATE_LIMIT_PERIOD` | `60` | Rate limit window (seconds) |
| `RATE_LIMIT_COOLDOWN` | `30` | Block duration after violation |
| `CACHE_TTL_SECONDS` | `3600` | Metadata cache duration (1 hour) |
| `CACHE_MAX_ENTRIES` | `200` | Max cache entries in memory |
| `TMP_FILE_MAX_AGE_MINUTES` | `30` | Auto-delete temp files after |
| `ADMIN_USER_IDS` | *(empty)* | Comma-separated admin Telegram IDs |
| `LOG_LEVEL` | `INFO` | DEBUG / INFO / WARNING / ERROR |

---

## 🤖 Bot Commands

| Command | Description |
|---|---|
| `/start` | Welcome message |
| `/help` | Detailed usage guide |
| `/cancel` | Cancel all your active downloads |
| `/stats` | Your usage statistics (admins see global stats) |

---

## 📐 Architecture

```
User sends YouTube URL
        │
        ▼
MessageHandler (url_validator)
        │
        ├─ Single Video ──→ YouTubeService.get_video_info()
        │                         │
        │                   VideoInfo (cached)
        │                         │
        │                   kb_format_selector()
        │                    [quality buttons]
        │
        └─ Playlist ──────→ YouTubeService.get_playlist_info()
                                  │
                            PlaylistInfo (cached)
                                  │
                            kb_playlist_menu()

User taps a format button
        │
        ▼
CallbackHandler
        │
        ├─ Create DownloadJob
        ├─ Enqueue in DownloadQueue (async)
        ├─ on_progress → edit message with progress bar
        ├─ Download completes → upload to Telegram
        └─ Cleanup temp file (scheduled 60s later)
```

---

## 🔒 Security Notes

- Bot token is never hardcoded — always via env vars
- Webhook secured with secret token
- Non-root Docker user
- Rate limiting prevents abuse
- File size checks before upload

---

## ⚠️ Legal Disclaimer

This bot is for **educational and personal use only**.  
Please respect [YouTube's Terms of Service](https://www.youtube.com/t/terms).  
Do not use this to download copyrighted content without permission.

---

## 📜 License

MIT — see [LICENSE](LICENSE)
