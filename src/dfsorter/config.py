import re
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class Game:
    name: str
    code: str
    fields: dict
    display_order: list[str]
    required_for_export: list[str]
    values: dict[str, tuple[str, str]]
    prefixes: dict[str, str]
    command_example: str = ""


class Registry:
    def __init__(self, directory: Path):
        self.directory = directory
        self.games: dict[str, Game] = {}
        self.aliases: dict[str, str] = {}
        self.errors: list[str] = []
        if not list(directory.glob("*.yaml")):
            self.errors.append(f"No game YAML files found in {directory}")
        for path in sorted(directory.glob("*.yaml")):
            try:
                self._load(yaml.safe_load(path.read_text(encoding="utf-8")))
            except (
                OSError,
                ValueError,
                TypeError,
                KeyError,
                AttributeError,
                yaml.YAMLError,
            ) as error:
                self.errors.append(f"{path.name}: {error}")

    def _load(self, raw):
        name, code = raw["name"], raw["code"]
        if not isinstance(name, str) or not name.strip() or not re.fullmatch(r"[A-Z0-9]{3}", code):
            raise ValueError("Expected a game name and three-character uppercase display code")
        fields = raw["fields"]
        reserved = {
            "rating",
            "game",
            "triage",
            "mainline",
            "description",
            "technical_condition",
            "clip_id",
            "source_path",
            "in_ms",
            "out_ms",
            "catalogue_modified_at",
        }
        if not isinstance(fields, dict) or reserved.intersection(fields):
            raise ValueError("Fields must be a mapping without global clip field names")
        fields = {"kill": {}, **fields}
        values, prefixes = {}, {}
        for key, definition in fields.items():
            if not re.fullmatch(r"[a-z][a-z0-9_]*", key):
                raise ValueError(f"Invalid field key: {key}")
            if not isinstance(definition, dict):
                raise ValueError(f"{key}: field definition must be a mapping")
            if key in {"kill", "clutch"}:
                if definition.get("multiple"):
                    raise ValueError(f"{key}: reserved fields are scalar")
                continue
            if definition.get("type") not in {"enum", "freeform"}:
                raise ValueError(f"{key}: expected enum or freeform type")
            if not isinstance(definition.get("multiple", False), bool):
                raise ValueError(f"{key}: multiple must be boolean")
            for prefix in [key, *definition.get("prefixes", [])]:
                folded = prefix.casefold()
                if not re.fullmatch(r"[a-z][a-z0-9_]*", folded) or folded in reserved | {
                    "kill",
                    "clutch",
                }:
                    raise ValueError(f"Invalid or reserved prefix: {prefix}")
                if folded in prefixes and prefixes[folded] != key:
                    raise ValueError(f"Ambiguous prefix: {prefix}")
                prefixes[folded] = key
            canonical = definition.get("values", [])
            if definition["type"] == "enum" and not canonical:
                raise ValueError(f"{key}: enum needs values")
            for alias, value in [
                *((value, value) for value in canonical),
                *definition.get("aliases", {}).items(),
            ]:
                if value not in canonical:
                    raise ValueError(f"{alias}: unknown canonical value {value}")
                folded = alias.casefold()
                target = (key, value)
                if folded in values and values[folded] != target:
                    raise ValueError(f"Ambiguous alias: {alias}")
                if re.fullmatch(r"(\d+k|1v\d+|r\d+)", folded):
                    raise ValueError(f"Alias conflicts with reserved token: {alias}")
                values[folded] = target
        order = raw["display_order"]
        required = raw.get("required_for_export", [])
        if not isinstance(order, list) or not isinstance(required, list):
            raise ValueError("display_order and required_for_export must be lists")
        if len(order) != len(set(order)) or any(key not in {*fields, "mainline"} for key in order):
            raise ValueError("Invalid display_order")
        if any(key not in fields for key in required):
            raise ValueError("Unknown required_for_export field")
        aliases = [name, *raw.get("aliases", [])]
        if name in self.games or any(game.code == code for game in self.games.values()):
            raise ValueError("Duplicate game name or display code")
        if any(alias.casefold() in self.aliases for alias in aliases):
            raise ValueError("Game alias already used by another game")
        command_example = raw.get("command_example", "")
        if not isinstance(command_example, str):
            raise ValueError("command_example must be text")
        self.games[name] = Game(
            name, code, fields, order, required, values, prefixes, command_example
        )
        for alias in aliases:
            self.aliases[alias.casefold()] = name

    def resolve(self, value: str) -> str | None:
        return self.aliases.get(value.casefold())

    def game(self, name: str | None) -> Game | None:
        return self.games.get(name)


def title(
    clip: dict,
    registry: Registry,
    selected: list[str] | None = None,
    prefix: bool = True,
    rich: bool = False,
    mainline_separator: str = " ",
) -> str:
    import html

    game = registry.game(clip.get("game"))
    order = game.display_order if game else ["mainline"]
    parts = []
    previous_key = None
    for key in order:
        if selected is not None and key not in selected:
            continue
        value = clip.get("mainline") if key == "mainline" else clip["metadata"].get(key)
        if value is None or value == "" or value == []:
            continue
        if key == "kill":
            value = f"{value}K"
        elif key == "clutch":
            value = f"1v{value}"
        elif isinstance(value, list):
            value = " ".join(value)
        if parts:
            parts.append(mainline_separator if "mainline" in (previous_key, key) else " ")
        if rich:
            escaped = html.escape(str(value))
            parts.append(f"<b>{escaped}</b>" if key == "mainline" else escaped)
        else:
            parts.append(str(value))
        previous_key = key
    fallback = Path(clip["source_path"]).stem
    result = "".join(parts) or (html.escape(fallback) if rich else fallback)
    return f"{game.code}_{result}" if game and prefix else result
