"""Typed in-memory job registry, bounded worker pool, and the yt-dlp boundary.

yt-dlp's ``YoutubeDL`` and its hook payloads are untyped. This module is the *only*
place ``Any`` is tolerated: the progress-hook dict and the info dict are converted to
the typed :class:`Job` immediately, and ``Any`` never propagates past here.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from yt_dlp import YoutubeDL

from .config import settings
from .media import generate_thumbnail


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
_pool = ThreadPoolExecutor(max_workers=settings.max_concurrent)


def submit(url: str) -> Job:
    """Register a queued job and hand it to the worker pool."""
    job = Job(id=uuid.uuid4().hex[:12], url=url)
    jobs[job.id] = job
    _pool.submit(_run, job.id, url)
    return job


def _hook(job_id: str) -> Callable[[dict[str, Any]], None]:
    def hook(d: dict[str, Any]) -> None:  # untyped yt-dlp payload stops here
        job = jobs[job_id]
        status = d.get("status")
        if status == "downloading":
            job.state = JobState.DOWNLOADING
            # Format from the numeric fields, not yt-dlp's "_*_str" — those carry
            # terminal ANSI colour codes that render as garbage in the browser.
            job.pct = _format_pct(d)
            job.speed = _format_speed(d.get("speed"))
            eta = d.get("eta")
            job.eta = int(eta) if isinstance(eta, (int, float)) else None
        elif status == "finished":
            job.state = JobState.PROCESSING

    return hook


def _format_pct(d: dict[str, Any]) -> str:
    downloaded = d.get("downloaded_bytes")
    total = d.get("total_bytes") or d.get("total_bytes_estimate")
    if isinstance(downloaded, (int, float)) and isinstance(total, (int, float)) and total:
        return f"{downloaded / total * 100:.1f}%"
    return ""


def _format_speed(speed: object) -> str:
    if isinstance(speed, (int, float)) and speed > 0:
        return f"{speed / 1024 / 1024:.2f} MiB/s"
    return ""


def _run(job_id: str, url: str) -> None:
    job = jobs[job_id]
    opts: dict[str, Any] = {
        "outtmpl": f"{settings.video_dir}/%(title)s [%(id)s].%(ext)s",
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "progress_hooks": [_hook(job_id)],
        "noprogress": True,
        "quiet": True,
    }
    try:
        settings.video_dir.mkdir(parents=True, exist_ok=True)
        with YoutubeDL(opts) as ydl:
            info: dict[str, Any] = ydl.extract_info(url, download=True)
        filename = _final_filename(info)  # convert untyped info to a typed name here
        job.filename = filename
        job.state = JobState.DONE
        if filename is not None:
            generate_thumbnail(filename)
    except Exception as exc:  # yt-dlp raises a broad set of errors; surface them
        job.state = JobState.ERROR
        job.error = str(exc)


def _final_filename(info: dict[str, Any]) -> str | None:
    """Pull the final (post-merge) filename out of an untyped yt-dlp info dict."""
    entries: list[dict[str, Any]] = info.get("entries") or [info]
    for entry in reversed(entries):
        for download in entry.get("requested_downloads") or []:
            filepath = download.get("filepath")
            if isinstance(filepath, str):
                return Path(filepath).name
    return None
