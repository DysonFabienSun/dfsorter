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


def library_overview(clips, media_info, period="All time", current_time=None):
    current_time = current_time or datetime.now(timezone.utc)
    current_time = current_time.astimezone(timezone.utc)
    days = PERIOD_DAYS[period]
    cutoff = current_time - timedelta(days=days) if days is not None else None
    counts = {}
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
    return total, rows, undated
