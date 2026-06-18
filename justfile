# videodl dev tasks. Run `just` to list recipes.

# Local video dir for development (override: just dev video_dir=/some/path)
video_dir := justfile_directory() + "/data/videos"

_default:
    @just --list

# Install/sync all dependencies (incl. dev) from the lockfile
install:
    uv sync

# Run the dev server with autoreload
dev:
    VIDEO_DIR={{video_dir}} uv run uvicorn app.main:app --reload --port 8080

# Strict type checking — must pass clean
typecheck:
    uv run mypy app

# Everything CI runs
check: typecheck

# Refresh yt-dlp (extractors rot fast), then re-lock
update-ytdlp:
    uv lock --upgrade-package yt-dlp

# Build and run the container stack
up:
    docker compose up --build

# Stop the container stack
down:
    docker compose down

# Build the image only
build:
    docker compose build

# Pull the latest published image and (re)start on the server
deploy:
    docker compose -f compose.prod.yaml pull
    docker compose -f compose.prod.yaml up -d
