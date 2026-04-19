from __future__ import annotations

from typing import Any

from .database import Database


def status_payload(db: Database) -> dict[str, Any]:
    latest_run = db.latest_run()
    counts = db.counts_by_status()
    if latest_run is None:
        return {
            "run": None,
            "files": counts,
            "message": "No indexing run has been recorded yet.",
        }

    return {
        "run": {
            "id": latest_run["id"],
            "status": latest_run["status"],
            "phase": latest_run["phase"],
            "message": latest_run["message"],
            "started_at": latest_run["started_at"],
            "finished_at": latest_run["finished_at"],
            "total_files": latest_run["total_files"],
            "processed_files": latest_run["processed_files"],
            "new_files": latest_run["new_files"],
            "updated_files": latest_run["updated_files"],
            "unchanged_files": latest_run["unchanged_files"],
            "skipped_files": latest_run["skipped_files"],
            "error_files": latest_run["error_files"],
            "deleted_files": latest_run["deleted_files"],
            "percent_complete": latest_run["percent_complete"],
            "elapsed_seconds": latest_run["elapsed_seconds"],
            "eta_seconds": latest_run["eta_seconds"],
            "last_path": latest_run["last_path"],
        },
        "files": counts,
    }


def error_payload(db: Database, limit: int) -> dict[str, Any]:
    rows = db.list_error_files(limit=limit)
    return {
        "count": len(rows),
        "results": [
            {
                "path": row["path"],
                "source_root": row["source_root"],
                "relative_path": row["relative_path"],
                "basename": row["basename"],
                "file_type": row["file_type"],
                "size_bytes": row["size_bytes"],
                "mtime_ns": row["mtime_ns"],
                "error_message": row["error_message"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ],
    }
