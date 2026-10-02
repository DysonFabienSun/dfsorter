from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from dfsorter.overview import (
    capture_datetime,
    compact_capture_time,
    library_overview,
    relative_capture_time,
)

NOW = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)


def clip(path, game=None, triage=None):
    return {"source_path": str(path), "game": game, "triage": triage}


def test_overview_aggregates_and_orders_tied_games(tmp_path):
    clips = [
        clip(tmp_path / "a.mp4", "VALORANT", "keep"),
        clip(tmp_path / "b.mp4", "VALORANT"),
        clip(tmp_path / "c.mp4", "Escape from Tarkov"),
        clip(tmp_path / "d.mp4", "Escape from Tarkov"),
        clip(tmp_path / "e.mp4", None, "discard"),
    ]
    for item in clips:
        (tmp_path / Path(item["source_path"]).name).write_bytes(b"clip")
    total, rows, undated, unavailable, sizes = library_overview(clips, {}, current_time=NOW)

    assert total == {"keep": 1, "pending": 3, "discard": 1}
    assert [name for name, _counts in rows] == [
        "Escape from Tarkov",
        "VALORANT",
        "Uncategorized",
    ]
    assert undated == 0
    assert unavailable == 0
    assert sum(sizes.values()) == 20


def test_overview_orders_games_by_total_with_uncategorized_last(tmp_path):
    clips = (
        [clip(tmp_path / f"pending-{index}.mp4", "Pending-heavy") for index in range(3)]
        + [clip(tmp_path / f"large-{index}.mp4", "Largest", "keep") for index in range(4)]
        + [clip(tmp_path / f"uncategorized-{index}.mp4") for index in range(5)]
    )
    for item in clips:
        (tmp_path / Path(item["source_path"]).name).write_bytes(b"clip")

    _total, rows, _undated, _unavailable, _sizes = library_overview(
        clips, {}, current_time=NOW
    )

    assert [name for name, _counts in rows] == ["Largest", "Pending-heavy", "Uncategorized"]


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

    recent_path = tmp_path / "recent.mp4"
    recent_path.write_bytes(b"12345")
    boundary_path = tmp_path / "boundary.mp4"
    boundary_path.write_bytes(b"123")
    (tmp_path / "old.mp4").write_bytes(b"old source excluded by period")
    total, rows, undated, unavailable, sizes = library_overview(
        [recent, boundary, old, undated], media, "7 days", NOW
    )

    assert total == {"keep": 1, "pending": 1}
    assert rows[0][1] == total
    assert undated == 0
    assert unavailable == 1
    assert sizes == {"VALORANT": 8}


@pytest.mark.parametrize("period", ["All time", "7 days"])
def test_overview_excludes_unavailable_even_with_cached_capture_date(tmp_path, period):
    available = clip(tmp_path / "available.mp4", "VALORANT", "keep")
    missing = clip(tmp_path / "missing.mp4", "VALORANT", "discard")
    (tmp_path / "available.mp4").write_bytes(b"clip")
    media = {
        available["source_path"]: {"created": "2026-09-24T12:00:00Z"},
        missing["source_path"]: {"created": "2026-09-24T12:00:00Z"},
    }

    total, rows, undated, unavailable, sizes = library_overview(
        [available, missing], media, period, NOW
    )

    assert total == {"keep": 1}
    assert rows == [("VALORANT", total)]
    assert undated == 0
    assert unavailable == 1
    assert sizes == {"VALORANT": 4}


@pytest.mark.parametrize("period, expected_total", [("All time", 1), ("7 days", 0)])
def test_overview_reports_available_file_without_usable_date(
    tmp_path, monkeypatch, period, expected_total
):
    item = clip(tmp_path / "undated.mp4", "VALORANT")
    (tmp_path / "undated.mp4").write_bytes(b"clip")
    monkeypatch.setattr("dfsorter.overview.capture_datetime", lambda *args: None)

    total, rows, undated, unavailable, sizes = library_overview(
        [item], {}, period, NOW
    )

    assert sum(total.values()) == expected_total
    assert bool(rows) == bool(expected_total)
    assert undated == 1
    assert unavailable == 0
    assert sum(sizes.values()) == 4 * expected_total


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
    assert compact_capture_time(None, now) == "—"
    assert compact_capture_time(now - timedelta(minutes=2), now) == "2m ago"
    assert compact_capture_time(now - timedelta(hours=2), now) == "2h ago"
    assert compact_capture_time(now - timedelta(days=1), now) == "1d ago"

    just_after_midnight = now.replace(hour=0, minute=5)
    assert relative_capture_time(
        just_after_midnight - timedelta(minutes=10), just_after_midnight
    ) == "Yesterday"
