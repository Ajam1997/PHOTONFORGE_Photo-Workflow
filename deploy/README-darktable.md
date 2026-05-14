# Darktable Docker Setup

Runs Darktable as a native window via Docker + X11 forwarding. Identical setup on Linux laptops and Windows 11 dev machines.

## Prerequisites

**Windows 11:**
- Docker Desktop (with WSL2 backend)
- Ubuntu WSL2 — run `scripts\darktable-install.bat` to install both

**Linux:**
- Docker + Docker Compose

## Installation (Windows)

Double-click `scripts\darktable-install.bat`. It will:
1. Check Docker Desktop is running
2. Install Ubuntu WSL2 if missing (requires restart)
3. Build the Darktable Docker image

## Running

**Windows — from Ubuntu WSL terminal:**
```bash
cd /mnt/<drive>/PHOTONForge/photo-workflow
docker compose -f deploy/docker-compose.darktable.yml up
```

**Linux:**
```bash
docker compose -f deploy/docker-compose.darktable.yml up
```

Darktable opens as a native window. Close the window to stop the container.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `PHOTOS_DIR` | `~/Pictures` | Host directory mounted as `/photos` inside container |
| `DISPLAY` | `:0` | X11 display (auto-detected on Linux and WSLg) |

Override at runtime:
```bash
PHOTOS_DIR=/mnt/e/Photos docker compose -f deploy/docker-compose.darktable.yml up
```

## Persistence

Darktable's library database and settings are stored in a named Docker volume (`deploy_darktable-config`). They persist across container restarts.

To reset to a clean state:
```bash
docker compose -f deploy/docker-compose.darktable.yml down -v
```

## Linux laptops — GPU acceleration

Uncomment the `devices` block in `docker-compose.darktable.yml` to enable hardware rendering:
```yaml
devices:
  - /dev/dri:/dev/dri
```
