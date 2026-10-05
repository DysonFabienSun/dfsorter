from datetime import date

import pytest
import test_ui
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QToolButton

from dfsorter import date_input
from dfsorter.date_input import DateInput, parse_capture_date
from dfsorter.theme import apply_theme

application = test_ui.application


@pytest.mark.parametrize(
    "text, today, expected",
    [
        ("", date(2026, 1, 1), None),
        ("3-7", date(2026, 1, 1), date(2026, 3, 7)),
        ("03-07", date(2027, 1, 1), date(2027, 3, 7)),
        (" 2025-3-7 ", date(2026, 1, 1), date(2025, 3, 7)),
        ("2026-03-7", date(2026, 1, 1), date(2026, 3, 7)),
        ("2-29", date(2028, 1, 1), date(2028, 2, 29)),
    ],
)
def test_parse_capture_date(text, today, expected):
    assert parse_capture_date(text, today=today) == expected


@pytest.mark.parametrize("text", ["3", "3-", "3-0", "2-29", "4-31", "13-1", "26-3-7", "2026-3-123"])
def test_invalid_capture_date(text):
    with pytest.raises(ValueError, match="valid dates"):
        parse_capture_date(text, today=date(2026, 1, 1))


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_date_ghost_during_typing_and_clicking(application, monkeypatch, theme):
    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 6)

    monkeypatch.setattr(date_input, "date", FixedDate)
    apply_theme(application, theme)
    control = DateInput()
    control.setClearButtonEnabled(True)
    control.resize(154, control.sizeHint().height())
    control.show()
    control.activateWindow()
    control.setFocus()
    application.processEvents()
    try:
        QTest.keyClicks(control, "3-")
        assert not control.visible_expansions()
        QTest.keyClicks(control, "1")
        assert control._display()[0] == "2026-3-1"
        assert control._display()[1] == ["text_muted"] * 5 + ["text_primary"] * 3
        QTest.keyClicks(control, "3")
        assert control._display()[0] == "2026-3-13"
        assert control.text() == "3-13"
        application.processEvents()
        clear = control.findChild(QToolButton)
        assert control._text_rect().right() < clear.x()
        assert abs(clear.geometry().center().y() - control.rect().center().y()) <= 1
        assert not control.grab().isNull()
        _, _, _, _, _, positions, rect, _ = control._geometry()
        # Every part of the inferred prefix maps to the raw date's start.
        for index in range(5):
            assert control._raw_at(rect.x() + (positions[index] + positions[index + 1]) / 2) == 0
        QTest.mouseClick(control, Qt.MouseButton.LeftButton,
                         pos=QPoint(rect.x() + positions[4], rect.center().y()))
        assert control.cursorPosition() == 0
        assert not control.visible_expansions()
        QTest.keyClick(control, Qt.Key.Key_End)
        assert control._display()[0] == "2026-3-13"
        control.selectAll()
        control.copy()
        assert application.clipboard().text() == "3-13"
        control.clearFocus()
        assert control._display()[0] == "2026-3-13"
        QTest.mouseClick(clear, Qt.MouseButton.LeftButton)
        assert control.text() == ""
        assert not control.visible_expansions()
        control.setText("2025-3-7")
        assert not control.visible_expansions()
    finally:
        control.close()
