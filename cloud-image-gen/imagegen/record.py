"""Write images to disk, verify they open, and write the JSON record."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

EXT_FOR_MIME = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
SAME_EXT = {".jpeg": ".jpg"}


def image_paths(base: Path, mime_types: list[str]) -> tuple[list[Path], list[str]]:
    """Final paths for each image; suffix follows the real MIME type returned."""
    notes, paths = [], []
    for i, mime in enumerate(mime_types, start=1):
        ext = EXT_FOR_MIME.get(mime, base.suffix or ".bin")
        stem = base.stem if len(mime_types) == 1 else f"{base.stem}_{i}"
        given = SAME_EXT.get(base.suffix.lower(), base.suffix.lower())
        if base.suffix and given != ext:
            notes.append(f"API 回傳 {mime}，副檔名由 {base.suffix} 改為 {ext}")
        paths.append(base.with_name(stem + ext))
    return paths, notes


def record_path(base: Path) -> Path:
    return base.with_suffix(".json") if base.suffix else base.with_name(base.name + ".json")


def save_and_verify(path: Path, data: bytes) -> dict:
    """Write bytes, then re-open with Pillow to prove the file is a valid image."""
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    with Image.open(io.BytesIO(path.read_bytes())) as img:
        img.verify()
    with Image.open(path) as img:
        width, height, fmt = img.width, img.height, img.format
    return {
        "path": str(path),
        "format": fmt,
        "width": width,
        "height": height,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
