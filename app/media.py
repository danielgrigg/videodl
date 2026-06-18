"""Filesystem scan and ffmpeg thumbnail generation.

The filesystem is the source of truth: a video is anything in ``VIDEO_DIR`` with a
known extension. Thumbnails are cached in ``.thumbs/`` alongside the videos.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import settings

VIDEO_EXTENSIONS = frozenset({".mp4", ".mkv", ".webm", ".mov", ".m4v"})


@dataclass(frozen=True)
class Video:
    name: str  # filename, used as the id in URLs
    size: int  # bytes
    mtime: float


def list_videos() -> list[Video]:
    """Return videos in ``VIDEO_DIR``, newest first."""
    if not settings.video_dir.is_dir():
        return []
    videos = [
        Video(name=p.name, size=p.stat().st_size, mtime=p.stat().st_mtime)
        for p in settings.video_dir.iterdir()
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
    ]
    videos.sort(key=lambda v: v.mtime, reverse=True)
    return videos


def video_path(name: str) -> Path | None:
    """Resolve a video filename to a path inside ``VIDEO_DIR``, or ``None`` if it
    escapes the directory or does not exist."""
    candidate = (settings.video_dir / name).resolve()
    base = settings.video_dir.resolve()
    if base not in candidate.parents or not candidate.is_file():
        return None
    return candidate


def thumb_path(name: str) -> Path:
    """Path to the cached thumbnail for ``name`` (may not exist yet)."""
    return settings.thumb_dir / f"{name}.jpg"


def generate_thumbnail(name: str) -> Path | None:
    """Grab a frame ~10% into the video and cache it as a JPEG.

    Returns the thumbnail path on success, ``None`` if the source is missing or
    ffmpeg fails.
    """
    source = video_path(name)
    if source is None:
        return None

    dest = thumb_path(name)
    if dest.is_file():
        return dest

    settings.thumb_dir.mkdir(parents=True, exist_ok=True)

    duration = _probe_duration(source)
    seek = duration * 0.1 if duration else 1.0

    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            f"{seek:.2f}",
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-vf",
            "scale=480:-2",
            str(dest),
        ],
        capture_output=True,
    )
    if result.returncode != 0 or not dest.is_file():
        return None
    return dest


def sweep_thumbnails() -> None:
    """Backfill thumbnails for videos already present at startup."""
    for video in list_videos():
        if not thumb_path(video.name).is_file():
            generate_thumbnail(video.name)


def _probe_duration(source: Path) -> float | None:
    """Return the video duration in seconds via ffprobe, or ``None`` on failure."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(source),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None
