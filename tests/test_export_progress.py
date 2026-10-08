import hashlib
from pathlib import Path

import pytest

import dfsorter.output as output


@pytest.fixture
def export_job(catalogue, tmp_path):
    def create(sizes, completed=0, pending=False):
        destination = tmp_path / "export"
        items = []
        for index, size in enumerate(sizes):
            source = tmp_path / f"source-{index}.mp4"
            with source.open("wb") as stream:
                stream.write(b"sample"[:size])
                stream.truncate(size)
            stat = source.stat()
            item = {
                "clip_id": str(index), "source_path": str(source),
                "source_size": size, "source_mtime_ns": stat.st_mtime_ns,
                "stem": f"clip-{index}", "directory": "", "completed": None,
            }
            if index < completed or pending:
                destination.mkdir(exist_ok=True)
                target = destination / f"clip-{index}.mp4"
                target.write_bytes(source.read_bytes())
                checksum = hashlib.sha256(target.read_bytes()).hexdigest()
                if pending:
                    item["pending"] = {
                        "target": str(target),
                        "temporary": str(destination / f"gone-{index}.part"),
                        "size": size, "sha256": checksum,
                    }
                else:
                    item["completed"] = {"path": str(target), "size": size, "sha256": checksum}
            items.append(item)
        manifest = {"destination": str(destination), "items": items}
        catalogue.save_export_job("progress", manifest, "Queued")
        return manifest
    return create


def advancing_clock(monkeypatch):
    ticks = iter(index * 0.11 for index in range(10000))
    monkeypatch.setattr(output, "monotonic", lambda: next(ticks))


def test_fresh_export_early_bytes_and_persisted_completion(catalogue, export_job):
    manifest = export_job([101 * 1024 * 1024])
    events = []

    def report(percent, detail):
        if percent == 100:
            assert catalogue.export_jobs()[0]["status"] == "Completed"
            assert catalogue.export_jobs()[0]["manifest"]["items"][0]["completed"]
        events.append((percent, detail))

    result = output.run_export_manifest(catalogue, "progress", detailed_progress=report)
    assert not result.error
    assert events[:2] == [(-1, "Preparing export…"), (-1, "Checking destination…")]
    assert (0, "Copying source-0.mp4") in events
    assert events[-2:] == [(99, "Copying source-0.mp4"), (100, "Export complete")]
    assert output._hash_file(result.completed[0], lambda: False) == output._hash_file(
        manifest["items"][0]["source_path"], lambda: False,
    )


def test_resume_advances_inside_verification_and_into_copying(
    catalogue, export_job, monkeypatch,
):
    manifest = export_job([4 * 1024 * 1024] * 2, completed=1)
    advancing_clock(monkeypatch)
    events = []
    result = output.run_export_manifest(
        catalogue, "progress", detailed_progress=lambda *event: events.append(event),
    )
    assert not result.error
    verification = [percent for percent, detail in events if detail == "Verifying clip-0.mp4"]
    assert verification == [-1, 12, 25, 37, 50, 50]
    copying = [percent for percent, detail in events if detail == "Copying source-1.mp4"]
    assert copying == [50, 62, 75, 87, 99, 99]
    measured = [percent for percent, _ in events if percent >= 0]
    assert measured == sorted(measured)
    for item, target in zip(manifest["items"], result.completed, strict=True):
        assert Path(target).read_bytes() == Path(item["source_path"]).read_bytes()


def test_recovery_hashes_and_counts_each_item_once(catalogue, export_job, monkeypatch):
    export_job([4 * 1024 * 1024], pending=True)
    advancing_clock(monkeypatch)
    original = output._hash_file
    hashed = []

    def hash_file(path, cancelled, advanced=lambda amount: None):
        hashed.append(str(path))
        return original(path, cancelled, advanced)

    monkeypatch.setattr(output, "_hash_file", hash_file)
    events = []
    result = output.run_export_manifest(
        catalogue, "progress", detailed_progress=lambda *event: events.append(event),
    )
    assert not result.error and hashed == result.completed
    assert len(list(Path(result.completed[0]).parent.glob("*.mp4"))) == 1
    assert (-1, "Recovering previous output…") in events
    assert [percent for percent, detail in events if detail == "Verifying clip-0.mp4"] == [
        -1, 25, 50, 75, 99, 99,
    ]
    assert (99, "Recovering previous output…") in events


@pytest.mark.parametrize("damage", ["changed", "missing"])
def test_completed_output_damage_still_fails(catalogue, export_job, damage):
    manifest = export_job([16], completed=1)
    target = Path(manifest["items"][0]["completed"]["path"])
    if damage == "changed":
        target.write_bytes(b"x" * 16)
    else:
        target.unlink()
    events = []
    result = output.run_export_manifest(
        catalogue, "progress", detailed_progress=lambda *event: events.append(event),
    )
    assert "Completed export copy changed" in result.error
    assert not result.cancelled and not result.completed
    assert all(percent != 100 for percent, _ in events)
    assert catalogue.export_jobs()[0]["status"] == "Failed"


@pytest.mark.parametrize("phase", ["Preparing export…", "Checking destination…", "Verifying", "Copying"])
def test_cancel_preparation_verification_and_copying(catalogue, export_job, phase, monkeypatch):
    manifest = export_job([4 * 1024 * 1024] * 2, completed=1)
    advancing_clock(monkeypatch)
    stopped = False
    events = []

    def report(percent, detail):
        nonlocal stopped
        events.append((percent, detail))
        threshold = 50 if phase == "Copying" else 0
        if detail.startswith(phase) and (phase.endswith("…") or percent > threshold):
            stopped = True

    result = output.run_export_manifest(
        catalogue, "progress", cancelled=lambda: stopped, detailed_progress=report,
    )
    assert result.cancelled
    target = Path(manifest["items"][0]["completed"]["path"])
    assert target.read_bytes() == Path(manifest["items"][0]["source_path"]).read_bytes()
    assert list(target.parent.glob("*.mp4")) == [target]
    assert not list(target.parent.glob("*.part"))
    assert catalogue.export_jobs()[0]["status"] == "Cancelled"
    assert all(percent != 100 for percent, _ in events)
    if phase == "Copying":
        assert events[-1][1] == "Cleaning unfinished output…"
        assert events[-1][0] >= 50


@pytest.mark.parametrize("sizes", [[], [0], [0, 0]])
def test_empty_and_zero_byte_exports(catalogue, export_job, sizes):
    export_job(sizes)
    events = []
    result = output.run_export_manifest(
        catalogue, "progress", detailed_progress=lambda *event: events.append(event),
    )
    assert not result.error and len(result.completed) == len(sizes)
    assert all(percent == -1 for percent, _ in events[:-1])
    assert events[-1] == (100, "Export complete")


def test_progress_throttles_bytes_but_forces_boundaries(monkeypatch):
    now = 0.0
    monkeypatch.setattr(output, "monotonic", lambda: now)
    events = []
    progress = output._ExportProgress(1000, lambda *event: events.append((now, *event)))
    progress.phase("Verifying first.mp4")
    for tick in range(100):
        now = tick / 100
        progress.advanced(1)
    byte_events = events[1:]
    assert byte_events[0] == (0.0, 0, "Verifying first.mp4")
    assert len(byte_events) <= 10
    assert all(later[0] - earlier[0] >= 0.1
               for earlier, later in zip(byte_events, byte_events[1:]))
    progress.emit()
    assert events[-1] == (0.99, 10, "Verifying first.mp4")
    progress.phase("Copying second.mp4")
    assert events[-1] == (0.99, 10, "Copying second.mp4")


def test_completion_waits_for_manifest_persistence(catalogue, export_job, monkeypatch):
    export_job([16])
    original = catalogue.save_export_job

    def save(job_id, manifest, status):
        if status == "Completed":
            raise OSError("Manifest persistence failed")
        original(job_id, manifest, status)

    monkeypatch.setattr(catalogue, "save_export_job", save)
    events = []
    result = output.run_export_manifest(
        catalogue, "progress", detailed_progress=lambda *event: events.append(event),
    )
    assert result.error == "Manifest persistence failed"
    assert len(result.completed) == 1 and Path(result.completed[0]).is_file()
    assert max(percent for percent, _ in events) == 99
    assert catalogue.export_jobs()[0]["status"] == "Failed"


def test_recovery_cleans_unpublished_copy_without_claiming_collision(
    catalogue, export_job, monkeypatch,
):
    manifest = export_job([4 * 1024 * 1024] * 2, pending=True)
    advancing_clock(monkeypatch)
    pending = manifest["items"][1]["pending"]
    temporary = Path(pending["temporary"])
    temporary.write_bytes(b"unfinished")
    collision = Path(pending["target"])
    collision.write_bytes(b"existing unrelated output")
    catalogue.save_export_job("progress", manifest, "Running")
    events = []
    result = output.run_export_manifest(
        catalogue, "progress", detailed_progress=lambda *event: events.append(event),
    )
    assert not result.error and len(result.completed) == 2
    assert not temporary.exists()
    assert collision.read_bytes() == b"existing unrelated output"
    assert Path(result.completed[1]).name == "clip-1 (1).mp4"
    assert (50, "Recovering previous output…") in events
    assert all(not detail.startswith("Verifying clip-1") for _, detail in events)
    measured = [percent for percent, _ in events if percent >= 0]
    assert measured == sorted(measured)
