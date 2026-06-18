# videodl

A single-container, server-rendered web app for downloading source videos with
[yt-dlp](https://github.com/yt-dlp/yt-dlp) and browsing/playing them. Runs on a home
server and is reached over Tailscale. No auth (the tailnet is the perimeter), no
database (the filesystem is the source of truth).

## Quick start (dev)

```sh
just install      # sync deps from the lockfile
just dev          # uvicorn with autoreload on :8080
just typecheck    # mypy --strict (must pass clean)
```

By default `just dev` writes downloads to `./data/videos`. Override with
`just dev video_dir=/some/path`.

## Deploy (Docker)

CI publishes the image to GitHub Container Registry on every push to `main` (tagged
`latest` + the short commit SHA) and on `v*` tags (semver tags):

```
ghcr.io/danielgrigg/videodl:latest
```

On the **enclave server** you only need `compose.prod.yaml` and a `.env` — it pulls
the image instead of building from source:

```sh
cp .env.example .env
# edit VIDEO_STORAGE_PATH; optionally pin VIDEODL_TAG to a SHA/vX.Y.Z
just deploy        # docker compose -f compose.prod.yaml pull && up -d
```

The package is **private** (it inherits the repo's visibility), so the server must
authenticate to GHCR once with a personal access token that has `read:packages`:

```sh
echo "$GHCR_PAT" | docker login ghcr.io -u danielgrigg --password-stdin
```

The container process must have **read-write** on `VIDEO_STORAGE_PATH` (downloads
write there, and `.thumbs/` is created inside it). Match the container user's UID/GID
to the directory owner, or `chown` it.

### Local Docker (build from source)

```sh
cp .env.example .env
just up            # docker compose up --build, serves on :8080
```

## Configuration

| Env var              | Default                      | Purpose                                        |
|----------------------|------------------------------|------------------------------------------------|
| `VIDEO_STORAGE_PATH` | `/srv/data0/studio/videos`   | Host dir mounted into the container (compose). |
| `VIDEO_DIR`          | `/data/videos`               | Path inside the container where videos live.   |
| `MAX_CONCURRENT`     | `2`                          | Max simultaneous yt-dlp downloads.             |

## Maintenance

yt-dlp extractors rot fast. Refresh periodically and rebuild:

```sh
just update-ytdlp   # uv lock --upgrade-package yt-dlp
just build
```

See `docs/videodl-plan.md` for the full design and architecture invariants.
