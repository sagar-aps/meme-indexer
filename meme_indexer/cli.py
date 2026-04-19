from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import logging
from pathlib import Path
from typing import Any

from tqdm import tqdm

from .config import load_config
from .database import Database
from .indexer import run_index
from .search import search_records
from .status import error_payload, status_payload


def _build_parser() -> argparse.ArgumentParser:
    default_config = Path(__file__).resolve().parent.parent / "config.toml"
    parser = argparse.ArgumentParser(prog="meme_indexer")
    parser.add_argument(
        "--config",
        default=str(default_config),
        help="Path to config.toml",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("index", help="Index configured meme libraries")

    search_parser = subparsers.add_parser("search", help="Search indexed memes")
    search_parser.add_argument("query", help="Query text")
    search_parser.add_argument("--limit", type=int, default=10, help="Maximum results")

    status_parser = subparsers.add_parser("status", help="Show index status")
    status_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="json",
        help="Output format",
    )

    errors_parser = subparsers.add_parser("errors", help="List files that failed during indexing")
    errors_parser.add_argument("--limit", type=int, default=20, help="Maximum results")
    errors_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="json",
        help="Output format",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    config = load_config(args.config)
    db = Database(config.db_path)
    db.initialize()

    try:
        try:
            if args.command == "index":
                reporter = TqdmProgressReporter()
                try:
                    summary = run_index(config, db, progress_reporter=reporter)
                finally:
                    reporter.close()
                print(json.dumps(asdict(summary), indent=2, sort_keys=True))
                return 0 if summary.status == "completed" else 1
            if args.command == "search":
                print(json.dumps(search_records(db, args.query, args.limit), indent=2, ensure_ascii=False))
                return 0
            if args.command == "status":
                payload = status_payload(db)
                if args.format == "text":
                    print(_format_status_text(payload))
                else:
                    print(json.dumps(payload, indent=2, ensure_ascii=False))
                return 0
            if args.command == "errors":
                payload = error_payload(db, limit=args.limit)
                if args.format == "text":
                    print(_format_errors_text(payload))
                else:
                    print(json.dumps(payload, indent=2, ensure_ascii=False))
                return 0
            parser.error(f"Unknown command: {args.command}")
            return 2
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).error("%s", exc)
            return 1
    finally:
        db.close()


def _format_status_text(payload: dict[str, Any]) -> str:
    run = payload.get("run")
    if run is None:
        return "No indexing run has been recorded yet."
    lines = [
        f"run_id: {run['id']}",
        f"status: {run['status']}",
        f"phase: {run['phase']}",
        f"processed: {run['processed_files']}/{run['total_files']}",
        f"percent_complete: {run['percent_complete']:.2f}",
        f"elapsed_seconds: {run['elapsed_seconds']:.1f}",
        f"eta_seconds: {run['eta_seconds'] if run['eta_seconds'] is not None else 'n/a'}",
        f"last_path: {run['last_path'] or 'n/a'}",
        f"file_counts: {payload.get('files', {})}",
    ]
    return "\n".join(lines)


def _format_errors_text(payload: dict[str, Any]) -> str:
    lines = [f"count: {payload['count']}"]
    for row in payload["results"]:
        lines.append(
            " | ".join(
                [
                    row["basename"],
                    row["file_type"],
                    row["path"],
                    row["error_message"] or "unknown error",
                ]
            )
        )
    return "\n".join(lines)


class TqdmProgressReporter:
    def __init__(self) -> None:
        self._bar: tqdm | None = None
        self._last_processed = 0

    def on_discovery_complete(self, total_files: int) -> None:
        self._bar = tqdm(
            total=total_files,
            unit="file",
            dynamic_ncols=True,
            desc="Indexing",
        )

    def on_progress(
        self,
        *,
        processed_files: int,
        total_files: int,
        last_path: str,
        eta_seconds: float | None,
    ) -> None:
        if self._bar is None:
            return
        delta = processed_files - self._last_processed
        if delta > 0:
            self._bar.update(delta)
            self._last_processed = processed_files
        self._bar.set_postfix_str(
            f"eta={_format_eta(eta_seconds)} file={Path(last_path).name}",
            refresh=False,
        )

    def close(self) -> None:
        if self._bar is not None:
            self._bar.close()
            self._bar = None


def _format_eta(eta_seconds: float | None) -> str:
    if eta_seconds is None:
        return "n/a"
    rounded = max(int(eta_seconds), 0)
    minutes, seconds = divmod(rounded, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{seconds:02d}s"
    return f"{seconds}s"
