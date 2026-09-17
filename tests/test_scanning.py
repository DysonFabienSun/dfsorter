import subprocess
import threading
import time
from pathlib import Path

import pytest

from dfsorter.catalogue import Catalogue, normalized
from dfsorter.media import inspect_media
from dfsorter.scanning import ScanCoordinator


def test_cache_lifecycle(catalogue, registry, clips, monkeypatch):
    calls = []

    def probe(path, *args):
        calls.append(path)
        return dict(duration=12, created="2026-09-17", error=None)

    monkeypatch.setattr("dfsorter.scanning.inspect_media", probe)
    monkeypatch.setattr("dfsorter.scanning.shutil.which", lambda name: "ffprobe")
    folder = catalogue.folders()[0]
    catalogue.patch(clips[0]["clip_id"], {"mainline": "Keep this"})
    catalogue.create_session([clip["clip_id"] for clip in reversed(clips)])
    project = catalogue.save_project("Saved")
    catalogue.patch(clips[0]["clip_id"], {}, membership=(project, True))
    session = catalogue.state("session")
    ScanCoordinator(catalogue, registry).run([folder])
    assert len(calls) == 3
    restarted = Catalogue(catalogue.path)
    assert ScanCoordinator(restarted, registry).run([folder])[2]["hits"] == 3
    assert len(calls) == 3
    path = Path(clips[0]["source_path"])
    path.write_bytes(b"changed")
    ScanCoordinator(restarted, registry).run([folder])
    assert len(calls) == 4
    (path.parent / "added.mp4").write_bytes(b"new")
    ScanCoordinator(restarted, registry).run([folder])
    assert len(calls) == 5
    path.unlink()
    ScanCoordinator(restarted, registry).run([folder])
    assert len(calls) == 5
    ScanCoordinator(restarted, registry, force=True).run([folder])
    assert len(calls) == 8
    assert restarted.state("session") == session
    assert restarted.clip(clips[0]["clip_id"])["mainline"] == "Keep this"
    assert restarted.member_ids(project) == {clips[0]["clip_id"]}
    destination = path.parent.parent / "moved"
    destination.mkdir()
    restarted.migrate(folder["folder_id"], destination)
    assert not restarted.media_cache()


def test_failure_expiry_change_and_purge(catalogue, registry, clips, monkeypatch):
    monkeypatch.setattr("dfsorter.scanning.shutil.which", lambda name: "ffprobe")
    monkeypatch.setattr(
        "dfsorter.scanning.inspect_media",
        lambda *args: dict(duration=None, created=None, error="broken"),
    )
    folders = catalogue.folders()
    assert ScanCoordinator(catalogue, registry).run(folders)[2]["probes"] == 3
    assert ScanCoordinator(catalogue, registry).run(folders)[2]["probes"] == 0
    with catalogue.connection() as database:
        database.execute("UPDATE media_cache SET inspected_at=0")
    assert ScanCoordinator(catalogue, registry).run(folders)[2]["probes"] == 3
    Path(clips[0]["source_path"]).write_bytes(b"retry")
    assert ScanCoordinator(catalogue, registry).run(folders)[2]["probes"] == 1
    catalogue.remove_folder(folders[0]["folder_id"], purge=True)
    assert not catalogue.media_cache()


def test_missing_tool_and_unstable_file(catalogue, registry, clips, monkeypatch):
    monkeypatch.setattr("dfsorter.scanning.shutil.which", lambda name: None)
    result = ScanCoordinator(catalogue, registry).run(catalogue.folders())
    assert len(result[1]) == 1
    assert not catalogue.media_cache()
    monkeypatch.setattr("dfsorter.scanning.shutil.which", lambda name: "ffprobe")

    def changed(path, *args):
        path.write_bytes(b"replacement")
        return dict(duration=1, created=None, error=None)

    monkeypatch.setattr("dfsorter.scanning.inspect_media", changed)
    result = ScanCoordinator(catalogue, registry).run(catalogue.folders())
    assert result[2]["warnings"] == 3
    assert not catalogue.media_cache()


def test_concurrency_order_and_folder_cancellation(
    catalogue, registry, clips, tmp_path, monkeypatch
):
    monkeypatch.setattr("dfsorter.scanning.shutil.which", lambda name: "ffprobe")
    lock = threading.Lock()
    active = 0
    peak = 0

    def probe(path, *args):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.03 if path.name == "clip-0.mp4" else 0.01)
        with lock:
            active -= 1
        return dict(duration=1, created=None, error=None)

    monkeypatch.setattr("dfsorter.scanning.inspect_media", probe)
    result = ScanCoordinator(catalogue, registry).run(catalogue.folders())
    assert peak == 2
    assert [item["path"] for item in result[0]] == [clip["source_path"] for clip in clips]
    other = tmp_path / "other"
    other.mkdir()
    (other / "new.mp4").write_bytes(b"new")
    other_id = catalogue.add_folder(other)
    cancelled = threading.Event()

    def cancel_probe(*args):
        cancelled.set()
        return dict(duration=1, created=None, error=None)

    monkeypatch.setattr("dfsorter.scanning.inspect_media", cancel_probe)
    folders = catalogue.folders()
    folders.sort(key=lambda folder: folder["folder_id"] == other_id)
    result = ScanCoordinator(catalogue, registry, cancelled.is_set).run(folders)
    assert len(result[0]) == 3
    assert len(catalogue.clips()) == 3
    assert "cancelled" in result[1][0]
    result = ScanCoordinator(catalogue, registry).run(
        [dict(path=str(tmp_path / "missing"), folder_id="bad"), folders[0]]
    )
    assert len(result[0]) == 3
    assert result[1]


def test_probe_reaps_on_cancel_and_timeout(monkeypatch):
    processes = []
    cancelled = threading.Event()

    class Process:
        returncode = None

        def __init__(self, *args, **kwargs):
            self.reaped = False
            processes.append(self)

        def communicate(self, timeout=None):
            if timeout is None:
                self.reaped = True
                return "", ""
            cancelled.set()
            raise subprocess.TimeoutExpired("probe", timeout)

        def poll(self):
            return self.returncode

        def kill(self):
            self.returncode = -1

    monkeypatch.setattr("dfsorter.media.subprocess.Popen", Process)
    with pytest.raises(InterruptedError):
        inspect_media(Path("fake.mp4"), "ffprobe", cancelled.is_set)
    assert processes[-1].reaped
    assert "timed out" in inspect_media(Path("fake.mp4"), "ffprobe", timeout=0)["error"]
    assert processes[-1].reaped


def test_version_one_migration_preserves_data(catalogue, clips):
    catalogue.create_session([clip["clip_id"] for clip in reversed(clips)])
    project = catalogue.save_project("Project")
    catalogue.patch(
        clips[0]["clip_id"],
        {"mainline": "Saved", "metadata": {"kill": 4}},
        membership=(project, True),
    )
    before = catalogue.clips()
    session = catalogue.state("session")
    with catalogue.connection() as database:
        database.execute("DROP TABLE media_cache")
        database.execute("PRAGMA user_version=1")
    migrated = Catalogue(catalogue.path)
    assert migrated.clips() == before
    assert migrated.state("session") == session
    assert migrated.member_ids(project) == {clips[0]["clip_id"]}
    assert not migrated.media_cache()
    assert normalized(clips[0]["source_path"]) == clips[0]["source_path"]


def test_cancel_during_ingestion_rolls_back_folder(catalogue, tmp_path):
    folder = tmp_path / "captures"
    folder.mkdir()
    folder_id = catalogue.add_folder(folder)
    checks = 0

    def cancelled():
        nonlocal checks
        checks += 1
        return checks == 2

    with pytest.raises(InterruptedError):
        catalogue.ingest(folder_id, [dict(path=str(folder / "new.mp4"), game=None)], cancelled)
    assert not catalogue.clips()
