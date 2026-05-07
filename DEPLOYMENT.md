# Deployment Guide

## Dependencies

### Python packages (pip)
```
Flask>=3.0.0
yt-dlp>=2024.1.0
certifi>=2024.1.1
```

### System dependencies (must be installed separately)
| Dependency | Purpose | Install |
|---|---|---|
| **Python 3.8+** | Runtime | https://python.org |
| **ffmpeg** | MP3 conversion | See below |

**Install ffmpeg:**
- macOS:  `brew install ffmpeg`
- Ubuntu/Debian: `sudo apt install ffmpeg`
- Windows: Download from https://ffmpeg.org/download.html and add `ffmpeg.exe` to your PATH

---

## Local setup (first time)

```bash
# 1. Clone / navigate to the project
cd Youtube-to-MP3

# 2. Create a virtual environment
python3 -m venv venv
source venv/bin/activate        # macOS/Linux
# venv\Scripts\activate         # Windows

# 3. Install Python packages
pip install -r requirements.txt

# 4. Verify ffmpeg is available
ffmpeg -version

# 5. Run the app
python app.py
```

Open http://localhost:5000 in your browser.

---

## Running on a server

### Environment variables
| Variable | Default | Description |
|---|---|---|
| `PORT` | `5000` | Port to listen on |
| `DEBUG` | `true` | Set to `false` in production |

### Production server (gunicorn)
```bash
pip install gunicorn
gunicorn -w 1 -b 0.0.0.0:5000 app:app
```

> **Important:** Use `-w 1` (single worker). The job store is in-memory, so multiple workers won't share state. For multi-worker deployments, replace `jobs` dict with Redis or a database.

### Docker (optional)
```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 5000
ENV DEBUG=false
CMD ["python", "app.py"]
```

---

## How it works

1. **Fetch** — yt-dlp extracts playlist metadata (no download) and returns video list
2. **Select** — User reviews embedded YouTube previews, deselects unwanted tracks
3. **Download** — Up to 3 parallel yt-dlp workers download + convert to MP3 via ffmpeg
4. **ZIP** — All MP3s are packaged into a ZIP named after the playlist
5. **Cleanup** — Files delete 2 min after download, or after 1 hour if unclaimed

Downloaded files are stored temporarily in `downloads/<job-id>/` and are gitignored.
