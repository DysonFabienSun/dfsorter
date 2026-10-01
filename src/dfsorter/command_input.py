from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QLineEdit, QStyle, QStyleOptionFrame

from .parsing import tokenize
from .theme import COLORS


@dataclass(frozen=True)
class Expansion:
    start: int
    end: int
    display: str
    matched: frozenset[int]


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


class CommandInput(QLineEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ghost_enabled = False
        self.ghost_game = None
        self._offset = 0
        self._drag_anchor = None
        self.textChanged.connect(self.update)
        self.cursorPositionChanged.connect(self.update)
        self.selectionChanged.connect(self.update)

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

    def _display(self):
        text = self.text()
        expansions = self.visible_expansions()
        display = []
        raw_positions = [0]
        raw_spans = []
        colors = []
        index = 0
        for expansion in expansions:
            while index < expansion.start:
                display.append(text[index])
                raw_spans.append((index, index + 1))
                colors.append("text_primary")
                index += 1
                raw_positions.append(index)
            midpoint = self.fontMetrics().horizontalAdvance(expansion.display) / 2
            width = 0
            for position, character in enumerate(expansion.display):
                display.append(character)
                raw_spans.append((expansion.start, expansion.end))
                colors.append("text_primary" if position in expansion.matched else "text_muted")
                width += self.fontMetrics().horizontalAdvance(character)
                raw_positions.append(expansion.start if width < midpoint else expansion.end)
            index = expansion.end
            raw_positions[-1] = index
        while index < len(text):
            display.append(text[index])
            raw_spans.append((index, index + 1))
            colors.append("text_primary")
            index += 1
            raw_positions.append(index)
        return "".join(display), colors, raw_positions, raw_spans, expansions

    def _text_rect(self):
        option = QStyleOptionFrame()
        self.initStyleOption(option)
        rect = self.style().subElementRect(QStyle.SubElement.SE_LineEditContents, option, self)
        return rect.adjusted(2, 0, -2, 0)

    def _positions(self, display):
        metrics = self.fontMetrics()
        positions = [0]
        for character in display:
            positions.append(positions[-1] + metrics.horizontalAdvance(character))
        return positions

    def _geometry(self):
        display, colors, raw_positions, raw_spans, expansions = self._display()
        positions = self._positions(display)
        rect = self._text_rect()
        cursor = self.cursorPosition()
        display_cursor = next(
            (index for index, raw in enumerate(raw_positions) if raw == cursor), len(display)
        )
        if positions[display_cursor] - self._offset > rect.width() - 2:
            self._offset = positions[display_cursor] - rect.width() + 2
        if positions[display_cursor] - self._offset < 0:
            self._offset = positions[display_cursor]
        self._offset = max(0, min(self._offset, max(0, positions[-1] - rect.width() + 2)))
        return (
            display,
            colors,
            raw_positions,
            raw_spans,
            expansions,
            positions,
            rect,
            display_cursor,
        )

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.visible_expansions():
            return
        display, colors, _, raw_spans, _, positions, rect, display_cursor = self._geometry()
        painter = QPainter(self)
        painter.setClipRect(rect)
        background = (
            COLORS["component_command_valid"]
            if self.property("validationState") == "valid"
            else COLORS["surface_control"]
        )
        painter.fillRect(rect, QColor(background))
        baseline = self.cursorRect().top() + self.fontMetrics().ascent()
        selection_start = self.selectionStart()
        selection_end = selection_start + len(self.selectedText()) if selection_start >= 0 else -1
        for index, character in enumerate(display):
            span_start, span_end = raw_spans[index]
            selected = (
                selection_start < span_end and span_start < selection_end
                if selection_start >= 0
                else False
            )
            character_rect = rect.adjusted(positions[index] - self._offset, 0, 0, 0)
            if selected:
                painter.fillRect(
                    character_rect.x(),
                    rect.y(),
                    positions[index + 1] - positions[index],
                    rect.height(),
                    QColor(COLORS["accent_selection"]),
                )
            painter.setPen(QColor(COLORS["text_primary"] if selected else COLORS[colors[index]]))
            painter.drawText(rect.x() + positions[index] - self._offset, baseline, character)
        if self.hasFocus():
            painter.setPen(QColor(COLORS["text_primary"]))
            caret_x = rect.x() + positions[display_cursor] - self._offset
            painter.drawLine(caret_x, rect.y() + 2, caret_x, rect.bottom() - 2)

    def _raw_at(self, x):
        display, _, raw_positions, _, _, positions, rect, _ = self._geometry()
        coordinate = x - rect.x() + self._offset
        for index in range(len(display)):
            if coordinate < (positions[index] + positions[index + 1]) / 2:
                return raw_positions[index]
        return raw_positions[-1]

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.visible_expansions():
            position = self._raw_at(event.position().x())
            self.setFocus()
            self._drag_anchor = position
            self.setCursorPosition(position)
            event.accept()
            return
        self._drag_anchor = None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_anchor is not None and event.buttons() & Qt.MouseButton.LeftButton:
            position = self._raw_at(event.position().x())
            self.setCursorPosition(self._drag_anchor)
            self.cursorForward(True, position - self._drag_anchor)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drag_anchor is not None:
            self._drag_anchor = None
            event.accept()
            return
        super().mouseReleaseEvent(event)
