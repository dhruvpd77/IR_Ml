"""Shrink QC clips before they are stored."""

import os
import shutil
import subprocess
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile


def ffmpeg_exe():
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
    except ImportError:
        return ""
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return ""


def compress_video(upload):
    """Return a short, smaller MP4. The original file is kept if ffmpeg cannot run."""
    exe = ffmpeg_exe()
    if not exe or upload is None:
        return upload
    suffix = os.path.splitext(upload.name or "")[1] or ".mp4"
    source = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    target = source.name + ".mp4"
    try:
        for chunk in upload.chunks():
            source.write(chunk)
        source.close()
        encoded = _encode(exe, source.name, target, audio=True) or _encode(exe, source.name, target, audio=False)
        if not encoded:
            upload.seek(0)
            return upload
        with open(target, "rb") as handle:
            data = handle.read()
        if len(data) < 1000:
            upload.seek(0)
            return upload
        original = getattr(upload, "size", 0) or 0
        if original and len(data) > original:
            upload.seek(0)
            return upload
        stem = os.path.splitext(os.path.basename(upload.name or "inspection"))[0][:180] or "inspection"
        return SimpleUploadedFile(f"{stem}.mp4", data, content_type="video/mp4")
    except (OSError, subprocess.SubprocessError):
        try:
            upload.seek(0)
        except Exception:
            pass
        return upload
    finally:
        for path in (source.name, target):
            try:
                os.remove(path)
            except OSError:
                pass


def _encode(exe, source, target, audio):
    command = [
        exe,
        "-y",
        "-i",
        source,
        "-t",
        "30",
        "-vf",
        "scale='min(854,iw)':-2",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "32",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
    ]
    if audio:
        command.extend(["-c:a", "aac", "-b:a", "64k"])
    else:
        command.append("-an")
    command.append(target)
    result = subprocess.run(command, capture_output=True, timeout=120)
    if result.returncode != 0 or not os.path.exists(target):
        return False
    return os.path.getsize(target) >= 1000
