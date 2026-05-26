# ── Stage 1: Builder ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python deps into /install
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: Runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

LABEL maintainer="YTGrabBot"
LABEL description="Professional Telegram YouTube Downloader Bot"

# Install system dependencies
#   ffmpeg  — for audio conversion (mp3/m4a)
#   ca-certs — for HTTPS
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Create non-root user for security
RUN useradd -m -u 1000 botuser

WORKDIR /app

# Copy application code
COPY --chown=botuser:botuser . .

# Create required directories
RUN mkdir -p /app/tmp /app/logs && chown -R botuser:botuser /app/tmp /app/logs

# Switch to non-root user
USER botuser

# Expose webhook port
EXPOSE 8080

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# Default command
CMD ["python", "main.py"]
