from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import logging
import os
import time
from typing import Protocol

from .config import AppConfig
from .database import Database
from .media import DiscoveredFile, classify_path
from .ocr import FileSkipped, OCRResult, ensure_external_dependencies, ocr_image, ocr_video_first_frame

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class IndexSummary:
    run_id: int
    total_files: int
    processed_files: int
    new_files: int
    updated_files: int
    unchanged_files: int
    skipped_files: int
    error_files: int
    deleted_files: int
    status: str


@dataclass(slots=True)
class DiscoveryResult:
    files: list[DiscoveredFile]
    scanned_roots: list[Path]


class ProgressReporter(Protocol):
    def on_discovery_complete(self, total_files: int) -> None: ...
    def on_progress(
        self,
        *,
        processed_files: int,
        total_files: int,
        last_path: str,
        eta_seconds: float | None,
    ) -> None: ...


def _discover_files(config: AppConfig) -> DiscoveryResult:
    discovered: list[DiscoveredFile] = []
    scanned_roots: list[Path] = []
    for source_root in config.source_paths:
        if not source_root.exists():
            LOGGER.warning("Source path does not exist: %s", source_root)
            continue
        scanned_roots.append(source_root)
        for root, dirs, files in os.walk(source_root):
            dirs[:] = [dirname for dirname in dirs if dirname != "@eaDir"]
            root_path = Path(root)
            for filename in files:
                path = (root_path / filename).resolve()
                file_type = classify_path(path)
                if file_type is None:
                    continue
                stat = path.stat()
                discovered.append(
                    DiscoveredFile(
                        path=path,
                        source_root=source_root,
                        relative_path=str(path.relative_to(source_root)),
                        basename=path.name,
                        file_type=file_type,
                        size_bytes=stat.st_size,
                        mtime_ns=stat.st_mtime_ns,
                    )
                )
    discovered.sort(key=lambda item: str(item.path))
    return DiscoveryResult(files=discovered, scanned_roots=scanned_roots)


def _run_ocr(file: DiscoveredFile, config: AppConfig) -> OCRResult:
    if file.file_type == "image":
        return ocr_image(file.path, config)
    if file.file_type == "video":
        return ocr_video_first_frame(file.path, config)
    raise ValueError(f"Unsupported file type: {file.file_type}")


def run_index(
    config: AppConfig,
    db: Database,
    progress_reporter: ProgressReporter | None = None,
) -> IndexSummary:
    ensure_external_dependencies()
    run_id = db.start_run(str(config.config_path))
    started_at = time.monotonic()
    summary = IndexSummary(
        run_id=run_id,
        total_files=0,
        processed_files=0,
        new_files=0,
        updated_files=0,
        unchanged_files=0,
        skipped_files=0,
        error_files=0,
        deleted_files=0,
        status="running",
    )

    try:
        discovery = _discover_files(config)
        discovered = discovery.files
        summary.total_files = len(discovered)
        if progress_reporter is not None:
            progress_reporter.on_discovery_complete(summary.total_files)
        db.update_run(
            run_id,
            phase="indexing",
            total_files=summary.total_files,
            message="Indexing discovered files",
        )

        seen_paths = set()
        for file in discovered:
            seen_paths.add(str(file.path))
            existing = db.fetch_file_by_path(str(file.path))
            unchanged = (
                existing is not None
                and existing["mtime_ns"] == file.mtime_ns
                and existing["size_bytes"] == file.size_bytes
                and existing["status"] in {"indexed", "skipped", "error"}
                and existing["deleted_at"] is None
            )

            if unchanged:
                summary.unchanged_files += 1
                summary.processed_files += 1
                _update_progress(
                    db,
                    run_id,
                    summary,
                    started_at,
                    str(file.path),
                    progress_reporter,
                )
                continue

            is_new = existing is None or existing["deleted_at"] is not None
            file_started_at = time.monotonic()
            discovered_at = _utc_now()
            try:
                ocr_result = _run_ocr(file, config)
                duration_seconds = time.monotonic() - file_started_at
                db.upsert_file(
                    path=str(file.path),
                    source_root=str(file.source_root),
                    relative_path=file.relative_path,
                    basename=file.basename,
                    file_type=file.file_type,
                    size_bytes=file.size_bytes,
                    mtime_ns=file.mtime_ns,
                    status="indexed",
                    skip_reason=None,
                    error_message=None,
                    ocr_text=ocr_result.text,
                    ocr_language=config.ocr_language,
                    media_width=ocr_result.width,
                    media_height=ocr_result.height,
                    video_duration_seconds=ocr_result.duration_seconds,
                    discovered_at=discovered_at,
                    indexed_at=discovered_at,
                    deleted_at=None,
                    duration_seconds=duration_seconds,
                )
                if is_new:
                    summary.new_files += 1
                else:
                    summary.updated_files += 1
            except FileSkipped as exc:
                duration_seconds = time.monotonic() - file_started_at
                db.upsert_file(
                    path=str(file.path),
                    source_root=str(file.source_root),
                    relative_path=file.relative_path,
                    basename=file.basename,
                    file_type=file.file_type,
                    size_bytes=file.size_bytes,
                    mtime_ns=file.mtime_ns,
                    status="skipped",
                    skip_reason=str(exc),
                    error_message=None,
                    ocr_text=None,
                    ocr_language=config.ocr_language,
                    media_width=None,
                    media_height=None,
                    video_duration_seconds=None,
                    discovered_at=discovered_at,
                    indexed_at=None,
                    deleted_at=None,
                    duration_seconds=duration_seconds,
                )
                summary.skipped_files += 1
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Failed to process %s", file.path)
                duration_seconds = time.monotonic() - file_started_at
                db.upsert_file(
                    path=str(file.path),
                    source_root=str(file.source_root),
                    relative_path=file.relative_path,
                    basename=file.basename,
                    file_type=file.file_type,
                    size_bytes=file.size_bytes,
                    mtime_ns=file.mtime_ns,
                    status="error",
                    skip_reason=None,
                    error_message=str(exc),
                    ocr_text=None,
                    ocr_language=config.ocr_language,
                    media_width=None,
                    media_height=None,
                    video_duration_seconds=None,
                    discovered_at=discovered_at,
                    indexed_at=None,
                    deleted_at=None,
                    duration_seconds=duration_seconds,
                )
                summary.error_files += 1

            summary.processed_files += 1
            _update_progress(db, run_id, summary, started_at, str(file.path), progress_reporter)

        deleted_at = _utc_now()
        if discovery.scanned_roots:
            for stale_row in db.active_files_for_roots([str(path) for path in discovery.scanned_roots]):
                if stale_row["path"] in seen_paths:
                    continue
                db.mark_deleted(stale_row["path"], deleted_at)
                summary.deleted_files += 1
                _update_progress(db, run_id, summary, started_at, stale_row["path"], progress_reporter)

        summary.status = "completed"
        db.update_run(
            run_id,
            deleted_files=summary.deleted_files,
            message="Indexing completed",
        )
        db.finish_run(run_id, "completed", "Indexing completed")
        return summary
    except Exception as exc:  # noqa: BLE001
        summary.status = "failed"
        db.finish_run(run_id, "failed", str(exc))
        raise


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _update_progress(
    db: Database,
    run_id: int,
    summary: IndexSummary,
    started_at: float,
    last_path: str,
    progress_reporter: ProgressReporter | None = None,
) -> None:
    elapsed_seconds = time.monotonic() - started_at
    percent_complete = 0.0
    eta_seconds = None
    if summary.total_files > 0:
        percent_complete = min(summary.processed_files / summary.total_files * 100.0, 100.0)
    if summary.processed_files > 0 and summary.total_files > summary.processed_files:
        rate = elapsed_seconds / summary.processed_files
        eta_seconds = max(rate * (summary.total_files - summary.processed_files), 0.0)

    db.update_run(
        run_id,
        total_files=summary.total_files,
        processed_files=summary.processed_files,
        new_files=summary.new_files,
        updated_files=summary.updated_files,
        unchanged_files=summary.unchanged_files,
        skipped_files=summary.skipped_files,
        error_files=summary.error_files,
        deleted_files=summary.deleted_files,
        percent_complete=percent_complete,
        elapsed_seconds=elapsed_seconds,
        eta_seconds=eta_seconds,
        last_path=last_path,
    )
    if progress_reporter is not None:
        progress_reporter.on_progress(
            processed_files=summary.processed_files,
            total_files=summary.total_files,
            last_path=last_path,
            eta_seconds=eta_seconds,
        )
