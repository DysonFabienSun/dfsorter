from datetime import datetime, timezone

from dfsorter.overview import capture_datetime, library_overview

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
