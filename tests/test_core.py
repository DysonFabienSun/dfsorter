from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from dfsorter.catalogue import Catalogue, normalized
from dfsorter.config import Registry, source_fallback, title
from dfsorter.media import discover
from dfsorter.output import (
    copy_one,
    export_project,
    prepare_export_manifest,
    run_export_manifest,
    safe_stem,
    share_clip,
    validate,
)
from dfsorter.parsing import parse_command, parse_command_details, preview_command, query_clips


@pytest.mark.parametrize("kind", ["enum", "freeform"])
@pytest.mark.parametrize("token", ["WEAPON", "MAP", "WPN", "KILL", "TAG"])
@pytest.mark.parametrize("as_alias", [False, True])
def test_config_rejects_value_field_name_and_prefix_collisions(tmp_path, kind, token, as_alias):
    definition = {"type": kind, "values": ["MP5" if as_alias else token]}
    if as_alias:
        definition["aliases"] = {token: "MP5"}
    raw = {
        "name": "Example", "code": "EXM",
        "fields": {
            "weapon": definition,
            "map": {"type": "freeform", "prefixes": ["wpn"]},
        },
        "display_order": ["weapon", "map", "mainline"],
    }
    registry = Registry(tmp_path, {"Example.yaml": raw})
    assert registry.game("Example") is None
    assert len(registry.errors) == 1
    assert "conflicts with a field name or prefix" in registry.errors[0]


def test_shipped_game_configs_have_no_collisions(registry):
    assert not registry.errors
    assert len(registry.games) == len(list(registry.directory.glob("*.yaml")))


@pytest.mark.parametrize("alias,faction", [
    ("squid", "Illuminate"), ("squids", "Illuminate"),
    ("bugs", "Terminids"), ("bots", "Automatons"),
])
def test_helldivers_factions_and_difficulty(registry, alias, faction):
    game = registry.game("Helldivers 2")
    assert registry.resolve("hd2") == game.name
    assert game.suggested_fields == ["faction", "difficulty"]
    for difficulty in range(1, 11):
        patch = parse_command(f"{alias} diff:{difficulty} R4", game.name, registry)
        assert patch == {
            "metadata": {"faction": faction, "difficulty": str(difficulty)}, "rating": 4,
        }
        assert title({"game": game.name, "source_path": "clip.mp4", **patch}, registry) == (
            f"HD2_{faction.lower()} {difficulty}"
        )
    for difficulty in ("0", "11", "hard", "1.5"):
        with pytest.raises(ValueError):
            parse_command(f"diff:{difficulty}", game.name, registry)


def test_wardogs_kill_config(registry):
    game = registry.game("Wardogs")
    assert registry.resolve("wd") == game.name
    assert set(game.fields) == {"kill"}
    patch = parse_command("3k R5 -- last stand", game.name, registry)
    assert patch == {"metadata": {"kill": 3}, "rating": 5, "mainline": "last stand"}
    assert title({"game": game.name, "source_path": "clip.mp4", **patch}, registry) == (
        "WD_3k last stand"
    )


def test_delta_force_operations_config(registry):
    game = registry.game("Delta Force")
    assert registry.resolve("df") == game.name
    assert game.code == "DF"
    assert len(game.fields["weapon"]["values"]) == 68
    assert len(game.fields["operator"]["values"]) == 17
    assert len(game.fields["map"]["values"]) == 6
    assert game.fields["difficulty"]["values"] == ["常规", "机密", "绝密"]
    assert game.fields["map"]["aliases"] == {
        "大坝": "零号大坝", "溪谷": "长弓溪谷", "长弓": "长弓溪谷",
        "航天": "航天基地", "巴克": "巴克什", "监狱": "潮汐监狱",
        "核电站": "AZ3核电站", "AZ3": "AZ3核电站",
    }
    assert parse_command("R93 R4", game.name, registry) == {
        "metadata": {"weapon": ["R93"]}, "rating": 4,
    }
    with pytest.raises(ValueError, match="Rating must be R1 through R5"):
        parse_command("R6", game.name, registry)
    with pytest.raises(ValueError, match="Unknown metadata: R9"):
        parse_command("R9", game.name, registry)
    assert parse_command("3k 溪谷 红狼 diff:机密 腾龙 野牛 R4", game.name, registry) == {
        "metadata": {
            "kill": 3,
            "map": "长弓溪谷",
            "operator": "红狼",
            "difficulty": "机密",
            "weapon": ["CI-19", "Bizon"],
        },
        "rating": 4,
    }


def test_apex_weapon_roster_and_shortcuts(registry):
    game = registry.game("Apex Legends")
    weapon = game.fields["weapon"]
    assert len(weapon["values"]) == 30
    assert weapon["multiple"] is True
    assert weapon["aliases"] == {
        "r301": "R-301", "r99": "R-99", "car": "C.A.R.", "lstar": "L-STAR",
        "devo": "Devotion", "g7": "G7 Scout", "3030": "30-30 Repeater",
        "crifle": "Charge Rifle", "ev8": "EVA-8", "mozam": "Mozambique",
        "pk": "Peacekeeper", "re45": "RE-45", "smark": "Sniper's Mark",
    }
    assert "P2020" in weapon["values"]
    assert parse_command("wpn:30-30 repeater", game.name, registry) == {
        "metadata": {"weapon": ["30-30 Repeater"]},
    }
    assert parse_command("wraith r301 3030 smark R4", game.name, registry) == {
        "metadata": {
            "legend": "Wraith",
            "weapon": ["R-301", "30-30 Repeater", "Sniper's Mark"],
        },
        "rating": 4,
    }


@pytest.mark.parametrize("code, valid", [
    ("D", False), ("DF", True), ("DFO", True), ("DFOR", True),
    ("ABCDEF", True), ("ABC123", True), ("ABCDEFG", False), ("abcdef", False),
])
def test_game_display_code_length(tmp_path, code, valid):
    raw = {"name": "Example", "code": code, "fields": {"kill": {}},
           "display_order": ["kill", "mainline"]}
    registry = Registry(tmp_path, {"Example.yaml": raw})
    assert (registry.game("Example") is not None) is valid


def test_search_treats_r93_as_plain_text_and_r6_as_invalid_rating(registry):
    clips = [{
        "source_path": "R93 clip.mp4", "game": "Delta Force", "metadata": {"weapon": ["R93"]},
        "mainline": "", "description": "", "tag": None, "rating": None,
    }]
    assert query_clips(clips, "R93", registry) == clips
    with pytest.raises(ValueError, match="Rating comparison needs a value from R1 through R5"):
        query_clips(clips, "R6", registry)


@pytest.mark.parametrize(
    "text,state,patch",
    [
        ("je", "typing", {}),
        ("agent:", "incomplete", {}),
        ("jett va", "typing", {"metadata": {"agent": "Jett"}}),
        ('jett tag:"unfinished', "incomplete", {"metadata": {"agent": "Jett"}}),
        ("jett R6", "invalid", {"metadata": {"agent": "Jett"}}),
        ("jett R9", "typing", {"metadata": {"agent": "Jett"}}),
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


def test_new_sessions_accept_pending_clips_only(catalogue, clips):
    decided_id = clips[0]["clip_id"]
    pending_id = clips[1]["clip_id"]
    catalogue.patch(decided_id, {"triage": "keep"})

    with pytest.raises(ValueError, match="Only pending clips"):
        catalogue.create_session([decided_id])

    catalogue.create_session([pending_id])
    catalogue.patch(pending_id, {"triage": "discard"})
    assert catalogue.state("session")["ids"] == [pending_id]


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
    assert migrated.rows("PRAGMA user_version")[0]["user_version"] == 10
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


@pytest.mark.parametrize(
    ("command", "weapon"),
    [
        ("hh", "Headhunter"),
        ("tdf", "Tour de Force"),
        ("Headhunter", "Headhunter"),
        ("Tour de Force", "Tour de Force"),
    ],
)
def test_valorant_weapon_links_infer_chamber(registry, command, weapon):
    result = parse_command_details(command, "VALORANT", registry)
    assert result.patch == {"metadata": {"weapon": [weapon], "agent": "Chamber"}}
    assert result.inferred == [("agent", "Chamber")]


def test_field_links_respect_explicit_and_saved_values(registry):
    explicit = parse_command_details("jett hh", "VALORANT", registry)
    assert explicit.patch["metadata"]["agent"] == "Jett"
    assert explicit.inferred == []
    saved = parse_command_details(
        "tdf", "VALORANT", registry, existing_metadata={"agent": "Cypher"}
    )
    assert saved.patch == {"metadata": {"weapon": ["Tour de Force"]}}
    assert saved.inferred == []


def test_field_link_validation_rejects_cycles_and_conflicts(tmp_path):
    cyclic = {
        "name": "Test",
        "code": "TST",
        "fields": {
            "first": {"type": "enum", "values": ["One"], "links": {"One": {"second": "Two"}}},
            "second": {"type": "enum", "values": ["Two"], "links": {"Two": {"first": "One"}}},
        },
        "display_order": ["first", "second"],
    }
    config_path = tmp_path / "test.yaml"
    config_path.write_text(yaml.safe_dump(cyclic), encoding="utf-8")
    assert "cycles" in Registry(tmp_path).errors[0]

    conflicting = {
        "name": "Test",
        "code": "TST",
        "fields": {
            "trigger": {
                "type": "enum",
                "multiple": True,
                "values": ["One", "Two"],
                "links": {"One": {"result": "A"}, "Two": {"result": "B"}},
            },
            "result": {"type": "enum", "values": ["A", "B"]},
        },
        "display_order": ["trigger", "result"],
    }
    config_path.write_text(yaml.safe_dump(conflicting), encoding="utf-8")
    game_registry = Registry(tmp_path)
    with pytest.raises(ValueError, match="Conflicting inferred values"):
        parse_command_details("One Two", "Test", game_registry)


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
    assert parse_command("TAG:LOW_FPS R2", None, registry) == {"mainline": "TAG:LOW_FPS R2"}
    assert parse_command('tag:""', None, registry) == {"mainline": 'tag:""'}
    assert parse_command("[3rd] R2", None, registry) == {"mainline": "[3rd] R2"}
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


@pytest.mark.parametrize("map_value", ["woods", "streets", "Streets of Tarkov"])
def test_freeform_stops_at_bare_enum_phrase(registry, map_value):
    expected = "Streets of Tarkov" if "street" in map_value.lower() else "Woods"
    assert parse_command(f"wpn:M4A1 {map_value}", "Escape from Tarkov", registry) == {
        "metadata": {"weapon": ["M4A1"], "map": expected}
    }
    assert parse_command(f"wpn:M4A1 map:{map_value}", "Escape from Tarkov", registry) == {
        "metadata": {"weapon": ["M4A1"], "map": expected}
    }


def test_quoted_freeform_keeps_enum_words_and_valorant_awp_alias(registry):
    assert parse_command('wpn:"M4 Woods" streets', "Escape from Tarkov", registry) == {
        "metadata": {"weapon": ["M4 Woods"], "map": "Streets of Tarkov"}
    }
    assert parse_command("awp", "VALORANT", registry) == {
        "metadata": {"weapon": ["Operator"]}
    }


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
    catalogue.set_state("review_destination", project_id)
    ids = [clip["clip_id"] for clip in reversed(clips)]
    catalogue.create_session(ids)
    catalogue.navigate(1)
    catalogue.patch(clip_id, parse_command("jett vandal R5", "VALORANT", registry), editing=True)
    assert catalogue.clip(clip_id)["triage"] is None
    assert not catalogue.member_ids(project_id)
    catalogue.patch(clip_id, {"triage": "keep"}, editing=True, auto_add_destination=project_id)
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
    catalogue.patch(clips[0]["clip_id"], {"mainline": "Ace", "tag": "Highlight"})
    for term in ("highlight", "VAL_", "jett", "operator", "ace"):
        assert query_clips(catalogue.clips(), term, registry)[0]["clip_id"] == clips[0]["clip_id"]
    catalogue.patch(clips[0]["clip_id"], {"rating": 4})
    catalogue.patch(clips[1]["clip_id"], {"rating": 2})
    for expression in ("rating:4", "R4", "r4 agent:jett"):
        assert [clip["clip_id"] for clip in query_clips(catalogue.clips(), expression, registry)] == [
            clips[0]["clip_id"]
        ]
    assert query_clips(catalogue.clips(), "rating:5", registry) == []
    for expression, expected in (
        ("rating:>2", {clips[0]["clip_id"]}),
        ("rating:>=2", {clips[0]["clip_id"], clips[1]["clip_id"]}),
        ("rating:<4", {clips[1]["clip_id"]}),
        ("rating:<=4", {clips[0]["clip_id"], clips[1]["clip_id"]}),
        ("rating:=4", {clips[0]["clip_id"]}),
        ("rating:>=4 agent:jett", {clips[0]["clip_id"]}),
        ("rating:>4", set()),
    ):
        assert {clip["clip_id"] for clip in query_clips(catalogue.clips(), expression, registry)} == expected
    for expression in ("rating:", "rating:>=", "rating:0", "rating:>6", "r6"):
        with pytest.raises(ValueError, match="Rating comparison needs a value from R1 through R5"):
            query_clips(catalogue.clips(), expression, registry)


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
    rated = next(Path(path) for path in result.completed if Path(path).parent.name == "R4")
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


@pytest.mark.parametrize("rating, folder", [(1, "R1"), (2, "R2"), (3, "R3"),
                                          (4, "R4"), (5, "R5"), (None, "unrated")])
def test_grouped_export_rating_folder_names(catalogue, clips, registry, tmp_path, rating, folder):
    catalogue.patch(clips[0]["clip_id"], {
        "triage": "keep", "mainline": "Example", "rating": rating,
    })
    clip = catalogue.clip(clips[0]["clip_id"])
    manifest = prepare_export_manifest(
        [clip], registry, tmp_path / "output", catalogue.folders(), group_rating=True,
    )
    assert manifest["items"][0]["directory"] == folder
    catalogue.save_export_job("rating-folders", manifest, "Queued")
    result = run_export_manifest(catalogue, "rating-folders")
    assert result.error is None
    assert Path(result.completed[0]).parent == tmp_path / "output" / folder
    token = f"r{rating} " if rating is not None else ""
    assert Path(result.completed[0]).stem == f"VAL_{token}example"


@pytest.mark.parametrize("prefix, lowercase, include_rating", [
    (True, True, True), (False, True, True), (True, False, True),
    (True, True, False),
])
def test_export_rating_filename_choices(catalogue, clips, registry, tmp_path,
                                       monkeypatch, prefix, lowercase, include_rating):
    catalogue.patch(clips[0]["clip_id"], {
        "triage": "keep", "mainline": "Highlight", "rating": 5,
    })
    clip = catalogue.clip(clips[0]["clip_id"])
    before = deepcopy(clip)
    formats = {"VALORANT": {"fields": ["mainline"], "prefix": prefix}}
    expected = ("VAL_" if prefix else "")
    expected += ("r5 " if lowercase else "R5 ") if include_rating else ""
    expected += "highlight" if lowercase else "Highlight"
    manifest = prepare_export_manifest(
        [clip], registry, tmp_path / "queued", catalogue.folders(), formats,
        lowercase=lowercase, include_rating=include_rating,
    )
    assert manifest["items"][0]["stem"] == expected
    result = export_project(
        [clip], registry, tmp_path / "direct", catalogue.folders(), formats,
        lowercase=lowercase, include_rating=include_rating,
    )
    assert result.error is None
    assert Path(result.completed[0]).stem == expected
    assert Path(result.completed[0]).read_bytes() == Path(clip["source_path"]).read_bytes()
    assert title(clip, registry, ["mainline"], prefix, lowercase=lowercase) == (
        ("VAL_" if prefix else "") + ("highlight" if lowercase else "Highlight")
    )
    received = []
    monkeypatch.setattr(
        "dfsorter.sharing.encode_share", lambda c, d, stem, *args: received.append(stem)
    )
    share_clip(clip, registry, tmp_path / "share", [], fields=["mainline"],
               prefix=prefix, lowercase=lowercase)
    assert received == [("VAL_" if prefix else "") + ("highlight" if lowercase else "Highlight")]
    assert clip == before == catalogue.clip(clip["clip_id"])


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
    with pytest.raises(ValueError, match="outside"):
        share_clip(clip, registry, Path(clip["source_path"]).parent / "shares", catalogue.folders())
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


def test_resumable_export_verifies_completed_files_and_preserves_snapshot(
    catalogue, clips, registry, tmp_path, monkeypatch
):
    import dfsorter.output as output

    for clip in clips:
        catalogue.patch(clip["clip_id"], {
            "triage": "keep", "metadata": {"agent": "Jett"},
        })
    frozen = catalogue.clips()
    destination = tmp_path / "export"
    manifest = prepare_export_manifest(frozen, registry, destination, catalogue.folders())
    catalogue.save_export_job("resume-test", manifest, "Queued")
    original_copy = output._copy_resumable
    cancelled = False
    calls = []

    def copy_then_cancel(*args, **kwargs):
        nonlocal cancelled
        result = original_copy(*args, **kwargs)
        calls.append(result[0])
        cancelled = True
        return result

    monkeypatch.setattr(output, "_copy_resumable", copy_then_cancel)
    first = run_export_manifest(catalogue, "resume-test", lambda: cancelled)
    assert first.cancelled and len(first.completed) == 1
    completed_path = Path(first.completed[0])
    original_bytes = completed_path.read_bytes()
    assert catalogue.export_jobs()[0]["manifest"]["items"][0]["completed"]["sha256"]

    completed_path.write_bytes(b"x" * len(original_bytes))
    monkeypatch.setattr(output, "_copy_resumable", original_copy)
    reopened = Catalogue(catalogue.path)
    failed = run_export_manifest(reopened, "resume-test")
    assert "changed" in failed.error and not failed.completed
    assert len(list(destination.glob("*.mp4"))) == 1

    completed_path.write_bytes(original_bytes)
    # Later metadata changes cannot alter frozen filenames or membership.
    catalogue.patch(frozen[1]["clip_id"], {"mainline": "Changed later"})
    resumed = run_export_manifest(reopened, "resume-test")
    assert resumed.error is None and len(resumed.completed) == len(frozen)
    assert resumed.completed[0] == str(completed_path)
    assert len(list(destination.glob("*.mp4"))) == len(frozen)


def test_export_resume_rejects_new_capture_folder(catalogue, clips, registry, tmp_path):
    clip = clips[0]
    catalogue.patch(clip["clip_id"], {
        "triage": "keep", "metadata": {"agent": "Jett"},
    })
    destination = tmp_path / "exports" / "project"
    manifest = prepare_export_manifest(
        [catalogue.clip(clip["clip_id"])], registry, destination, catalogue.folders(),
    )
    catalogue.save_export_job("nested-output", manifest, "Queued")
    (tmp_path / "exports").mkdir()
    catalogue.add_folder(tmp_path / "exports")

    result = run_export_manifest(catalogue, "nested-output")

    assert result.error == "Output must be outside all configured capture folders"
    assert not destination.exists()


def test_parallel_export_jobs_never_overwrite_each_other(catalogue, clips, registry, tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    catalogue.patch(clips[0]["clip_id"], {
        "triage": "keep", "metadata": {"agent": "Jett"},
    })
    destination = tmp_path / "shared-destination"
    manifest = prepare_export_manifest(
        [catalogue.clip(clips[0]["clip_id"])], registry, destination, catalogue.folders(),
    )
    for job_id in ("parallel-a", "parallel-b"):
        catalogue.save_export_job(job_id, manifest, "Queued")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda job_id: run_export_manifest(catalogue, job_id),
                                ("parallel-a", "parallel-b")))
    assert all(result.error is None for result in results)
    paths = [result.completed[0] for result in results]
    assert len(set(paths)) == 2
    assert all(Path(path).read_bytes() == Path(clips[0]["source_path"]).read_bytes()
               for path in paths)


def test_export_resume_recovers_copy_published_before_manifest_commit(
    catalogue, clips, registry, tmp_path
):
    import hashlib

    catalogue.patch(clips[0]["clip_id"], {
        "triage": "keep", "metadata": {"agent": "Jett"},
    })
    manifest = prepare_export_manifest(
        [catalogue.clip(clips[0]["clip_id"])], registry,
        tmp_path / "export", catalogue.folders(),
    )
    item = manifest["items"][0]
    target = Path(manifest["destination"]) / f"{item['stem']}.mp4"
    target.parent.mkdir()
    data = Path(item["source_path"]).read_bytes()
    target.write_bytes(data)
    item["pending"] = {
        "target": str(target), "temporary": str(target.parent / "gone.part"),
        "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
    }
    catalogue.save_export_job("published-before-commit", manifest, "Running")
    result = run_export_manifest(Catalogue(catalogue.path), "published-before-commit")
    assert result.error is None and result.completed == [str(target)]
    assert len(list(target.parent.glob("*.mp4"))) == 1


def test_remove_folder_purges_catalogue_without_deleting_sources(catalogue, clips):
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


def test_remove_unavailable_keeps_available_clips_and_updates_references(catalogue, clips):
    missing = clips[0]
    surviving = clips[1]
    catalogue.create_session([missing["clip_id"], surviving["clip_id"]])
    project = catalogue.save_project("Saved")
    catalogue.patch(missing["clip_id"], {}, membership=(project, True))
    Path(missing["source_path"]).unlink()

    with pytest.raises(ValueError, match="availability changed"):
        catalogue.remove_unavailable([surviving["clip_id"]])
    backup = catalogue.backup()
    catalogue.remove_unavailable([missing["clip_id"]])

    assert catalogue.state("session") == {"ids": [surviving["clip_id"]], "index": 0}
    assert not catalogue.member_ids(project)
    assert surviving["clip_id"] in {item["clip_id"] for item in catalogue.clips()}
    assert missing["clip_id"] in {item["clip_id"] for item in Catalogue(backup).clips()}


def test_reassociate_unavailable_moves_only_matched_clip(catalogue, clips, tmp_path):
    missing = clips[0]
    surviving = clips[1]
    original = surviving["source_path"]
    replacement = tmp_path / "replacement"
    replacement.mkdir()
    target = replacement / Path(missing["source_path"]).name
    target.write_bytes(Path(missing["source_path"]).read_bytes())
    Path(missing["source_path"]).unlink()
    catalogue.patch(missing["clip_id"], {"mainline": "Retained"})
    catalogue.create_session([missing["clip_id"]])

    catalogue.reassociate_unavailable(
        {missing["clip_id"]: (missing["source_path"], str(target), None)}, replacement
    )

    assert catalogue.clip(missing["clip_id"])["source_path"] == str(target.resolve())
    assert catalogue.clip(missing["clip_id"])["mainline"] == "Retained"
    assert catalogue.clip(surviving["clip_id"])["source_path"] == original
    assert catalogue.state("session")["ids"] == [missing["clip_id"]]
    assert str(replacement.resolve()) in {folder["path"] for folder in catalogue.folders()}


def test_reassociate_rejects_existing_catalogue_identity(catalogue, clips, tmp_path):
    missing = clips[0]
    Path(missing["source_path"]).unlink()
    target = Path(clips[1]["source_path"])
    with pytest.raises(ValueError, match="already belong"):
        catalogue.reassociate_unavailable(
            {missing["clip_id"]: (missing["source_path"], str(target), None)}, target.parent
        )
    assert catalogue.clip(missing["clip_id"])["source_path"] == missing["source_path"]


def test_reassociate_rejects_file_changed_after_preview(catalogue, clips, tmp_path):
    missing = clips[0]
    Path(missing["source_path"]).unlink()
    replacement = tmp_path / "replacement"
    replacement.mkdir()
    target = replacement / Path(missing["source_path"]).name
    target.write_bytes(b"changed")

    with pytest.raises(ValueError, match="availability changed"):
        catalogue.reassociate_unavailable(
            {missing["clip_id"]: (missing["source_path"], str(target), 4)}, replacement
        )
    assert catalogue.clip(missing["clip_id"])["source_path"] == missing["source_path"]
    assert str(replacement.resolve()) not in {folder["path"] for folder in catalogue.folders()}


def test_unquoted_multiword_enum(registry):
    assert parse_command("Tour de Force 3k", "VALORANT", registry)["metadata"] == {
        "weapon": ["Tour de Force"],
        "kill": 3,
        "agent": "Chamber",
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
    cs2_fallback = {
        **fallback,
        "game": "Counter-strike 2",
        "source_path": "Counter-strike 2 2026.09.22.DVR.mp4",
    }
    assert title(cs2_fallback, registry, lowercase=lowercase) == "CS2_2026.09.22.DVR"
    cs2_fallback["source_path"] = "cs2_2026.09.22.DVR.mp4"
    assert title(cs2_fallback, registry, lowercase=lowercase) == "CS2_2026.09.22.DVR"
    assert source_fallback(
        cs2_fallback, registry.game("Counter-strike 2"), include_suffix=True
    ) == "2026.09.22.DVR.mp4"
    assert title(cs2_fallback, registry, prefix=False, lowercase=lowercase) == (
        "cs2_2026.09.22.DVR"
    )
    assert title(clip, registry, selected=["kill"], prefix=False, lowercase=lowercase) == (
        "4k" if lowercase else "4K"
    )
