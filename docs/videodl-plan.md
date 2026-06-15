# videodl — build plan

A minimalist, server-rendered web app to download source videos with yt-dlp and browse/play them. Runs in a single container on the home Ubuntu server, accessed over the tailnet at `video.griggx.com`.

## Confirmed decisions

- **Stack:** Python 3.12, FastAPI + Jinja2. yt-dlp used as a library (progress hooks, format selection) — not shelled out.
- **Tooling:** `uv` for env + dependency management (`pyproject.toml` + committed `uv.lock`, reproducible builds).
- **Typing:** strong typing throughout — typed `Job` model, typed settings, full annotations, checked in CI/locally. yt-dlp has no type stubs, so it's quarantined behind a single `Any` boundary (see below) rather than letting `Any` bleed across the app.
- **Downloads:** background jobs with live progress.
- **Tiles:** thumbnails + in-browser playback.
- **No auth** — the tailnet is the perimeter.
- **No database** — in-memory job registry; the filesystem is the source of truth, so completed downloads survive restarts (they're just files). Only in-flight jobs are lost on restart, which is acceptable.
- **Networking:** `video.griggx.com` A record → the server's Tailscale IP. The container publishes a host port; no reverse proxy.
- **Container format:** remux to mp4 (`merge_output_format`). Cheap (no transcode). Caveat: VP9/AV1 sources stay VP9/AV1 inside the mp4 — fine in Chrome/Firefox, won't play in Safari. Revisit with transcode-on-demand only if Safari/iOS playback is needed.

## Data flows

**Download.** `POST /download` creates a job in an in-memory registry and submits it to a bounded thread pool (yt-dlp blocks, so it runs off the event loop). `progress_hooks` push `% / speed / ETA / state` into the typed job record. The browser receives live updates via SSE from `GET /events`. On finish, a thumbnail is generated and the tile flips to "ready".

**Playback.** `<video src="/videos/{name}">`. Starlette's `FileResponse` honours HTTP Range requests, so seeking works without custom byte-range code. uvicorn serves files directly.

**Thumbnails.** ffmpeg grabs a frame ~10% into the file, cached to `.thumbs/{name}.jpg` (sibling dir, keeps the videos folder clean). Generated on download-finish, plus a startup sweep to backfill thumbnails for videos already in the folder.

## Project structure

```
videodl/
  app/
    main.py        # FastAPI app + routes
    config.py      # typed Settings (pydantic-settings)
    jobs.py        # typed registry, worker, progress hook
    media.py       # folder scan + ffmpeg thumbnail
    templates/
      index.html   # dashboard: form + active jobs + tile grid
      _tile.html   # single video tile (partial)
    static/
      app.css
      sse.js       # tiny SSE client, updates job rows
  Dockerfile
  docker-compose.yml
  pyproject.toml
  uv.lock          # committed
```

## Routes

| Method | Path             | Purpose                                            |
|--------|------------------|----------------------------------------------------|
| GET    | `/`              | Dashboard: submit form, active jobs, video tiles   |
| POST   | `/download`      | Accept URL (+ optional format), create job         |
| GET    | `/events`        | SSE stream of job progress                          |
| GET    | `/videos/{name}` | Range-enabled file serving (playback + download)   |
| GET    | `/thumb/{name}`  | Serve cached thumbnail (generate on miss)          |

## Typed config

```python
# config.py
from pathlib import Path
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    video_dir: Path = Path("/data/videos")
    max_concurrent: int = 2

settings = Settings()   # reads VIDEO_DIR, MAX_CONCURRENT from env
```

## Core: typed job + hook → registry → SSE

The only non-obvious coupling. yt-dlp's `YoutubeDL` and its hook dict are untyped — that's the one tolerated `Any` boundary; everything the app touches afterwards is a typed `Job`.

```python
# jobs.py
from enum import Enum
from typing import Any, Callable
from pydantic import BaseModel
from yt_dlp import YoutubeDL
from .config import settings

class JobState(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"

class Job(BaseModel):
    id: str
    url: str
    state: JobState = JobState.QUEUED
    pct: str = ""
    speed: str = ""
    eta: int | None = None
    filename: str | None = None
    error: str | None = None

jobs: dict[str, Job] = {}

def _hook(job_id: str) -> Callable[[dict[str, Any]], None]:
    def hook(d: dict[str, Any]) -> None:      # untyped yt-dlp payload stops here
        job = jobs[job_id]
        if d.get("status") == "downloading":
            job.state = JobState.DOWNLOADING
            job.pct = str(d.get("_percent_str", "")).strip()
            job.speed = str(d.get("_speed_str", "")).strip()
            job.eta = d.get("eta")
        elif d.get("status") == "finished":
            job.state = JobState.PROCESSING
    return hook

def run(job_id: str, url: str) -> None:
    opts: dict[str, Any] = {
        "outtmpl": f"{settings.video_dir}/%(title)s [%(id)s].%(ext)s",
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "progress_hooks": [_hook(job_id)],
    }
    with YoutubeDL(opts) as ydl:
        ydl.download([url])
    jobs[job_id].state = JobState.DONE
    # then: generate thumbnail for the finished file
```

`Job` being a pydantic model gives `.model_dump()` for free, so SSE frames serialise without extra glue. `/events` drains job state and yields SSE frames (`sse-starlette`'s `EventSourceResponse`). A `ThreadPoolExecutor(max_workers=settings.max_concurrent)` runs `run()`, so a pasted playlist won't saturate the box.

## pyproject.toml

```toml
[project]
name = "videodl"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi",
    "uvicorn[standard]",
    "jinja2",
    "yt-dlp",
    "python-multipart",
    "sse-starlette",
    "pydantic-settings",
]

[dependency-groups]
dev = ["mypy"]

[tool.mypy]
strict = true
python_version = "3.12"

# yt-dlp ships no stubs — ignore only that import, keep strict everywhere else
[[tool.mypy.overrides]]
module = ["yt_dlp.*"]
ignore_missing_imports = true
```

`mypy --strict` is the safe default checker. If you'd rather stay all-Astral, `ty` (their checker) is an option but still preview as of now — pyright is the mature non-mypy alternative.

## Container (uv)

**Dockerfile**
```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# pin uv for reproducibility (bump deliberately)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app

# deps first for layer caching
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app/ ./app/
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH" \
    VIDEO_DIR=/data/videos \
    MAX_CONCURRENT=2
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

**docker-compose.yml**
```yaml
services:
  videodl:
    build: .
    ports:
      - "8080:8080"           # reachable on the Tailscale IP
    volumes:
      - /srv/data0/studio/videos:/data/videos
    environment:
      - VIDEO_DIR=/data/videos
      - MAX_CONCURRENT=2
    restart: unless-stopped
```

## Setup notes

- The container process must have **read-write** on `/srv/data0/studio/videos` (downloads write there, and `.thumbs/` is created inside it). Match the container user's UID/GID to the directory owner, or `chown` the dir, to avoid permission grief.
- Commit `uv.lock`; the Dockerfile builds with `--frozen` so images match local exactly.
- yt-dlp updates frequently; `uv lock --upgrade-package yt-dlp` and rebuild periodically to keep extractors current.
- `8080` is published on all interfaces but only reachable via the tailnet in practice. Tighten with the host firewall for belt-and-braces.

## Build order

1. `uv init` + `uv add` the deps above; scaffold `GET /` rendering an empty dashboard from a folder scan.
2. `/videos/{name}` + an inline `<video>` player; confirm range/seeking works.
3. `media.py` thumbnails + startup sweep; render the tile grid.
4. `jobs.py` typed registry + thread pool + `POST /download`.
5. `/events` SSE + `sse.js`; wire live progress into job rows.
6. Dockerise and bring up via compose.

Dev loop: `uv run uvicorn app.main:app --reload` and `uv run mypy app` (wire the latter into a pre-commit hook or CI).

## Possible later extensions

- SQLite for persistent job history/logs.
- Format/quality picker in the form.
- Cookies file mount for auth-gated sources.
- Transcode-on-demand for Safari/iOS playback.
- Delete/rename actions on tiles.
