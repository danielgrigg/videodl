FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# pin uv for reproducibility (bump deliberately)
COPY --from=ghcr.io/astral-sh/uv:0.6.13 /uv /uvx /bin/
WORKDIR /app

# deps first for layer caching
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app/ ./app/
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH" \
    VIDEO_DIR=/data/videos \
    MAX_CONCURRENT=2
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
