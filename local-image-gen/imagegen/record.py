"""Write the image to disk, verify it opens, and write the JSON record."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path


def record_path(image: Path) -> Path:
    return image.with_suffix(".json")


def save_and_verify(path: Path, data: bytes) -> dict:
    """Write bytes, then re-open with Pillow to prove the file is a valid image."""
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    with Image.open(io.BytesIO(path.read_bytes())) as img:
        img.verify()
    with Image.open(path) as img:
        width, height, fmt = img.width, img.height, img.format
    return {"path": str(path), "format": fmt, "width": width, "height": height,
            "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
