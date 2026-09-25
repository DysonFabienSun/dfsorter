import re
from dataclasses import dataclass
from pathlib import Path

import yaml

GLOBAL_FIELDS = {
    "rating", "game", "triage", "mainline", "description", "tag", "clip_id",
    "source_path", "in_ms", "out_ms", "catalogue_modified_at",
}


@dataclass
class Game:
    name: str
    code: str
    fields: dict
    display_order: list[str]
    suggested_fields: list[str]
    values: dict[str, tuple[str, str]]
    prefixes: dict[str, str]
    links: dict[str, dict[str, dict[str, object]]]
    command_example: str = ""


class Registry:
    def __init__(self, directory: Path, replacements: dict[str, object] | None = None):
        self.directory = directory
        self.games: dict[str, Game] = {}
        self.aliases: dict[str, str] = {}
        self.errors: list[str] = []
        paths = {path.name: path for path in directory.glob("*.yaml")}
        if replacements:
            paths.update({name: directory / name for name in replacements})
        if not paths:
            self.errors.append(f"No game YAML files found in {directory}")
        for name, path in sorted(paths.items()):
            try:
                raw = replacements[name] if replacements and name in replacements else yaml.safe_load(
                    path.read_text(encoding="utf-8")
                )
                self._load(raw)
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
        reserved = GLOBAL_FIELDS
        if not isinstance(fields, dict) or reserved.intersection(fields):
            raise ValueError("Fields must be a mapping without global clip field names")
        fields = {"kill": {}, **fields}
        values, prefixes, links = {}, {}, {}
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
            field_links = definition.get("links", {})
            if not isinstance(field_links, dict):
                raise ValueError(f"{key}: links must be a mapping")
            links[key] = field_links
        order = raw["display_order"]
        suggested = raw.get("suggested_fields", raw.get("required_for_export", []))
        if not isinstance(order, list) or not isinstance(suggested, list):
            raise ValueError("display_order and suggested_fields must be lists")
        if len(order) != len(set(order)) or any(key not in {*fields, "mainline"} for key in order):
            raise ValueError("Invalid display_order")
        if any(key not in fields for key in suggested):
            raise ValueError("Unknown suggested_fields field")
        normalized_links = {}
        for source_key, field_links in links.items():
            source_definition = fields[source_key]
            normalized_links[source_key] = {}
            for source_value, targets in field_links.items():
                if not isinstance(source_value, (str, int)) or not isinstance(targets, dict) or not targets:
                    raise ValueError(f"{source_key}: link entries need a source value and targets")
                if source_definition.get("type") == "enum" and source_value not in source_definition["values"]:
                    raise ValueError(f"{source_key}: unknown link source value {source_value}")
                normalized_targets = {}
                for target_key, target_value in targets.items():
                    if target_key not in fields:
                        raise ValueError(f"{source_key}: unknown link target field {target_key}")
                    target_definition = fields[target_key]
                    multiple = target_definition.get("multiple", False)
                    target_values = target_value if isinstance(target_value, list) else [target_value]
                    if multiple != isinstance(target_value, list):
                        expected = "a list" if multiple else "a scalar"
                        raise ValueError(f"{source_key}: {target_key} link target must be {expected}")
                    if target_definition.get("type") == "enum" and any(
                        value not in target_definition["values"] for value in target_values
                    ):
                        raise ValueError(f"{source_key}: unknown {target_key} link value")
                    if target_key in {"kill", "clutch"} and (
                        type(target_value) is not int or target_value < (0 if target_key == "kill" else 1)
                    ):
                        raise ValueError(f"{source_key}: invalid {target_key} link value")
                    normalized_targets[target_key] = target_value
                normalized_links[source_key][str(source_value).casefold()] = normalized_targets
        graph = {
            source: {target for targets in field_links.values() for target in targets}
            for source, field_links in normalized_links.items()
        }
        visiting, visited = set(), set()

        def check_cycle(field):
            if field in visiting:
                raise ValueError("Field links must not contain cycles")
            if field in visited:
                return
            visiting.add(field)
            for target in graph.get(field, set()):
                check_cycle(target)
            visiting.remove(field)
            visited.add(field)

        for field in graph:
            check_cycle(field)
        aliases = [name, *raw.get("aliases", [])]
        if name in self.games or any(game.code == code for game in self.games.values()):
            raise ValueError("Duplicate game name or display code")
        if any(alias.casefold() in self.aliases for alias in aliases):
            raise ValueError("Game alias already used by another game")
        command_example = raw.get("command_example", "")
        if not isinstance(command_example, str):
            raise ValueError("command_example must be text")
        self.games[name] = Game(
            name, code, fields, order, suggested, values, prefixes, normalized_links, command_example
        )
        for alias in aliases:
            self.aliases[alias.casefold()] = name

    def resolve(self, value: str) -> str | None:
        return self.aliases.get(value.casefold())

    def game(self, name: str | None) -> Game | None:
        return self.games.get(name)


def has_review_metadata(clip: dict, game: Game) -> bool:
    def populated(value):
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, list):
            return any(populated(item) for item in value)
        return value is not None

    return bool((clip.get("mainline") or "").strip()) or any(
        populated(value)
        for key, value in clip.get("metadata", {}).items()
        if key in game.fields
    )


def source_fallback(clip: dict, game: Game | None, *, include_suffix: bool = False) -> str:
    path = Path(clip["source_path"])
    fallback = path.name if include_suffix else path.stem
    if not game:
        return fallback
    for leading in (game.name, game.code):
        match = re.match(rf"{re.escape(leading)}(?=$|[\s._-])[\s._-]*", fallback, re.IGNORECASE)
        if match and match.end() < len(fallback):
            return fallback[match.end() :]
    return fallback


def title(
    clip: dict,
    registry: Registry,
    selected: list[str] | None = None,
    prefix: bool = True,
    rich: bool = False,
    mainline_separator: str = " ",
    *,
    lowercase: bool = True,
    rich_styles: dict[str, str] | None = None,
    underline_first_mainline_word: bool = False,
) -> str:
    import html

    def styled(text, role):
        if rich and rich_styles:
            return f'<span style="{rich_styles[role]}">{text}</span>'
        return text

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
            separator = mainline_separator if "mainline" in (previous_key, key) else " "
            parts.append(styled(html.escape(separator) if rich else separator, "separator"))
        value = str(value).lower() if lowercase else str(value)
        if rich:
            escaped = html.escape(value)
            if key == "mainline" and underline_first_mainline_word:
                escaped = re.sub(r"^(\s*)(\S+)", r"\1<u>\2</u>", escaped)
            if rich_styles:
                parts.append(styled(escaped, "mainline" if key == "mainline" else "metadata"))
            else:
                parts.append(f"<b>{escaped}</b>" if key == "mainline" else escaped)
        else:
            parts.append(value)
        previous_key = key
    fallback = source_fallback(clip, game if prefix else None)
    result = "".join(parts) or (html.escape(fallback) if rich else fallback)
    return (
        styled(html.escape(game.code + "_") if rich else game.code + "_", "prefix") + result
        if game and prefix
        else result
    )
