from django.utils import timezone


def format_seconds(seconds):
    seconds = int(seconds or 0)
    if seconds < 0:
        seconds = 0
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _secs = divmod(remainder, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m"
    return f"{seconds}s"


def format_duration(start, end=None):
    if not start:
        return "—"
    end = end or timezone.now()
    return format_seconds((end - start).total_seconds())
