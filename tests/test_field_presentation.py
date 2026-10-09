import pytest

from dfsorter.config import Registry
from dfsorter.config_merge import merge
from dfsorter.parsing import parse_command, preview_command


@pytest.fixture
def empty_registry(tmp_path):
    return Registry(tmp_path, {"Empty.yaml": {
        "name": "Empty", "code": "EMP", "fields": {}, "display_order": ["mainline"],
    }})


@pytest.mark.parametrize("game", [None, "Missing", "Empty"])
@pytest.mark.parametrize("text,patch", [
    ("  R4 tag:example 3k  ", {"mainline": "R4 tag:example 3k"}),
    ('An "unfinished title', {"mainline": 'An "unfinished title'}),
    ('A "quoted -- phrase"', {"mainline": 'A "quoted -- phrase"'}),
    ("-- title", {"mainline": "title"}),
    (" -- title -- description ", {"mainline": "title", "description": "description"}),
    ("-- --", {"mainline": "", "description": ""}),
    (" ", {}),
])
def test_mainline_only_input(empty_registry, game, text, patch):
    assert parse_command(text, game, empty_registry) == patch
    assert preview_command(text, game, empty_registry)[0] == patch


@pytest.mark.parametrize("text", ["title -- description", "R4 -- title", "-- title -- description -- extra"])
def test_mainline_only_rejects_ambiguous_separators(empty_registry, text):
    with pytest.raises(ValueError):
        parse_command(text, "Empty", empty_registry)
    patch, state, message = preview_command(text, "Empty", empty_registry)
    assert state in {"incomplete", "invalid"}
    assert message and patch == {}


def test_explicit_fields_and_presentation_defaults(empty_registry, tmp_path):
    assert empty_registry.game("Empty").fields == {}
    assert empty_registry.game("Empty").review_fields == ["mainline", "rating", "tag"]
    raw = {"name": "Example", "code": "EX", "fields": {"kill": {}, "note": {"type": "freeform"}},
           "display_order": ["kill", "mainline"], "suggested_fields": ["note"],
           "field_order": ["note", "mainline", "kill", "tag", "rating"],
           "review_fields": ["note", "mainline"]}
    registry = Registry(tmp_path, {"Example.yaml": raw})
    game = registry.game("Example")
    assert not registry.errors
    assert game.display_order == ["mainline", "kill"]
    assert game.review_fields == ["note", "mainline"]
    raw["review_fields"] = []
    assert Registry(tmp_path, {"Example.yaml": raw}).errors


def test_presentation_keys_merge_without_losing_local_visibility():
    base = {"review_fields": ["kill", "mainline"], "field_order": ["kill", "mainline", "rating", "tag"]}
    local = {**base, "review_fields": ["mainline"]}
    incoming = {**base, "command_example": "3k"}
    assert merge(base, local, incoming) == {**local, "command_example": "3k"}
