from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

PERIOD_DAYS = {
    "7 days": 7,
    "30 days": 30,
    "3 months": 90,
    "6 months": 180,
    "1 year": 365,
    "All time": None,
}


def capture_datetime(clip, media_info):
    created = media_info.get(clip["source_path"], {}).get("created")
    if created:
        try:
            value = datetime.fromisoformat(created.replace("Z", "+00:00"))
            return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone.utc)
        except (TypeError, ValueError):
            pass
    try:
        return datetime.fromtimestamp(Path(clip["source_path"]).stat().st_ctime, timezone.utc)
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


def library_overview(clips, media_info, period="All time", current_time=None):
    current_time = current_time or datetime.now(timezone.utc)
    current_time = current_time.astimezone(timezone.utc)
    days = PERIOD_DAYS[period]
    cutoff = current_time - timedelta(days=days) if days is not None else None
    counts = {}
    sizes = Counter()
    undated = 0
    for clip in clips:
        captured = capture_datetime(clip, media_info)
        if captured is None:
            undated += 1
            if cutoff is not None:
                continue
        elif cutoff is not None and not cutoff <= captured <= current_time:
            continue
        game = clip["game"] or "Uncategorized"
        state = clip["triage"] or "pending"
        counts.setdefault(game, Counter())[state] += 1
        try:
            sizes[game] += Path(clip["source_path"]).stat().st_size
        except OSError:
            pass

    total = Counter()
    for game_counts in counts.values():
        total.update(game_counts)
    rows = sorted(
        counts.items(),
        key=lambda item: (
            item[0] == "Uncategorized",
            -item[1]["pending"],
            item[0].casefold(),
        ),
    )
    return total, rows, undated, sizes
