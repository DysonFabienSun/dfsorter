import shutil
import subprocess
import time
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from dfsorter.thumbnails import ThumbnailCache
from dfsorter.ui import ROOT, Window, style_application
from dfsorter.widgets import CLIP_ROLE


@pytest.fixture(scope="module")
def application():
    app = QApplication.instance() or QApplication([])
    style_application(app)
    return app


def wait_for(application, predicate, seconds=8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        application.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_thumbnail_cache_extracts_reuses_and_invalidates(tmp_path, application):
    source = tmp_path / "short.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                    "-i", "color=c=red:s=160x90:d=0.6", "-c:v", "mpeg4", "-y", str(source)],
                   check=True)
    clip = {"clip_id": "one", "source_path": str(source), "duration": 0.6}
    cache = ThumbnailCache(tmp_path)
    try:
        key, image = cache.request(clip)
        assert image is None
        assert wait_for(application, lambda: key in cache.memory)
        assert cache.memory[key].size().width() == 168
        assert cache.memory[key].size().height() == 96
        assert (tmp_path / "cache/thumbnails" / f"{key}.png").exists()
        assert cache.request(clip)[0] == key
        cache.memory.clear()
        assert not cache.get(clip)[1].isNull()
        source.write_bytes(b"changed")
        changed, image = cache.get(clip)
        assert changed != key and image is None
    finally:
        cache.close()


def test_missing_and_undecodable_sources(tmp_path, application):
    cache = ThumbnailCache(tmp_path)
    clip = {"clip_id": "broken", "source_path": str(tmp_path / "missing.mp4")}
    try:
        assert cache.request(clip) == (None, None)
        Path(clip["source_path"]).write_bytes(b"not video")
        key, image = cache.request(clip)
        assert image is None
        assert wait_for(application, lambda: key in cache.failed)
        assert cache.request(clip) == (key, None)
        Path(clip["source_path"]).write_bytes(b"changed invalid video")
        new_key, _ = cache.request(clip)
        assert new_key != key
        assert new_key in cache.pending
    finally:
        cache.close()


def test_thumbnail_ffmpeg_does_not_open_windows_console(tmp_path, monkeypatch, application):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"video")
    calls = []

    def fake_run(command, **kwargs):
        calls.append(kwargs)
        image = QImage(168, 96, QImage.Format.Format_RGB32)
        image.save(command[-1])
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("dfsorter.thumbnails.tool", lambda name: "ffmpeg")
    monkeypatch.setattr("dfsorter.thumbnails.subprocess.run", fake_run)
    cache = ThumbnailCache(tmp_path)
    try:
        assert not cache._extract("console-check", str(source), 2).isNull()
        assert calls[0]["creationflags"] == (
            subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        )
    finally:
        cache.close()


def test_stale_thumbnail_does_not_change_filtered_browse(tmp_path, application):
    shutil.copytree(ROOT / "configs", tmp_path / "configs")
    window = Window(tmp_path)
    window.show()
    try:
        folder = tmp_path / "captures"
        folder.mkdir()
        for name in ("alpha.mp4", "beta.mp4"):
            (folder / name).write_bytes(b"invalid")
        folder_id = window.catalogue.add_folder(folder)
        window.catalogue.ingest(folder_id, [
            {"path": str(folder / name), "game": "VALORANT"}
            for name in ("alpha.mp4", "beta.mp4")
        ])
        window.panel("Browse")
        window.refresh_library()
        application.processEvents()
        old = window.library.item(0)
        old_id = old.data(Qt.ItemDataRole.UserRole)
        key = "old-source-key"
        data = old.data(CLIP_ROLE)
        data["thumbnail_key"] = key
        old.setData(CLIP_ROLE, data)
        window.browse_search.setText("no matching filename")
        application.processEvents()
        assert window.library.count() == 0
        picture = QImage(168, 96, QImage.Format.Format_RGB32)
        window.thumbnail_ready(old_id, key, picture)
        assert window.library.count() == 0
    finally:
        window.close()
        application.processEvents()
