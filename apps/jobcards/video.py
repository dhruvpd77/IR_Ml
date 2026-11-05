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
    """Return a much smaller MP4 of the full clip. The original is kept if ffmpeg cannot run."""
    exe = ffmpeg_exe()
    if not exe or upload is None:
        return upload
    suffix = os.path.splitext(upload.name or "")[1] or ".mp4"
    source = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    target = source.name + ".mp4"
    tighter = source.name + ".tight.mp4"
    try:
        for chunk in upload.chunks():
            source.write(chunk)
        source.close()
        encoded = _encode(exe, source.name, target, width=640, crf=35, rate="450k", audio="32k") or _encode(
            exe, source.name, target, width=640, crf=35, rate="450k", audio=""
        )
        if encoded and os.path.getsize(target) > 25 * 1024 * 1024:
            squeezed = _encode(exe, source.name, tighter, width=480, crf=38, rate="280k", audio="24k") or _encode(
                exe, source.name, tighter, width=480, crf=38, rate="280k", audio=""
            )
            if squeezed and os.path.getsize(tighter) < os.path.getsize(target):
                os.replace(tighter, target)
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
        for path in (source.name, target, tighter):
            try:
                os.remove(path)
            except OSError:
                pass


def _encode(exe, source, target, width, crf, rate, audio):
    command = [
        exe,
        "-y",
        "-i",
        source,
        "-vf",
        f"scale='min({width},iw)':-2",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        str(crf),
        "-maxrate",
        rate,
        "-bufsize",
        rate,
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
    ]
    if audio:
        command.extend(["-c:a", "aac", "-ac", "1", "-b:a", audio])
    else:
        command.append("-an")
    command.append(target)
    try:
        result = subprocess.run(command, capture_output=True, timeout=300)
    except subprocess.TimeoutExpired:
        return False
    if result.returncode != 0 or not os.path.exists(target):
        return False
    return os.path.getsize(target) >= 1000
