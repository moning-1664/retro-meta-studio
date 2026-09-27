"""Validate and stage an image supplied by drag/drop or the OS clipboard."""

from __future__ import annotations

import base64
import binascii
import io
import uuid
from pathlib import Path

from PIL import Image, UnidentifiedImageError

MAX_IMAGE_BYTES = 24 * 1024 * 1024
EXTENSIONS = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp", "GIF": ".gif"}


def stage_image(encoded: str, directory: Path) -> Path:
    if len(encoded) > (MAX_IMAGE_BYTES * 4 // 3 + 8):
        raise ValueError("이미지가 24MB 제한을 넘었습니다.")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("이미지 데이터가 올바르지 않습니다.") from None
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ValueError("이미지가 비었거나 24MB 제한을 넘었습니다.")
    try:
        with Image.open(io.BytesIO(data)) as image:
            suffix = EXTENSIONS.get(image.format or "")
            if not suffix:
                raise ValueError("PNG, JPEG, WebP, GIF 이미지만 가져올 수 있습니다.")
            image.verify()
    except (UnidentifiedImageError, OSError):
        raise ValueError("이미지 파일을 읽을 수 없습니다.") from None
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{uuid.uuid4().hex}{suffix}"
    destination.write_bytes(data)
    return destination
