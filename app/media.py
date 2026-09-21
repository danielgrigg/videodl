"""Filesystem scan and ffmpeg thumbnail generation.

The filesystem is the source of truth: a video is anything under ``VIDEO_DIR`` with a
known extension, at any depth, outside hidden directories. Thumbnails are cached in
``.thumbs/`` alongside the videos, mirroring the folder structure.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from itertools import groupby
from pathlib import Path, PurePosixPath

from .config import settings

VIDEO_EXTENSIONS = frozenset({".mp4", ".mkv", ".webm", ".mov", ".m4v"})


@dataclass(frozen=True)
class Video:
    path: str  # POSIX path relative to VIDEO_DIR, used as the id in URLs
    size: int  # bytes
    mtime: float

    @property
    def name(self) -> str:
        return PurePosixPath(self.path).name

    @property
    def folder(self) -> str:
        parent = PurePosixPath(self.path).parent
        return "" if parent == PurePosixPath(".") else str(parent)


def list_videos() -> list[Video]:
    """Return videos anywhere under ``VIDEO_DIR``, newest first."""
    if not settings.video_dir.is_dir():
        return []
    videos = [
        Video(
            path=p.relative_to(settings.video_dir).as_posix(),
            size=p.stat().st_size,
            mtime=p.stat().st_mtime,
        )
        for p in settings.video_dir.rglob("*")
        if p.is_file()
        and p.suffix.lower() in VIDEO_EXTENSIONS
        and not _is_hidden(p.relative_to(settings.video_dir))
    ]
    videos.sort(key=lambda v: v.mtime, reverse=True)
    return videos


def group_by_folder(videos: list[Video]) -> list[tuple[str, list[Video]]]:
    """Group videos by folder: top-level first, then folders alphabetically, each
    keeping the newest-first order."""
    ordered = sorted(videos, key=lambda v: (v.folder != "", v.folder, -v.mtime))
    return [(folder, list(group)) for folder, group in groupby(ordered, key=lambda v: v.folder)]


def _is_hidden(rel: Path) -> bool:
    return any(part.startswith(".") for part in rel.parts)


def video_path(path: str) -> Path | None:
    """Resolve a relative video path to a file inside ``VIDEO_DIR``, or ``None`` if
    it escapes the directory or does not exist."""
    candidate = (settings.video_dir / path).resolve()
    base = settings.video_dir.resolve()
    if base not in candidate.parents or not candidate.is_file():
        return None
    return candidate


def thumb_path(path: str) -> Path:
    """Path to the cached thumbnail for ``path`` (may not exist yet)."""
    return settings.thumb_dir / f"{path}.jpg"


def generate_thumbnail(path: str) -> Path | None:
    """Grab a frame ~10% into the video and cache it as a JPEG.

    Returns the thumbnail path on success, ``None`` if the source is missing or
    ffmpeg fails.
    """
    source = video_path(path)
    if source is None:
        return None

    dest = thumb_path(path)
    if dest.is_file():
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)

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
        if not thumb_path(video.path).is_file():
            generate_thumbnail(video.path)


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
