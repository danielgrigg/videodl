"""FastAPI app: dashboard, downloads, SSE progress, and range-enabled playback."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

from . import jobs, media

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Backfill thumbnails for videos already on disk, off the event loop.
    await asyncio.to_thread(media.sweep_thumbnails)
    yield


app = FastAPI(title="videodl", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {"videos": media.list_videos(), "jobs": list(jobs.jobs.values())},
    )


@app.post("/download")
async def download(url: str = Form(...)) -> RedirectResponse:
    url = url.strip()
    if url:
        jobs.submit(url)
    return RedirectResponse("/", status_code=303)


@app.get("/events")
async def events(request: Request) -> EventSourceResponse:
    async def stream() -> AsyncIterator[dict[str, str]]:
        while True:
            if await request.is_disconnected():
                break
            payload = [job.model_dump(mode="json") for job in jobs.jobs.values()]
            yield {"event": "jobs", "data": json.dumps(payload)}
            await asyncio.sleep(1.0)

    return EventSourceResponse(stream())


@app.get("/videos/{name}")
async def serve_video(name: str) -> FileResponse:
    path = media.video_path(name)
    if path is None:
        raise HTTPException(status_code=404)
    return FileResponse(path)  # Starlette honours HTTP Range for free


@app.get("/thumb/{name}")
async def serve_thumb(name: str) -> FileResponse:
    path = media.thumb_path(name)
    if not path.is_file():
        generated = await asyncio.to_thread(media.generate_thumbnail, name)
        if generated is None:
            raise HTTPException(status_code=404)
        path = generated
    return FileResponse(path, media_type="image/jpeg")
