"""Flexible local capture dates with a decorative current-year prefix."""

import re
from datetime import date

from PySide6.QtWidgets import QToolButton

from .ghost_input import Expansion, GhostInput

DATE_PATTERN = re.compile(r"(?:([0-9]{4})-)?([0-9]{1,2})-([0-9]{1,2})")


def parse_capture_date(text, *, today=None):
    text = text.strip()
    if not text:
        return None
    match = DATE_PATTERN.fullmatch(text)
    try:
        if match is None:
            raise ValueError
        year, month, day = match.groups()
        return date(int(year) if year else (today or date.today()).year, int(month), int(day))
    except ValueError:
        raise ValueError("Capture dates must be valid dates in YYYY-M-D or M-D format") from None


class DateInput(GhostInput):
    def visible_expansions(self):
        text = self.text()
        trimmed = text.strip()
        match = DATE_PATTERN.fullmatch(trimmed)
        if match is None or match.group(1):
            return []
        try:
            resolved = parse_capture_date(trimmed)
        except ValueError:
            return []
        prefix = f"{resolved.year:04d}-"
        start = len(text) - len(text.lstrip())
        if self.hasFocus() and self.cursorPosition() == start:
            return []
        return [Expansion(start, start, prefix, frozenset())]

    def _text_rect(self):
        rect = super()._text_rect()
        for button in self.findChildren(QToolButton):
            if button.isVisible():
                rect.setRight(min(rect.right(), button.x() - 2))
        return rect
