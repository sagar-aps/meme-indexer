from __future__ import annotations

from typing import Any

from .database import Database


def search_records(db: Database, query: str, limit: int) -> dict[str, Any]:
    rows = db.search(query, limit=limit)
    return {
        "query": query,
        "count": len(rows),
        "results": [
            {
                "path": row["path"],
                "source_root": row["source_root"],
                "relative_path": row["relative_path"],
                "basename": row["basename"],
                "file_type": row["file_type"],
                "status": row["status"],
                "score": row["score"],
                "snippet": row["snippet"],
                "ocr_text": row["ocr_text"],
                "size_bytes": row["size_bytes"],
                "mtime_ns": row["mtime_ns"],
                "media_width": row["media_width"],
                "media_height": row["media_height"],
                "video_duration_seconds": row["video_duration_seconds"],
                "indexed_at": row["indexed_at"],
            }
            for row in rows
        ],
    }
