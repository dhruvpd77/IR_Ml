"""Shrink inspection clips before they are stored. Tuned for speed on PythonAnywhere."""

import os
import shutil
import subprocess
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile

# Skip re-encode when the phone file is already small enough for the shop.
SKIP_BELOW = 4 * 1024 * 1024


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
    """Return a smaller MP4 of the full clip. Prefers speed over extra quality."""
    if upload is None:
        return upload
    original = getattr(upload, "size", 0) or 0
    if original and original <= SKIP_BELOW:
        try:
            upload.seek(0)
        except Exception:
            pass
        return upload
    exe = ffmpeg_exe()
    if not exe:
        return upload
    suffix = os.path.splitext(upload.name or "")[1] or ".mp4"
    source = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    target = source.name + ".mp4"
    try:
        for chunk in upload.chunks():
            source.write(chunk)
        source.close()
        # One fast pass only: 480px, ultrafast, light audio. No second encode.
        encoded = _encode(exe, source.name, target, width=480, crf=40, rate="280k", audio="24k") or _encode(
            exe, source.name, target, width=480, crf=40, rate="280k", audio=""
        )
        if not encoded:
            upload.seek(0)
            return upload
        with open(target, "rb") as handle:
            data = handle.read()
        if len(data) < 1000:
            upload.seek(0)
            return upload
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


def _encode(exe, source, target, width, crf, rate, audio):
    command = [
        exe,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        source,
        "-vf",
        f"scale='min({width},iw)':-2",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-tune",
        "fastdecode",
        "-crf",
        str(crf),
        "-maxrate",
        rate,
        "-bufsize",
        str(int(rate.rstrip("k")) * 2) + "k" if rate.endswith("k") else rate,
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-threads",
        "0",
    ]
    if audio:
        command.extend(["-c:a", "aac", "-ac", "1", "-b:a", audio, "-ar", "16000"])
    else:
        command.append("-an")
    command.append(target)
    try:
        result = subprocess.run(command, capture_output=True, timeout=180)
    except subprocess.TimeoutExpired:
        return False
    if result.returncode != 0 or not os.path.exists(target):
        return False
    return os.path.getsize(target) >= 1000
