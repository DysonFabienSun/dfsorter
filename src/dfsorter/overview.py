from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from stat import S_ISREG

PERIOD_DAYS = {
    "7 days": 7,
    "30 days": 30,
    "3 months": 90,
    "6 months": 180,
    "1 year": 365,
    "All time": None,
}


def capture_datetime(clip, media_info, stat_for=None):
    created = media_info.get(clip["source_path"], {}).get("created")
    if created:
        try:
            value = datetime.fromisoformat(created.replace("Z", "+00:00"))
            return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone.utc)
        except (TypeError, ValueError):
            pass
    try:
        source = clip["source_path"]
        stamp = stat_for(source) if stat_for else Path(source).stat()
        return datetime.fromtimestamp(stamp.st_ctime, timezone.utc) if stamp else None
    except OSError:
        return None


def relative_capture_time(captured, current_time=None):
    if captured is None:
        return "Date unavailable"
    now = (current_time or datetime.now().astimezone()).astimezone()
    local = captured.astimezone(now.tzinfo)
    seconds = max(0, (now - local).total_seconds())
    days = (now.date() - local.date()).days
    if days < 1:
        if seconds < 60:
            return "Just now"
        if seconds < 3600:
            count, unit = int(seconds // 60), "minute"
        else:
            count, unit = int(seconds // 3600), "hour"
    elif days == 1:
        return "Yesterday"
    elif days < 30:
        count, unit = days, "day"
    elif days < 365:
        count, unit = days // 30, "month"
    else:
        count, unit = days // 365, "year"
    return f"{count} {unit}{'' if count == 1 else 's'} ago"


def compact_capture_time(captured, current_time=None):
    """Short relative label for the right edge of Home and Session cards."""
    label = relative_capture_time(captured, current_time)
    if label == "Date unavailable":
        return "—"
    if label == "Just now":
        return "now"
    if label == "Yesterday":
        return "1d ago"
    count, unit, _ago = label.split()
    suffix = {"minute": "m", "hour": "h", "day": "d", "month": "mo", "year": "y"}[
        unit.rstrip("s")
    ]
    return f"{count}{suffix} ago"


def library_overview(clips, media_info, period="All time", current_time=None, stat_for=None):
    current_time = current_time or datetime.now(timezone.utc)
    current_time = current_time.astimezone(timezone.utc)
    days = PERIOD_DAYS[period]
    cutoff = current_time - timedelta(days=days) if days is not None else None
    counts = {}
    sizes = Counter()
    undated = 0
    unavailable = 0
    for clip in clips:
        try:
            source = clip["source_path"]
            stamp = stat_for(source) if stat_for else Path(source).stat()
        except OSError:
            stamp = None
        if stamp is None or not S_ISREG(stamp.st_mode):
            unavailable += 1
            continue
        captured = capture_datetime(clip, media_info, stat_for)
        if captured is None:
            undated += 1
            if cutoff is not None:
                continue
        elif cutoff is not None and not cutoff <= captured <= current_time:
            continue
        game = clip["game"] or "Uncategorized"
        state = clip["triage"] or "pending"
        counts.setdefault(game, Counter())[state] += 1
        sizes[game] += stamp.st_size

    total = Counter()
    for game_counts in counts.values():
        total.update(game_counts)
    rows = sorted(
        counts.items(),
        key=lambda item: (
            item[0] == "Uncategorized",
            -sum(item[1].values()),
            item[0].casefold(),
        ),
    )
    return total, rows, undated, unavailable, sizes
