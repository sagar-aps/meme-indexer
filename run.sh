#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
"$DIR/.venv/bin/python" -m meme_indexer "$@"
