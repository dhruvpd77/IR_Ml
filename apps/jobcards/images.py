"""Shrink inspection photos before they are stored."""

import os
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image, ImageOps, UnidentifiedImageError


def compress_image(upload):
    """Return a smaller JPEG. The original is kept if the picture cannot be read."""
    if upload is None:
        return upload
    try:
        upload.seek(0)
        image = Image.open(upload)
        image = ImageOps.exif_transpose(image)
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        elif image.mode == "L":
            image = image.convert("RGB")
        image.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=55, optimize=True)
        data = buffer.getvalue()
    except (UnidentifiedImageError, OSError, ValueError):
        try:
            upload.seek(0)
        except Exception:
            pass
        return upload
    if len(data) < 500:
        try:
            upload.seek(0)
        except Exception:
            pass
        return upload
    original = getattr(upload, "size", 0) or 0
    if original and len(data) > original:
        try:
            upload.seek(0)
        except Exception:
            pass
        return upload
    stem = os.path.splitext(os.path.basename(upload.name or "photo"))[0][:180] or "photo"
    return SimpleUploadedFile(f"{stem}.jpg", data, content_type="image/jpeg")
