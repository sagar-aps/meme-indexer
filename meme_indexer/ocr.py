from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import subprocess
import tempfile
import time

from PIL import Image
import pytesseract

from .config import AppConfig


class FileSkipped(Exception):
    pass


@dataclass(slots=True)
class OCRResult:
    text: str
    width: int | None
    height: int | None
    duration_seconds: float | None


def ensure_external_dependencies() -> None:
    missing: list[str] = []
    for binary in ("tesseract", "ffmpeg", "ffprobe"):
        if subprocess.run(
            ["bash", "-lc", f"command -v {binary} >/dev/null 2>&1"],
            check=False,
        ).returncode != 0:
            missing.append(binary)
    if missing:
        raise RuntimeError(
            "Missing required system dependencies: "
            + ", ".join(missing)
            + ". Install them before running the indexer."
        )


def _clean_text(raw_text: str) -> str:
    lines = [line.strip() for line in raw_text.splitlines()]
    return "\n".join(line for line in lines if line)


def _remaining_seconds(started_at: float, limit_seconds: int) -> float:
    elapsed = time.monotonic() - started_at
    return max(limit_seconds - elapsed, 0.0)


def ocr_image(path: Path, config: AppConfig) -> OCRResult:
    started_at = time.monotonic()
    with Image.open(path) as image:
        image.load()
        width, height = image.size
        remaining = _remaining_seconds(started_at, config.max_ocr_seconds)
        if remaining <= 0:
            raise FileSkipped("OCR time limit exceeded before image OCR started")
        text = pytesseract.image_to_string(
            image,
            lang=config.ocr_language,
            timeout=max(1, int(remaining)),
        )
    return OCRResult(
        text=_clean_text(text),
        width=width,
        height=height,
        duration_seconds=None,
    )


def _probe_video(path: Path, timeout_seconds: int) -> tuple[int | None, int | None, float | None]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=True,
    )
    payload = json.loads(result.stdout or "{}")
    streams = payload.get("streams", [])
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
    width = video_stream.get("width")
    height = video_stream.get("height")
    duration = payload.get("format", {}).get("duration")
    return width, height, float(duration) if duration else None


def ocr_video_first_frame(path: Path, config: AppConfig) -> OCRResult:
    started_at = time.monotonic()
    remaining = _remaining_seconds(started_at, config.max_ocr_seconds)
    if remaining <= 0:
        raise FileSkipped("OCR time limit exceeded before video processing started")

    probe_timeout = min(config.video_extract_timeout_seconds, max(1, int(remaining)))
    width, height, duration_seconds = _probe_video(path, timeout_seconds=probe_timeout)

    with tempfile.TemporaryDirectory(prefix="meme-index-", dir=config.project_root / "state") as tmp_dir:
        frame_path = Path(tmp_dir) / "frame.png"
        remaining = _remaining_seconds(started_at, config.max_ocr_seconds)
        if remaining <= 0:
            raise FileSkipped("OCR time limit exceeded before frame extraction")

        extract_timeout = min(config.video_extract_timeout_seconds, max(1, int(remaining)))
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                str(config.video_frame_offset_seconds),
                "-i",
                str(path),
                "-frames:v",
                "1",
                str(frame_path),
            ],
            capture_output=True,
            text=True,
            timeout=extract_timeout,
            check=True,
        )

        remaining = _remaining_seconds(started_at, config.max_ocr_seconds)
        if remaining <= 0:
            raise FileSkipped("OCR time limit exceeded before video OCR")

        with Image.open(frame_path) as image:
            image.load()
            extracted_width, extracted_height = image.size
            text = pytesseract.image_to_string(
                image,
                lang=config.ocr_language,
                timeout=max(1, int(remaining)),
            )

    return OCRResult(
        text=_clean_text(text),
        width=width or extracted_width,
        height=height or extracted_height,
        duration_seconds=duration_seconds,
    )
