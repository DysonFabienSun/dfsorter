import re
from dataclasses import dataclass
from pathlib import Path

from .config import Registry


@dataclass
class Token:
    value: str
    quoted: bool = False
    start: int = 0
    end: int = 0


def segments(text: str) -> list[str]:
    result, start, quote = [], 0, None
    index = 0
    while index < len(text):
        character = text[index]
        if character in {'"', "'"}:
            if quote == character:
                quote = None
            elif quote is None and (
                index == 0 or text[index - 1].isspace() or text[index - 1] == ":"
            ):
                quote = character
        if quote is None and text[index : index + 2] == "--":
            result.append(text[start:index])
            start = index + 2
            index += 1
        index += 1
    if quote:
        raise ValueError("Unclosed quotation mark")
    result.append(text[start:])
    if len(result) > 3:
        raise ValueError("At most two unquoted -- separators are allowed")
    return result


def tokenize(text: str) -> list[Token]:
    result = []
    index = 0
    while index < len(text):
        if text[index].isspace():
            index += 1
            continue
        start = index
        value, quote, quoted = "", None, False
        while index < len(text):
            character = text[index]
            if quote:
                if character == quote:
                    quote = None
                else:
                    value += character
            elif character in {'"', "'"} and (index == start or text[index - 1] == ":"):
                quote, quoted = character, True
            elif character.isspace():
                break
            else:
                value += character
            index += 1
        if quote:
            raise ValueError("Unclosed quotation mark")
        result.append(Token(value, quoted, start, index))
    return result


def parse_command(text: str, game_name: str | None, registry: Registry) -> dict:
    parts = segments(text)
    patch, metadata = {}, {}
    if len(parts) > 1:
        patch["mainline"] = parts[1]
    if len(parts) > 2:
        patch["description"] = parts[2]
    game = registry.game(game_name)
    tokens = tokenize(parts[0])

    def assign(key, value):
        if key == "rating":
            target = patch
            multiple = False
        else:
            target = metadata
            multiple = game.fields[key].get("multiple", False)
        if multiple:
            current = target.setdefault(key, [])
            if str(value).casefold() not in [str(item).casefold() for item in current]:
                current.append(value)
        elif key in target and target[key] != value:
            raise ValueError(f"Conflicting values for {key}")
        else:
            target[key] = value

    def recognized(token):
        lowered = token.value.casefold()
        if token.quoted and ":" not in lowered:
            return False
        return bool(
            re.fullmatch(r"(\d+k|1v\d+|r\d+)", lowered)
            or (game and lowered.split(":", 1)[0] in game.prefixes and ":" in lowered)
        )

    index = 0
    while index < len(tokens):
        token = tokens[index].value
        folded = token.casefold()
        if re.fullmatch(r"r\d+", folded):
            rating = int(folded[1:])
            if rating not in range(1, 6):
                raise ValueError("Rating must be R1 through R5")
            assign("rating", rating)
        elif not game:
            raise ValueError("Assign a configured game before entering structured metadata")
        elif re.fullmatch(r"\d+k", folded):
            if "kill" not in game.fields:
                raise ValueError("This game has no kill field")
            assign("kill", int(folded[:-1]))
        elif re.fullmatch(r"1v\d+", folded):
            if "clutch" not in game.fields:
                raise ValueError("This game has no clutch field")
            assign("clutch", int(folded[2:]))
        elif ":" in token:
            prefix, value = token.split(":", 1)
            key = game.prefixes.get(prefix.casefold())
            if key is None:
                raise ValueError(f"Unknown field prefix: {prefix}")
            definition = game.fields[key]
            if definition["type"] == "freeform":
                while index + 1 < len(tokens) and not recognized(tokens[index + 1]):
                    gap = parts[0][tokens[index].end : tokens[index + 1].start]
                    index += 1
                    value += gap + tokens[index].value
            else:
                resolved = game.values.get(value.casefold())
                if not resolved or resolved[0] != key:
                    raise ValueError(f"Unknown {key}: {value}")
                value = resolved[1]
            if not value:
                raise ValueError(f"{key} needs a value")
            assign(key, value)
        else:
            resolved = game.values.get(folded)
            consumed = index
            for end in range(index + 1, len(tokens)):
                phrase = " ".join(item.value for item in tokens[index : end + 1]).casefold()
                if phrase in game.values:
                    resolved = game.values[phrase]
                    consumed = end
            if resolved is None:
                raise ValueError(f"Unknown metadata: {token}")
            assign(*resolved)
            index = consumed
        index += 1
    if metadata:
        patch["metadata"] = metadata
    return patch


def query_clips(clips: list[dict], expression: str, registry: Registry) -> list[dict]:
    terms = [token.value for token in tokenize(expression)]
    tests = []
    known_fields = {key for game in registry.games.values() for key in game.fields}
    for term in terms:
        if ":" not in term:
            needle = term.casefold()
            tests.append(
                lambda clip, needle=needle: (
                    needle
                    in " ".join(
                        [
                            Path(clip["source_path"]).name,
                            clip.get("mainline") or "",
                            clip.get("description") or "",
                        ]
                    ).casefold()
                )
            )
            continue
        key, value = term.split(":", 1)
        key = key.casefold()
        if key == "rating":
            raise ValueError("Rating is not searchable or filterable")
        if key not in known_fields | {"game", "triage", "technical_condition"}:
            raise ValueError(f"Unknown query field: {key}")
        if not value:
            raise ValueError(f"{key} needs a query value")
        if key in {"kill", "clutch"}:
            match = re.fullmatch(r"(>=|<=|>|<|=)?(\d+)", value)
            if not match:
                raise ValueError(f"Invalid numeric comparison: {term}")
            operator, number = match[1] or "=", int(match[2])

            def numeric(clip, key=key, operator=operator, number=number):
                stored = clip["metadata"].get(key)
                if not isinstance(stored, int):
                    return False
                return {
                    "=": stored == number,
                    ">": stored > number,
                    "<": stored < number,
                    ">=": stored >= number,
                    "<=": stored <= number,
                }[operator]

            tests.append(numeric)
        else:

            def matches(clip, key=key, value=value):
                expected = value.casefold()
                if key == "game":
                    actual = clip["game"]
                    expected = (registry.resolve(value) or value).casefold()
                elif key in {"triage", "technical_condition"}:
                    actual = clip[key] or ("undefined" if key == "triage" else "")
                else:
                    game = registry.game(clip["game"])
                    if game is None or key not in game.fields:
                        return False
                    actual = clip["metadata"].get(key)
                    resolved = game.values.get(expected)
                    if resolved and resolved[0] == key:
                        expected = resolved[1].casefold()
                values = actual if isinstance(actual, list) else [actual]
                return any(str(item).casefold() == expected for item in values)

            tests.append(matches)
    return [clip for clip in clips if all(test(clip) for test in tests)]


def requests_discarded(expression):
    return any(token.value.casefold() == "triage:discard" for token in tokenize(expression))
