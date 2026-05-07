import os
import re
import json
import uuid
import time
import shutil
import zipfile
import threading
import concurrent.futures
from pathlib import Path

import certifi
import requests
import yt_dlp
from flask import Flask, render_template, request, jsonify, send_file

os.environ["SSL_CERT_FILE"] = certifi.where()

app = Flask(__name__)

DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Shared job store for both search jobs and download jobs
jobs: dict = {}
jobs_lock = threading.Lock()

CURL_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()


def cleanup_job(job_id: str):
    with jobs_lock:
        job = jobs.pop(job_id, None)
    if job:
        folder = job.get("folder")
        if folder and os.path.exists(folder):
            shutil.rmtree(folder, ignore_errors=True)


def _stale_cleanup_loop():
    while True:
        time.sleep(300)
        cutoff = time.time() - 3600
        with jobs_lock:
            stale = [jid for jid, j in list(jobs.items()) if j.get("created_at", 0) < cutoff]
        for jid in stale:
            cleanup_job(jid)


threading.Thread(target=_stale_cleanup_loop, daemon=True).start()


# ---------------------------------------------------------------------------
# Apple Music parsing
# ---------------------------------------------------------------------------

def fetch_apple_music_html(url: str) -> str:
    """Fetch the raw HTML of an Apple Music playlist page."""
    resp = requests.get(url, headers=CURL_HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.text


def parse_apple_music_html(html: str) -> dict:
    """
    Extract playlist title and track list from the JSON blob Apple Music
    embeds in a <script> tag on every page.

    Returns {"playlist_title": str, "tracks": [{"title", "artist", "album",
              "duration_ms", "artwork_url"}, ...]}
    """
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL)

    for script in scripts:
        # Quick pre-filter before expensive JSON parse
        if '"artistName"' not in script and '"subtitleLinks"' not in script:
            continue
        try:
            data = json.loads(script)
        except (json.JSONDecodeError, ValueError):
            continue

        try:
            page_data = data["data"][0]["data"]
        except (KeyError, IndexError, TypeError):
            continue

        # Playlist title from SEO data
        seo = page_data.get("seoData", {})
        raw_title = seo.get("pageTitle") or ""
        playlist_title = re.sub(r"\s*[-–]\s*Apple Music$", "", raw_title).strip() or "Playlist"

        # Find the section that holds actual tracks (has 'duration' on its items)
        track_section = None
        for sec in page_data.get("sections", []):
            items = sec.get("items") or []
            if items and "duration" in items[0] and "title" in items[0]:
                track_section = sec
                break

        if not track_section:
            continue

        tracks = []
        for item in track_section["items"]:
            title = item.get("title") or ""
            if not title:
                continue

            artist = ""
            subtitle = item.get("subtitleLinks") or []
            if subtitle:
                artist = subtitle[0].get("title") or ""

            album = ""
            tertiary = item.get("tertiaryLinks") or []
            if tertiary:
                album = tertiary[0].get("title") or ""

            duration_ms = item.get("duration") or 0

            artwork_url = ""
            art_dict = (item.get("artwork") or {}).get("dictionary") or {}
            if art_dict.get("url"):
                # Replace Apple's dimension placeholders with 500x500
                artwork_url = art_dict["url"].replace("{w}x{h}bb.{f}", "500x500bb.jpg")

            tracks.append({
                "title": title,
                "artist": artist,
                "album": album,
                "duration_ms": int(duration_ms),
                "artwork_url": artwork_url,
            })

        if tracks:
            return {"playlist_title": playlist_title, "tracks": tracks}

    return {}


# ---------------------------------------------------------------------------
# YouTube search
# ---------------------------------------------------------------------------

def search_youtube_for_song(title: str, artist: str, duration_ms: int) -> dict | None:
    """
    Use yt-dlp to search YouTube and return the best-matching video.
    Matching is done by minimizing duration difference from the Apple Music duration.
    """
    query = f"{title} {artist} audio" if artist else f"{title} audio"
    target_seconds = duration_ms / 1000.0

    ydl_opts = {
        "extract_flat": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 20,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            results = ydl.extract_info(f"ytsearch5:{query}", download=False)
    except Exception:
        return None

    entries = (results or {}).get("entries") or []
    best = None
    min_diff = float("inf")

    for entry in entries:
        if not entry or not entry.get("id"):
            continue
        dur = entry.get("duration")
        if dur is None:
            continue
        diff = abs(dur - target_seconds)
        if diff < min_diff:
            min_diff = diff
            best = entry

    if not best:
        return None

    video_id = best["id"]
    yt_dur = best.get("duration", 0)
    mins, secs = divmod(int(yt_dur), 60) if yt_dur else (0, 0)

    return {
        "yt_id": video_id,
        "yt_url": f"https://www.youtube.com/watch?v={video_id}",
        "yt_thumbnail": f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg",
        "yt_title": best.get("title") or "",
        "yt_channel": best.get("channel") or best.get("uploader") or "",
        "yt_duration": f"{mins}:{secs:02d}" if yt_dur else "—",
    }


def _yt_search_worker(job_id: str, tracks: list):
    """
    Background thread: search YouTube for each track in parallel (3 at a time),
    updating the job's `matched` list as results come in.
    """
    def search_one(args):
        idx, track = args
        result = search_youtube_for_song(
            track["title"], track["artist"], track["duration_ms"]
        )
        entry = {
            "idx": idx,
            "title": track["title"],
            "artist": track["artist"],
            "album": track["album"],
            "artwork_url": track["artwork_url"],
            "duration_ms": track["duration_ms"],
        }
        if result:
            entry.update(result)
            entry["matched"] = True
        else:
            entry["matched"] = False

        with jobs_lock:
            if job_id in jobs:
                jobs[job_id]["matched"].append(entry)
                jobs[job_id]["completed"] += 1

        return entry

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(search_one, enumerate(tracks)))

    with jobs_lock:
        if job_id in jobs:
            jobs[job_id]["status"] = "done"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/fetch-playlist", methods=["POST"])
def fetch_playlist():
    """
    1. Fetch the Apple Music playlist page HTML.
    2. Parse track list from embedded JSON.
    3. Start background YouTube search job.
    4. Return song metadata + job_id immediately so the UI can show progress.
    """
    url = (request.json or {}).get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400

    if "music.apple.com" not in url:
        return jsonify({"error": "Please enter an Apple Music playlist URL (music.apple.com)"}), 400

    try:
        html = fetch_apple_music_html(url)
    except requests.RequestException as e:
        return jsonify({"error": f"Could not fetch the playlist page: {e}"}), 400

    parsed = parse_apple_music_html(html)
    if not parsed or not parsed.get("tracks"):
        return jsonify({"error": "Could not find any tracks on that page. Make sure the playlist is public."}), 400

    tracks = parsed["tracks"]
    playlist_title = parsed["playlist_title"]

    job_id = str(uuid.uuid4())
    with jobs_lock:
        jobs[job_id] = {
            "type": "search",
            "status": "running",
            "total": len(tracks),
            "completed": 0,
            "matched": [],
            "playlist_title": playlist_title,
            "created_at": time.time(),
        }

    threading.Thread(
        target=_yt_search_worker,
        args=(job_id, tracks),
        daemon=True,
    ).start()

    # Return immediately with track stubs (no YouTube data yet) + job_id
    stubs = [
        {"title": t["title"], "artist": t["artist"], "artwork_url": t["artwork_url"]}
        for t in tracks
    ]
    return jsonify({
        "job_id": job_id,
        "playlist_title": playlist_title,
        "total": len(tracks),
        "songs": stubs,
    })


@app.route("/api/search-progress/<job_id>")
def search_progress(job_id):
    """Poll the YouTube search job status."""
    with jobs_lock:
        job = jobs.get(job_id)

    if not job or job.get("type") != "search":
        return jsonify({"error": "Job not found"}), 404

    # Sort matched results by their original playlist index
    matched = sorted(job["matched"], key=lambda x: x.get("idx", 0))

    return jsonify({
        "status": job["status"],
        "total": job["total"],
        "completed": job["completed"],
        "matched": matched,
    })


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def _download_one(args):
    idx, song, folder, job_id = args
    title = song.get("title") or f"track_{idx + 1}"
    video_id = song.get("yt_id") or song.get("id") or str(idx)
    safe_name = f"{idx + 1:03d} - {sanitize_filename(title)}"

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(folder, f"{safe_name}.%(ext)s"),
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 60,
    }

    url = song.get("yt_url") or song.get("url") or ""
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        result = {"id": video_id, "title": title, "status": "ok"}
    except Exception as e:
        result = {"id": video_id, "title": title, "status": "error", "error": str(e)}

    with jobs_lock:
        if job_id in jobs:
            jobs[job_id]["completed"] += 1
            jobs[job_id]["completed_songs"].append(result)

    return result


def _download_worker(job_id: str, songs: list, playlist_title: str):
    with jobs_lock:
        folder = jobs[job_id]["folder"]

    args = [(i, song, folder, job_id) for i, song in enumerate(songs)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        list(executor.map(_download_one, args))

    safe_title = sanitize_filename(playlist_title) or "playlist"
    zip_path = os.path.join(folder, f"{safe_title}.zip")

    try:
        mp3_files = sorted(Path(folder).glob("*.mp3"))
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in mp3_files:
                zf.write(f, f.name)

        with jobs_lock:
            if job_id in jobs:
                jobs[job_id]["status"] = "done"
                jobs[job_id]["zip_path"] = zip_path
                jobs[job_id]["zip_name"] = f"{safe_title}.zip"
                jobs[job_id]["mp3_count"] = len(mp3_files)
    except Exception as e:
        with jobs_lock:
            if job_id in jobs:
                jobs[job_id]["status"] = "error"
                jobs[job_id]["error"] = str(e)


@app.route("/api/download", methods=["POST"])
def start_download():
    data = request.json or {}
    songs = data.get("songs", [])
    playlist_title = data.get("playlist_title", "playlist")

    if not songs:
        return jsonify({"error": "No songs selected"}), 400

    job_id = str(uuid.uuid4())
    folder = os.path.join(DOWNLOAD_DIR, job_id)
    os.makedirs(folder)

    with jobs_lock:
        jobs[job_id] = {
            "type": "download",
            "status": "running",
            "total": len(songs),
            "completed": 0,
            "completed_songs": [],
            "folder": folder,
            "created_at": time.time(),
            "zip_path": None,
            "zip_name": None,
            "mp3_count": 0,
            "error": None,
        }

    threading.Thread(
        target=_download_worker,
        args=(job_id, songs, playlist_title),
        daemon=True,
    ).start()

    return jsonify({"job_id": job_id})


@app.route("/api/download-progress/<job_id>")
def download_progress(job_id):
    with jobs_lock:
        job = jobs.get(job_id)

    if not job or job.get("type") != "download":
        return jsonify({"error": "Job not found"}), 404

    return jsonify({
        "status": job["status"],
        "total": job["total"],
        "completed": job["completed"],
        "completed_songs": job["completed_songs"],
        "mp3_count": job.get("mp3_count", 0),
        "error": job.get("error"),
    })


@app.route("/api/download-zip/<job_id>")
def download_zip(job_id):
    with jobs_lock:
        job = jobs.get(job_id)

    if not job or job["status"] != "done":
        return jsonify({"error": "Not ready or job not found"}), 404

    zip_path = job.get("zip_path")
    if not zip_path or not os.path.exists(zip_path):
        return jsonify({"error": "ZIP file not found"}), 404

    zip_name = job.get("zip_name", "playlist.zip")

    def _delayed_cleanup():
        time.sleep(120)
        cleanup_job(job_id)

    threading.Thread(target=_delayed_cleanup, daemon=True).start()

    return send_file(zip_path, as_attachment=True, download_name=zip_name)


@app.route("/api/cleanup/<job_id>", methods=["POST"])
def cleanup_endpoint(job_id):
    cleanup_job(job_id)
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5003))
    debug = os.environ.get("DEBUG", "true").lower() == "true"
    app.run(debug=debug, host="0.0.0.0", port=port)
