# meme-indexer

Persistent host-side meme indexing for later OpenClaw integration.

The project scans one or more filesystem roots, extracts OCR text from images and the first frame of videos, stores metadata in SQLite, and exposes a CLI for indexing, search, status, error inspection, and MCP serving.

## Features

- Multiple configurable meme source paths via `config.toml`
- Automatic SQLite schema creation from Python
- Incremental indexing based on path, file size, and modified time
- Deleted-file detection by marking stale records as `deleted`
- OCR text stored as UTF-8
- SQLite FTS5 search with fallback substring search
- Durable run history with progress, ETA, and completion percentage
- Live terminal progress for indexing via `tqdm`
- Stable `run.sh` wrapper that always uses the local `.venv`

## Project layout

- `config.toml`: checked-in runtime configuration
- `run.sh`: stable entrypoint for external callers
- `meme_indexer/`: Python package
- `state/`: runtime SQLite database and transient extraction files

## System dependencies

This project requires:

- `tesseract-ocr`
- `ffmpeg`

On Ubuntu/Debian:

```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr ffmpeg
```

English OCR uses Tesseract's default `eng` model. If you add more OCR languages later, install the matching Tesseract language packages and update `ocr_language` in `config.toml`.

## Python environment

Create the local virtual environment and install the package:

```bash
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -e .
```

If `python3 -m venv` is unavailable on the host, install `python3-venv` with apt. As a fallback, you can bootstrap `virtualenv` in user space and create the same local `.venv` with:

```bash
python3 -m pip install --user --break-system-packages virtualenv
python3 -m virtualenv .venv
./.venv/bin/pip install -e .
```

## Usage

Use the wrapper script so callers do not need to activate the virtual environment:

```bash
./run.sh index
./run.sh search "obama"
./run.sh status
./run.sh errors
```

Optional flags:

```bash
./run.sh index --config /path/to/config.toml
./run.sh search "you get what you deserve" --limit 20
./run.sh status --format text
./run.sh errors --limit 10 --format text
```

## MCP server

The project includes a FastMCP server in `meme_indexer.mcp_server` that exposes the indexed meme library to MCP clients without installing anything into OpenClaw.

Run it with the project venv:

```bash
cd /home/sagar_ap/homelab/meme-indexer
./.venv/bin/python -m meme_indexer.mcp_server
```

Exposed MCP tools:

- `search_memes(query: str, limit: int = 5)`
- `meme_index_status()`
- `meme_index_errors(limit: int = 20)`
- `trigger_index()`

## Docker deployment

The repo also includes a persistent Docker deployment for the MCP server.

Build and start it:

```bash
cd /home/sagar_ap/homelab/meme-indexer
docker compose up -d --build
```

Inspect logs:

```bash
docker compose logs -f meme-indexer-mcp
```

The container runs FastMCP over `streamable-http` on port `8000` and mounts:

- `./config.toml` at `/app/config.toml`
- `./state` at `/app/state`
- `/mnt/nas-data/homes/sagar_ap/Memes` read-only at the same path in-container

Stop it without removing state:

```bash
docker compose stop meme-indexer-mcp
```

## Search output

`search` returns JSON by default. Each result includes:

- absolute file path
- file type
- basename
- OCR text snippet
- metadata such as dimensions, duration, timestamps, and status

## Indexing behavior

- New and modified files are processed
- Unchanged files are skipped safely
- Missing files from configured roots are marked `deleted`
- Files that exceed the configured OCR limit are marked `skipped`
- Video OCR in v1 uses the first extracted frame, controlled by `video_frame_offset_seconds`

## Status output

`status` reads the most recent index run and reports:

- run state
- total files
- processed count
- percent complete
- elapsed time
- estimated remaining time
- counts for indexed, skipped, errors, and deleted records

## Error inspection

`errors` lists files that failed OCR or media probing during indexing so you can inspect bad media without digging through logs.
