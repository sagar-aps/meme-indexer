from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass(slots=True)
class AppConfig:
    project_root: Path
    config_path: Path
    source_paths: list[Path]
    db_path: Path
    ocr_language: str
    max_ocr_seconds: int
    video_frame_offset_seconds: float
    video_extract_timeout_seconds: int


def load_config(config_path: str | Path | None = None) -> AppConfig:
    if config_path is None:
        config_file = Path.cwd() / "config.toml"
    else:
        config_file = Path(config_path).expanduser().resolve()

    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_file}")

    raw = tomllib.loads(config_file.read_text(encoding="utf-8"))
    index = raw.get("index", {})
    source_paths = [
        Path(value).expanduser().resolve()
        for value in index.get("source_paths", [])
    ]
    if not source_paths:
        raise ValueError("config.toml must define at least one [index].source_paths entry")

    project_root = config_file.parent.resolve()
    db_path = (project_root / index.get("db_path", "state/meme-index.db")).resolve()

    return AppConfig(
        project_root=project_root,
        config_path=config_file.resolve(),
        source_paths=source_paths,
        db_path=db_path,
        ocr_language=index.get("ocr_language", "eng"),
        max_ocr_seconds=int(index.get("max_ocr_seconds", 3600)),
        video_frame_offset_seconds=float(index.get("video_frame_offset_seconds", 1.0)),
        video_extract_timeout_seconds=int(index.get("video_extract_timeout_seconds", 120)),
    )
