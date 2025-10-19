#!/usr/bin/env python3
"""
👻Ghosttube-V-3👻 Backend - Production Grade
Concurrent downloads, adaptive rate limiting, intelligent retry logic
Halloween Edition - October 2025
"""

import os
import sys
import subprocess
import requests
import re
import time
import json
import logging
import uuid
from pathlib import Path
from urllib.parse import quote_plus, parse_qs, urlparse
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict, field
from typing import List, Optional, Dict, Tuple
from enum import Enum
from threading import Lock
from collections import deque

# ============================================================================
# LOGGING
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('ghosttube.log'),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ============================================================================
# VERSION & IMPORTS
# ============================================================================

if sys.version_info < (3, 8):
    log.error("Python 3.8+ required")
    sys.exit(1)

try:
    from stem import Signal
    from stem.control import Controller
    from fastapi import FastAPI, HTTPException, BackgroundTasks
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse
    from pydantic import BaseModel, Field
    import uvicorn
except ImportError as e:
    log.error(f"Missing: {e}")
    log.error("pip install requests[socks] stem yt-dlp fastapi uvicorn pydantic")
    sys.exit(1)

# ============================================================================
# CONFIG & CONSTANTS
# ============================================================================

BASE_DIR = Path(__file__).parent.resolve()
OUTPUT_DIR = BASE_DIR / 'output'
OUTPUT_AUDIO = OUTPUT_DIR / 'audio'
OUTPUT_VIDEO = OUTPUT_DIR / 'video'
OUTPUT_TRANSCRIPTS = OUTPUT_DIR / 'transcripts'
LOGS_DIR = OUTPUT_DIR / 'logs'

for d in [OUTPUT_AUDIO, OUTPUT_VIDEO, OUTPUT_TRANSCRIPTS, LOGS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

TOR_PROXY = 'socks5://127.0.0.1:9050'
TOR_HOST = '127.0.0.1'
TOR_PORT = 9051
PROXIES = {'http': TOR_PROXY, 'https': TOR_PROXY}

COOKIES_FILE = str(BASE_DIR / 'YT_cookies.txt') if (BASE_DIR / 'YT_cookies.txt').exists() else None

# Concurrent settings
MAX_CONCURRENT_DOWNLOADS = 3
MAX_WORKERS = 2
CHUNK_SIZE = 1024 * 1024  # 1MB chunks for streaming

# Retry & backoff
MAX_RETRIES = 3
INITIAL_BACKOFF = 2  # seconds
MAX_BACKOFF = 60  # seconds
RATE_LIMIT_THRESHOLD = 3  # consecutive 429s before IP rotation

# Search timeout
SEARCH_TIMEOUT = 30

# ============================================================================
# RATE LIMIT & CIRCUIT BREAKER
# ============================================================================

@dataclass
class RateLimitTracker:
    """Track rate limits per URL/IP"""
    consecutive_429s: int = 0
    last_429_time: float = 0.0
    backoff_until: float = 0.0
    ip_rotation_needed: bool = False
    
    def record_429(self):
        self.consecutive_429s += 1
        self.last_429_time = time.time()
        if self.consecutive_429s >= RATE_LIMIT_THRESHOLD:
            self.ip_rotation_needed = True
        
        # Exponential backoff
        backoff = min(INITIAL_BACKOFF * (2 ** (self.consecutive_429s - 1)), MAX_BACKOFF)
        self.backoff_until = time.time() + backoff
        log.warning(f"Rate limited (count={self.consecutive_429s}), backoff={backoff}s")
    
    def record_success(self):
        self.consecutive_429s = 0
        self.ip_rotation_needed = False
    
    def should_wait(self) -> Tuple[bool, float]:
        """Returns (should_wait, seconds_to_wait)"""
        if time.time() < self.backoff_until:
            wait = self.backoff_until - time.time()
            return (True, wait)
        return (False, 0.0)

# ============================================================================
# DATA MODELS
# ============================================================================

class AudioFormat(str, Enum):
    MP3 = 'mp3'
    AAC = 'aac'
    FLAC = 'flac'
    WAV = 'wav'
    OGG = 'ogg'
    OPUS = 'opus'
    M4A = 'm4a'

class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    max_results: int = Field(50, ge=1, le=100)
    is_url: bool = False

class DownloadRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    audio: bool = True
    video: bool = False
    transcripts: bool = False
    format: AudioFormat = AudioFormat.MP3
    max_results: int = Field(50, ge=1, le=100)
    concurrent_downloads: int = Field(3, ge=1, le=10)
    is_url: bool = False
    urls: Optional[List[str]] = None

@dataclass
class DownloadResult:
    url: str
    title: str
    status: str  # 'success', 'failed', 'skipped'
    error: Optional[str] = None
    duration: float = 0.0
    size_mb: float = 0.0
    retries: int = 0
    ip: str = ''
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

@dataclass
class JobState:
    job_id: str
    query: str
    status: str  # 'queued', 'downloading', 'complete', 'failed'
    progress: int = 0
    message: str = ''
    total_videos: int = 0
    completed_videos: int = 0
    failed_videos: int = 0
    start_time: float = field(default_factory=time.time)
    results: List[DownloadResult] = field(default_factory=list)

# ============================================================================
# GLOBAL STATE & QUEUE
# ============================================================================

state_lock = Lock()
rate_limiter = RateLimitTracker()

jobs: Dict[str, JobState] = {}
current_job: Optional[str] = None
download_queue: deque = deque()

# ============================================================================
# UTILITIES
# ============================================================================

def sanitize_name(s: str, max_len: int = 80) -> str:
    s = re.sub(r'[<>:"/\\|?*\n\r\t]', '', s)
    s = re.sub(r'\s+', '_', s.strip())
    return (s[:max_len] if s else 'search_results')

def get_file_size_mb(path: Path) -> float:
    try:
        return path.stat().st_size / (1024 * 1024)
    except:
        return 0.0

def get_video_title(url: str) -> str:
    """Extract title with timeout"""
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'yt_dlp', '--quiet', '--no-warnings', '-e', url],
            capture_output=True, text=True, timeout=15
        )
        return (result.stdout.strip() or 'Unknown')
    except subprocess.TimeoutExpired:
        return 'Unknown (timeout)'
    except:
        return 'Unknown'

# ============================================================================
# TOR MANAGEMENT
# ============================================================================

tor_ip_cache = {'ip': 'Unknown', 'time': 0}
tor_cache_ttl = 60  # seconds

def get_tor_ip(force_refresh: bool = False) -> str:
    """Get Tor IP with caching"""
    global tor_ip_cache
    
    if not force_refresh and time.time() - tor_ip_cache['time'] < tor_cache_ttl:
        return tor_ip_cache['ip']
    
    try:
        r = requests.get('https://api.ipify.org?format=text', proxies=PROXIES, timeout=15)
        ip = r.text.strip()
        tor_ip_cache = {'ip': ip, 'time': time.time()}
        log.debug(f"Tor IP: {ip}")
        return ip
    except Exception as e:
        log.error(f"Failed to get Tor IP: {e}")
        return 'Unknown'

def check_tor() -> Tuple[bool, str]:
    """Verify Tor is working"""
    ip = get_tor_ip(force_refresh=True)
    
    if 'Unknown' in ip or 'Error' in ip:
        return (False, ip)
    
    try:
        real_ip = requests.get('https://api.ipify.org?format=text', timeout=10).text.strip()
        if ip == real_ip:
            log.error("Tor IP matches real IP!")
            return (False, ip)
    except:
        pass
    
    return (True, ip)

def rotate_tor() -> bool:
    """Rotate Tor circuit with retries"""
    for attempt in range(3):
        try:
            with Controller.from_port(address=TOR_HOST, port=TOR_PORT) as ctrl:
                ctrl.authenticate()
                ctrl.signal(Signal.NEWNYM)
            time.sleep(8)  # Wait for new circuit
            ip = get_tor_ip(force_refresh=True)
            log.info(f"👻 Tor rotated, new IP: {ip}")
            return True
        except Exception as e:
            log.warning(f"Rotate attempt {attempt + 1}/3 failed: {e}")
            time.sleep(2)
    
    log.error("Failed to rotate Tor after 3 attempts")
    return False

# ============================================================================
# SEARCH (Multi-method with fallback - yt-dlp first for more results)
# ============================================================================

def search_youtube(query: str, max_results: int = 50) -> List[str]:
    """Search with multiple fallback methods - yt-dlp first for bulk results"""
    log.info(f"👻 Search: '{query}' (max={max_results})")
    
    methods = [
        ('yt-dlp', lambda: _search_ytdlp(query, max_results)),  # New: yt-dlp for high-volume search
        ('DuckDuckGo', lambda: _search_duckduckgo(query, max_results)),
        ('Direct YouTube', lambda: _search_youtube_direct(query, max_results)),
        ('Bing', lambda: _search_bing(query, max_results))
    ]
    
    for name, method in methods:
        try:
            log.debug(f"Trying search method: {name}")
            results = method()
            if results:
                log.info(f"👻 Found {len(results)} videos via {name}")
                return results[:max_results]
        except Exception as e:
            log.debug(f"  {name} failed: {e}")
            continue
    
    raise Exception("All search methods failed")

def _search_ytdlp(query: str, max_results: int) -> List[str]:
    """Use yt-dlp for robust, high-volume YouTube search"""
    cmd = [
        sys.executable, '-m', 'yt_dlp',
        '--flat-playlist',
        f'ytsearch{query}'  # ytsearchN:query for N results, but omit N for max
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            log.warning(f"yt-dlp search failed: {result.stderr}")
            return []
        lines = result.stdout.strip().split('\n')
        urls = []
        for line in lines:
            line = line.strip()
            if 'youtube.com/watch' in line or 'youtu.be' in line:
                match = re.search(r'(https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)[^ \n]+)', line)
                if match:
                    url = match.group(1)
                    if url not in urls:
                        urls.append(url)
                        if len(urls) >= max_results:
                            break
        log.info(f"yt-dlp returned {len(urls)} URLs")
        return urls
    except Exception as e:
        log.error(f"yt-dlp search error: {e}")
        return []

def _search_duckduckgo(query: str, max_results: int) -> List[str]:
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query + ' site:youtube.com')}"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    r = requests.get(url, headers=headers, proxies=PROXIES, timeout=SEARCH_TIMEOUT)
    r.raise_for_status()
    
    urls, seen = [], set()
    for u in re.findall(r'href="([^"]+)"', r.text):
        if u.startswith('//'):
            u = 'https:' + u
        
        if 'uddg=' in u:
            try:
                parsed = urlparse(u)
                qs = parse_qs(parsed.query)
                u = requests.utils.unquote(qs['uddg'][0]) if 'uddg' in qs else u
            except:
                continue
        
        if ('youtube.com/watch' in u or 'youtu.be/' in u) and u not in seen:
            seen.add(u)
            urls.append(u)
            if len(urls) >= max_results:
                break
    
    return urls

def _search_youtube_direct(query: str, max_results: int) -> List[str]:
    url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    r = requests.get(url, headers=headers, proxies=PROXIES, timeout=SEARCH_TIMEOUT)
    r.raise_for_status()
    
    vids = re.findall(r'/watch\?v=([a-zA-Z0-9_-]{11})', r.text)
    return [f"https://www.youtube.com/watch?v={v}" for v in vids[:max_results]]

def _search_bing(query: str, max_results: int) -> List[str]:
    url = f"https://www.bing.com/videos/search?q={quote_plus(query + ' youtube')}"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    r = requests.get(url, headers=headers, proxies=PROXIES, timeout=SEARCH_TIMEOUT)
    r.raise_for_status()
    
    urls, seen = [], set()
    for u in re.findall(r'href="([^"]+)"', r.text):
        if 'youtube.com/watch' in u or 'youtu.be/' in u:
            if u not in seen:
                seen.add(u)
                urls.append(u)
                if len(urls) >= max_results:
                    break
    
    return urls

# ============================================================================
# DOWNLOAD WITH INTELLIGENT RETRY
# ============================================================================

def download_video(url: str, audio: bool = True, video: bool = False,
                  transcripts: bool = False, audio_format: str = 'mp3',
                  subdir: str = 'downloads') -> DownloadResult:
    """Download with exponential backoff retry"""
    
    start_time = time.time()
    title = get_video_title(url)
    retries = 0
    
    audio_dir = OUTPUT_AUDIO / subdir
    video_dir = OUTPUT_VIDEO / subdir
    trans_dir = OUTPUT_TRANSCRIPTS / subdir
    
    cmd_base = [
        sys.executable, '-m', 'yt_dlp',
        '--proxy', TOR_PROXY,
        '--socket-timeout', '30',
        '--retries', '2',
        '--fragment-retries', '2',
        '--no-warnings',
        '--no-playlist',
        '--quiet',
        '--continue',
        '--no-abort-on-unavailable-fragments'
    ]
    
    if COOKIES_FILE:
        cmd_base.extend(['--cookies', COOKIES_FILE])
    
    for attempt in range(MAX_RETRIES):
        # Check rate limiting backoff
        should_wait, wait_time = rate_limiter.should_wait()
        if should_wait:
            log.warning(f"Rate limit backoff: waiting {wait_time:.1f}s")
            time.sleep(wait_time)
        
        try:
            if audio:
                audio_dir.mkdir(parents=True, exist_ok=True)
                cmd = cmd_base + [
                    '-x', '--audio-format', audio_format,
                    '--audio-quality', '0',
                    '-o', str(audio_dir / '%(title)s.%(ext)s'),
                    url
                ]
                subprocess.run(cmd, check=True, capture_output=True, timeout=300)
            
            if video:
                video_dir.mkdir(parents=True, exist_ok=True)
                cmd = cmd_base + [
                    '-f', 'bestvideo+bestaudio/best',
                    '--merge-output-format', 'mp4',
                    '-o', str(video_dir / '%(title)s.%(ext)s'),
                    url
                ]
                subprocess.run(cmd, check=True, capture_output=True, timeout=600)
            
            if transcripts:
                trans_dir.mkdir(parents=True, exist_ok=True)
                cmd = cmd_base + [
                    '--skip-download',
                    '--write-auto-sub',
                    '--sub-langs', 'en',
                    '--convert-subs', 'txt',
                    '-o', str(trans_dir / '%(title)s.%(ext)s'),
                    url
                ]
                subprocess.run(cmd, check=True, capture_output=True, timeout=60)
            
            rate_limiter.record_success()
            
            size_mb = sum(
                get_file_size_mb(f) for f in audio_dir.glob('*')
                if f.is_file()
            ) if audio else 0.0
            
            log.info(f"👻 Success: {title} (retries={retries})")
            return DownloadResult(
                url=url, title=title, status='success',
                duration=time.time() - start_time,
                size_mb=size_mb, retries=retries,
                ip=get_tor_ip()
            )
        
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.decode() if e.stderr else str(e)
            retries += 1
            
            # Detect error type
            if '429' in error_msg or 'Too Many Requests' in error_msg:
                rate_limiter.record_429()
                if rate_limiter.ip_rotation_needed:
                    log.warning("Rate limit threshold reached, need IP rotation")
                    return DownloadResult(
                        url=url, title=title, status='failed',
                        error='Rate limited - IP rotation needed',
                        duration=time.time() - start_time, retries=retries,
                        ip=get_tor_ip()
                    )
                if attempt < MAX_RETRIES - 1:
                    log.info(f"429 received, retry {attempt + 1}/{MAX_RETRIES}")
                    time.sleep(INITIAL_BACKOFF * (2 ** attempt))
                    continue
            
            if any(x in error_msg for x in ['Video unavailable', 'not available']):
                return DownloadResult(
                    url=url, title=title, status='failed',
                    error='Video unavailable',
                    duration=time.time() - start_time, retries=retries
                )
            
            if any(x in error_msg for x in ['age-restricted', 'Sign in']):
                return DownloadResult(
                    url=url, title=title, status='failed',
                    error='Age-restricted (need cookies)',
                    duration=time.time() - start_time, retries=retries
                )
            
            if attempt < MAX_RETRIES - 1:
                wait = INITIAL_BACKOFF * (2 ** attempt)
                log.warning(f"Download failed, retry {attempt + 1}/{MAX_RETRIES} in {wait}s: {error_msg[:50]}")
                time.sleep(wait)
                continue
            
            return DownloadResult(
                url=url, title=title, status='failed',
                error=error_msg[:150],
                duration=time.time() - start_time, retries=retries
            )
        
        except subprocess.TimeoutExpired:
            retries += 1
            if attempt < MAX_RETRIES - 1:
                log.warning(f"Timeout, retry {attempt + 1}/{MAX_RETRIES}")
                time.sleep(INITIAL_BACKOFF * (2 ** attempt))
                continue
            return DownloadResult(
                url=url, title=title, status='failed',
                error='Timeout - video too large or connection slow',
                duration=time.time() - start_time, retries=retries
            )
        
        except Exception as e:
            retries += 1
            if attempt < MAX_RETRIES - 1:
                log.warning(f"Unexpected error, retry {attempt + 1}/{MAX_RETRIES}: {e}")
                time.sleep(INITIAL_BACKOFF * (2 ** attempt))
                continue
            return DownloadResult(
                url=url, title=title, status='failed',
                error=str(e)[:150],
                duration=time.time() - start_time, retries=retries
            )
    
    return DownloadResult(
        url=url, title=title, status='failed',
        error='Max retries exceeded',
        duration=time.time() - start_time, retries=retries
    )

# ============================================================================
# CONCURRENT DOWNLOAD WORKER
# ============================================================================

def _download_worker(job_id: str, req: DownloadRequest):
    """Main download job with concurrent workers"""
    global current_job, rate_limiter
    
    job = jobs[job_id]
    job.status = 'downloading'
    
    try:
        subdir = sanitize_name(req.query)
        
        # Handle direct URLs (skip search entirely)
        if req.urls and len(req.urls) > 0:
            results = req.urls
            job.message = f'Downloading {len(results)} video(s)...'
        elif req.is_url:
            results = [req.query.strip()]
            job.message = 'Downloading video...'
        else:
            # Batch search
            job.message = 'Searching for videos...'
            results = search_youtube(req.query, req.max_results)
        
        job.total_videos = len(results)
        
        if not results:
            job.status = 'failed'
            job.message = 'No videos found'
            return
        
        log.info(f"[JOB {job_id[:8]}] Starting download of {len(results)} videos (concurrent={req.concurrent_downloads})")
        
        # Concurrent downloads
        with ThreadPoolExecutor(max_workers=min(req.concurrent_downloads, MAX_CONCURRENT_DOWNLOADS)) as executor:
            futures = {}
            
            for i, url in enumerate(results):
                future = executor.submit(
                    download_video,
                    url,
                    audio=req.audio,
                    video=req.video,
                    transcripts=req.transcripts,
                    audio_format=req.format.value,
                    subdir=subdir
                )
                futures[future] = i
            
            completed = 0
            for future in as_completed(futures):
                result = future.result()
                job.results.append(result)
                
                if result.status == 'success':
                    job.completed_videos += 1
                elif result.status == 'failed':
                    job.failed_videos += 1
                
                completed += 1
                job.progress = int((completed / len(results)) * 100)
                job.message = f"Downloaded {completed}/{len(results)} (✓{job.completed_videos} ✗{job.failed_videos})"
                
                # Check if IP rotation needed
                if rate_limiter.ip_rotation_needed:
                    log.info(f"[JOB {job_id[:8]}] Rotating IP due to rate limiting...")
                    job.message = "Rotating IP due to rate limit..."
                    if rotate_tor():
                        rate_limiter.ip_rotation_needed = False
                    time.sleep(3)
        
        job.status = 'complete'
        job.progress = 100
        job.message = f"Complete! ✓{job.completed_videos} successful, ✗{job.failed_videos} failed"
        
        # Save detailed log
        log_file = LOGS_DIR / f"job_{job_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(log_file, 'w') as f:
            results_data = [asdict(r) for r in job.results]
            json.dump({
                'job_id': job_id,
                'query': req.query,
                'duration': time.time() - job.start_time,
                'results': results_data
            }, f, indent=2)
        
        log.info(f"[JOB {job_id[:8]}] Saved results to {log_file}")
        
    except Exception as e:
        log.error(f"[JOB {job_id[:8]}] Fatal error: {e}")
        job.status = 'failed'
        job.message = f'Error: {str(e)[:100]}'

# ============================================================================
# FASTAPI
# ============================================================================

app = FastAPI(
    title="👻Ghosttube-V-3👻 Backend",
    description="Spooky production-grade privacy-focused downloader",
    version="3.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

@app.on_event("startup")
async def startup():
    print("\n" + "="*70)
    print("  👻 GHOSTTUBE-V-3 👻 - HALLOWEEN EDITION")
    print("="*70)
    
    # Check yt-dlp
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'yt_dlp', '--version'],
            capture_output=True, text=True, timeout=5
        )
        print(f"👻 yt-dlp: {result.stdout.strip()}")
    except:
        log.error("yt-dlp not available!")
        sys.exit(1)
    
    # Check Tor
    ok, ip = check_tor()
    if not ok:
        log.error(f"Tor not available - {ip}")
        sys.exit(1)
    
    print(f"👻 Tor: {ip}")
    print(f"👻 Cookies: {'YES' if COOKIES_FILE else 'NO'}")
    print(f"👻 Concurrent downloads: {MAX_CONCURRENT_DOWNLOADS}")
    print(f"👻 Max retries: {MAX_RETRIES}")
    print(f"👻 Output: {OUTPUT_DIR}")
    print(f"\n👻 API: http://127.0.0.1:8000")
    print(f"👻 Docs: http://127.0.0.1:8000/docs")
    print("="*70 + "\n")

@app.get("/")
async def root():
    """Serve the frontend HTML"""
    html_file = BASE_DIR / 'index.html'
    if html_file.exists():
        return FileResponse(html_file)
    return {"name": "👻Ghosttube-V-3👻", "status": "running", "docs": "/docs", "error": "index.html not found"}

@app.get("/api/status")
async def api_status():
    ok, ip = check_tor()
    return {
        "tor_connected": ok,
        "tor_ip": ip,
        "cookies": COOKIES_FILE is not None,
        "active_jobs": len([j for j in jobs.values() if j.status in ['queued', 'downloading']]),
        "total_jobs": len(jobs)
    }
# if the user passes a url, it will download just that single content
@app.post("/api/search")
async def api_search(req: SearchRequest):
    try:
        # Direct URL - no search needed
        if req.is_url:
            urls = [req.query.strip()]
            titles = {}
            for url in urls:
                title = get_video_title(url)
                titles[url] = title
            return {
                "query": req.query,
                "results": urls,
                "titles": titles,
                "count": len(urls),
                "is_url": True
            }
        
        # Batch search
        results = search_youtube(req.query.strip(), req.max_results)
        if not results:
            raise HTTPException(404, "No videos found")
        
        # Get titles for all results
        titles = {}
        for url in results:
            title = get_video_title(url)
            titles[url] = title
        
        return {
            "query": req.query,
            "results": results,
            "titles": titles,
            "count": len(results),
            "is_url": False
        }
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Search error: {e}")
        raise HTTPException(500, f"Search failed: {str(e)}")

@app.post("/api/download")
async def api_download(req: DownloadRequest, bg_tasks: BackgroundTasks):
    if not (req.audio or req.video or req.transcripts):
        raise HTTPException(400, "Select at least one: audio, video, transcripts")
    
    job_id = str(uuid.uuid4())
    job = JobState(
        job_id=job_id,
        query=req.query,
        status='queued'
    )
    
    with state_lock:
        jobs[job_id] = job
    
    bg_tasks.add_task(_download_worker, job_id, req)
    
    return {
        "job_id": job_id,
        "status": "queued",
        "query": req.query,
        "message": "Download queued - check /progress/{job_id} for status"
    }

@app.get("/api/progress/{job_id}")
async def api_progress(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    
    job = jobs[job_id]
    return {
        "job_id": job_id,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "total_videos": job.total_videos,
        "completed": job.completed_videos,
        "failed": job.failed_videos,
        "elapsed": time.time() - job.start_time,
        "start_time": job.start_time,
        "results": [asdict(r) for r in job.results] if job.status == 'complete' else []
    }

@app.post("/api/rotate")
async def api_rotate():
    old_ip = get_tor_ip()
    if not rotate_tor():
        raise HTTPException(500, "Failed to rotate Tor")
    
    new_ip = get_tor_ip(force_refresh=True)
    return {"success": True, "old_ip": old_ip, "new_ip": new_ip}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
