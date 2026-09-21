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

## Deploy

CI publishes the image to GitHub Container Registry on every push to `main` (tagged
`latest` + the short commit SHA) and on `v*` tags (semver tags):

```
ghcr.io/danielgrigg/videodl:latest
```

**This repo does not deploy itself.** videodl runs on the enclave server as a service in
the [griggx-gitops](https://github.com/danielgrigg/griggx-gitops) compose stack
(`nodes/enclave/compose.yml`): portless behind traefik at `https://video.griggx.com`,
as `user: "1000:1000"`, with `/srv/data0/studio/videos` mounted at `/data/videos`.

To roll out a new build, from the gitops checkout:

```sh
just enclave-deploy videodl   # git pull on the host, then compose pull && up -d
just enclave-logs videodl
just enclave-ps
```

The package is **private** (it inherits the repo's visibility), so the host must
authenticate to GHCR once with a personal access token that has `read:packages`:

```sh
echo "$GHCR_PAT" | docker login ghcr.io -u danielgrigg --password-stdin
```

The container process must have **read-write** on the mounted video directory
(downloads write there, and `.thumbs/` is created inside it). The `1000:1000` user
matches the other media services that share that tree.

### Local Docker (build from source)

```sh
cp .env.example .env
just up            # docker compose up --build, serves on :8080
```

## Configuration

| Env var              | Default                      | Purpose                                        |
|----------------------|------------------------------|------------------------------------------------|
| `VIDEO_STORAGE_PATH` | `/srv/data0/studio/videos`   | Host dir mounted into the container (local `just up` only; enclave sets this in gitops). |
| `VIDEO_DIR`          | `/data/videos`               | Path inside the container where videos live.   |
| `MAX_CONCURRENT`     | `2`                          | Max simultaneous yt-dlp downloads.             |

## Maintenance

yt-dlp extractors rot fast. A weekly workflow (`refresh-ytdlp.yml`) bumps the pin in
`uv.lock` and republishes the image; do it by hand with:

```sh
just update-ytdlp   # uv lock --upgrade-package yt-dlp — commit the lockfile
```

The image installs with `uv sync --frozen`, so a rebuild alone does not pick up a newer
yt-dlp; the lockfile must change. Then `just enclave-deploy videodl` from gitops.

See `docs/videodl-plan.md` for the full design and architecture invariants.
