"""Typed application settings, read from the environment via pydantic-settings."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Where downloaded videos live. The container mounts the host storage path here.
    video_dir: Path = Path("/data/videos")
    # yt-dlp blocks, so downloads run on a bounded thread pool. Keep a pasted
    # playlist from saturating the box.
    max_concurrent: int = 2

    @property
    def thumb_dir(self) -> Path:
        """Thumbnails cache, kept as a sibling of the videos to stay out of the grid."""
        return self.video_dir / ".thumbs"


settings = Settings()
