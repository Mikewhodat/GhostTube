# ===========================
#  GhostTube FastAPI + Tor
#  Optimized for Alpine + persistent shared volume
# ===========================
FROM python:3.12-alpine

# ---- System dependencies ----
RUN apk add --no-cache tor ffmpeg wget

# ---- Configure Tor ----
RUN echo "SocksPort 127.0.0.1:9050" >> /etc/tor/torrc && \
    echo "ControlPort 127.0.0.1:9051" >> /etc/tor/torrc && \
    echo "CookieAuthentication 1" >> /etc/tor/torrc && \
    echo "Log notice file /var/log/tor/log" >> /etc/tor/torrc && \
    mkdir -p /var/log/tor && chmod 700 /var/log/tor

# ---- Working directory ----
WORKDIR /app

# ---- Copy source ----
COPY fastapi-ghosttube-v-3.py ./fastapi-ghosttube-v-3.py
COPY index.html .
COPY ghosttube-tutorial.html .
COPY YT_cookies.txt .

# ---- Python dependencies ----
RUN pip install --no-cache-dir \
    requests[socks] \
    stem \
    yt-dlp \
    fastapi \
    uvicorn \
    pydantic

# ---- Shared volume setup ----
RUN mkdir -p /root/shared/audio /root/shared/video /root/shared/transcripts && \
    chown -R root:root /root/shared && \
    ln -sf /root/shared output

# Declare the shared volume for persistence
VOLUME ["/root/shared"]

# ---- Networking ----
EXPOSE 8000

# ---- Healthcheck ----
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:8000/status || exit 1

# ---- Startup ----
CMD ["sh", "-c", "echo 'Starting Tor...' && tor -f /etc/tor/torrc & sleep 15 && echo 'Starting FastAPI...' && python fastapi-ghosttube-v-3.py"]
