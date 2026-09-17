from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from dfsorter.catalogue import Catalogue, normalized
from dfsorter.config import Registry, title
from dfsorter.media import discover
from dfsorter.output import copy_one, export_project, safe_stem, share_clip, validate
from dfsorter.parsing import parse_command, query_clips


def test_canonical_patch_and_text(registry):
    patch = parse_command(
        '1V4 3K kj sheriff VANDAL sheriff R4 -- My  "Best" play! --  Notes  ', "VALORANT", registry
    )
    assert patch == {
        "metadata": {"clutch": 4, "kill": 3, "agent": "Killjoy", "weapon": ["Sheriff", "Vandal"]},
        "rating": 4,
        "mainline": 'My  "Best" play!',
        "description": "Notes",
    }
    assert parse_command("phantom", "VALORANT", registry) == {"metadata": {"weapon": ["Phantom"]}}


@pytest.mark.parametrize(
    "text",
    [
        "jett sage",
        "R0",
        "R6",
        "jett nonsense",
        "3k 4k",
        "jett -- title -- desc -- extra",
        '"unclosed',
    ],
)
def test_invalid_command(text, registry):
    with pytest.raises(ValueError):
        parse_command(text, "VALORANT", registry)


def test_freeform_and_quoted_boundaries(registry):
    trimmed = parse_command(
        'wpn:"  M4A1   SOPMOD  " --  Nice  shot  --  Notes  ', "Battlefield 6", registry
    )
    assert trimmed == {
        "metadata": {"weapon": ["M4A1   SOPMOD"]},
        "mainline": "Nice  shot",
        "description": "Notes",
    }
    assert parse_command('agent:"  Jett  "', "VALORANT", registry)["metadata"] == {"agent": "Jett"}
    with pytest.raises(ValueError):
        parse_command('wpn:"   "', "Battlefield 6", registry)
    patch = parse_command('wpn:M4A1   SOPMOD wpn:"R4" 3K -- title', "Battlefield 6", registry)
    assert patch["metadata"] == {"weapon": ["M4A1   SOPMOD", "R4"], "kill": 3}
    assert parse_command('"Tour de Force"', "VALORANT", registry)["metadata"]["weapon"] == [
        "Tour de Force"
    ]
    assert parse_command('wpn:"a -- b" R2', "Battlefield 6", registry)["metadata"]["weapon"] == [
        "a -- b"
    ]
    assert parse_command("R3 -- Player's moment", None, registry)["rating"] == 3
    with pytest.raises(ValueError):
        parse_command("1v3", "Battlefield 6", registry)


def test_invalid_config_is_reported(tmp_path):
    raw = {
        "name": "Test",
        "code": "TST",
        "aliases": [],
        "fields": {
            "agent": {"type": "enum", "values": ["One"], "aliases": {"same": "One"}},
            "weapon": {"type": "enum", "values": ["Two"], "aliases": {"same": "Two"}},
        },
        "display_order": ["agent", "weapon"],
        "required_for_export": [],
    }
    (tmp_path / "test.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    registry = Registry(tmp_path)
    assert registry.errors and not registry.games


def test_patch_undo_membership_and_live_session(catalogue, clips, registry):
    clip_id = clips[0]["clip_id"]
    project_id = catalogue.save_project("Montage")
    catalogue.set_state("active_project", project_id)
    ids = [clip["clip_id"] for clip in reversed(clips)]
    catalogue.create_session(ids)
    catalogue.navigate(1)
    catalogue.patch(clip_id, parse_command("jett vandal R5", "VALORANT", registry), editing=True)
    assert catalogue.clip(clip_id)["triage"] is None
    assert not catalogue.member_ids(project_id)
    catalogue.patch(clip_id, {"triage": "keep"}, editing=True)
    assert catalogue.member_ids(project_id) == {clip_id}
    catalogue.undo()
    assert catalogue.clip(clip_id)["triage"] is None
    assert not catalogue.member_ids(project_id)
    catalogue.undo(redo=True)
    catalogue.patch(clip_id, {"triage": "discard"}, editing=True)
    assert catalogue.member_ids(project_id) == {clip_id}
    reopened = Catalogue(catalogue.path)
    assert reopened.state("session") == {"ids": ids, "index": 1}
    assert reopened.clip(clip_id)["triage"] == "discard"
    with pytest.raises(ValueError):
        reopened.create_session(ids)


def test_game_change_and_hidden_fields(catalogue, clips, registry):
    clip_id = clips[0]["clip_id"]
    catalogue.patch(
        clip_id,
        {
            "metadata": {"agent": "Jett", "weapon": ["Vandal"], "old": "preserved"},
            "mainline": "Main",
            "rating": 3,
            "in_ms": 100,
            "out_ms": 200,
        },
    )
    assert "preserved" not in title(catalogue.clip(clip_id), registry)
    catalogue.patch(clip_id, {"game": "Battlefield 6", "metadata": {}}, replace_metadata=True)
    clip = catalogue.clip(clip_id)
    assert clip["metadata"] == {} and clip["mainline"] == "Main" and clip["in_ms"] == 100
    catalogue.undo()
    assert catalogue.clip(clip_id)["metadata"]["old"] == "preserved"


def test_missing_rescan_and_migration(catalogue, clips, tmp_path):
    first = clips[0]
    folder = catalogue.folders()[0]
    catalogue.patch(first["clip_id"], {"mainline": "Keep me"})
    catalogue.create_session([first["clip_id"]])
    Path(first["source_path"]).unlink()
    catalogue.ingest(folder["folder_id"], [])
    assert len(catalogue.clips()) == 3
    destination = tmp_path / "moved"
    destination.mkdir()
    catalogue.migrate(folder["folder_id"], destination)
    migrated = catalogue.clip(first["clip_id"])
    assert migrated["source_path"] == normalized(destination / Path(first["source_path"]).name)
    assert migrated["mainline"] == "Keep me"
    assert catalogue.state("session")["ids"] == [first["clip_id"]]


def test_migration_collision_is_atomic(catalogue, clips, tmp_path):
    folder = catalogue.folders()[0]
    other = tmp_path / "other"
    other.mkdir()
    other_id = catalogue.add_folder(other)
    catalogue.ingest(other_id, [{"path": str(other / "clip-0.mp4"), "game": None}])
    catalogue.remove_folder(other_id)
    before = catalogue.clips()
    with pytest.raises(ValueError, match="collide"):
        catalogue.migrate(folder["folder_id"], other)
    assert catalogue.clips() == before
    assert catalogue.folders()[0]["path"] == folder["path"]


def test_ranges_do_not_replace_valid_range(catalogue, clips):
    clip_id = clips[0]["clip_id"]
    catalogue.patch(clip_id, {"in_ms": 10, "out_ms": 200})
    with pytest.raises(ValueError):
        catalogue.patch(clip_id, {"in_ms": 300})
    assert catalogue.clip(clip_id)["in_ms"] == 10


def test_queries(catalogue, clips, registry):
    catalogue.patch(
        clips[0]["clip_id"],
        {
            "triage": "keep",
            "technical_condition": "LOW_FPS",
            "metadata": {"agent": "Jett", "weapon": ["Operator"], "kill": 4},
        },
    )
    assert (
        len(query_clips(catalogue.clips(), "game:val agent:jett weapon:op kill:>=4", registry)) == 1
    )
    assert (
        len(query_clips(catalogue.clips(), "technical_condition:low_fps triage:keep", registry))
        == 1
    )
    assert len(query_clips(catalogue.clips(), "clip-0", registry)) == 1
    with pytest.raises(ValueError, match="Rating"):
        query_clips(catalogue.clips(), "rating:5", registry)


def test_discovery_nearest_and_forced(tmp_path, registry, monkeypatch):
    monkeypatch.setattr(
        "dfsorter.media.inspect_media", lambda path: {"duration": 1, "created": None, "error": None}
    )
    root = tmp_path / "capture"
    nested = root / "valorant" / "tarkov" / "round"
    nested.mkdir(parents=True)
    (nested / "sample.MP4").write_bytes(b"test")
    assert discover(root, registry)[0]["game"] == "Escape from Tarkov"
    assert discover(root, registry, "Battlefield 6")[0]["game"] == "Battlefield 6"


def test_export_validation_and_preservation(catalogue, clips, registry, tmp_path):
    assert len(validate(clips, registry)) == 3
    for clip in clips:
        catalogue.patch(
            clip["clip_id"], {"triage": "keep", "metadata": {"agent": "Jett", "weapon": ["Vandal"]}}
        )
    clip_id = clips[0]["clip_id"]
    catalogue.patch(clip_id, {"in_ms": 100, "out_ms": 500, "rating": 4})
    before = {clip["source_path"]: Path(clip["source_path"]).read_bytes() for clip in clips}
    destination = tmp_path / "export"
    result = export_project(
        catalogue.clips(), registry, destination, catalogue.folders(), group_rating=True
    )
    assert not result.error and len(result.completed) == 3
    rated = next(Path(path) for path in result.completed if "Rating 4" in path)
    assert rated.read_bytes() == before[clips[0]["source_path"]]
    assert not list(destination.rglob("*.xmp"))
    assert all(Path(path).read_bytes() == content for path, content in before.items())
    again = export_project(
        catalogue.clips(), registry, destination, catalogue.folders(), group_rating=True
    )
    assert set(again.completed).isdisjoint(result.completed)
    catalogue.patch(clip_id, {"game": None})
    with pytest.raises(ValueError, match="configured game"):
        export_project(catalogue.clips(), registry, tmp_path / "blocked", catalogue.folders())
    assert not (tmp_path / "blocked").exists()


def test_copy_collision_cancel_and_share(catalogue, clips, registry, tmp_path):
    clip = deepcopy(clips[0])
    output = tmp_path / "output"
    output.mkdir()
    (output / "clip.xmp").write_bytes(b"previous")
    target = Path(copy_one(clip, output, "clip"))
    assert target.name == "clip.mp4"
    assert Path(copy_one(clip, output, "clip")).name == "clip (1).mp4"
    assert (output / "clip.xmp").read_bytes() == b"previous"
    clip["in_ms"], clip["out_ms"] = 1, 2
    with pytest.raises(InterruptedError):
        copy_one(clip, output, "cancelled", cancelled=lambda: True)
    assert not list(output.glob("cancelled*"))
    with pytest.raises(ValueError, match="outside"):
        share_clip(clip, registry, Path(clip["source_path"]).parent, catalogue.folders())
    assert safe_stem("CON") == "_CON"
    assert safe_stem("bad:name.") == "bad_name"


def test_partial_export_reports_completed(catalogue, clips, registry, tmp_path, monkeypatch):
    for clip in clips:
        catalogue.patch(
            clip["clip_id"], {"triage": "keep", "metadata": {"agent": "Jett", "weapon": ["Vandal"]}}
        )
    import dfsorter.output as output

    original = output.copy_one
    calls = []

    def interrupted(clip, *args, **kwargs):
        calls.append(clip["clip_id"])
        if len(calls) == 2:
            raise OSError("Simulated destination failure")
        return original(clip, *args, **kwargs)

    monkeypatch.setattr(output, "copy_one", interrupted)
    result = export_project(catalogue.clips(), registry, tmp_path / "export", catalogue.folders())
    assert len(result.completed) == 1
    assert result.error == "Simulated destination failure"
    assert Path(result.completed[0]).exists()
    assert len(list((tmp_path / "export").glob("*.mp4"))) == 1


def test_purge_only_catalogue(catalogue, clips):
    source = Path(clips[0]["source_path"])
    before = source.read_bytes()
    catalogue.create_session([clip["clip_id"] for clip in clips])
    project = catalogue.save_project("Project")
    catalogue.patch(clips[0]["clip_id"], {}, membership=(project, True))
    catalogue.remove_folder(catalogue.folders()[0]["folder_id"], purge=True)
    assert not catalogue.clips() and catalogue.state("session") is None
    assert not catalogue.member_ids(project)
    assert source.read_bytes() == before


def test_unquoted_multiword_enum(registry):
    assert parse_command("Tour de Force 3k", "VALORANT", registry)["metadata"] == {
        "weapon": ["Tour de Force"],
        "kill": 3,
    }
