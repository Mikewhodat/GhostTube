#!/usr/bin/env python3
"""GhostTube V4 - YouTube content collector with FastAPI - NO TOR"""

import os
import sys
import subprocess
import requests
import re
import urllib.parse
import time
import uuid
from pathlib import Path
from urllib.parse import quote_plus
from datetime import datetime
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from concurrent.futures import ThreadPoolExecutor
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).parent
COOKIE_FILE = SCRIPT_DIR / "YT_cookies.txt"

OUTPUT_DIR = Path(os.getenv('OUTPUT_DIR', './output'))
OUTPUT_AUDIO = OUTPUT_DIR / "audio"
OUTPUT_VIDEO = OUTPUT_DIR / "video"
OUTPUT_TRANSCRIPTS = OUTPUT_DIR / "transcripts"

jobs: Dict[str, dict] = {}

def sanitize_dirname(s):
    clean = re.sub(r'[<>:"/\\|?*]', '', s).replace(' ', '_').strip()
    return clean or "search_results"

def ensure_dirs():
    for d in [OUTPUT_AUDIO, OUTPUT_VIDEO, OUTPUT_TRANSCRIPTS]:
        d.mkdir(parents=True, exist_ok=True)

def get_ip():
    try:
        resp = requests.get('https://ident.me', timeout=10)
        return resp.text.strip()
    except Exception as e:
        logger.error(f"Failed to get IP: {e}")
        return "Unknown"

def get_video_title(url):
    try:
        base_args = []
        if COOKIE_FILE.exists():
            base_args.extend(["--cookies", str(COOKIE_FILE)])
        
        cmd = ["python", "-m", "yt_dlp", *base_args, "--get-title", url]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return result.stdout.strip() or "Unknown Title"
    except Exception as e:
        logger.error(f"Failed to get title for {url}: {e}")
        return "Unknown Title"

def search_youtube_broad(query, max_results=10):
    """Broad search - V2 method for diverse results"""
    search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(query + ' youtube')}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    response = requests.get(search_url, headers=headers, timeout=30)
    response.raise_for_status()
    
    pattern = r'href="([^"]*youtube\.com/watch[^"]*)"'
    youtube_urls = re.findall(pattern, response.text)
    
    pattern_short = r'href="([^"]*youtu\.be/[^"]*)"'
    youtube_urls.extend(re.findall(pattern_short, response.text))
    
    urls = []
    seen = set()
    
    for url in youtube_urls:
        if url.startswith('//duckduckgo.com/l/?'):
            try:
                parsed = urllib.parse.urlparse(url)
                params = urllib.parse.parse_qs(parsed.query)
                if 'uddg' in params:
                    url = params['uddg'][0]
            except:
                continue
        
        if url.startswith('//'):
            url = 'https:' + url
        elif not url.startswith('http'):
            url = 'https://' + url
            
        video_id = None
        if 'youtube.com/watch' in url:
            try:
                parsed = urllib.parse.urlparse(url)
                params = urllib.parse.parse_qs(parsed.query)
                if 'v' in params:
                    video_id = params['v'][0]
            except:
                continue
        elif 'youtu.be/' in url:
            try:
                video_id = url.split('youtu.be/')[1].split('?')[0].split('&')[0]
            except:
                continue
        
        if video_id and video_id not in seen:
            seen.add(video_id)
            normalized_url = f'https://www.youtube.com/watch?v={video_id}'
            urls.append(normalized_url)
            
            if len(urls) >= max_results:
                break
    
    return urls

def search_youtube_precise(query, max_results=10):
    """Precise search - site-specific for exact matches"""
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)} site:youtube.com OR site:music.youtube.com"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    
    pattern = r'<a[^>]+class="result__a"[^>]+href="([^"]+)"'
    raw_urls = re.findall(pattern, response.text)
    
    urls = []
    seen = set()
    
    for u in raw_urls:
        if u.startswith("//"):
            u = "https:" + u
        if "uddg=" in u:
            parsed = urllib.parse.urlparse(u)
            qs = urllib.parse.parse_qs(parsed.query)
            if "uddg" in qs:
                u = urllib.parse.unquote(qs["uddg"][0])
        
        if ("youtube.com" in u or "youtu.be" in u) and u not in seen:
            seen.add(u)
            urls.append(u)
            if len(urls) >= max_results:
                break
    
    return urls

def get_playlist_videos(playlist_url, max_results=50):
    """Extract videos from YouTube playlist using yt-dlp"""
    try:
        base_args = []
        if COOKIE_FILE.exists():
            base_args.extend(["--cookies", str(COOKIE_FILE)])
        
        cmd = [
            "python", "-m", "yt_dlp",
            *base_args,
            "--flat-playlist",
            "--print", "url",
            "--playlist-end", str(max_results),
            playlist_url
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            logger.error(f"Playlist extraction failed: {result.stderr}")
            return []
        
        urls = [line.strip() for line in result.stdout.split('\n') if line.strip()]
        return urls[:max_results]
        
    except Exception as e:
        logger.error(f"Failed to extract playlist: {e}")
        return []

def get_channel_videos(channel_url, max_results=50):
    """Extract videos from YouTube channel using yt-dlp"""
    try:
        base_args = []
        if COOKIE_FILE.exists():
            base_args.extend(["--cookies", str(COOKIE_FILE)])
        
        # Normalize channel URL
        if '/videos' not in channel_url and '/streams' not in channel_url:
            if channel_url.endswith('/'):
                channel_url = channel_url + 'videos'
            else:
                channel_url = channel_url + '/videos'
        
        cmd = [
            "python", "-m", "yt_dlp",
            *base_args,
            "--flat-playlist",
            "--print", "url",
            "--playlist-end", str(max_results),
            channel_url
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            logger.error(f"Channel extraction failed: {result.stderr}")
            return []
        
        urls = [line.strip() for line in result.stdout.split('\n') if line.strip()]
        return urls[:max_results]
        
    except Exception as e:
        logger.error(f"Failed to extract channel videos: {e}")
        return []

def download_single_video(url, audio, video, transcripts, audio_dir, video_dir, trans_dir, audio_format, current_ip):
    result = {
        'url': url,
        'title': 'Unknown',
        'status': 'pending',
        'size_mb': 0,
        'duration': 0,
        'retries': 0,
        'ip': current_ip
    }
    
    try:
        result['title'] = get_video_title(url)
        
        base_args = []
        if COOKIE_FILE.exists():
            base_args.extend(["--cookies", str(COOKIE_FILE)])
        
        start_time = time.time()
        
        if audio and audio_dir:
            cmd = [
                "python", "-m", "yt_dlp", *base_args, "-x",
                "--audio-format", audio_format,
                "--audio-quality", "0",
                "-o", str(audio_dir / "%(title)s.%(ext)s"),
                url
            ]
            subprocess.run(cmd, check=True, capture_output=True, timeout=300)
        
        if video and video_dir:
            cmd = [
                "python", "-m", "yt_dlp", *base_args,
                "-f", "bestvideo+bestaudio",
                "--merge-output-format", "mp4",
                "-o", str(video_dir / "%(title)s.%(ext)s"),
                url
            ]
            subprocess.run(cmd, check=True, capture_output=True, timeout=600)
        
        if transcripts and trans_dir:
            cmd = [
                "python", "-m", "yt_dlp", *base_args,
                "--skip-download",
                "--write-auto-sub", "--sub-lang", "en",
                "--convert-subs", "txt",
                "-o", str(trans_dir / "%(title)s.%(ext)s"),
                url
            ]
            subprocess.run(cmd, check=True, capture_output=True, timeout=60)
        
        result['duration'] = time.time() - start_time
        result['status'] = 'success'
        
    except Exception as e:
        logger.error(f"Download failed for {url}: {e}")
        result['status'] = 'failed'
        result['error'] = str(e)
    
    return result

def process_download_job(job_id, query, urls, audio, video, transcripts, audio_format, concurrent):
    job = jobs[job_id]
    job['status'] = 'downloading'
    job['start_time'] = time.time()
    
    subdir = sanitize_dirname(query)
    audio_dir = OUTPUT_AUDIO / subdir if audio else None
    video_dir = OUTPUT_VIDEO / subdir if video else None
    trans_dir = OUTPUT_TRANSCRIPTS / subdir if transcripts else None
    
    if audio_dir:
        audio_dir.mkdir(parents=True, exist_ok=True)
    if video_dir:
        video_dir.mkdir(parents=True, exist_ok=True)
    if trans_dir:
        trans_dir.mkdir(parents=True, exist_ok=True)
    
    job['total_videos'] = len(urls)
    job['completed_videos'] = 0
    job['failed_videos'] = 0
    job['results'] = []
    
    current_ip = get_ip()
    
    with ThreadPoolExecutor(max_workers=concurrent) as executor:
        futures = []
        for url in urls:
            future = executor.submit(
                download_single_video,
                url, audio, video, transcripts,
                audio_dir, video_dir, trans_dir,
                audio_format, current_ip
            )
            futures.append(future)
        
        for future in futures:
            result = future.result()
            job['results'].append(result)
            
            if result['status'] == 'success':
                job['completed_videos'] += 1
            else:
                job['failed_videos'] += 1
            
            job['progress'] = int((job['completed_videos'] + job['failed_videos']) / job['total_videos'] * 100)
            job['message'] = f"Completed {job['completed_videos']}/{job['total_videos']} videos"
    
    job['status'] = 'complete'
    job['elapsed'] = time.time() - job['start_time']
    job['message'] = f"Download complete: {job['completed_videos']} succeeded, {job['failed_videos']} failed"

class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    max_results: Optional[int] = Field(50, ge=1, le=100)
    search_type: str = Field('broad', pattern='^(broad|precise|playlist|channel)$')

class SearchResponse(BaseModel):
    query: str
    results: List[str]
    titles: Dict[str, str]
    count: int
    subdir: str

class DownloadRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    audio: bool = True
    video: bool = False
    transcripts: bool = False
    format: str = Field('mp3', pattern='^(mp3|aac|flac|wav|ogg|opus|m4a)$')
    max_results: Optional[int] = Field(10, ge=1, le=100)
    concurrent_downloads: Optional[int] = Field(3, ge=1, le=10)
    search_type: str = Field('broad', pattern='^(broad|precise|playlist|channel|direct)$')
    urls: Optional[List[str]] = None

class DownloadResponse(BaseModel):
    job_id: str
    query: str
    status: str
    message: str

class StatusResponse(BaseModel):
    message: str
    current_ip: str
    cookies_found: bool

class ProgressResponse(BaseModel):
    job_id: str
    query: str
    status: str
    progress: int
    message: str
    total_videos: int
    completed_videos: int
    failed_videos: int
    elapsed: float
    results: Optional[List[dict]] = None

app = FastAPI(title="GhostTube V4 API", version="4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup():
    ensure_dirs()
    logger.info("GhostTube V4 starting...")
    
    if COOKIE_FILE.exists():
        logger.info(f"Cookie file found: {COOKIE_FILE}")
    else:
        logger.info("No cookie file found (YT_cookies.txt)")

@app.get("/")
async def root():
    index_path = SCRIPT_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {
        "name": "GhostTube V4 API",
        "version": "4.0",
        "cookies_available": COOKIE_FILE.exists(),
        "endpoints": ["/api/status", "/api/search", "/api/download", "/api/progress/{job_id}"]
    }

@app.get("/api/status", response_model=StatusResponse)
async def status():
    ip = get_ip()
    return StatusResponse(
        message="Running",
        current_ip=ip,
        cookies_found=COOKIE_FILE.exists()
    )

@app.post("/api/search", response_model=SearchResponse)
async def api_search(req: SearchRequest):
    try:
        results = []
        
        if req.search_type == 'broad':
            results = search_youtube_broad(req.query, req.max_results)
        elif req.search_type == 'precise':
            results = search_youtube_precise(req.query, req.max_results)
        elif req.search_type == 'playlist':
            results = get_playlist_videos(req.query, req.max_results)
        elif req.search_type == 'channel':
            results = get_channel_videos(req.query, req.max_results)
        
        if not results:
            raise HTTPException(404, f"No videos found using {req.search_type} search")
        
        titles = {}
        for url in results:
            titles[url] = get_video_title(url)
        
        return SearchResponse(
            query=req.query,
            results=results,
            titles=titles,
            count=len(results),
            subdir=sanitize_dirname(req.query)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Search failed: {e}")
        raise HTTPException(500, str(e))

@app.post("/api/download", response_model=DownloadResponse)
async def api_download(req: DownloadRequest, background_tasks: BackgroundTasks):
    if not (req.audio or req.video or req.transcripts):
        raise HTTPException(400, "Select at least one download type")
    
    try:
        urls = []
        
        if req.search_type == 'direct' and req.urls:
            urls = req.urls
        elif req.search_type == 'direct':
            urls = [req.query] if req.query.startswith('http') else []
        elif req.search_type == 'broad':
            urls = search_youtube_broad(req.query, req.max_results)
        elif req.search_type == 'precise':
            urls = search_youtube_precise(req.query, req.max_results)
        elif req.search_type == 'playlist':
            urls = get_playlist_videos(req.query, req.max_results)
        elif req.search_type == 'channel':
            urls = get_channel_videos(req.query, req.max_results)
        
        if not urls:
            raise HTTPException(404, f"No videos found using {req.search_type} method")
        
        job_id = str(uuid.uuid4())
        jobs[job_id] = {
            'job_id': job_id,
            'query': req.query,
            'status': 'queued',
            'progress': 0,
            'message': 'Initializing download...',
            'total_videos': len(urls),
            'completed_videos': 0,
            'failed_videos': 0,
            'start_time': 0,
            'elapsed': 0,
            'results': []
        }
        
        background_tasks.add_task(
            process_download_job,
            job_id, req.query, urls,
            req.audio, req.video, req.transcripts,
            req.format, req.concurrent_downloads
        )
        
        return DownloadResponse(
            job_id=job_id,
            query=req.query,
            status='queued',
            message=f'Download queued for {len(urls)} videos using {req.search_type} method'
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Download endpoint failed: {e}")
        raise HTTPException(500, str(e))

@app.get("/api/progress/{job_id}", response_model=ProgressResponse)
async def get_progress(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    
    job = jobs[job_id]
    return ProgressResponse(
        job_id=job['job_id'],
        query=job['query'],
        status=job['status'],
        progress=job['progress'],
        message=job['message'],
        total_videos=job['total_videos'],
        completed_videos=job['completed_videos'],
        failed_videos=job['failed_videos'],
        elapsed=job['elapsed'],
        results=job.get('results', []) if job['status'] == 'complete' else None
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
