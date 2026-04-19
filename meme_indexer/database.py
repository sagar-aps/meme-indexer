from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path
import sqlite3
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass(slots=True)
class FileRecord:
    id: int
    path: str
    source_root: str
    relative_path: str
    basename: str
    file_type: str
    size_bytes: int
    mtime_ns: int
    status: str
    ocr_text: str | None


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA synchronous = NORMAL")

    def close(self) -> None:
        self.connection.close()

    def initialize(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY,
                path TEXT NOT NULL UNIQUE,
                source_root TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                basename TEXT NOT NULL,
                file_type TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                sha256 TEXT,
                status TEXT NOT NULL,
                skip_reason TEXT,
                error_message TEXT,
                ocr_text TEXT,
                ocr_language TEXT,
                media_width INTEGER,
                media_height INTEGER,
                video_duration_seconds REAL,
                discovered_at TEXT NOT NULL,
                indexed_at TEXT,
                deleted_at TEXT,
                duration_seconds REAL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            );

            CREATE INDEX IF NOT EXISTS idx_files_source_root ON files(source_root);
            CREATE INDEX IF NOT EXISTS idx_files_status ON files(status);
            CREATE INDEX IF NOT EXISTS idx_files_mtime_ns ON files(mtime_ns);

            CREATE VIRTUAL TABLE IF NOT EXISTS meme_fts USING fts5(
                basename,
                path,
                ocr_text
            );

            CREATE TABLE IF NOT EXISTS index_runs (
                id INTEGER PRIMARY KEY,
                config_path TEXT NOT NULL,
                status TEXT NOT NULL,
                phase TEXT NOT NULL,
                message TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                total_files INTEGER NOT NULL DEFAULT 0,
                processed_files INTEGER NOT NULL DEFAULT 0,
                new_files INTEGER NOT NULL DEFAULT 0,
                updated_files INTEGER NOT NULL DEFAULT 0,
                unchanged_files INTEGER NOT NULL DEFAULT 0,
                skipped_files INTEGER NOT NULL DEFAULT 0,
                error_files INTEGER NOT NULL DEFAULT 0,
                deleted_files INTEGER NOT NULL DEFAULT 0,
                percent_complete REAL NOT NULL DEFAULT 0,
                elapsed_seconds REAL NOT NULL DEFAULT 0,
                eta_seconds REAL,
                last_path TEXT
            );
            """
        )
        self.connection.commit()

    def fetch_file_by_path(self, path: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM files WHERE path = ?",
            (path,),
        ).fetchone()

    def upsert_file(
        self,
        *,
        path: str,
        source_root: str,
        relative_path: str,
        basename: str,
        file_type: str,
        size_bytes: int,
        mtime_ns: int,
        status: str,
        discovered_at: str,
        indexed_at: str | None,
        deleted_at: str | None,
        duration_seconds: float | None,
        skip_reason: str | None = None,
        error_message: str | None = None,
        ocr_text: str | None = None,
        ocr_language: str | None = None,
        media_width: int | None = None,
        media_height: int | None = None,
        video_duration_seconds: float | None = None,
    ) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO files (
                path, source_root, relative_path, basename, file_type, size_bytes,
                mtime_ns, status, skip_reason, error_message, ocr_text, ocr_language,
                media_width, media_height, video_duration_seconds, discovered_at,
                indexed_at, deleted_at, duration_seconds, updated_at
            ) VALUES (
                :path, :source_root, :relative_path, :basename, :file_type, :size_bytes,
                :mtime_ns, :status, :skip_reason, :error_message, :ocr_text, :ocr_language,
                :media_width, :media_height, :video_duration_seconds, :discovered_at,
                :indexed_at, :deleted_at, :duration_seconds, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            )
            ON CONFLICT(path) DO UPDATE SET
                source_root = excluded.source_root,
                relative_path = excluded.relative_path,
                basename = excluded.basename,
                file_type = excluded.file_type,
                size_bytes = excluded.size_bytes,
                mtime_ns = excluded.mtime_ns,
                status = excluded.status,
                skip_reason = excluded.skip_reason,
                error_message = excluded.error_message,
                ocr_text = excluded.ocr_text,
                ocr_language = excluded.ocr_language,
                media_width = excluded.media_width,
                media_height = excluded.media_height,
                video_duration_seconds = excluded.video_duration_seconds,
                discovered_at = excluded.discovered_at,
                indexed_at = excluded.indexed_at,
                deleted_at = excluded.deleted_at,
                duration_seconds = excluded.duration_seconds,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            """,
            {
                "path": path,
                "source_root": source_root,
                "relative_path": relative_path,
                "basename": basename,
                "file_type": file_type,
                "size_bytes": size_bytes,
                "mtime_ns": mtime_ns,
                "status": status,
                "skip_reason": skip_reason,
                "error_message": error_message,
                "ocr_text": ocr_text,
                "ocr_language": ocr_language,
                "media_width": media_width,
                "media_height": media_height,
                "video_duration_seconds": video_duration_seconds,
                "discovered_at": discovered_at,
                "indexed_at": indexed_at,
                "deleted_at": deleted_at,
                "duration_seconds": duration_seconds,
            },
        )
        row = self.fetch_file_by_path(path)
        if row is None:
            raise RuntimeError(f"Failed to upsert file record for {path}")
        self.connection.execute(
            "DELETE FROM meme_fts WHERE rowid = ?",
            (row["id"],),
        )
        if status != "deleted":
            self.connection.execute(
                "INSERT INTO meme_fts(rowid, basename, path, ocr_text) VALUES (?, ?, ?, ?)",
                (row["id"], basename, path, ocr_text or ""),
            )
        self.connection.commit()
        return int(row["id"])

    def mark_deleted(self, path: str, deleted_at: str) -> None:
        row = self.fetch_file_by_path(path)
        if row is None:
            return
        self.connection.execute(
            """
            UPDATE files
            SET status = 'deleted',
                deleted_at = ?,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE path = ?
            """,
            (deleted_at, path),
        )
        self.connection.execute("DELETE FROM meme_fts WHERE rowid = ?", (row["id"],))
        self.connection.commit()

    def start_run(self, config_path: str) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO index_runs (config_path, status, phase, started_at)
            VALUES (?, 'running', 'scanning', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            """,
            (config_path,),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def update_run(self, run_id: int, **fields: Any) -> None:
        if not fields:
            return
        assignments = ", ".join(f"{key} = :{key}" for key in fields)
        fields["run_id"] = run_id
        self.connection.execute(
            f"UPDATE index_runs SET {assignments} WHERE id = :run_id",
            fields,
        )
        self.connection.commit()

    def finish_run(self, run_id: int, status: str, message: str | None = None) -> None:
        self.connection.execute(
            """
            UPDATE index_runs
            SET status = ?,
                phase = 'finished',
                message = COALESCE(?, message),
                finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ?
            """,
            (status, message, run_id),
        )
        self.connection.commit()

    def latest_run(self) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM index_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()

    def active_files_for_roots(self, source_roots: list[str]) -> list[sqlite3.Row]:
        placeholders = ", ".join("?" for _ in source_roots)
        query = (
            f"SELECT * FROM files WHERE source_root IN ({placeholders}) AND status != 'deleted'"
        )
        return list(self.connection.execute(query, source_roots))

    def counts_by_status(self) -> dict[str, int]:
        rows = self.connection.execute(
            "SELECT status, COUNT(*) AS count FROM files GROUP BY status"
        ).fetchall()
        return {row["status"]: int(row["count"]) for row in rows}

    def list_error_files(self, limit: int) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                """
                SELECT
                    path,
                    source_root,
                    relative_path,
                    basename,
                    file_type,
                    size_bytes,
                    mtime_ns,
                    error_message,
                    updated_at
                FROM files
                WHERE status = 'error'
                ORDER BY basename ASC
                LIMIT ?
                """,
                (limit,),
            )
        )

    def search(self, query: str, limit: int) -> list[sqlite3.Row]:
        tokens = [token for token in "".join(ch if ch.isalnum() else " " for ch in query).lower().split() if token]
        params: dict[str, Any] = {"limit": limit}
        if tokens:
            match_query = " AND ".join(f"{token}*" for token in tokens)
            params["match_query"] = match_query
            params["like_query"] = f"%{query.lower()}%"
            return list(
                self.connection.execute(
                    """
                    WITH ranked AS (
                        SELECT
                            files.*,
                            bm25(meme_fts) AS score,
                            snippet(meme_fts, 2, '[', ']', '...', 12) AS snippet
                        FROM meme_fts
                        JOIN files ON files.id = meme_fts.rowid
                        WHERE meme_fts MATCH :match_query
                          AND files.status != 'deleted'
                    ),
                    fallback AS (
                        SELECT
                            files.*,
                            1e9 AS score,
                            substr(COALESCE(files.ocr_text, ''), 1, 240) AS snippet
                        FROM files
                        WHERE files.status != 'deleted'
                          AND files.id NOT IN (SELECT id FROM ranked)
                          AND (
                              lower(files.ocr_text) LIKE :like_query OR
                              lower(files.path) LIKE :like_query OR
                              lower(files.basename) LIKE :like_query
                          )
                    )
                    SELECT * FROM (
                        SELECT * FROM ranked
                        UNION ALL
                        SELECT * FROM fallback
                    )
                    ORDER BY score ASC, basename ASC
                    LIMIT :limit
                    """,
                    params,
                )
            )
        params["like_query"] = f"%{query.lower()}%"
        return list(
            self.connection.execute(
                """
                SELECT
                    files.*,
                    1e9 AS score,
                    substr(COALESCE(files.ocr_text, ''), 1, 240) AS snippet
                FROM files
                WHERE files.status != 'deleted'
                  AND (
                      lower(files.ocr_text) LIKE :like_query OR
                      lower(files.path) LIKE :like_query OR
                      lower(files.basename) LIKE :like_query
                  )
                ORDER BY basename ASC
                LIMIT :limit
                """,
                params,
            )
        )
