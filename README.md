# 🕵️ GhostTube

**Anonymous YouTube Content Collector with Tor Integration**

[![Docker](https://img.shields.io/badge/Docker-Containerized-2496ED?logo=docker)](https://www.docker.com/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Web_API-009688?logo=fastapi)](https://fastapi.tiangolo.com/)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python)](https://python.org)
[![Tor](https://img.shields.io/badge/Tor-Privacy-7D4698?logo=tor-browser)](https://torproject.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

GhostTube is a sophisticated, privacy-focused YouTube downloader that routes all traffic through Tor for complete anonymity. It combines DuckDuckGo search with yt-dlp downloads to collect YouTube content without leaving digital footprints.

## ✨ Features

### 🔐 Privacy & Anonymity
- **Tor Integration**: All traffic routed through Tor network
- **IP Rotation**: Automatic Tor identity switching between requests
- **DuckDuckGo Search**: No direct YouTube API usage to avoid tracking
- **Cookie-less Operation**: No persistent tracking mechanisms

### 📥 Download Capabilities
- **Multi-format Audio**: MP3, AAC, FLAC, WAV, OGG, Opus, M4A
- **High-quality Video**: MP4 format downloads
- **Transcript Extraction**: Automatic caption/subtitle downloads
- **Batch Processing**: Queue multiple downloads
- **Organized Output**: Automatic folder structure creation

### 🚀 Modern Architecture
- **FastAPI Backend**: High-performance async API
- **Docker Containerized**: Easy deployment and isolation
- **Web Interface**: Modern dark-themed UI
- **RESTful API**: Full programmatic access
- **Health Monitoring**: Container health checks and auto-restart

### 🌐 User Interface
- **Responsive Design**: Works on desktop and mobile
- **Real-time Status**: Live download progress and Tor connection status
- **Format Selection**: Choose audio/video formats and quality
- **Search Integration**: Built-in YouTube content discovery

## 🏗️ Architecture

```
┌─────────────────┐    ┌──────────────┐    ┌─────────────────┐
│   Web Browser   │────│  GhostTube   │────│   Tor Network   │
│                 │    │   FastAPI    │    │                 │
└─────────────────┘    └──────────────┘    └─────────────────┘
                              │                       │
                              │                       │
                              ▼                       ▼
                    ┌──────────────┐         ┌─────────────────┐
                    │  yt-dlp      │         │  DuckDuckGo     │
                    │  Downloader  │         │  Search         │
                    └──────────────┘         └─────────────────┘
                              │                       │
                              │                       │
                              ▼                       ▼
                    ┌──────────────┐         ┌─────────────────┐
                    │  Local       │         │  YouTube        │
                    │  Storage     │         │  Content        │
                    └──────────────┘         └─────────────────┘
```

## 📁 Project Structure

```
ghosttube/
├── README.md                     # This documentation
├── docker-compose.yml           # Docker Compose configuration
├── Dockerfile                   # Container build instructions
├── fastapi-ghosttube-v-2.py    # Main FastAPI application (active)
├── fastapi-ghosttube-docker.py # Docker-optimized version
└── index.html                  # Web interface frontend
```

### 📄 File Descriptions

| File | Description | Key Features |
|------|-------------|--------------|
| `docker-compose.yml` | Container orchestration | Volume mounts, health checks, networking |
| `Dockerfile` | Alpine Linux container | Tor setup, Python dependencies, security config |
| `fastapi-ghosttube-v-2.py` | Main application (650 lines) | API endpoints, Tor integration, download logic |
| `fastapi-ghosttube-docker.py` | Docker variant (608 lines) | Container-optimized version |
| `index.html` | Web interface | Modern UI, real-time updates, responsive design |

## 🚀 Quick Start

### Prerequisites

- Docker & Docker Compose
- 2GB+ available disk space
- Internet connection

### 1. Clone Repository

```bash
git clone https://github.com/yourusername/ghosttube.git
cd ghosttube
```

### 2. Start Container

```bash
# Start GhostTube
docker compose up -d

# Check status
docker compose logs -f
```

### 3. Access Interface

- **Web UI**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/status

### 4. First Download

1. Open web interface
2. Enter search query (e.g., "Blue October music")
3. Select formats (Audio: MP3, Video: MP4, Transcripts: Yes)
4. Click "Download"
5. Check `./downloads/` folder for results

## 🔧 Configuration

### Docker Compose Settings

```yaml
services:
  ghosttube:
    build: .
    container_name: ghosttube
    ports:
      - "8000:8000"
    volumes:
      - ./downloads:/root/shared:rw  # Change download path here
    restart: unless-stopped
    environment:
      - PYTHONUNBUFFERED=1
```

### Download Directory Structure

```
downloads/
├── audio/
│   └── [query_name]/
│       ├── song1.mp3
│       ├── song2.flac
│       └── ...
├── video/
│   └── [query_name]/
│       ├── video1.mp4
│       └── ...
└── transcripts/
    └── [query_name]/
        ├── video1.en.vtt
        └── ...
```

### Supported Audio Formats

| Format | Quality | File Size | Compatibility |
|--------|---------|-----------|---------------|
| MP3 | Good | Medium | Universal |
| AAC | Better | Medium | Modern devices |
| FLAC | Lossless | Large | Audiophile |
| WAV | Uncompressed | Largest | Professional |
| OGG | Good | Small | Open source |
| Opus | Excellent | Smallest | Streaming |
| M4A | Good | Medium | Apple devices |

## 🔌 API Reference

### Base URL: `http://localhost:8000`

### Endpoints

#### `GET /`
**Root endpoint with API information**
```json
{
  "name": "YouTube Collector Agent API",
  "version": "2.1",
  "description": "Anonymous YouTube content collector"
}
```

#### `GET /status`
**Check API and Tor connection status**
```json
{
  "message": "YouTube Collector API running",
  "tor_connected": true,
  "current_ip": "192.42.116.195",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

#### `POST /search`
**Search YouTube content via DuckDuckGo**

Request:
```json
{
  "query": "Blue October music",
  "max_results": 10
}
```

Response:
```json
{
  "query": "Blue October music",
  "results": [
    "https://youtube.com/watch?v=...",
    "https://youtube.com/watch?v=..."
  ],
  "count": 10
}
```

#### `POST /download`
**Download YouTube content**

Request:
```json
{
  "query": "Blue October Into The Ocean",
  "audio": true,
  "video": false,
  "transcripts": true,
  "audio_format": "mp3",
  "max_results": 5
}
```

Response:
```json
{
  "success": true,
  "message": "Download completed successfully",
  "results": [
    {
      "url": "https://youtube.com/watch?v=...",
      "title": "Into The Ocean",
      "status": "completed",
      "files": ["audio/Blue_October/Into_The_Ocean.mp3"]
    }
  ],
  "download_path": "/root/shared/audio/Blue_October/"
}
```

#### `POST /rotate`
**Manually rotate Tor identity**
```json
{
  "success": true,
  "old_ip": "192.42.116.195",
  "new_ip": "185.220.101.42",
  "message": "Tor identity rotated successfully"
}
```

## 🛠️ Development

### Local Development Setup

1. **Clone and setup**:
```bash
git clone https://github.com/yourusername/ghosttube.git
cd ghosttube
```

2. **Install Tor** (Ubuntu/Debian):
```bash
sudo apt update
sudo apt install tor
sudo service tor start
```

3. **Configure Tor** (`/etc/tor/torrc`):
```
SocksPort 127.0.0.1:9050
ControlPort 127.0.0.1:9051
CookieAuthentication 1
```

4. **Install Python dependencies**:
```bash
pip install fastapi uvicorn requests[socks] stem yt-dlp pydantic
```

5. **Run development server**:
```bash
python fastapi-ghosttube-v-2.py
```

### Testing

```bash
# Test Tor connection
curl --socks5-hostname 127.0.0.1:9050 https://check.torproject.org/api/ip

# Test API endpoints
curl http://localhost:8000/status
curl -X POST http://localhost:8000/search -H "Content-Type: application/json" -d '{"query":"test","max_results":5}'
```

## 🐳 Docker Details

### Container Specifications
- **Base Image**: `python:3.12-alpine`
- **Size**: ~200MB compressed
- **Ports**: 8000 (HTTP API)
- **Volumes**: `/root/shared` (downloads)
- **Health Check**: 30s interval, 3 retries

### Build Process
```bash
# Build container
docker build -t ghosttube .

# Run manually
docker run -d -p 8000:8000 -v $(pwd)/downloads:/root/shared:rw ghosttube
```

### Environment Variables
```bash
PYTHONUNBUFFERED=1    # Real-time log streaming
```

## 🔒 Security & Privacy

### Privacy Features
- **No Direct YouTube API**: Bypasses YouTube's tracking
- **Tor Routing**: All traffic through Tor network
- **No Cookies**: Stateless operation
- **IP Rotation**: Regular identity changes
- **Local Storage**: Downloads stored locally

### Security Considerations
- Container runs with minimal privileges
- No sensitive data persistence
- Regular security updates via Alpine base
- Isolated network namespace

### Tor Configuration
```
SocksPort 127.0.0.1:9050      # SOCKS proxy
ControlPort 127.0.0.1:9051    # Control port
CookieAuthentication 1         # Authentication
Log notice file /var/log/tor/log
```

## 📊 Performance

### System Requirements
- **RAM**: 256MB minimum, 512MB recommended
- **CPU**: 1 core, 2+ cores recommended
- **Storage**: 1GB+ free space for downloads
- **Network**: Stable internet connection

### Benchmarks
- **Container Startup**: ~15-30 seconds
- **Audio Download**: ~30-60 seconds per song
- **Video Download**: ~1-5 minutes per video
- **Search Response**: ~2-5 seconds
- **Tor Identity Rotation**: ~10-15 seconds

## 🚨 Troubleshooting

### Common Issues

#### Container Shows "Unhealthy"
```bash
# Check logs
docker compose logs ghosttube

# Restart container
docker compose restart ghosttube
```

#### Tor Connection Failed
```bash
# Verify Tor is running in container
docker compose exec ghosttube ps aux | grep tor

# Check Tor logs
docker compose exec ghosttube cat /var/log/tor/log
```

#### Downloads Not Working
```bash
# Check volume mount
docker compose exec ghosttube ls -la /root/shared/

# Verify permissions
sudo chown -R $USER:$USER ./downloads/
```

#### Web Interface Not Loading
```bash
# Check port binding
docker compose ps
netstat -tlnp | grep 8000

# Test API directly
curl http://localhost:8000/status
```

### Debug Commands

```bash
# Container shell access
docker compose exec ghosttube sh

# Real-time logs
docker compose logs -f ghosttube

# Check Tor connection
docker compose exec ghosttube wget -qO- https://check.torproject.org/api/ip
```

## 🤝 Contributing

### Development Workflow

1. **Fork the repository**
2. **Create feature branch**: `git checkout -b feature-name`
3. **Make changes and test**
4. **Submit pull request**

### Code Standards
- Follow PEP 8 for Python code
- Add docstrings for new functions
- Update README for new features
- Test with Docker before submitting

### Reporting Issues
- Use GitHub issues
- Include logs and system info
- Provide reproduction steps

## 📜 Legal & Disclaimer

### Important Notes
- **Educational Purpose**: This tool is for educational and personal use
- **Respect Copyright**: Only download content you have permission to use
- **YouTube ToS**: Be aware of YouTube's Terms of Service
- **Local Laws**: Comply with your local copyright and privacy laws

### Liability
- Users are responsible for their usage
- Developers not liable for misuse
- Tool provided "as-is" without warranty

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

### Technologies Used
- [FastAPI](https://fastapi.tiangolo.com/) - Modern Python web framework
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - YouTube downloader
- [Tor](https://torproject.org) - Anonymous communication
- [Docker](https://docker.com) - Containerization
- [Alpine Linux](https://alpinelinux.org) - Lightweight container base

### Contributors
- Mike Jones- Initial development and maintenance

## 📞 Support

- **GitHub Issues**: [Report bugs or request features](https://github.com/Mikewhodat/ghosttube/issues)
- **Documentation**: Check this README and API docs at `/docs`
- **Community**: Join discussions in GitHub Discussions

---

**⚠️ Remember**: Use responsibly and respect copyright laws. This tool is designed for privacy-conscious users who want to collect content they have permission to download.

**🕵️ Stay Anonymous**: GhostTube helps protect your privacy, but always be aware of your local laws and regulations.

# V1 code code does not contain a cookies.txt captured from a signed in account from a throwaway email.Obviously future versions will contain that
# if you are experiencing issues where the fast API is not loading the reason for that is you need to change the CMD for
Tor a little longer. Currently, it is 30 seconds, but the bootstrap needs time to actually complete for connection.

So, if you're getting this cycle of the fast, API attempting to load and failing to load the reason for that is because I've set this script up to reject.
Standard networking configurations. the good news is, it's all self-contained within the container.

```bash
CMD ["sh", "-c", "echo 'Starting Tor...' && tor -f /etc/tor/torrc & sleep 60 && echo 'Starting FastAPI...' && python fastapi-ghosttube-v-2.py"]
```
