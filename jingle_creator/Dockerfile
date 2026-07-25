FROM python:3.11-slim

# Install ffmpeg system-wide (Railway runs Linux, no ffmpeg.exe)
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Expose port (Railway injects $PORT at runtime)
EXPOSE 8080

# Start server
CMD uvicorn jingle_server:app --host 0.0.0.0 --port ${PORT:-8080}
