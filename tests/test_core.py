from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from dfsorter.catalogue import Catalogue, normalized
from dfsorter.config import Registry, title
from dfsorter.media import discover
from dfsorter.output import copy_one, export_project, safe_stem, share_clip, validate
from dfsorter.parsing import parse_command, preview_command, query_clips


@pytest.mark.parametrize(
    "text,state,patch",
    [
        ("je", "typing", {}),
        ("agent:", "incomplete", {}),
        ("jett va", "typing", {"metadata": {"agent": "Jett"}}),
        ('jett tag:"unfinished', "incomplete", {"metadata": {"agent": "Jett"}}),
        ("jett R9", "invalid", {"metadata": {"agent": "Jett"}}),
        ("jett sage", "invalid", {"metadata": {"agent": "Jett"}}),
        ("nonsense jett", "invalid", {}),
        ("jett nonsense ", "invalid", {"metadata": {"agent": "Jett"}}),
        ('tag:""', "valid", {"tag": None}),
        ("jett -- Title", "valid", {"metadata": {"agent": "Jett"}, "mainline": "Title"}),
    ],
)
def test_command_preview(registry, text, state, patch):
    actual_patch, actual_state, _ = preview_command(text, "VALORANT", registry)
    assert (actual_patch, actual_state) == (patch, state)
    if state == "valid":
        assert actual_patch == parse_command(text, "VALORANT", registry)
    else:
        assert preview_command(text, "VALORANT", registry, submitted=True)[1] == "invalid"


def test_folder_case_and_disabled_sessions(catalogue, tmp_path):
    root = tmp_path / "MixedCASE"
    root.mkdir()
    folder_id = catalogue.add_folder(root)
    video = root / "VideoCASE.mp4"
    video.write_bytes(b"test")
    catalogue.ingest(folder_id, [{"path": str(video), "game": None}])
    clip = catalogue.clips()[0]
    assert catalogue.folders()[0]["path"] == str(root.resolve())
    assert clip["source_path"] == str(video.resolve())
    catalogue.create_session([clip["clip_id"]])
    session = catalogue.state("session")
    catalogue.enable_folder(folder_id, False)
    with pytest.raises(ValueError, match="disabled capture folders"):
        catalogue.create_session([clip["clip_id"]], replace=True)
    assert catalogue.state("session") == session
    catalogue.enable_folder(folder_id, True)
    catalogue.create_session([clip["clip_id"]], replace=True)
    catalogue.enable_folder(folder_id, False)
    catalogue.remove_folder(folder_id)
    assert not catalogue.clips()
    assert catalogue.state("session") is None
    assert video.exists()


def test_ingest_backfills_only_missing_game(catalogue, tmp_path):
    root = tmp_path / "captures"
    root.mkdir()
    folder_id = catalogue.add_folder(root)
    unassigned = root / "unassigned.mp4"
    assigned = root / "assigned.mp4"
    unassigned.write_bytes(b"unassigned")
    assigned.write_bytes(b"assigned")
    catalogue.ingest(
        folder_id,
        [
            {"path": str(unassigned), "game": None},
            {"path": str(assigned), "game": "VALORANT"},
        ],
    )
    with catalogue.connection() as database:
        database.execute("UPDATE clips SET catalogue_modified_at='before-rescan'")

    catalogue.ingest(
        folder_id,
        [
            {"path": str(unassigned), "game": "Counter-strike 2"},
            {"path": str(assigned), "game": "Counter-strike 2"},
        ],
    )

    clips = {Path(clip["source_path"]).name: clip for clip in catalogue.clips()}
    assert clips["unassigned.mp4"]["game"] == "Counter-strike 2"
    assert clips["unassigned.mp4"]["catalogue_modified_at"] != "before-rescan"
    assert clips["assigned.mp4"]["game"] == "VALORANT"
    assert clips["assigned.mp4"]["catalogue_modified_at"] == "before-rescan"


def test_legacy_path_case_migration(catalogue, tmp_path):
    import os

    if os.name != "nt":
        pytest.skip("Windows path casing")
    root = tmp_path / "MixedCASE"
    root.mkdir()
    video = root / "VideoCASE.mp4"
    video.write_bytes(b"test")
    folder_id = catalogue.add_folder(root)
    catalogue.ingest(folder_id, [{"path": str(video), "game": None}])
    clip_id = catalogue.clips()[0]["clip_id"]
    catalogue.create_session([clip_id])
    catalogue.cache_media(
        [
            dict(
                path=str(video.resolve()),
                size=4,
                mtime_ns=video.stat().st_mtime_ns,
                duration=1.5,
                created=None,
                error=None,
                inspected_at=1.0,
            )
        ]
    )
    missing = root / "MissingCASE.mp4"
    catalogue.ingest(folder_id, [{"path": str(missing), "game": None}])
    with catalogue.connection() as database:
        database.execute("UPDATE folders SET path=lower(path)")
        database.execute("UPDATE clips SET source_path=lower(source_path)")
        database.execute("UPDATE media_cache SET path=lower(path)")
        database.execute("PRAGMA user_version=2")
    restored = Catalogue(catalogue.path)
    assert restored.folders()[0]["path"] == str(root.resolve())
    assert restored.clip(clip_id)["source_path"] == str(video.resolve())
    assert restored.state("session")["ids"] == [clip_id]
    assert restored.media_cache()[str(video.resolve())]["duration"] == 1.5
    assert str(root.resolve() / "missingcase.mp4") in {
        clip["source_path"] for clip in restored.clips()
    }
    restored.ingest(folder_id, [{"path": str(video).lower(), "game": None}])
    assert len(restored.clips()) == 2
    with pytest.raises(ValueError, match="overlap"):
        restored.add_folder(str(root).lower())


@pytest.mark.parametrize("version", [1, 2, 3])
def test_tag_column_migration_preserves_catalogue(catalogue, clips, version):
    clip_id = clips[0]["clip_id"]
    project = catalogue.save_project("Saved project")
    catalogue.patch(
        clip_id,
        {"tag": "Favorite 精选", "rating": 4, "metadata": {"agent": "Jett"}},
        membership=(project, True),
    )
    catalogue.create_session([clip["clip_id"] for clip in clips])
    before = catalogue.clips()
    session = catalogue.state("session")
    with catalogue.connection() as database:
        database.execute("ALTER TABLE clips RENAME COLUMN tag TO technical_condition")
        database.execute(f"PRAGMA user_version = {version}")
    migrated = Catalogue(catalogue.path)
    assert migrated.clips() == before
    assert migrated.state("session") == session
    assert migrated.member_ids(project) == {clip_id}
    assert migrated.rows("PRAGMA user_version")[0]["user_version"] == 6
    assert Catalogue(catalogue.path).clips() == before
    migrated.patch(clip_id, {"tag": "Highlight"})
    migrated.undo()
    assert migrated.clip(clip_id)["tag"] == "Favorite 精选"
    migrated.undo(redo=True)
    assert migrated.clip(clip_id)["tag"] == "Highlight"
    migrated.patch(clip_id, {"tag": None})
    assert migrated.clip(clip_id)["tag"] is None


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


def test_cs2_config_and_weapon_aliases(registry):
    game = registry.game("Counter-strike 2")
    assert registry.resolve("CS2") == "Counter-strike 2"
    assert game.code == "CS2"
    assert game.suggested_fields == ["side", "weapon"]
    assert parse_command(
        "1v4 3k ct a1 a4 m4 scout fn57 taser d2 R4 -- retake",
        "Counter-strike 2",
        registry,
    ) == {
        "metadata": {
            "clutch": 4,
            "kill": 3,
            "side": "CT",
            "weapon": ["M4A1-S", "M4A4", "SSG08", "Five-SeveN", "Zeusx27"],
            "map": "Dust2",
        },
        "rating": 4,
        "mainline": "retake",
    }
    assert parse_command(
        "glock usp p2k dualies fiveseven 57 cz deagle revolver mac10 mp5 ump "
        "bizon mag7 sawedoff ak ak47 krieg scar",
        "Counter-strike 2",
        registry,
    ) == {
        "metadata": {
            "weapon": [
                "Glock18",
                "USP-S",
                "P2000",
                "DualBerettas",
                "Five-SeveN",
                "CZ75-Auto",
                "DesertEagle",
                "R8Revolver",
                "MAC-10",
                "MP5-SD",
                "UMP45",
                "PP-Bizon",
                "MAG-7",
                "Sawed-Off",
                "AK-47",
                "SG553",
                "SCAR-20",
            ]
        }
    }


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


def test_tag_commands_and_brim_alias(registry, catalogue, clips):
    patch = parse_command('tag:"Audio <issue>" brim R3 -- title', "VALORANT", registry)
    assert patch == {
        "tag": "Audio <issue>",
        "metadata": {"agent": "Brimstone"},
        "rating": 3,
        "mainline": "title",
    }
    assert parse_command("TAG:LOW_FPS R2", None, registry) == {
        "tag": "LOW_FPS",
        "rating": 2,
    }
    assert parse_command('tag:""', None, registry) == {"tag": None}
    assert parse_command("[3rd] R2", None, registry) == {"tag": "3rd", "rating": 2}
    assert parse_command("wpn:M4 [LOW_FPS]", "Battlefield 6", registry) == {
        "metadata": {"weapon": ["M4"]}, "tag": "LOW_FPS",
    }
    assert parse_command("wpn:M4 tag:LOW_FPS", "Battlefield 6", registry) == {
        "metadata": {"weapon": ["M4"]},
        "tag": "LOW_FPS",
    }
    for text in ["tag:", "tag:A tag:B", 'tag:"" tag:A', 'tag:"unclosed',
                 "[]", "[audio issue]", "[A] tag:B"]:
        with pytest.raises(ValueError):
            parse_command(text, "VALORANT", registry)
    catalogue.patch(clips[0]["clip_id"], patch)
    assert catalogue.tag_exists("AUDIO <ISSUE>")
    assert not catalogue.tag_exists("missing")
    assert (
        query_clips(catalogue.clips(), 'tag:"audio <issue>"', registry)[0]["clip_id"]
        == clips[0]["clip_id"]
    )
    with pytest.raises(ValueError):
        query_clips(catalogue.clips(), "tag:", registry)


def test_tag_lookup_uses_unicode_casefold(catalogue, clips):
    catalogue.patch(clips[0]["clip_id"], {"tag": "Straße"})
    assert catalogue.tag_exists("STRASSE")


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


def test_atomic_snapshot_commit_and_conflict(catalogue, clips):
    clip_id = clips[0]["clip_id"]
    project_id = catalogue.save_project("Atomic")
    baseline = catalogue.snapshot(clip_id)
    draft = catalogue.draft_snapshot(
        baseline,
        {"rating": 4, "mainline": "Staged", "metadata": {"agent": "Jett"}},
        membership=(project_id, True),
    )
    assert catalogue.clip(clip_id)["rating"] is None
    assert catalogue.member_ids(project_id) == set()
    history = list(catalogue.undo_stack)
    assert catalogue.commit_snapshot(baseline, baseline) is False
    assert catalogue.undo_stack == history
    assert catalogue.commit_snapshot(baseline, draft) is True
    assert catalogue.clip(clip_id)["mainline"] == "Staged"
    assert catalogue.member_ids(project_id) == {clip_id}
    assert len(catalogue.undo_stack) == len(history) + 1
    catalogue.undo()
    assert catalogue.clip(clip_id)["mainline"] is None
    assert catalogue.member_ids(project_id) == set()

    baseline = catalogue.snapshot(clip_id)
    draft = catalogue.draft_snapshot(baseline, {"rating": 5})
    catalogue.patch(clip_id, {"tag": "newer"})
    with pytest.raises(ValueError, match="changed outside Editing"):
        catalogue.commit_snapshot(baseline, draft)
    assert catalogue.clip(clip_id)["rating"] is None
    assert catalogue.clip(clip_id)["tag"] == "newer"


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
    catalogue.remove_folder(other_id, purge=False)
    before = catalogue.clips()
    with pytest.raises(ValueError, match="collide"):
        catalogue.migrate(folder["folder_id"], other)
    assert catalogue.clips() == before
    assert catalogue.folders()[0]["path"] == folder["path"]


def test_migration_collision_ignores_case_on_windows(catalogue, clips, tmp_path):
    import os

    if os.name != "nt":
        pytest.skip("Windows path identity")
    folder = catalogue.folders()[0]
    destination = tmp_path / "MixedCASE"
    destination.mkdir()
    other_id = catalogue.add_folder(destination)
    catalogue.ingest(other_id, [{"path": str(destination / "CLIP-0.mp4"), "game": None}])
    catalogue.remove_folder(other_id, purge=False)
    before = catalogue.clips()
    with pytest.raises(ValueError, match="collide"):
        catalogue.migrate(folder["folder_id"], destination)
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
            "tag": "LOW_FPS",
            "metadata": {"agent": "Jett", "weapon": ["Operator"], "kill": 4},
        },
    )
    assert (
        len(query_clips(catalogue.clips(), "game:val agent:jett weapon:op kill:>=4", registry)) == 1
    )
    assert len(query_clips(catalogue.clips(), "tag:low_fps triage:keep", registry)) == 1
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
    validation_errors = validate(clips, registry)
    assert len(validation_errors) == 3
    assert all("verdict is pending" in message for _, message in validation_errors)
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


def test_export_minimum_metadata_and_yaml_suggestions(catalogue, clips, registry):
    clip_id = clips[0]["clip_id"]
    assert registry.game("VALORANT").suggested_fields == ["agent", "weapon"]
    catalogue.patch(clip_id, {"triage": "keep", "tag": "3rd", "rating": 3,
                              "description": "comment"})
    assert "at least one metadata field or mainline" in validate(
        [catalogue.clip(clip_id)], registry
    )[0][1]
    catalogue.patch(clip_id, {"mainline": "Player clutch"})
    assert validate([catalogue.clip(clip_id)], registry) == []
    catalogue.patch(clip_id, {"mainline": None, "metadata": {"kill": 2}})
    assert validate([catalogue.clip(clip_id)], registry) == []


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


def test_remove_unlinked_preserves_surviving_session_position(catalogue, clips, tmp_path):
    folder = catalogue.folders()[0]
    ids = [clip["clip_id"] for clip in clips]
    catalogue.remove_folder(folder["folder_id"], purge=False)
    other = tmp_path / "other"
    other.mkdir()
    source = other / "kept.mp4"
    source.write_bytes(b"untouched")
    registered = catalogue.add_folder(other)
    catalogue.ingest(registered, [{"path": str(source), "game": None}])
    current = next(clip["clip_id"] for clip in catalogue.clips() if clip["clip_id"] not in ids)
    catalogue.create_session([ids[0], current, ids[1]], replace=True)
    catalogue.navigate(1)
    backup = catalogue.backup()
    catalogue.remove_unlinked(ids)
    assert catalogue.state("session") == {"ids": [current], "index": 0}
    assert catalogue.clip(current)["source_path"] == str(source.resolve())
    assert not catalogue.unlinked_clips()
    assert len(Catalogue(backup).clips()) == 4
    assert all(Path(clip["source_path"]).exists() for clip in clips)
    with pytest.raises(ValueError, match="linked"):
        catalogue.remove_unlinked([current])
    assert source.read_bytes() == b"untouched"


def test_unquoted_multiword_enum(registry):
    assert parse_command("Tour de Force 3k", "VALORANT", registry)["metadata"] == {
        "weapon": ["Tour de Force"],
        "kill": 3,
    }


@pytest.mark.parametrize("lowercase", [True, False])
def test_generated_title_casing(registry, catalogue, clips, tmp_path, monkeypatch, lowercase):
    clip_id = clips[0]["clip_id"]
    catalogue.patch(
        clip_id,
        {
            "triage": "keep",
            "mainline": "My <BEST>  中文",
            "metadata": {
                "kill": 4,
                "agent": "Clove",
                "map": "Corrode",
                "weapon": ["Phantom", "Vandal"],
            },
        },
    )
    clip = catalogue.clip(clip_id)
    before = deepcopy(clip)
    body = "4K Clove Corrode Phantom Vandal My <BEST>  中文"
    expected = "VAL_" + (body.lower() if lowercase else body)
    assert title(clip, registry, lowercase=lowercase) == expected
    assert "&lt;" in title(clip, registry, rich=True, lowercase=lowercase)
    result = export_project([clip], registry, tmp_path / "export", [], lowercase=lowercase)
    assert Path(result.completed[0]).stem == safe_stem(expected)
    assert Path(result.completed[0]).read_bytes() == Path(clip["source_path"]).read_bytes()
    received = []
    monkeypatch.setattr(
        "dfsorter.sharing.encode_share", lambda c, d, stem, *args: received.append(stem)
    )
    share_clip(clip, registry, tmp_path / "share", [], lowercase=lowercase)
    share_clip(clip, registry, tmp_path / "share", [], custom="My Custom NAME", lowercase=lowercase)
    assert received == [safe_stem(expected), "My Custom NAME"]
    assert clip == before == catalogue.clip(clip_id)
    fallback = {**clip, "metadata": {}, "mainline": None, "source_path": "Original NAME.MP4"}
    assert title(fallback, registry, lowercase=lowercase) == "VAL_Original NAME"
    assert title(clip, registry, selected=["kill"], prefix=False, lowercase=lowercase) == (
        "4k" if lowercase else "4K"
    )
