from __future__ import annotations

from dataclasses import asdict
import logging
import threading
from typing import Any

from fastmcp import FastMCP

from .config import default_config_path, load_config
from .database import Database
from .indexer import run_index
from .search import search_records
from .status import error_payload, status_payload

LOGGER = logging.getLogger(__name__)
MCP = FastMCP("meme-indexer")
_INDEX_LOCK = threading.Lock()


def _open_db() -> Database:
    config = load_config(default_config_path())
    db = Database(config.db_path)
    db.initialize()
    return db


@MCP.tool
def search_memes(query: str, limit: int = 5) -> dict[str, Any]:
    """Search indexed memes and return compact structured results."""
    db = _open_db()
    try:
        payload = search_records(db, query=query, limit=limit)
        return {
            "query": payload["query"],
            "count": payload["count"],
            "results": [
                {
                    "path": row["path"],
                    "basename": row["basename"],
                    "score": row["score"],
                    "snippet": row["snippet"],
                    "status": row["status"],
                }
                for row in payload["results"]
            ],
        }
    finally:
        db.close()


@MCP.tool
def meme_index_status() -> dict[str, Any]:
    """Return the latest durable indexing status."""
    db = _open_db()
    try:
        return status_payload(db)
    finally:
        db.close()


@MCP.tool
def meme_index_errors(limit: int = 20) -> dict[str, Any]:
    """List files that failed indexing."""
    db = _open_db()
    try:
        return error_payload(db, limit=limit)
    finally:
        db.close()


@MCP.tool
def trigger_index() -> dict[str, Any]:
    """Run an in-process indexing pass using the existing meme-indexer code."""
    if not _INDEX_LOCK.acquire(blocking=False):
        return {
            "started": False,
            "status": "busy",
            "message": "An indexing run is already in progress in this server process.",
        }

    try:
        config = load_config(default_config_path())
        db = Database(config.db_path)
        db.initialize()
        try:
            summary = run_index(config, db, progress_reporter=None)
            return {
                "started": True,
                "status": summary.status,
                "summary": asdict(summary),
            }
        finally:
            db.close()
    finally:
        _INDEX_LOCK.release()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    MCP.run()


if __name__ == "__main__":
    main()
