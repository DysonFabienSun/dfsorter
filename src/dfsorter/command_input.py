from .ghost_input import Expansion, GhostInput
from .parsing import tokenize


def _matched_letters(alias: str, display: str) -> frozenset[int]:
    positions = []
    search_from = 0
    for letter in alias.casefold():
        position = display.find(letter, search_from)
        if position < 0:
            return frozenset()
        positions.append(position)
        search_from = position + 1
    return frozenset(positions)


def command_expansions(text: str, game) -> list[Expansion]:
    if game is None:
        return []
    structured_end = len(text)
    quote = None
    for index, character in enumerate(text):
        if character in {'"', "'"} and (
            quote == character
            or quote is None
            and (index == 0 or text[index - 1].isspace() or text[index - 1] == ":")
        ):
            quote = None if quote == character else character
        if quote is None and text[index : index + 2] == "--":
            structured_end = index
            break
    try:
        tokens = tokenize(text[:structured_end])
    except ValueError:
        return []
    expansions = []
    for token in tokens:
        if token.quoted:
            continue
        value = token.value
        start = token.start
        field = None
        if ":" in value:
            prefix, value = value.split(":", 1)
            field = game.prefixes.get(prefix.casefold())
            start += len(prefix) + 1
            if not field:
                continue
        resolved = game.values.get(value.casefold())
        if not resolved or field and resolved[0] != field:
            continue
        definition = game.fields[resolved[0]]
        if value.casefold() not in {alias.casefold() for alias in definition.get("aliases", {})}:
            continue
        display = resolved[1].lower()
        expansions.append(Expansion(start, token.end, display, _matched_letters(value, display)))
    return expansions


class CommandInput(GhostInput):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ghost_enabled = False
        self.ghost_game = None

    def set_ghost_context(self, enabled, game):
        self.ghost_enabled = enabled
        self.ghost_game = game
        self.update()

    def visible_expansions(self):
        if not self.ghost_enabled:
            return []
        cursor = self.cursorPosition() if self.hasFocus() else -1
        return [
            expansion
            for expansion in command_expansions(self.text(), self.ghost_game)
            if not (expansion.start <= cursor <= expansion.end)
        ]
