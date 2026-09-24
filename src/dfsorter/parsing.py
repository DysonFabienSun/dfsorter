import re
from dataclasses import dataclass
from pathlib import Path

from .config import Registry, title


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
        patch["mainline"] = parts[1].strip()
    if len(parts) > 2:
        patch["description"] = parts[2].strip()
    game = registry.game(game_name)
    tokens = tokenize(parts[0])

    def assign(key, value):
        if key in {"rating", "tag"}:
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
            or lowered.startswith("tag:")
            or lowered.startswith("[")
            or (game and lowered.split(":", 1)[0] in game.prefixes and ":" in lowered)
        )

    def enum_boundary(start):
        if tokens[start].quoted:
            return False
        for end in range(start, len(tokens)):
            if any(item.quoted for item in tokens[start : end + 1]):
                break
            phrase = " ".join(item.value for item in tokens[start : end + 1]).casefold()
            resolved = game.values.get(phrase)
            if resolved and game.fields[resolved[0]]["type"] == "enum":
                return True
        return False

    index = 0
    while index < len(tokens):
        token = tokens[index].value.strip()
        folded = token.casefold()
        if folded.startswith("tag:"):
            value = token.split(":", 1)[1].strip()
            if not value and not tokens[index].quoted:
                raise ValueError('tag needs a value; use tag:"" to clear')
            assign("tag", value or None)
        elif token.startswith("[") or token.endswith("]"):
            if not re.fullmatch(r"\[[^\[\]\s]+\]", token):
                raise ValueError("Bracketed tags need one non-empty word without spaces")
            assign("tag", token[1:-1])
        elif re.fullmatch(r"r\d+", folded):
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
                while (
                    index + 1 < len(tokens)
                    and not recognized(tokens[index + 1])
                    and not enum_boundary(index + 1)
                ):
                    gap = parts[0][tokens[index].end : tokens[index + 1].start]
                    index += 1
                    value += gap + tokens[index].value
            else:
                consumed = index
                candidate = value.strip()
                resolved = game.values.get(candidate.casefold())
                for end in range(index + 1, len(tokens)):
                    candidate += " " + tokens[end].value
                    possible = game.values.get(candidate.casefold())
                    if possible and possible[0] == key:
                        resolved = possible
                        consumed = end
                if not resolved or resolved[0] != key:
                    raise ValueError(f"Unknown {key}: {value}")
                value = resolved[1]
                index = consumed
            value = value.strip()
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


def preview_command(text: str, game_name: str | None, registry: Registry, *, submitted=False):
    """Return a presentation-only patch, validation state and explanation."""
    if not text.strip():
        return {}, "empty", ""
    try:
        return parse_command(text, game_name, registry), "valid", "Enter to apply"
    except ValueError as error:
        message = str(error)
    patch = {}
    game = registry.game(game_name)
    missing_enum_value = bool(
        game and text.rstrip().endswith(":")
        and text.split()[-1][:-1].casefold() in game.prefixes
    )
    # Reuse the submission grammar: only fully parseable prefixes can contribute.
    for boundary in reversed(list(re.finditer(r"\s+", text))):
        try:
            patch = parse_command(text[:boundary.start()], game_name, registry)
            break
        except ValueError:
            continue
    if submitted:
        state = "invalid"
    elif message == "Unclosed quotation mark" or "needs a value" in message or missing_enum_value:
        state = "incomplete"
        if missing_enum_value:
            message = "Enter a value after the field prefix"
    elif message.startswith("Unknown "):
        # An unknown token still being typed is not an error until delimited.
        state = "invalid"
        if not text[-1].isspace():
            # Only defer errors if removing the final token leaves valid input.
            prefix = text.rsplit(None, 1)[0] if len(text.split()) > 1 else ""
            try:
                parse_command(prefix, game_name, registry)
            except ValueError:
                pass
            else:
                state = "typing"
    else:
        state = "invalid"
    return patch, state, "" if state == "typing" else message


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
                            clip.get("tag") or "",
                            title(clip, registry, lowercase=False),
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
        if key not in known_fields | {"game", "triage", "tag"}:
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
                elif key in {"triage", "tag"}:
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
