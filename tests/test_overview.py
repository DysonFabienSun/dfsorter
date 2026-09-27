from datetime import datetime, timedelta, timezone

from dfsorter.overview import capture_datetime, library_overview, relative_capture_time

NOW = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)


def clip(path, game=None, triage=None):
    return {"source_path": str(path), "game": game, "triage": triage}


def test_overview_aggregates_and_orders_pending_work(tmp_path):
    clips = [
        clip(tmp_path / "a.mp4", "VALORANT", "keep"),
        clip(tmp_path / "b.mp4", "VALORANT"),
        clip(tmp_path / "c.mp4", "Escape from Tarkov"),
        clip(tmp_path / "d.mp4", "Escape from Tarkov"),
        clip(tmp_path / "e.mp4", None, "discard"),
    ]
    total, rows, undated = library_overview(clips, {}, current_time=NOW)

    assert total == {"keep": 1, "pending": 3, "discard": 1}
    assert [name for name, _counts in rows] == [
        "Escape from Tarkov",
        "VALORANT",
        "Uncategorized",
    ]
    assert undated == 5


def test_overview_filters_rolling_dates_and_discloses_undated(tmp_path):
    recent = clip(tmp_path / "recent.mp4", "VALORANT", "keep")
    boundary = clip(tmp_path / "boundary.mp4", "VALORANT")
    old = clip(tmp_path / "old.mp4", "VALORANT", "discard")
    undated = clip(tmp_path / "missing.mp4", "VALORANT")
    media = {
        recent["source_path"]: {"created": "2026-09-24T12:00:00Z"},
        boundary["source_path"]: {"created": "2026-09-18T12:00:00Z"},
        old["source_path"]: {"created": "2026-09-18T11:59:59Z"},
    }

    total, rows, missing = library_overview([recent, boundary, old, undated], media, "7 days", NOW)

    assert total == {"keep": 1, "pending": 1}
    assert rows[0][1] == total
    assert missing == 1


def test_capture_date_prefers_media_and_falls_back_to_file(tmp_path):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"video")
    item = clip(source)
    cached = capture_datetime(item, {str(source): {"created": "2020-01-02T03:04:05Z"}})
    fallback = capture_datetime(item, {})

    assert cached == datetime(2020, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert fallback is not None
    assert fallback.tzinfo == timezone.utc


def test_relative_capture_time_uses_local_calendar_and_coarse_units():
    local_zone = datetime.now().astimezone().tzinfo
    now = datetime(2026, 9, 25, 12, 0, tzinfo=local_zone)
    cases = [
        (now - timedelta(seconds=30), "Just now"),
        (now - timedelta(minutes=1), "1 minute ago"),
        (now - timedelta(hours=2), "2 hours ago"),
        (now - timedelta(days=1), "Yesterday"),
        (now - timedelta(days=2), "2 days ago"),
        (now - timedelta(days=60), "2 months ago"),
        (now - timedelta(days=730), "2 years ago"),
    ]
    for captured, expected in cases:
        assert relative_capture_time(captured, now) == expected
    assert relative_capture_time(None, now) == "Date unavailable"

    just_after_midnight = now.replace(hour=0, minute=5)
    assert relative_capture_time(
        just_after_midnight - timedelta(minutes=10), just_after_midnight
    ) == "Yesterday"
