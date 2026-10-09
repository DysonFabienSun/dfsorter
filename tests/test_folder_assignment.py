import sqlite3

import pytest

from dfsorter.catalogue import Catalogue
from dfsorter.media import discover_paths
from dfsorter.scanning import ScanCoordinator


def test_modes_and_existing_assignments(catalogue, registry, tmp_path):
    root = tmp_path / "VAL"
    nested = root / "wonderfulVideos123" / "uuid"
    nested.mkdir(parents=True)
    (nested / "clip.mp4").touch()
    folder_id = catalogue.add_folder(root, assignment_mode="unclassified")
    found = discover_paths(root, registry, assignment_mode="unclassified")
    assert found[0]["game"] is None
    catalogue.ingest(folder_id, found)
    assert discover_paths(root, registry)[0]["game"] == "VALORANT"
    catalogue.set_folder_assignment(folder_id, "single_game", "Battlefield 6", games=registry.games)
    catalogue.ingest(folder_id, discover_paths(root, registry, "Battlefield 6"))
    assert catalogue.clips()[0]["game"] == "Battlefield 6"
    catalogue.set_folder_assignment(folder_id, "automatic", games=registry.games)
    catalogue.ingest(folder_id, discover_paths(root, registry))
    assert catalogue.clips()[0]["game"] == "Battlefield 6"
    catalogue.set_folder_assignment(folder_id, "unclassified", games=registry.games)
    catalogue.ingest(folder_id, found)
    assert catalogue.clips()[0]["game"] == "Battlefield 6"
    assert Catalogue(catalogue.path).folders()[0]["assignment_mode"] == "unclassified"
    for mode, game in [("bad", None), ("single_game", None), ("single_game", "Missing")]:
        with pytest.raises(ValueError):
            catalogue.set_folder_assignment(folder_id, mode, game, games=registry.games)
    assert catalogue.folders()[0]["assignment_mode"] == "unclassified"


def test_version_nine_folder_migration(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as database:
        database.execute("CREATE TABLE folders (folder_id TEXT PRIMARY KEY, path TEXT UNIQUE NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, forced_game TEXT)")
        database.executemany("INSERT INTO folders VALUES (?,?,?,?)", [
            ("auto", str(tmp_path / "auto"), 1, None),
            ("single", str(tmp_path / "single"), 0, "VALORANT"),
        ])
        database.execute("PRAGMA user_version=9")
    catalogue = Catalogue(path)
    folders = {folder["folder_id"]: folder for folder in catalogue.folders()}
    assert folders["auto"]["assignment_mode"] == "automatic"
    assert folders["single"]["assignment_mode"] == "single_game"
    assert folders["single"]["enabled"] == 0
    assert Catalogue(path).folders() == catalogue.folders()


def test_relink_retains_assignment(catalogue, registry, tmp_path):
    root = tmp_path / "original"
    root.mkdir()
    folder_id = catalogue.add_folder(root, "VALORANT")
    destination = tmp_path / "moved"
    root.rename(destination)
    catalogue.migrate(folder_id, destination)
    folder = catalogue.folders()[0]
    assert folder["assignment_mode"] == "single_game"
    assert folder["forced_game"] == "VALORANT"
    assert folder["path"] == str(destination.resolve())


def test_missing_game_skips_cleanup_and_rule_changes_reuse_cache(catalogue, registry, tmp_path, monkeypatch):
    root = tmp_path / "captures"
    root.mkdir()
    video = root / "clip.mp4"
    video.touch()
    folder_id = catalogue.add_folder(root)
    monkeypatch.setattr("dfsorter.scanning.tool", lambda name: "ffprobe")
    monkeypatch.setattr("dfsorter.scanning.inspect_media", lambda *args: dict(duration=1, created=None, error=None, hdr=0))
    ScanCoordinator(catalogue, registry).run(catalogue.folders())
    catalogue.set_folder_assignment(folder_id, "single_game", "VALORANT", games=registry.games)
    result = ScanCoordinator(catalogue, registry).run(catalogue.folders())
    assert result[2]["probes"] == 0
    assert catalogue.clips()[0]["game"] == "VALORANT"
    video.unlink()
    registry.games.pop("VALORANT")
    result = ScanCoordinator(catalogue, registry).run(catalogue.folders())
    assert any("configuration unavailable" in error for error in result[1])
    assert len(catalogue.clips()) == 1
