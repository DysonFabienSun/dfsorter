"""Round-trip YAML storage for the graphical game configuration editor."""

import hashlib
import io
import os
import re
import tempfile
from collections import Counter
from copy import deepcopy
from pathlib import Path

from ruamel.yaml import YAML

from .config import Registry

TOP_KEYS = {
    "name",
    "code",
    "aliases",
    "fields",
    "display_order",
    "suggested_fields",
    "required_for_export",
    "command_example",
}
FIELD_KEYS = {"type", "multiple", "prefixes", "values", "aliases", "links"}


def yaml_parser():
    parser = YAML(typ="rt")
    parser.preserve_quotes = True
    parser.width = 120
    return parser


def plain(value):
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [plain(item) for item in value]
    return value


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def validate_candidate(directory, filename, candidate):
    before = Counter(Registry(directory).errors)
    after = Registry(directory, {filename: plain(candidate)})
    added = list((Counter(after.errors) - before).elements())
    if added:
        raise ValueError("\n".join(added))
    if not any(game.name == candidate.get("name") for game in after.games.values()):
        raise ValueError("Game definition could not be loaded")


def merge_mapping(document, draft, known_keys):
    for key in known_keys:
        if key not in draft:
            document.pop(key, None)
        elif key == "fields" and isinstance(document.get(key), dict):
            old_fields = document[key]
            for removed in set(old_fields) - set(draft[key]):
                del old_fields[removed]
            for field, definition in draft[key].items():
                if field in old_fields and isinstance(old_fields[field], dict):
                    merge_mapping(old_fields[field], definition, FIELD_KEYS)
                else:
                    old_fields[field] = deepcopy(definition)
        elif plain(document.get(key)) != draft[key]:
            document[key] = deepcopy(draft[key])
    return document


class GameFile:
    def __init__(self, path: Path):
        self.path = path
        self.digest = fingerprint(path)
        self.parse_error = None
        try:
            self.text = path.read_text(encoding="utf-8") if path.exists() else ""
        except UnicodeDecodeError:
            self.text = path.read_bytes().decode("utf-8", errors="replace")
            self.parse_error = "File is not UTF-8. Replace invalid characters before saving."
        try:
            self.document = (
                yaml_parser().load(self.text) if self.text and not self.parse_error else None
            )
        except Exception as error:
            self.document = None
            self.parse_error = str(error)

    def draft(self):
        if self.parse_error:
            raise ValueError(self.parse_error)
        if not isinstance(self.document, dict):
            raise ValueError("Game YAML must contain a mapping")
        return {key: plain(value) for key, value in self.document.items() if key in TOP_KEYS}

    def save(self, draft, directory, *, raw_text=None):
        if fingerprint(self.path) != self.digest:
            raise ValueError("The YAML file changed outside DFSorter. Reload it before saving.")
        if raw_text is None:
            document = deepcopy(self.document) if self.document is not None else {}
            merge_mapping(document, draft, TOP_KEYS)
            stream = io.StringIO()
            yaml_parser().dump(document, stream)
            output = stream.getvalue()
        else:
            output = raw_text
            document = yaml_parser().load(output)
            if not isinstance(document, dict):
                raise ValueError("Game YAML must contain a mapping")
            if (
                isinstance(self.document, dict)
                and isinstance(self.document.get("name"), str)
                and document.get("name") != self.document["name"]
            ):
                raise ValueError("Canonical names of existing games cannot be changed")
        validate_candidate(directory, self.path.name, document)
        if self.digest is None and self.path.exists():
            raise ValueError("A game file with this name already exists")
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                suffix=".tmp",
                prefix=f".{self.path.stem}-",
                dir=directory,
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(output)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
        self.__init__(self.path)


def new_game_path(directory, name):
    if not name or name != name.strip() or re.search(r'[<>:"/\\|?*\x00-\x1f]', name):
        raise ValueError("Game name contains characters that cannot be used in a filename")
    reserved = {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
    if name.endswith((".", " ")) or name.casefold().split(".")[0] in reserved:
        raise ValueError("Game name cannot be used as a filename")
    path = directory / f"{name}.yaml"
    if any(
        candidate.name.casefold() == path.name.casefold() for candidate in directory.glob("*.yaml")
    ):
        raise ValueError("A game file with this name already exists")
    return path
