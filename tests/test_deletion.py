import os
from pathlib import Path

import pytest

from dfsorter.catalogue import Catalogue
from dfsorter.deletion import delete_original, delete_reviewed, preview


def discard(catalogue, clips):
    for clip in clips:
        catalogue.patch(clip["clip_id"], {"triage": "discard"})


def test_preview_whole_library_and_retains_references(catalogue, clips):
    discard(catalogue, clips[:2])
    catalogue.patch(clips[2]["clip_id"], {"triage": "keep"})
    catalogue.create_session([clip["clip_id"] for clip in clips])
    folder = catalogue.folders()[0]
    catalogue.remove_folder(folder["folder_id"], purge=False)
    snapshot = catalogue.clips()
    session = catalogue.state("session")
    reviewed = preview(catalogue)
    assert len(reviewed) == 2
    assert sum(item.size for item in reviewed) == 51200
    assert all("file modified" in item.date for item in reviewed)
    result = delete_reviewed(catalogue, reviewed)
    assert all(status == "Deleted" for path, status in result), result
    assert all(not Path(item.path).exists() for item in reviewed)
    assert Path(clips[2]["source_path"]).exists()
    assert catalogue.clips() == snapshot
    assert catalogue.state("session") == session


@pytest.mark.parametrize("change", ["keep", "replace", "path", "missing"])
def test_changed_candidate_never_deleted(catalogue, clips, tmp_path, change):
    discard(catalogue, clips[:1])
    reviewed = preview(catalogue)
    path = Path(reviewed[0].path)
    if change == "keep":
        catalogue.patch(clips[0]["clip_id"], {"triage": "keep"})
    elif change == "replace":
        path.unlink()
        path.write_bytes(b"replacement")
    elif change == "missing":
        path.unlink()
    else:
        with catalogue.connection() as database:
            database.execute(
                "UPDATE clips SET source_path=? WHERE clip_id=?",
                (str(tmp_path / "different.mp4"), clips[0]["clip_id"]),
            )
    result = delete_reviewed(catalogue, reviewed)
    assert result[0][1].startswith("Skipped / failed")
    assert path.exists() == (change != "missing")


def test_partial_failure_cancel_and_missing(catalogue, clips):
    discard(catalogue, clips)
    Path(clips[0]["source_path"]).unlink()
    reviewed = preview(catalogue)
    assert reviewed[0].problem
    calls = []

    def denied(path, expected):
        calls.append(path)
        raise PermissionError("File locked")

    results = delete_reviewed(catalogue, reviewed, denied)
    assert len(calls) == 2
    assert not catalogue.hidden_deleted_ids()
    assert all(status.startswith("Skipped / failed") for path, status in results)
    results = delete_reviewed(catalogue, reviewed, denied, cancelled=lambda: True)
    assert all(status == "Cancelled; not deleted" for path, status in results)
    assert len(calls) == 2


@pytest.mark.skipif(os.name != "nt", reason="Windows handle deletion")
def test_open_writer_blocks_deletion(catalogue, clips):
    discard(catalogue, clips[:1])
    reviewed = preview(catalogue)
    with open(reviewed[0].path, "r+b"):
        result = delete_reviewed(catalogue, reviewed)
    assert result[0][1].startswith("Skipped / failed")
    assert Path(reviewed[0].path).exists()


def test_handle_rechecks_replacement(catalogue, clips):
    discard(catalogue, clips[:1])
    reviewed = preview(catalogue)[0]
    path = Path(reviewed.path)
    path.unlink()
    path.write_bytes(b"new file after path check")
    with pytest.raises(ValueError, match="changed since preview"):
        delete_original(reviewed.path, reviewed.signature)
    assert path.read_bytes() == b"new file after path check"


def test_junction_excluded(catalogue, clips, monkeypatch):
    discard(catalogue, clips[:1])
    monkeypatch.setattr(Path, "is_junction", lambda path: path.name == "captures")
    reviewed = preview(catalogue)
    assert "junctions" in reviewed[0].problem
    assert delete_reviewed(catalogue, reviewed)[0][1].startswith("Skipped / failed")
    assert Path(reviewed[0].path).exists()


def test_selected_source_delete_preserves_catalogue(catalogue, clips):
    catalogue.patch(clips[0]["clip_id"], {"triage": "keep"})
    snapshot = catalogue.clips()
    candidates = preview(catalogue, clip_id=clips[0]["clip_id"])
    assert len(candidates) == 1
    blocked = delete_reviewed(catalogue, candidates)
    assert "no longer discarded" in blocked[0][1]
    result = delete_reviewed(catalogue, candidates, require_discard=False)
    assert result[0][1] == "Deleted"
    assert not Path(clips[0]["source_path"]).exists()
    assert Path(clips[1]["source_path"]).exists()
    assert catalogue.clips() == snapshot


def test_version_four_upgrade_retains_missing_sources(catalogue, clips):
    Path(clips[0]["source_path"]).unlink()
    catalogue.create_session([clip["clip_id"] for clip in clips])
    session = catalogue.state("session")
    with catalogue.connection() as database:
        database.execute("DROP TABLE deleted_sources")
        database.execute("PRAGMA user_version=4")
    restarted = Catalogue(catalogue.path)
    assert restarted.clips() == clips
    assert restarted.state("session") == session
    assert restarted.hidden_deleted_ids() == set()
    assert restarted.rows("PRAGMA user_version")[0]["user_version"] == 6


@pytest.mark.parametrize("available_at_relink", [False, True])
def test_deleted_source_restart_and_migration(catalogue, clips, tmp_path, available_at_relink):
    clip_id = clips[0]["clip_id"]
    catalogue.patch(clip_id, {"mainline": "Retained", "triage": "keep", "in_ms": 10, "out_ms": 20})
    catalogue.create_session([clip_id])
    project = catalogue.save_project("Retained project")
    with catalogue.connection() as database:
        database.execute("INSERT INTO members VALUES (?, ?)", (project, clip_id))
    before = catalogue.clip(clip_id)
    result = delete_reviewed(catalogue, preview(catalogue, clip_id=clip_id), require_discard=False)
    assert result[0][1] == "Deleted"
    restarted = Catalogue(catalogue.path)
    assert restarted.hidden_deleted_ids() == {clip_id}
    destination = tmp_path / "migrated"
    destination.mkdir()
    if available_at_relink:
        (destination / Path(before["source_path"]).name).write_bytes(b"restored video")
    restarted.migrate(restarted.folders()[0]["folder_id"], destination)
    assert restarted.hidden_deleted_ids() == (set() if available_at_relink else {clip_id})
    restored = Path(restarted.clip(clip_id)["source_path"])
    restored.write_bytes(b"restored video")
    assert restarted.hidden_deleted_ids() == set()
    assert restarted.clip(clip_id) == {**before, "source_path": str(restored)}
    assert restarted.member_ids(project) == {clip_id}
    assert restarted.state("session")["ids"] == [clip_id]
    restored.unlink()
    assert Catalogue(catalogue.path).hidden_deleted_ids() == set()
