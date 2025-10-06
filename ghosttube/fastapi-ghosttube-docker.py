#!/usr/bin/env python3
"""
YouTube Collector Agent with Tor Integration (FastAPI Version - Docker Optimized)

A comprehensive YouTube content collector that combines DuckDuckGo search with
yt-dlp downloads, all routed through Tor for privacy and anonymity.

Workflow:
    1. Checks system prerequisites (Python, Tor, required packages)
    2. Searches DuckDuckGo for YouTube content via Tor proxy
    3. Downloads media with automatic Tor identity rotation
    4. Creates subdirectories conditionally based on user selections

Features:
    - Multiple audio format support (MP3, AAC, FLAC, WAV, OGG, Opus, M4A)
    - Video download in MP4 format
    - Optional transcript extraction
    - Tor identity rotation for enhanced privacy
    - Organized output structure with query-based subdirectories
    - RESTful API with CORS support for web interface integration

Requirements:
    - Python 3.7+
    - Tor service running with:
        * SOCKS proxy on 127.0.0.1:9050
        * ControlPort 9051
        * CookieAuthentication enabled
    - Internet connection
    - Sufficient disk space for downloads

Author: YouTube Collector Agent
Version: 2.1 (Docker Optimized)
"""

import os
import sys
import subprocess
import requests
import re
import urllib.parse
import time
from pathlib import Path
from urllib.parse import quote_plus
from stem import Signal
from stem.control import Controller
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum

# ============================================================================
# CONFIGURATION CONSTANTS
# ============================================================================

TOR_PROXY = 'socks5://127.0.0.1:9050'
TOR_CONTROL_PORT = 9051
PROXIES = {'http': TOR_PROXY, 'https': TOR_PROXY}

SCRIPT_DIR = Path.cwd()
# VENV_DIR disabled in Docker
OUTPUT_DIR = SCRIPT_DIR / "output"
OUTPUT_AUDIO = OUTPUT_DIR / "audio"
OUTPUT_VIDEO = OUTPUT_DIR / "video"
OUTPUT_TRANSCRIPTS = OUTPUT_DIR / "transcripts"

# ============================================================================
# ENUMS FOR VALIDATION
# ============================================================================

class AudioFormat(str, Enum):
    """
    Supported audio format options for downloads.
    Each format has different characteristics:
    - MP3: Universal compatibility, good compression
    - AAC: Better quality than MP3 at same bitrate
    - FLAC: Lossless compression, larger files
    - WAV: Uncompressed, largest files
    - OGG: Open-source alternative to MP3
    - Opus: Modern codec, excellent for streaming
    - M4A: Apple-preferred format, good quality
    """
    MP3 = "mp3"
    AAC = "aac"
    FLAC = "flac"
    WAV = "wav"
    OGG = "ogg"
    OPUS = "opus"
    M4A = "m4a"

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def sanitize_query_for_dir(query):
    """
    Sanitize a search query string to create a valid directory name.
    Removes or replaces characters that are invalid in directory names across
    different operating systems (Windows, macOS, Linux).

    Args:
        query (str): The raw search query string from user input
    
    Returns:
        str: A sanitized string safe for use as a directory name

    Example:
        >>> sanitize_query_for_dir("Kiss: Greatest Hits")
        'Kiss_Greatest_Hits'
    """
    sanitized = re.sub(r'[<>:"/\\|?*]', '', query)
    sanitized = sanitized.replace(' ', '_').strip()
    if not sanitized:
        sanitized = "search_results"
    return sanitized

def print_header(text):
    """
    Print a formatted section header for better terminal output readability.
    
    Args:
        text (str): The header text to display
    """
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}\n")

def ensure_directories():
    """
    Create necessary directories if they don't exist.
    Ensures the virtual environment and output directories are ready.
    """
    for directory in [OUTPUT_AUDIO, OUTPUT_VIDEO, OUTPUT_TRANSCRIPTS]:
        directory.mkdir(parents=True, exist_ok=True)

# ============================================================================
# TOR NETWORK FUNCTIONS
# ============================================================================

def get_current_ip():
    """
    Fetch the current public IP address via Tor proxy.
    Uses ident.me service to determine the exit node IP.
    
    Returns:
        str: The current IP address or error message
    """
    try:
        print("[TOR] Fetching current IP address...")
        resp = requests.get('https://ident.me', proxies=PROXIES, timeout=10)
        ip = resp.text.strip()
        print(f"[TOR] Current IP: {ip}")
        return ip
    except Exception as e:
        print(f"[TOR] Error fetching IP: {e}")
        return f"Error: {e}"

def renew_tor_identity():
    """
    Request a new Tor circuit to rotate the public IP address.
    Sends NEWNYM signal to Tor control port to establish a new circuit.
    
    Returns:
        bool: True if rotation succeeded, False otherwise
    """
    try:
        print("[TOR] ⟳ Requesting new Tor identity...")
        with Controller.from_port(port=TOR_CONTROL_PORT) as ctrl:
            ctrl.authenticate()
            ctrl.signal(Signal.NEWNYM)
        print("[TOR] ⏱  Waiting 5 seconds for new circuit...")
        time.sleep(5)
        print("[TOR] ✓ Identity rotation complete")
        return True
    except Exception as e:
        print(f"[TOR] ✗ Identity rotation failed: {e}")
        return False

def check_tor_connection():
    """
    Verify that Tor is running and accessible.
    Tests connection to Tor SOCKS proxy and retrieves current IP.
    
    Returns:
        tuple: (success: bool, ip_or_error: str)
    """
    try:
        print("[TOR] Checking Tor connection...")
        ip = get_current_ip()
        if "Error" in ip:
            print(f"[TOR] ✗ Connection failed")
            return False, ip
        print(f"[TOR] ✓ Connected successfully")
        return True, ip
    except Exception as e:
        print(f"[TOR] ✗ Connection failed: {e}")
        return False, f"Connection failed: {e}"

# ============================================================================
# SYSTEM PREREQUISITES CHECK
# ============================================================================

def check_prerequisites():
    """
    Verify and setup all system prerequisites for the script.
    
    Checks:
    - Python version (3.7+)
    - Tor connection
    - Virtual environment existence
    - Required Python packages
    
    Returns:
        str: Path to Python binary in virtual environment
    
    Exits:
        sys.exit(1) if critical requirements are not met
    """
    print_header("Checking Prerequisites")
    
    if sys.version_info < (3, 7):
        print("[ERROR] Python 3.7+ required")
        sys.exit(1)
    print(f"✓ Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")

    print("\n[INFO] Checking Tor connection...")
    tor_ok, tor_ip = check_tor_connection()
    if not tor_ok:
        print(f"[ERROR] Cannot connect to Tor: {tor_ip}")
        print("[INFO] Please ensure Tor is running with:")
        print("  - SOCKS proxy on 127.0.0.1:9050")
        print("  - ControlPort 9051")
        print("  - CookieAuthentication enabled")
        sys.exit(1)
    print(f"✓ Tor is running (IP: {tor_ip})")

    print("\n[✓] All prerequisites checked and ready!\n")
    return "python"

# ============================================================================
# SEARCH FUNCTIONS
# ============================================================================

def search_youtube(query, max_results=10):
    """
    Search DuckDuckGo for YouTube content via Tor proxy.
    
    Uses DuckDuckGo HTML search to find YouTube videos without JavaScript.
    All requests are routed through Tor for privacy.
    
    Args:
        query (str): Search query string
        max_results (int): Maximum number of results to return (default: 10)
        
    Returns:
        list: List of YouTube URLs found
        
    Raises:
        Exception: If search fails or network error occurs
    """
    print(f"\n[SEARCH] {'='*60}")
    print(f"[SEARCH] Query: '{query}'")
    print(f"[SEARCH] Max results: {max_results}")
    print(f"[SEARCH] {'='*60}")
    
    search_url = (
        f"https://html.duckduckgo.com/html/"
        f"?q={quote_plus(query)} site:youtube.com OR site:music.youtube.com"
    )
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    try:
        print(f"[SEARCH] Sending request to DuckDuckGo via Tor...")
        response = requests.get(search_url, headers=headers, proxies=PROXIES, timeout=30)
        response.raise_for_status()
        print(f"[SEARCH] ✓ Response received (Status: {response.status_code})")
        
        print(f"[SEARCH] Parsing results...")
        pattern = r'<a[^>]+class="result__a"[^>]+href="([^"]+)"'
        raw_urls = re.findall(pattern, response.text)
        print(f"[SEARCH] Found {len(raw_urls)} raw URLs")
        
        clean_urls, seen = [], set()
        for url in raw_urls:
            if url.startswith("//"):
                url = "https:" + url
            if "uddg=" in url:
                parsed = urllib.parse.urlparse(url)
                qs = urllib.parse.parse_qs(parsed.query)
                if "uddg" in qs:
                    url = urllib.parse.unquote(qs["uddg"][0])
            
            if not ("youtube.com" in url or "youtu.be" in url):
                continue
            
            if url not in seen:
                seen.add(url)
                clean_urls.append(url)
                print(f"[SEARCH]   [{len(clean_urls)}] {url}")
            
            if len(clean_urls) >= max_results:
                break
        
        print(f"[SEARCH] ✓ Found {len(clean_urls)} YouTube URLs")
        print(f"[SEARCH] {'='*60}\n")
        return clean_urls
    except Exception as e:
        print(f"[SEARCH] ✗ Search failed: {e}")
        raise

# ============================================================================
# DOWNLOAD FUNCTIONS
# ============================================================================

def download_media(python_bin, url, audio, video, download_transcripts,
                   audio_subdir, video_subdir, transcripts_subdir, audio_format="mp3"):
    """
    Download audio, video, and/or transcripts from YouTube using yt-dlp.
    
    All downloads are routed through Tor proxy for privacy. Uses yt-dlp's
    extensive format selection and post-processing capabilities.
    
    Args:
        python_bin (str): Path to Python binary
        url (str): YouTube URL to download
        audio (bool): Whether to download audio
        video (bool): Whether to download video
        download_transcripts (bool): Whether to download transcripts
        audio_subdir (Path): Directory for audio files
        video_subdir (Path): Directory for video files
        transcripts_subdir (Path): Directory for transcript files
        audio_format (str): Audio format (mp3, flac, etc.)
        
    Raises:
        Exception: If download fails
    """
    print(f"\n[DOWNLOAD] {'='*60}")
    print(f"[DOWNLOAD] URL: {url}")
    print(f"[DOWNLOAD] Options: Audio={audio}, Video={video}, Transcripts={download_transcripts}")
    if audio:
        print(f"[DOWNLOAD] Audio format: {audio_format}")
    print(f"[DOWNLOAD] {'='*60}")
    
    tor_args = ["--proxy", TOR_PROXY]

    try:
        if audio:
            print(f"[DOWNLOAD] 🎵 Downloading audio...")
            cmd_audio = [
                python_bin, "-m", "yt_dlp", *tor_args, "-x",
                "--audio-format", audio_format,
                "--audio-quality", "0",
                "-o", str(audio_subdir / "%(title)s.%(ext)s"), 
                url
            ]
            result = subprocess.run(cmd_audio, check=True, capture_output=True, text=True)
            if result.stdout:
                print(f"[DOWNLOAD] {result.stdout}")
            print(f"[DOWNLOAD] ✓ Audio download complete")

        if video:
            print(f"[DOWNLOAD] 🎬 Downloading video...")
            cmd_video = [
                python_bin, "-m", "yt_dlp", *tor_args, 
                "-f", "bestvideo+bestaudio",
                "--merge-output-format", "mp4",
                "-o", str(video_subdir / "%(title)s.%(ext)s"), 
                url
            ]
            result = subprocess.run(cmd_video, check=True, capture_output=True, text=True)
            if result.stdout:
                print(f"[DOWNLOAD] {result.stdout}")
            print(f"[DOWNLOAD] ✓ Video download complete")

        if download_transcripts:
            print(f"[DOWNLOAD] 📝 Downloading transcripts...")
            cmd_transcript = [
                python_bin, "-m", "yt_dlp", *tor_args, 
                "--skip-download",
                "--write-auto-sub", "--sub-lang", "en", 
                "--convert-subs", "txt",
                "-o", str(transcripts_subdir / "%(title)s.%(ext)s"), 
                url
            ]
            result = subprocess.run(cmd_transcript, check=True, capture_output=True, text=True)
            if result.stdout:
                print(f"[DOWNLOAD] {result.stdout}")
            print(f"[DOWNLOAD] ✓ Transcript download complete")
        
        print(f"[DOWNLOAD] ✓ All downloads complete for this URL")
        print(f"[DOWNLOAD] {'='*60}\n")
            
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr if e.stderr else str(e)
        print(f"[DOWNLOAD] ✗ Download failed: {error_msg}")
        print(f"[DOWNLOAD] {'='*60}\n")
        raise Exception(f"Download failed: {error_msg}")

# ============================================================================
# FASTAPI MODELS
# ============================================================================

class SearchRequest(BaseModel):
    """Request model for search endpoint."""
    query: str = Field(..., min_length=1, max_length=200, description="Search query")
    max_results: Optional[int] = Field(10, ge=1, le=50, description="Maximum results (1-50)")

class SearchResponse(BaseModel):
    """Response model for search endpoint."""
    query: str
    results: List[str]
    count: int
    subdir: str

class DownloadRequest(BaseModel):
    """Request model for download endpoint."""
    query: str = Field(..., min_length=1, max_length=200, description="Search query")
    audio: bool = Field(True, description="Download audio")
    video: bool = Field(False, description="Download video")
    transcripts: bool = Field(False, description="Download transcripts")
    format: AudioFormat = Field(AudioFormat.MP3, description="Audio format")
    max_results: Optional[int] = Field(10, ge=1, le=50, description="Maximum results (1-50)")

class DownloadResult(BaseModel):
    """Result model for individual download."""
    url: str
    status: str
    old_ip: str
    new_ip: str

class DownloadResponse(BaseModel):
    """Response model for download endpoint."""
    query: str
    downloads: List[DownloadResult]
    audio_dir: Optional[str]
    video_dir: Optional[str]
    transcripts_dir: Optional[str]

class RotateResponse(BaseModel):
    """Response model for Tor rotation endpoint."""
    success: bool
    old_ip: str
    new_ip: str

class StatusResponse(BaseModel):
    """Response model for status endpoint."""
    message: str
    current_ip: str
    tor_connected: bool

# ============================================================================
# FASTAPI APP
# ============================================================================

app = FastAPI(
    title="YouTube Collector Agent API",
    version="2.1",
    description="Privacy-focused YouTube content collector via Tor"
)

@app.get("/", response_class=FileResponse)
async def serve_frontend():
    return FileResponse("index.html")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PYTHON_BIN = None

@app.on_event("startup")
async def startup_event():
    """Initialize prerequisites on server startup."""
    global PYTHON_BIN
    print("\n╔════════════════════════════════════════════════════════════╗")
    print("║          YOUTUBE COLLECTOR AGENT - STARTING                ║")
    print("╚════════════════════════════════════════════════════════════╝\n")
    ensure_directories()
    PYTHON_BIN = check_prerequisites()
    print("\n╔════════════════════════════════════════════════════════════╗")
    print("║  ✓ SERVER READY                                            ║")
    print("║  API: http://0.0.0.0:8000                                  ║")
    print("║  Docs: http://0.0.0.0:8000/docs                            ║")
    print("╚════════════════════════════════════════════════════════════╝\n")

@app.get("/api/info", response_model=dict)
async def root():
    """Root endpoint with API information."""
    return {
        "name": "YouTube Collector Agent API",
        "version": "2.1",
        "status": "running",
        "endpoints": {
            "GET /status": "Check Tor connection status",
            "POST /search": "Search for YouTube videos",
            "POST /download": "Search and download videos",
            "POST /rotate": "Rotate Tor identity"
        }
    }

@app.get("/status", response_model=StatusResponse)
async def api_status():
    """Check API and Tor connection status."""
    tor_ok, ip = check_tor_connection()
    return StatusResponse(
        message="YouTube Collector API running",
        current_ip=ip if tor_ok else "Not connected",
        tor_connected=tor_ok
    )

@app.post("/search", response_model=SearchResponse)
async def api_search(req: SearchRequest):
    """Search for YouTube videos via DuckDuckGo through Tor."""
    try:
        query_dir = sanitize_query_for_dir(req.query)
        results = search_youtube(req.query, req.max_results)
        
        if not results:
            raise HTTPException(status_code=404, detail="No YouTube videos found")
        
        return SearchResponse(
            query=req.query,
            results=results,
            count=len(results),
            subdir=query_dir
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/download", response_model=DownloadResponse)
async def api_download(req: DownloadRequest):
    """Search for and download YouTube content."""
    if not (req.audio or req.video or req.transcripts):
        raise HTTPException(status_code=400, detail="Select at least one download type")
    
    try:
        query_dir = sanitize_query_for_dir(req.query)
        AUDIO_SUBDIR = OUTPUT_AUDIO / query_dir
        VIDEO_SUBDIR = OUTPUT_VIDEO / query_dir
        TRANSCRIPTS_SUBDIR = OUTPUT_TRANSCRIPTS / query_dir
        
        if req.audio:
            AUDIO_SUBDIR.mkdir(parents=True, exist_ok=True)
        if req.video:
            VIDEO_SUBDIR.mkdir(parents=True, exist_ok=True)
        if req.transcripts:
            TRANSCRIPTS_SUBDIR.mkdir(parents=True, exist_ok=True)
        
        results = search_youtube(req.query, max_results=req.max_results)
        
        if not results:
            raise HTTPException(status_code=404, detail="No YouTube videos found")
        
        download_logs = []
        old_ip = get_current_ip()
        renew_tor_identity()
        new_ip = get_current_ip()
        
        for i, url in enumerate(results, 1):
            if i > 1 and (i - 1) % 3 == 0:
                old_ip = new_ip
                if renew_tor_identity():
                    new_ip = get_current_ip()
            
            try:
                download_media(
                    PYTHON_BIN, url, 
                    req.audio, req.video, req.transcripts,
                    AUDIO_SUBDIR, VIDEO_SUBDIR, TRANSCRIPTS_SUBDIR, 
                    req.format.value
                )
                download_logs.append(DownloadResult(
                    url=url, status="success", old_ip=old_ip, new_ip=new_ip
                ))
            except Exception as e:
                download_logs.append(DownloadResult(
                    url=url, status=f"failed: {str(e)}", old_ip=old_ip, new_ip=new_ip
                ))
        
        return DownloadResponse(
            query=req.query,
            downloads=download_logs,
            audio_dir=str(AUDIO_SUBDIR) if req.audio else None,
            video_dir=str(VIDEO_SUBDIR) if req.video else None,
            transcripts_dir=str(TRANSCRIPTS_SUBDIR) if req.transcripts else None
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/rotate", response_model=RotateResponse)
async def api_rotate():
    """Manually rotate Tor identity."""
    old_ip = get_current_ip()
    success = renew_tor_identity()
    new_ip = get_current_ip()
    return RotateResponse(success=success, old_ip=old_ip, new_ip=new_ip)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")