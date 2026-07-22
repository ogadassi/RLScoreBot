# ── Multi-Stage Dockerfile for RLScoreBot 2026 Cloud Edition ───────────────
FROM python:3.11-slim

# Install system dependencies including FFmpeg and C build tools for PyNaCl / Discord Voice
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    build-essential \
    libffi-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code and static assets
COPY . .

# Expose Web Port for Webhook & Web Application
EXPOSE 8080

ENV PORT=8080

CMD ["python", "RLScoreBot.py"]
