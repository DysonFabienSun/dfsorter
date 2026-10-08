import os
import shutil
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")

import PySide6
import pytest
import yaml
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QColor, QCursor, QImage, QKeyEvent, QMouseEvent, QPainter, QTextDocument
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStyle,
    QStyleOptionComboBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from dfsorter.catalogue import Catalogue
from dfsorter.command_input import CommandInput, command_expansions
from dfsorter.deletion import preview
from dfsorter.deletion_dialog import DeletionDialog
from dfsorter.settings_dialog import SettingsDialog
from dfsorter.theme import COLORS, FONT_SIZES, symbol_text
from dfsorter.tips import TipWidget
from dfsorter.ui import ROOT, Window, style_application
from dfsorter.unavailable_dialog import UnavailableClipsDialog
from dfsorter.update_ui import UpdateController
from dfsorter.widgets import CLIP_ROLE, FOLDER_ROLE, CaptureFolderDelegate, VerdictBar, icon


@pytest.fixture(scope="module")
def application():
    QCoreApplication.addLibraryPath(str(Path(PySide6.__file__).parent / "plugins"))
    instance = QApplication.instance() or QApplication([])
    style_application(instance)
    yield instance


@pytest.fixture
def window(tmp_path, application, close_window):
    shutil.copytree(ROOT / "configs/shipped", tmp_path / "configs/games")
    shutil.copytree(ROOT / "configs/tips", tmp_path / "configs/tips")
    result = Window(tmp_path)
    result.show()
    application.processEvents()
    yield result
    close_window(result, application)


def wait_for(application, predicate, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        application.processEvents()
        if predicate():
            return True
        QTest.qWait(20)
    return False


@pytest.fixture
def registration_window(window, application, tmp_path):
    ids = add_clips(window, tmp_path)
    window.catalogue.patch(ids[0], {"game": "Escape from Tarkov"})
    window.panel("Editing")
    window.activateWindow()
    window.command.setFocus()
    application.processEvents()
    return window


def test_named_value_registration_saves_without_submitting(registration_window, application):
    from dfsorter.config_editor import GAME_ADDITIONS_ROLE, GAME_SIZE_ROLE
    from dfsorter.parsing import parse_command

    window = registration_window
    command = window.command
    command.setText("wpn:m16a1 ")
    assert '<b>Tab to add <u>m16a1</u> to Escape from Tarkov config</b>' in window.command_feedback.text()
    clip_before = window.catalogue.clip(window.current_id)
    cursor = command.cursorPosition()
    QTest.keyClick(command, Qt.Key.Key_Tab)
    assert command.hasFocus()
    assert window.command_feedback.text() == 'New weapon: <u>m16a1</u> · Tab to finalize · Enter to cancel'
    QTest.keyClick(command, Qt.Key.Key_Tab)
    assert window.named_value_registration is None
    assert command.text() == "m16a1 "
    assert command.cursorPosition() == cursor - len("wpn:")
    assert window.catalogue.clip(window.current_id) == clip_before
    assert parse_command("m16a1", "Escape from Tarkov", window.registry)["metadata"] == {"weapon": ["m16a1"]}
    saved = yaml.safe_load((window.root / "configs/games/Escape from Tarkov.yaml").read_text(encoding="utf-8"))
    assert saved["fields"]["weapon"]["values"] == ["m16a1"]
    assert "Tab to add" not in window.command_feedback.text()
    config_history = window.config_editor.histories.get("Escape from Tarkov.yaml")
    assert config_history is None or not config_history.undo_stack
    window.panel("Config")
    item = next(window.config_editor.games.item(index) for index in range(window.config_editor.games.count())
                if window.config_editor.games.item(index).text() == "Escape from Tarkov")
    assert item.data(GAME_ADDITIONS_ROLE) == "(+1 named value)"
    assert item.data(GAME_SIZE_ROLE) in item.toolTip()
    assert "(+1 named value)" in item.toolTip()


@pytest.mark.parametrize("text,cursor,offered", [
    ("wpn:m16a1", None, False),
    ("wpn:m16a1 ", None, True),
    ("wpn:m16a1 ", 7, False),
    ("wpn:m16a1 ", 9, False),
    ("wpn:m16 a1 ", 7, False),
    ("wpn:m16 a1 ", None, True),
    ('wpn:"m16 a1" ', None, True),
    ("wpn:m16a1 map:lab", None, True),
    ("wpn:m16a1 -- description", None, True),
    ("wpn:m16a1 R6 ", None, False),
    ('wpn:"m16a1 ', None, False),
    ("-- wpn:m16a1 ", None, False),
])
def test_named_value_offer_boundaries(registration_window, text, cursor, offered):
    window = registration_window
    window.command.setText(text)
    if cursor is not None:
        window.command.setCursorPosition(cursor)
    assert ("Tab to add" in window.command_feedback.text()) is offered


@pytest.mark.parametrize("cancel", ["enter", "escape", "caret", "typing", "selection", "focus", "page", "game"])
def test_named_value_cancel_suppresses_for_run(registration_window, cancel):
    window = registration_window
    command = window.command
    command.setText("wpn:m16a1 ")
    before = window.catalogue.clip(window.current_id)
    QTest.keyClick(command, Qt.Key.Key_Tab)
    if cancel == "enter":
        QTest.keyClick(command, Qt.Key.Key_Return)
        assert command.hasFocus()
    elif cancel == "escape":
        QTest.keyClick(command, Qt.Key.Key_Escape)
        assert command.hasFocus()
    elif cancel == "caret":
        command.setCursorPosition(1)
    elif cancel == "typing":
        QTest.keyClicks(command, "x")
    elif cancel == "selection":
        command.selectAll()
    elif cancel == "focus":
        window.review_mode()
    elif cancel == "page":
        window.panel("Session")
    elif cancel == "game":
        window.catalogue.patch(window.current_id, {"game": "VALORANT"})
        window.render_clip()
        window.catalogue.patch(window.current_id, {"game": "Escape from Tarkov"})
    assert window.named_value_registration is None
    assert ("Escape from Tarkov", "weapon", "m16a1") in window.suppressed_named_values
    if cancel in {"enter", "escape", "focus", "page"}:
        assert command.text() == "wpn:m16a1 "
    window.panel("Editing")
    command.setFocus()
    command.setText("wpn:M16A1 ")
    assert "Tab to add" not in window.command_feedback.text()
    assert window.catalogue.clip(window.current_id)["metadata"] == before["metadata"]
    command.setText("wpn:m16a2 ")
    assert "Tab to add" in window.command_feedback.text()


def test_named_value_multiple_fields_tag_and_known_alias(registration_window):
    from dfsorter.config_store import GameFile

    window = registration_window
    source = GameFile(window.root / "configs/games/Escape from Tarkov.yaml")
    draft = source.draft()
    draft["fields"]["map"]["type"] = "freeform"
    source.save(draft, source.path.parent)
    window.reload_configs()
    window.command.setText("wpn:m16a1 wpn:m16a2 map:new map tag:TEST ")
    assert "New tag" in window.command_feedback.text()
    for field, value in [("weapon", "m16a1"), ("weapon", "m16a2"), ("map", "new map")]:
        assert f"Tab to add <u>{value}</u>" in window.command_feedback.text()
        QTest.keyClick(window.command, Qt.Key.Key_Tab)
        assert window.named_value_registration["candidate"].field == field
        QTest.keyClick(window.command, Qt.Key.Key_Tab)
    assert window.named_value_additions["Escape from Tarkov"] == 3
    window.command.setText("map:LABS ")
    assert "Tab to add" not in window.command_feedback.text()
    window.command.setText("wpn:M16A1 ")
    assert "Tab to add" not in window.command_feedback.text()


def test_named_value_blocks_config_draft_and_retains_history(registration_window):
    window = registration_window
    editor = window.config_editor
    filename = "Escape from Tarkov.yaml"
    editor.load_game(filename)
    editor.example.setText("changed example")
    assert editor.dirty
    window.command.setFocus()
    window.command.setText("wpn:m16a1 ")
    QTest.keyClick(window.command, Qt.Key.Key_Tab)
    assert window.named_value_registration is None
    assert "Config draft" in window.command_feedback.text()
    assert editor.save()
    history_count = len(editor.histories[filename].undo_stack)
    window.command.setFocus()
    QTest.keyClick(window.command, Qt.Key.Key_Tab)
    QTest.keyClick(window.command, Qt.Key.Key_Tab)
    assert len(editor.histories[filename].undo_stack) == history_count
    assert not editor.dirty
    editor.undo()
    assert editor.example.text() != "changed example"
    assert "m16a1" in editor.collect()["fields"]["weapon"]["values"]
    assert editor.save()
    assert "m16a1" in window.registry.game("Escape from Tarkov").fields["weapon"]["values"]


@pytest.mark.parametrize("failure", ["external", "write", "collision"])
def test_named_value_failure_preserves_confirmation(registration_window, monkeypatch, failure):
    window = registration_window
    command = window.command
    command.setText("wpn:Factory " if failure == "collision" else "wpn:m16a1 ")
    QTest.keyClick(command, Qt.Key.Key_Tab)
    source = window.named_value_registration["source"]
    if failure == "external":
        source.path.write_text(source.text + "\n# External change\n", encoding="utf-8")
    elif failure == "write":
        monkeypatch.setattr(source, "save", lambda *_args: (_ for _ in ()).throw(OSError("Write failed")))
    before = source.path.read_bytes()
    QTest.keyClick(command, Qt.Key.Key_Tab)
    assert source.path.read_bytes() == before
    assert window.named_value_registration is not None
    assert window.named_value_error
    assert "Tab to finalize" in window.command_feedback.text()
    assert not window.named_value_additions
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert window.named_value_registration is None


def test_named_value_keys_keep_submission_optional(registration_window, application):
    window = registration_window
    command = window.command
    command.setText("wpn:m16a1 ")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert window.catalogue.clip(window.current_id)["metadata"]["weapon"] == ["m16a1"]
    assert "m16a1" not in window.registry.game("Escape from Tarkov").fields["weapon"].get("values", [])
    command.setText("wpn:m16a2 ")
    QTest.keyClick(command, Qt.Key.Key_Tab)
    for key in (Qt.Key.Key_Tab, Qt.Key.Key_Return):
        event = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier, "", True)
        application.sendEvent(command, event)
        assert window.named_value_registration is not None
        assert not window.named_value_additions
    QTest.keyClick(command, Qt.Key.Key_Tab)
    command.setText("wpn:M16A2 ")
    assert "Tab to add" not in window.command_feedback.text()
    QTest.keyClick(command, Qt.Key.Key_Tab)
    assert not command.hasFocus()


@pytest.mark.parametrize("text,expected", [
    ("wpn:m16a1 wpn:other ", "m16a1 wpn:other "),
    ("weapon:m16a1 map:lab -- title", "m16a1 map:lab -- title"),
    ('wpn:"M16 A1" map:lab', '"M16 A1" map:lab'),
    ('"wpn:m16a1" map:lab', '"m16a1" map:lab'),
    ("wpn:M16   A1 map:lab", "M16   A1 map:lab"),
])
def test_named_value_finalization_strips_only_registered_prefix(registration_window, text, expected):
    from dfsorter.parsing import parse_command

    window = registration_window
    command = window.command
    command.setText(text)
    original_patch = parse_command(text, "Escape from Tarkov", window.registry)
    original_cursor = command.cursorPosition()
    QTest.keyClick(command, Qt.Key.Key_Tab)
    assert command.text() == text
    QTest.keyClick(command, Qt.Key.Key_Tab)
    assert command.text() == expected
    assert command.cursorPosition() == original_cursor - (len(text) - len(expected))
    assert window.drafts[window.current_id] == expected
    assert parse_command(expected, "Escape from Tarkov", window.registry) == original_patch
    command.undo()
    assert command.text() == text


def test_named_value_prefix_removal_preserves_preceding_freeform(registration_window):
    from dfsorter.config_store import GameFile
    from dfsorter.parsing import parse_command

    window = registration_window
    source = GameFile(window.root / "configs/games/Escape from Tarkov.yaml")
    draft = source.draft()
    draft["fields"]["map"]["type"] = "freeform"
    source.save(draft, source.path.parent)
    window.reload_configs()
    command = window.command
    command.setText("map:new map wpn:new weapon ")
    command.setCursorPosition(6)
    patch = parse_command(command.text(), "Escape from Tarkov", window.registry)
    QTest.keyClick(command, Qt.Key.Key_Tab)
    assert window.named_value_registration["candidate"].field == "weapon"
    QTest.keyClick(command, Qt.Key.Key_Tab)
    assert command.text() == "map:new map new weapon "
    assert command.cursorPosition() == 6
    assert parse_command(command.text(), "Escape from Tarkov", window.registry) == patch


def test_command_ghost_expansions_use_configured_aliases(registry):
    game = registry.game("VALORANT")
    expansions = command_expansions("hh weapon:tdf -- hh", game)
    assert [(item.start, item.end, item.display, item.matched) for item in expansions] == [
        (0, 2, "headhunter", frozenset({0, 4})),
        (10, 13, "tour de force", frozenset({0, 5, 8})),
    ]
    assert command_expansions('"hh" weapon:hh', game)[0].start == 12
    assert command_expansions("hh nonsense", game)[0].display == "headhunter"
    assert command_expansions("hh", registry.game("Overwatch")) == []


def test_command_ghost_expansion_keeps_raw_text(registry, application):
    command = CommandInput()
    game = registry.game("VALORANT")
    command.show()
    command.set_ghost_context(True, game)
    command.setText("hh tdf")
    command.setFocus()
    command.setCursorPosition(6)
    application.processEvents()
    assert [item.display for item in command.visible_expansions()] == ["headhunter"]
    assert command._display()[0] == "headhunter tdf"
    assert not command.grab().isNull()
    command.setCursorPosition(1)
    assert [item.display for item in command.visible_expansions()] == ["tour de force"]
    assert command.text() == "hh tdf"
    command.selectAll()
    command.copy()
    assert application.clipboard().text() == "hh tdf"
    command.set_ghost_context(False, game)
    assert command.visible_expansions() == []
    command.close()


def test_command_ghost_click_collapses_to_raw_boundary(registry, application):
    command = CommandInput()
    command.resize(360, 30)
    command.show()
    command.set_ghost_context(True, registry.game("VALORANT"))
    command.setText("hh ")
    command.setCursorPosition(3)
    application.processEvents()
    assert command.visible_expansions()
    display, _, _, _, _, positions, rect, _ = command._geometry()
    assert display == "headhunter "
    QTest.mouseClick(command, Qt.MouseButton.LeftButton, pos=QPoint(rect.x() + positions[1], rect.center().y()))
    assert command.cursorPosition() in (0, 2)
    assert command.visible_expansions() == []
    assert command.text() == "hh "
    command.close()


def test_command_ghost_text_keeps_native_baseline(registry, application):
    command = CommandInput()
    command.resize(360, 38)
    command.show()
    command.setFocus()
    command.set_ghost_context(True, registry.game("VALORANT"))
    command.setText("hh ")

    def first_letter_top():
        application.processEvents()
        image = command.grab().toImage()
        rect = command._text_rect()
        return min(
            vertical
            for vertical in range(rect.top(), rect.bottom())
            for horizontal in range(rect.left() + 1, rect.left() + 8)
            if (color := image.pixelColor(horizontal, vertical)).red() < 135
            and color.green() < 145
            and color.blue() < 155
        )

    command.setCursorPosition(0)
    native_top = first_letter_top()
    command.setCursorPosition(3)
    assert command.visible_expansions()
    assert first_letter_top() == native_top
    command.close()


def test_command_ghost_setting_persists(window, application):
    dialog = SettingsDialog(window)
    assert dialog.ghost_autocomplete.isChecked()
    dialog.ghost_autocomplete.setChecked(False)
    assert window.settings["ghost_autocomplete_enabled"] is False
    assert window.settings_path.exists()
    assert yaml.safe_load(window.settings_path.read_text(encoding="utf-8"))["ghost_autocomplete_enabled"] is False
    dialog.close()


def test_editing_tips_setting_persists(window, application):
    dialog = SettingsDialog(window)
    assert dialog.editing_tips.isChecked()
    dialog.editing_tips.setChecked(False)
    assert window.settings["editing_tips_enabled"] is False
    assert yaml.safe_load(window.settings_path.read_text(encoding="utf-8"))["editing_tips_enabled"] is False
    assert not window.tip_timer.isActive()
    dialog.close()


@pytest.mark.parametrize(
    "icon_name,color_role",
    [
        ("info-tip", "accent_default"),
        ("triangle-alert", "status_warning"),
    ],
)
def test_editing_tip_uses_widget_dpr_for_both_icons(
    application, monkeypatch, close_window, icon_name, color_role
):
    tip = TipWidget(size=12, icon_name=icon_name, color_role=color_role)
    tip.set_message("Tip")
    tip.resize(100, 15)
    tip.show()
    application.processEvents()
    assert tip.symbol.devicePixelRatio() == tip.devicePixelRatioF()

    monkeypatch.setattr(tip, "devicePixelRatioF", lambda: 1.25)
    tip.repaint()
    assert tip.symbol_dpr == 1.25
    assert tip.symbol.size() == QSize(round(tip.tip_size * 1.25), round(tip.tip_size * 1.25))
    assert tip.symbol.devicePixelRatio() == 1.25
    assert icon(icon_name, COLORS[color_role], size=12, dpr=1.25).availableSizes() == [
        QSize(15, 15)
    ]
    monkeypatch.undo()
    close_window(tip, application)


@pytest.mark.parametrize("icon_name,detail_row", [("info-tip", 3), ("triangle-alert", 8)])
def test_small_tip_icon_retains_punctuation(application, icon_name, detail_row):
    image = icon(icon_name, size=12, dpr=1).pixmap(QSize(12, 12), 1.0).toImage()
    coverage = sum(image.pixelColor(column, detail_row).alpha() for column in (5, 6))
    assert coverage >= 90


@pytest.mark.parametrize("icon_name", ["info-tip", "triangle-alert"])
@pytest.mark.parametrize("ratio", [1.0, 1.25])
def test_tip_paint_preserves_bitmap_with_parent_offset(
    application, monkeypatch, close_window, icon_name, ratio
):
    parent = QWidget()
    parent.resize(220, 50)
    tip = TipWidget(parent, icon_name=icon_name)
    tip.set_message("Tip")
    monkeypatch.setattr(tip, "devicePixelRatioF", lambda: ratio)
    for size in (11, 12, 13):
        tip.set_tip_size(size)
        for height in (19, 20):
            tip.setGeometry(7, 9, 200, height)
            image = QImage(
                round(parent.width() * ratio),
                round(parent.height() * ratio),
                QImage.Format.Format_ARGB32_Premultiplied,
            )
            image.setDevicePixelRatio(ratio)
            image.fill(Qt.GlobalColor.transparent)
            parent.render(image)
            text_width = tip.fontMetrics().horizontalAdvance(tip.message)
            left = round((tip.x() + tip.width() - size - 4 - text_width) * ratio)
            top = round((tip.y() + height / 2) * ratio - tip.symbol.height() / 2)
            expected = QImage(tip.symbol.size(), image.format())
            expected.fill(image.pixelColor(0, 0))
            source = tip.symbol.toImage()
            source.setDevicePixelRatio(1)
            painter = QPainter(expected)
            painter.drawImage(0, 0, source)
            painter.end()
            actual = image.copy(left, top, tip.symbol.width(), tip.symbol.height())
            actual.setDevicePixelRatio(1)
            assert actual == expected, (size, height, ratio)
    monkeypatch.undo()
    close_window(parent, application)


def test_editing_bottom_size_setting_updates_row_without_rotating(window, tmp_path):
    add_clips(window, tmp_path)
    window.panel("Editing")
    current_tip = window.editing_tip.message
    shown = set(window.tips.shown)
    dialog = SettingsDialog(window)
    assert [dialog.editing_bottom_size.button(size).text() for size in (11, 12, 13)] == [
        "11 px", "12 px", "13 px"
    ]
    assert dialog.editing_bottom_size.checkedId() == 12
    assert window.editing_tip.font().pixelSize() == 12
    assert 'font-size:12px' in window.field_reminder.text()
    dialog.editing_bottom_size.button(11).click()
    assert window.settings["editing_bottom_size"] == 11
    assert window.editing_tip.font().pixelSize() == 11
    assert 'font-size:11px' in window.field_reminder.text()
    dialog.editing_bottom_size.button(13).click()
    assert window.settings["editing_bottom_size"] == 13
    assert window.editing_tip.font().pixelSize() == 13
    assert 'font-size:13px' in window.field_reminder.text()
    assert window.editing_tip.message == current_tip
    assert window.tips.shown == shown
    assert yaml.safe_load(window.settings_path.read_text(encoding="utf-8"))["editing_bottom_size"] == 13
    dialog.close()


def test_editing_bottom_size_shows_every_option_without_popup(window, application):
    dialog = SettingsDialog(window)
    dialog.show()
    application.processEvents()
    assert all(dialog.editing_bottom_size.button(size).isVisible() for size in (11, 12, 13))
    assert dialog.editing_bottom_size.checkedId() == 12
    dialog.close()


def test_editing_bottom_size_changes_on_mouse_release(window, application):
    dialog = SettingsDialog(window)
    dialog.show()
    application.processEvents()
    button = dialog.editing_bottom_size.button(13)
    QTest.mousePress(button, Qt.MouseButton.LeftButton)
    assert dialog.editing_bottom_size.checkedId() == 12
    assert window.editing_bottom_size() == 12
    QTest.mouseRelease(button, Qt.MouseButton.LeftButton)
    assert dialog.editing_bottom_size.checkedId() == 13
    assert window.editing_bottom_size() == 13
    dialog.close()


def test_editing_tips_rotate_on_pane_return_but_not_clip_change(window, application, tmp_path):
    ids = add_clips(window, tmp_path)
    window.panel("Editing")
    application.processEvents()
    assert window.editing_tip.message
    assert window.editing_tip.font().pixelSize() == 12
    assert 'font-size:12px' in window.field_reminder.text()
    assert window.editing_tip.isVisible()
    assert not window.editing_tip.grab().isNull()
    assert window.editing_tip.x() - window.field_reminder.geometry().right() >= 12
    assert window.field_reminder.width() >= window.field_reminder.sizeHint().width()
    assert window.editing_tip.width() > 0
    assert window.tip_timer.isActive()
    shown = set(window.tips.shown)
    message = window.editing_tip.message
    window.load_clip(ids[-1])
    assert window.editing_tip.message == message
    assert window.tips.shown == shown
    window.panel("Home")
    assert not window.tip_timer.isActive()
    window.panel("Editing")
    assert window.tips.shown != shown
    assert window.tip_timer.isActive()


def test_status_bar_exists_before_deferred_startup_work(window):
    assert window.status_bar is window.statusBar()
    assert not window.status_bar.isHidden()
    assert window.status_bar.currentMessage() == ""


def test_home_game_configs_button_opens_config(window):
    window.game_configs_button.click()
    assert window.current_panel == "Config"
    assert window.nav["Config"].isChecked()


def test_update_check_is_in_settings_menu(window):
    assert "Check for updates…" in [action.text() for action in window.settings_menu.actions()]


def test_portable_launch_checks_for_updates_once(application, tmp_path, monkeypatch):
    import dfsorter.ui as ui

    shutil.copytree(ROOT / "configs/shipped", tmp_path / "configs/games")
    shutil.copytree(ROOT / "configs/tips", tmp_path / "configs/tips")
    monkeypatch.setattr(ui, "installed_release", lambda: {"version": "1.0.0"})
    checks = []
    monkeypatch.setattr(
        Window, "check_for_updates", lambda self, *, quiet=False: checks.append(quiet)
    )
    result = Window(tmp_path)
    result.show()
    try:
        application.processEvents()
        application.processEvents()
        assert checks == [True]
    finally:
        result.close()
        application.processEvents()


@pytest.mark.parametrize(
    "outcome, expected",
    [("current", []), ("offline", []), ("newer", ["question"])],
)
def test_quiet_update_check_only_prompts_for_new_release(
    window, application, monkeypatch, outcome, expected
):
    import dfsorter.update_ui as update_ui

    monkeypatch.setattr(update_ui, "installed_release", lambda: {"version": "1.0.0"})
    result = {
        "current": {"version": "1.0.0"},
        "offline": OSError("offline"),
        "newer": {"version": "1.1.0"},
    }[outcome]
    def latest_release():
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(update_ui, "latest_release", latest_release)
    dialogs = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: dialogs.append("information"))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: dialogs.append("warning"))
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args: dialogs.append("question") or QMessageBox.StandardButton.No,
    )
    controller = UpdateController(window)
    controller.check(quiet=True)
    assert wait_for(application, lambda: not controller.checking)
    assert controller.progress is None
    assert dialogs == expected


def test_session_library_overview_defaults_and_does_not_change_filters(
    window, application, tmp_path
):
    root = tmp_path / "overview"
    root.mkdir()
    folder = window.catalogue.add_folder(root)
    paths = [root / f"clip-{index}.mp4" for index in range(3)]
    for path, size in zip(paths, (16, 8, 4)):
        with path.open("wb") as source:
            source.truncate(size * 1024 * 1024)
    window.catalogue.ingest(
        folder,
        [
            {"path": str(paths[0]), "game": "VALORANT"},
            {"path": str(paths[1]), "game": "VALORANT"},
            {"path": str(paths[2]), "game": None},
        ],
    )
    clips = window.catalogue.clips()
    window.catalogue.patch(clips[0]["clip_id"], {"triage": "keep"})
    window.catalogue.patch(clips[1]["clip_id"], {"triage": "discard"})
    window.panel("Session")
    application.processEvents()

    assert window.overview_period == "All time"
    assert window.overview_period_buttons["All time"].isChecked()
    period_buttons = list(window.overview_period_buttons.values())
    assert all(
        right.geometry().left() == left.geometry().right() + 1
        for left, right in zip(period_buttons, period_buttons[1:])
    )
    assert [button.property("periodPosition") for button in period_buttons] == [
        "first",
        "middle",
        "middle",
        "middle",
        "middle",
        "last",
    ]
    summary = window.findChild(QWidget, "overviewSummary")
    games = window.findChildren(QWidget, "overviewGame")
    assert [game.findChild(QLabel).text() for game in games] == ["VALORANT", "Uncategorized"]
    summary_bar = summary.findChild(VerdictBar)
    game_bars = [game.findChild(VerdictBar) for game in games]
    assert summary_bar.height() == 16
    assert all(bar.height() == 12 and bar.reference_total == 3 for bar in game_bars)
    assert summary_bar.width() == game_bars[0].width()
    game_image = game_bars[0].grab().toImage()
    scaled_width = round(game_bars[0].width() * 2 / 3)
    assert game_image.pixelColor(scaled_width - 3, 6) == QColor(COLORS["status_danger"])
    assert game_image.pixelColor(scaled_width + 2, 6) != QColor(COLORS["status_danger"])
    assert any("0.03 GB" in label.text() for label in summary.findChildren(QLabel))
    assert "3 clips · 2 processed (67%)" in [label.text() for label in summary.findChildren(QLabel)]
    selected = window.clip_filter.selected_values()
    window.set_overview_period("7 days")
    assert window.clip_filter.selected_values() == selected


def test_session_overview_reports_unavailable_files_in_all_time(window, application, tmp_path):
    root = tmp_path / "overview-missing"
    root.mkdir()
    available = root / "available.mp4"
    missing = root / "missing.mp4"
    available.write_bytes(b"clip")
    folder = window.catalogue.add_folder(root)
    window.catalogue.ingest(
        folder,
        [{"path": str(available), "game": "VALORANT"},
         {"path": str(missing), "game": "VALORANT"}],
    )
    window.panel("Session")
    application.processEvents()

    summary = window.findChild(QWidget, "overviewSummary")
    assert "1 clips · 0 processed (0%)" in [
        label.text() for label in summary.findChildren(QLabel)
    ]
    assert window.overview_undated.text() == (
        "1 clip file is missing or unreachable (excluded)."
    )
    assert window.overview_undated.isVisible()


def test_verdict_bar_scales_game_total_and_keeps_tiny_game_visible(application):
    bar = VerdictBar()
    bar.setFixedHeight(12)
    bar.set_reference_total(100)
    bar.set_counts(25, 15, 10)
    bar.resize(200, 12)
    bar.show()
    application.processEvents()

    image = bar.grab().toImage()
    assert image.pixelColor(10, 6) == QColor(COLORS["status_success"])
    assert image.pixelColor(65, 6) == QColor(COLORS["status_danger"])
    assert image.pixelColor(90, 6) == QColor(COLORS["text_muted"])
    assert image.pixelColor(110, 6) != QColor(COLORS["status_success"])
    assert image.pixelColor(110, 6) != QColor(COLORS["status_danger"])
    assert image.pixelColor(110, 6) != QColor(COLORS["text_muted"])

    bar.set_counts(0, 0, 1)
    bar.set_reference_total(301)
    application.processEvents()
    image = bar.grab().toImage()
    assert image.pixelColor(1, 6) == QColor(COLORS["text_muted"])
    assert image.pixelColor(4, 6) != QColor(COLORS["text_muted"])

    bar.resize(300, 12)
    bar.set_counts(25, 15, 10)
    bar.set_reference_total(100)
    application.processEvents()
    image = bar.grab().toImage()
    assert image.pixelColor(149, 6) == QColor(COLORS["text_muted"])
    assert image.pixelColor(151, 6) != QColor(COLORS["text_muted"])
    bar.close()


def test_session_pane_top_rows_preserve_heading_and_toolbar_insets(window, application):
    window.set_theme("dark", persist=False)
    window.panel("Session")
    for width, height in ((1400, 900), (1200, 700)):
        window.resize(width, height)
        application.processEvents()
        search_top = window.search.mapTo(window, QPoint()).y()
        for label in (window.findChild(QLabel, "overviewHeading"),):
            assert label.mapTo(window, QPoint()).y() == search_top - 4
            assert label.height() >= window.search.height()
    overview_top = window.findChild(QLabel, "overviewHeading").mapTo(window, QPoint()).y()
    window.panel("Home")
    application.processEvents()
    home_heading = next(
        label for label in window.findChildren(QLabel)
        if label.text() == "Capture folders" and label.isVisible()
    )
    assert home_heading.mapTo(window, QPoint()).y() == overview_top


def test_library_toolbar_surface_and_alignment(window, application):
    from dfsorter.theme import THEMES

    for scheme in ("light", "dark"):
        window.set_theme(scheme, persist=False)
        for panel, search in (("Home", window.search), ("Browse", window.browse_search)):
            window.panel(panel)
            application.processEvents()
            toolbar = window.library_toolbar
            assert toolbar.isVisible()
            assert toolbar.geometry().top() == 0
            assert toolbar.width() == window.left.width()
            assert search.mapTo(toolbar, QPoint()).x() == 8
            assert search.mapTo(toolbar, QPoint()).y() == 8
            assert search.mapTo(toolbar, QPoint()).x() + search.width() == toolbar.width() - 8
            assert window.clip_filter.mapTo(toolbar, QPoint()).x() == 8
            assert (
                window.time_sort.mapTo(toolbar, QPoint()).x() + window.time_sort.width()
                <= toolbar.width() - 8
            )
            assert (
                window.filters.y() - (search.mapTo(toolbar, QPoint()).y() + search.height())
                == 8
            )
            toolbar_image = toolbar.grab().toImage()
            toolbar_color = QColor(THEMES[scheme]["bg_library_toolbar"])
            assert toolbar_image.pixelColor(2, 2) == toolbar_color
            assert toolbar_image.pixelColor(toolbar.width() - 2, toolbar.height() - 1) == toolbar_color
            toolbar_bottom = toolbar.mapTo(window, QPoint(0, toolbar.height())).y()
            assert window.library.viewport().mapTo(window, QPoint()).y() == toolbar_bottom
        window.panel("Config")
        application.processEvents()
        assert window.library_toolbar.isHidden()


def test_home_session_first_visible_clip_meets_toolbar(window, application, tmp_path):
    captures = tmp_path / "captures"
    captures.mkdir()
    paths = [captures / "hidden.mp4", captures / "visible.mp4"]
    for path in paths:
        path.write_bytes(b"test")
    folder = window.catalogue.add_folder(captures)
    window.catalogue.ingest(folder, [{"path": str(path), "game": None} for path in paths])
    for panel in ("Home", "Session"):
        window.panel(panel)
        window.search.setText("visible")
        application.processEvents()
        assert window.library.count() == 1
        toolbar_bottom = window.library_toolbar.mapTo(window, QPoint()).y() + window.library_toolbar.height()
        viewport_top = window.library.viewport().mapTo(window, QPoint()).y()
        assert viewport_top == toolbar_bottom
        assert window.library.visualItemRect(window.library.item(0)).top() == 0
        viewport = window.library.viewport()
        row = window.library.visualItemRect(window.library.item(0))
        assert viewport.grab().toImage().pixelColor(row.center().x(), 0) == QColor(
            COLORS["accent_selection"]
        )
        window.library.clearSelection()
        point = row.center()
        QCoreApplication.sendEvent(
            viewport,
            QMouseEvent(
                QEvent.Type.MouseMove, QPointF(point), QPointF(viewport.mapToGlobal(point)),
                Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            ),
        )
        application.processEvents()
        assert viewport.grab().toImage().pixelColor(row.center().x(), 0) == QColor(
            COLORS["surface_hover"]
        )
        window.search.clear()


def test_config_heading_matches_workspace_sections_in_dark_mode(window, application):
    window.set_theme("dark", persist=False)
    window.panel("Home")
    application.processEvents()
    home_heading = next(
        label for label in window.findChildren(QLabel)
        if label.text() == "Capture folders" and label.isVisible()
    )
    home_top = home_heading.mapTo(window, QPoint()).y()
    home_left = home_heading.mapTo(window, QPoint()).x()
    window.panel("Config")
    application.processEvents()
    config_heading = window.config_editor.config_heading
    glyph = next(
        label for label in window.config_editor.findChildren(QLabel)
        if label.property("headingIcon") == "file-cog"
    )
    assert config_heading.property("role") == "sectionHeading"
    assert config_heading.font().pixelSize() == home_heading.font().pixelSize() == 22
    assert glyph.property("headingIconSize") == 24
    assert config_heading.mapTo(window, QPoint()).y() == home_top
    assert config_heading.mapTo(window, QPoint()).x() == home_left


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_config_sidebar_uses_continuous_surfaces(window, application, scheme):
    window.set_theme(scheme, persist=False)
    window.panel("Config")
    application.processEvents()
    header = window.config_editor.sidebar_header
    sidebar = window.config_editor.sidebar
    assert header.geometry().left() == 0
    assert header.geometry().top() == 0
    assert header.width() == window.left.width()
    assert sidebar.mapTo(window.left, QPoint()).x() == 0
    assert header.grab().toImage().pixelColor(2, 2) == QColor(COLORS["bg_library_toolbar"])
    image = window.left.grab().toImage()
    sidebar_top = sidebar.mapTo(window.left, QPoint()).y()
    assert image.pixelColor(2, sidebar_top + 2) == QColor(COLORS["surface_sidebar"])
    assert image.pixelColor(2, sidebar_top + sidebar.height() - 2) == QColor(
        COLORS["surface_sidebar"]
    )
    games_image = window.config_editor.games.viewport().grab().toImage()
    assert games_image.pixelColor(2, games_image.height() - 2) == QColor(
        COLORS["surface_sidebar"]
    )


def test_editing_header_uses_compact_left_inset(window, application, tmp_path):
    add_clips(window, tmp_path)
    window.set_theme("dark", persist=False)
    window.panel("Editing")
    application.processEvents()
    assert window.session_header.geometry().left() == 0
    assert window.session_header.width() == window.left.width()
    assert window.session_header.grab().toImage().pixelColor(2, 2) == QColor(
        COLORS["bg_library_toolbar"]
    )
    assert window.session_heading.mapTo(window.left, QPoint()).x() == 12
    heading_top = window.session_heading.mapTo(window.session_header, QPoint()).y()
    heading_center = heading_top + window.session_heading.height() / 2
    position_center = (
        window.session_position.mapTo(window.session_header, QPoint()).y()
        + window.session_position.height() / 2
    )
    action_center = (
        window.next_undefined_button.mapTo(window.session_header, QPoint()).y()
        + window.next_undefined_button.height() / 2
    )
    assert heading_top == 12
    heading_bottom_gap = (
        window.session_header.height() - heading_top - window.session_heading.height()
    )
    assert abs(heading_top - heading_bottom_gap) <= 1
    assert window.session_position.contentsMargins().top() == 2
    assert abs(heading_center - position_center) <= 1
    assert abs(heading_center - action_center) <= 1
    assert window.session_position.text() == "1 / 1"
    assert window.session_position.mapTo(window.left, QPoint()).x() < 150


def test_session_overview_scrolls_above_pinned_setup(
    window, application, tmp_path, monkeypatch
):
    window.set_theme("dark", persist=False)
    window.panel("Session")
    window.resize(1400, 600)
    for index in range(40):
        window.overview_rows.addWidget(QLabel(f"Additional game {index}"))
    application.processEvents()

    scroll = window.findChild(QScrollArea, "sessionOverviewScroll")
    overview = window.findChild(QWidget, "sessionOverview")
    setup = window.findChild(QWidget, "sessionSetup")
    assert overview.property("role") == "transparent"
    assert setup.property("role") == "transparent"
    controls = {control.text(): control for control in setup.findChildren(QPushButton)}
    assert scroll.verticalScrollBar().maximum() > 0
    assert abs(overview.width() - scroll.viewport().width()) <= 2
    assert setup.width() == scroll.width()
    assert setup.geometry().top() > scroll.geometry().bottom()
    assert window.session_setup_heading.text() == "No active session"
    assert controls["Create Session"].isVisible()
    assert not controls["End session"].isVisible()
    assert "Resume session" not in controls

    setup_height = setup.height()
    assert window.splitter.count() == 2
    assert not hasattr(window, "projects_toggle")
    application.processEvents()
    assert window.splitter.count() == 2
    assert abs(overview.width() - scroll.viewport().width()) <= 2
    assert setup.height() == setup_height
    assert scroll.verticalScrollBar().maximum() > 0

    add_clips(window, tmp_path)
    window.refresh_references()
    application.processEvents()
    assert setup.height() == setup_height
    assert window.session_setup_heading.text() == "Active session"
    assert window.session_progress.states == ("pending",)
    assert window.session_progress.processed == 0
    assert window.session_progress.last_processed == 0
    assert window.session_verdicts.text() == "0 Keep · 0 Discard · 1 Pending"
    assert window.session_setup_heading.mapTo(setup, QPoint()).y() > 10
    assert window.session_progress.mapTo(setup, QPoint()).y() - (
        window.session_setup_heading.mapTo(setup, QPoint()).y()
        + window.session_setup_heading.height()
    ) < 12
    assert controls["End session"].isVisible()
    assert not controls["Create Session"].isVisible()

    monkeypatch.setattr(window, "confirm", lambda *_args: True)
    controls["End session"].click()
    application.processEvents()
    assert window.catalogue.state("session") is None
    assert window.session_setup_heading.text() == "No active session"
    assert controls["Create Session"].isVisible()
    assert not controls["End session"].isVisible()

    window.refresh_library_overview([])
    assert wait_for(application, lambda: scroll.verticalScrollBar().maximum() == 0, timeout=1)


def test_session_progress_follows_frozen_order_and_marks_unavailable(
    window, application, tmp_path
):
    window.set_theme("dark", persist=False)
    captures = tmp_path / "session-progress"
    captures.mkdir()
    folder = window.catalogue.add_folder(captures)
    paths = [captures / f"clip-{index}.mp4" for index in range(5)]
    for path in paths:
        path.write_bytes(b"video")
    window.catalogue.ingest(folder, [{"path": str(path), "game": "VALORANT"} for path in paths])
    clip_ids = [clip["clip_id"] for clip in window.catalogue.clips()]
    window.catalogue.create_session(clip_ids)
    window.catalogue.patch(clip_ids[1], {"triage": "keep"})
    window.catalogue.patch(clip_ids[4], {"triage": "discard"})
    paths[2].unlink()
    window.refresh_session_status()
    window.panel("Session")
    application.processEvents()

    assert window.session_progress.states == (
        "pending", "keep", "unavailable", "pending", "discard"
    )
    assert window.session_progress.processed == 2
    assert window.session_progress.last_processed == 5
    assert window.session_progress.height() > 16
    assert window.session_verdicts.text().endswith(
        f'<span style="color: {COLORS["status_warning"]}">1 Unavailable</span>'
    )
    assert "2 processed (40%)" not in window.session_verdicts.text()

    window.catalogue.patch(clip_ids[2], {"triage": "keep"})
    window.refresh_session_status()
    assert window.session_progress.processed == 3
    assert window.session_progress.last_processed == 5
    assert window.session_progress.states[2] == "unavailable"
    end_image = window.session_progress.grab().toImage()
    assert end_image.pixelColor(window.session_progress.width() - 2, 10) == QColor(
        COLORS["accent_default"]
    )
    assert end_image.pixelColor(window.session_progress.width() - 12, 3) == QColor(
        COLORS["accent_default"]
    )

    window.catalogue.patch(clip_ids[4], {"triage": None})
    window.refresh_session_status()
    assert window.session_progress.processed == 2
    assert window.session_progress.last_processed == 3
    progress = window.session_progress
    image = progress.grab().toImage()
    keep_start = round(progress.width() / 5)
    cursor = round(progress.width() * 3 / 5)
    assert image.pixelColor(keep_start, 36) == QColor(COLORS["status_success"])
    assert image.pixelColor(cursor, 27) == QColor(COLORS["accent_default"])
    assert image.pixelColor(cursor + 18, 3) == QColor(COLORS["accent_default"])

    window.catalogue.patch(clip_ids[1], {"triage": None})
    window.catalogue.patch(clip_ids[2], {"triage": None})
    window.refresh_session_status()
    start_image = progress.grab().toImage()
    assert progress.last_processed == 0
    assert start_image.pixelColor(1, 10) == QColor(COLORS["accent_default"])


def test_video_surface_fits_landscape_and_portrait_sources(application):
    from PySide6.QtWidgets import QWidget

    from dfsorter.playback import AspectVideoContainer

    surface = QWidget()
    container = AspectVideoContainer(surface)
    container.resize(1000, 500)
    container.show()
    application.processEvents()
    try:
        container.set_video_size(1920, 1080)
        assert surface.geometry().getRect() == (55, 0, 889, 500)
        container.set_video_size(1080, 1920)
        assert surface.geometry().getRect() == (359, 0, 281, 500)
        container.set_video_size(0, 0)
        assert surface.geometry() == container.rect()
    finally:
        container.close()


def test_player_volume_geometry_and_media_colors(window, application):
    from dfsorter.theme import COLORS, THEMES

    window.panel("Browse")
    application.processEvents()
    player = window.browse.player
    assert player.volume.height() == 18
    volume_center = player.volume.mapTo(player, player.volume.rect().center()).y()
    time_center = player.time.mapTo(player, player.time.rect().center()).y()
    assert abs(volume_center - time_center) <= 1
    assert COLORS["component_timeline_progress"] == COLORS["accent_default"]
    assert COLORS["component_volume_progress"] != COLORS["component_timeline_progress"]
    assert COLORS["component_clip_scrollbar_track"] != COLORS["component_timeline_track"]
    assert COLORS["component_clip_scrollbar_thumb"] != COLORS["component_clip_scrollbar_track"]
    assert (
        THEMES["dark"]["component_clip_scrollbar_thumb"]
        != THEMES["dark"]["component_clip_scrollbar_track"]
    )
    assert THEMES["light"]["component_volume_track"] != THEMES["light"]["border_default"]


def test_player_volume_track_drag_updates_continuously(window, application):
    window.panel("Browse")
    application.processEvents()
    volume = window.browse.player.volume
    volume.setValue(0)

    start = QPoint(5, volume.rect().center().y())
    middle = QPoint(5 + round((volume.width() - 10) * 0.37), volume.rect().center().y())
    end = QPoint(volume.width() - 5, volume.rect().center().y())
    QTest.mousePress(volume, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(volume, middle)
    application.processEvents()
    assert abs(volume.value() - 37) <= 1
    QTest.mouseMove(volume, end)
    QTest.mouseRelease(volume, Qt.MouseButton.LeftButton, pos=end)

    assert volume.value() == 100


def test_player_volume_is_shared_and_persists(window, application):
    import yaml

    window.browse.player.volume.setValue(37)
    assert window.browse.player.volume.value() == 37
    assert window.player.volume.value() == 37
    assert window.export_player.volume.value() == 37
    assert yaml.safe_load(window.settings_path.read_text(encoding="utf-8"))[
        "playback_volume"
    ] == 37

    restarted = Window(window.root)
    try:
        assert restarted.browse.player.volume.value() == 37
        assert restarted.player.volume.value() == 37
        assert restarted.export_player.volume.value() == 37
    finally:
        restarted.close()
        application.processEvents()

    settings = yaml.safe_load(window.settings_path.read_text(encoding="utf-8"))
    settings["playback_volume"] = 38
    window.settings_path.write_text(yaml.safe_dump(settings), encoding="utf-8")
    restarted = Window(window.root)
    try:
        assert restarted.browse.player.volume.value() == 38
        assert restarted.player.volume.value() == 38
        assert restarted.export_player.volume.value() == 38
        assert yaml.safe_load(window.settings_path.read_text(encoding="utf-8"))[
            "playback_volume"
        ] == 38
    finally:
        restarted.close()
        application.processEvents()


def catalogue_dump(window):
    with window.catalogue.connection() as database:
        return list(database.iterdump())


def test_atomic_single_clip_edit_save_revert_and_session_preservation(
    window, application, tmp_path, monkeypatch
):
    root = tmp_path / "atomic-captures"
    root.mkdir()
    folder = window.catalogue.add_folder(root)
    paths = [root / f"clip-{index}.mp4" for index in range(2)]
    for path in paths:
        path.write_bytes(b"video")
    window.catalogue.ingest(
        folder, [{"path": str(path), "game": "VALORANT"} for path in paths]
    )
    ids = [clip["clip_id"] for clip in window.catalogue.clips()]
    window.catalogue.create_session(ids)
    session = window.catalogue.state("session")
    history = list(window.catalogue.undo_stack)

    window.start_atomic_edit(ids[1], "Home")
    application.processEvents()
    assert window.current_panel == "Editing"
    assert window.session_heading.text() == "Single clip"
    assert window.library.count() == 1
    assert not window.next_undefined_button.isVisible()
    assert not window.player.previous_button.isEnabled()
    assert not window.player.next_button.isEnabled()
    window.edit({"rating": 4, "mainline": "Atomic title"})
    assert window.rating.value == 4
    assert window.catalogue.clip(ids[1])["rating"] is None
    assert window.catalogue.undo_stack == history
    assert window.atomic_save_button.isEnabled()
    window.atomic_save_button.click()
    application.processEvents()
    assert window.current_panel == "Home"
    assert window.selected_id(window.library) == ids[1]
    assert window.catalogue.clip(ids[1])["mainline"] == "Atomic title"
    assert window.catalogue.clip(ids[1])["triage"] is None
    assert window.catalogue.state("session") == session
    assert len(window.catalogue.undo_stack) == len(history) + 1
    window.undo()
    assert window.catalogue.clip(ids[1])["mainline"] == "Atomic title"
    window.panel("Editing")
    window.switch_editing_clip(ids[1])
    window.undo()
    assert window.catalogue.clip(ids[1])["mainline"] is None
    window.panel("Home")
    session = window.catalogue.state("session")

    window.start_atomic_edit(ids[0], "Browse")
    window.edit({"tag": "temporary"})
    monkeypatch.setattr(window, "confirm_revert_atomic", lambda: True)
    window.revert_atomic_edit()
    application.processEvents()
    assert window.current_panel == "Browse"
    assert window.selected_id(window.library) == ids[0]
    assert window.browse_selected_id == ids[0]
    assert window.catalogue.clip(ids[0])["tag"] is None
    assert window.catalogue.state("session") == session


def test_atomic_return_restores_origin_scroll_position(
    window, application, tmp_path, monkeypatch
):
    root = tmp_path / "atomic-scroll"
    root.mkdir()
    folder = window.catalogue.add_folder(root)
    paths = [root / f"clip-{index:02}.mp4" for index in range(30)]
    for path in paths:
        path.write_bytes(b"video")
    window.catalogue.ingest(
        folder, [{"path": str(path), "game": "VALORANT"} for path in paths]
    )
    window.refresh_library()
    application.processEvents()
    clip_id = window.library.item(15).data(Qt.ItemDataRole.UserRole)
    scrollbar = window.library.verticalScrollBar()
    scrollbar.setValue(scrollbar.maximum() // 2)
    home_scroll = scrollbar.value()
    assert home_scroll > 0

    window.start_atomic_edit(clip_id, "Home")
    window.edit({"rating": 4, "mainline": "Scroll clip"})
    window.save_atomic_edit()
    application.processEvents()
    assert window.current_panel == "Home"
    assert window.selected_id(window.library) == clip_id
    assert scrollbar.value() == home_scroll

    window.panel("Browse")
    application.processEvents()
    scrollbar.setValue(scrollbar.maximum() // 3)
    browse_scroll = scrollbar.value()
    assert browse_scroll > 0
    window.start_atomic_edit(clip_id, "Browse")
    monkeypatch.setattr(window, "confirm_revert_atomic", lambda: True)
    window.revert_atomic_edit()
    application.processEvents()
    assert window.current_panel == "Browse"
    assert window.selected_id(window.library) == clip_id
    assert scrollbar.value() == browse_scroll


@pytest.mark.parametrize("action", ["button", "shift_enter", "input_shift_enter"])
def test_atomic_save_actions_return_to_browse(window, application, tmp_path, action):
    root = tmp_path / "atomic-save-actions"
    root.mkdir()
    path = root / "clip.mp4"
    path.write_bytes(b"video")
    folder = window.catalogue.add_folder(root)
    window.catalogue.ingest(folder, [{"path": str(path), "game": "VALORANT"}])
    clip_id = window.catalogue.clips()[0]["clip_id"]

    window.panel("Browse")
    window.start_atomic_edit(clip_id, "Browse")
    window.edit({"mainline": "Edited clip"})
    if action == "button":
        window.atomic_save_button.click()
    elif action == "input_shift_enter":
        window.command.setFocus()
        QTest.keyClick(window.command, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    else:
        QTest.keyClick(window.player, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    application.processEvents()

    assert window.current_panel == "Browse"
    assert window.browse.clip["clip_id"] == clip_id
    assert window.selected_id(window.library) == clip_id
    assert window.catalogue.clip(clip_id)["triage"] is None
    assert window.catalogue.clip(clip_id)["mainline"] == "Edited clip"


def test_atomic_shift_enter_preserves_explicit_verdict(window, application, tmp_path):
    root = tmp_path / "atomic-verdict"
    root.mkdir()
    path = root / "clip.mp4"
    path.write_bytes(b"video")
    folder = window.catalogue.add_folder(root)
    window.catalogue.ingest(folder, [{"path": str(path), "game": None}])
    clip_id = window.catalogue.clips()[0]["clip_id"]

    window.panel("Browse")
    window.start_atomic_edit(clip_id, "Browse")
    window.edit({"rating": 3})
    assert window.atomic_save_button.isEnabled()
    QTest.keyClick(window.player, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    application.processEvents()
    assert window.current_panel == "Browse"
    assert window.catalogue.clip(clip_id)["rating"] == 3
    assert window.catalogue.clip(clip_id)["triage"] is None

    window.start_atomic_edit(clip_id, "Browse")
    window.edit({"triage": "discard"})
    assert window.atomic_save_button.isEnabled()
    QTest.keyClick(window.player, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    application.processEvents()
    assert window.current_panel == "Browse"
    assert window.catalogue.clip(clip_id)["triage"] == "discard"
    assert window.catalogue.clip(clip_id)["rating"] == 3


def test_atomic_save_preserves_existing_keep_and_membership(window, tmp_path):
    root = tmp_path / "atomic-existing-keep"
    root.mkdir()
    path = root / "clip.mp4"
    path.write_bytes(b"video")
    folder = window.catalogue.add_folder(root)
    window.catalogue.ingest(folder, [{"path": str(path), "game": "VALORANT"}])
    clip_id = window.catalogue.clips()[0]["clip_id"]
    project_id = window.catalogue.save_project("Project")
    window.catalogue.set_state("review_destination", project_id)
    window.catalogue.patch(clip_id, {"triage": "keep"})

    window.start_atomic_edit(clip_id, "Home")
    window.edit({"rating": 2})
    assert window.save_atomic_edit()
    assert window.catalogue.clip(clip_id)["triage"] == "keep"
    assert window.catalogue.member_ids(project_id) == set()


def test_atomic_notice_replaces_rotating_tip(window, application, tmp_path):
    root = tmp_path / "atomic-notice"
    root.mkdir()
    path = root / "clip.mp4"
    path.write_bytes(b"video")
    folder = window.catalogue.add_folder(root)
    window.catalogue.ingest(folder, [{"path": str(path), "game": None}])
    clip_id = window.catalogue.clips()[0]["clip_id"]

    window.settings["editing_tips_enabled"] = False
    window.start_atomic_edit(clip_id, "Home")
    application.processEvents()
    assert window.atomic_edit_notice.isVisible()
    assert window.atomic_edit_notice.icon_name == "triangle-alert"
    assert window.atomic_edit_notice.color_role == "status_warning"
    assert "Save or Shift+Enter keeps the selected verdict" in window.atomic_edit_notice.message
    assert window.atomic_edit_notice.font() == window.editing_tip.font()
    assert type(window.atomic_edit_notice) is type(window.editing_tip)
    assert not window.editing_tip.isVisible()
    assert not window.tip_timer.isActive()

    window.settings["editing_bottom_size"] = 11
    window.update_editing_bottom_size()
    assert window.atomic_edit_notice.font().pixelSize() == 11
    window.settings["editing_bottom_size"] = 13
    window.update_editing_bottom_size()
    assert window.atomic_edit_notice.font().pixelSize() == 13

    window.discard_atomic_edit()
    window.panel("Home")
    application.processEvents()
    assert not window.atomic_edit_notice.isVisible()


def test_atomic_entry_controls_and_context_target(window, application, tmp_path, monkeypatch):
    root = tmp_path / "atomic-controls"
    root.mkdir()
    path = root / "clip.mp4"
    path.write_bytes(b"video")
    folder = window.catalogue.add_folder(root)
    window.catalogue.ingest(folder, [{"path": str(path), "game": None}])
    clip_id = window.catalogue.clips()[0]["clip_id"]
    window.panel("Browse")
    application.processEvents()
    assert window.browse.edit_button.toolTip() == "Edit clip…"
    assert window.browse.edit_button.accessibleName() == "Edit clip"
    assert window.browse.edit_button.isEnabled()
    window.browse.edit_button.click()
    assert window.atomic_edit.clip_id == clip_id
    monkeypatch.setattr(window, "confirm_revert_atomic", lambda: True)
    window.revert_atomic_edit()
    window.panel("Home")
    window.context_clip_id = clip_id
    window.edit_context_clip()
    assert window.atomic_edit.origin == "Home"


def test_atomic_navigation_reverts_and_shift_enter_validates(
    window, application, tmp_path, monkeypatch
):
    root = tmp_path / "atomic-prompt"
    root.mkdir()
    path = root / "clip.mp4"
    path.write_bytes(b"video")
    folder = window.catalogue.add_folder(root)
    window.catalogue.ingest(folder, [{"path": str(path), "game": "VALORANT"}])
    clip_id = window.catalogue.clips()[0]["clip_id"]

    window.start_atomic_edit(clip_id, "Home")
    window.edit({"rating": 3})
    assert window.atomic_save_button.isEnabled()
    monkeypatch.setattr(window, "confirm_revert_atomic", lambda: False)
    window.panel("Config")
    assert window.current_panel == "Editing"
    assert window.atomic_edit is not None

    window.command.setText("invalid command")
    assert not window.atomic_save_button.isEnabled()
    draft = window.atomic_edit.draft
    QTest.keyClick(window.command, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert window.atomic_edit.draft == draft
    assert window.command.text() == "invalid command"
    window.review_mode()
    QTest.keyClick(window.player, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert window.atomic_edit.draft == draft
    assert window.current_panel == "Editing"

    window.pending_in = 100
    monkeypatch.setattr(window, "confirm_revert_atomic", lambda: True)
    window.panel("Config")
    application.processEvents()
    assert window.current_panel == "Config"
    assert window.atomic_edit is None
    assert window.catalogue.clip(clip_id)["rating"] is None


def test_atomic_save_conflict_keeps_draft(window, tmp_path):
    root = tmp_path / "atomic-conflict"
    root.mkdir()
    path = root / "clip.mp4"
    path.write_bytes(b"video")
    folder = window.catalogue.add_folder(root)
    window.catalogue.ingest(folder, [{"path": str(path), "game": "VALORANT"}])
    clip_id = window.catalogue.clips()[0]["clip_id"]

    window.start_atomic_edit(clip_id, "Home")
    window.edit({"rating": 5, "mainline": "Conflict clip"})
    window.catalogue.patch(clip_id, {"tag": "external"})
    assert not window.save_atomic_edit()
    assert window.current_panel == "Editing"
    assert window.atomic_edit is not None
    assert window.catalogue.clip(clip_id)["rating"] is None
    assert window.catalogue.clip(clip_id)["tag"] == "external"


def test_atomic_membership_and_close_discard(window, application, tmp_path):
    root = tmp_path / "atomic-membership"
    root.mkdir()
    path = root / "clip.mp4"
    path.write_bytes(b"video")
    folder = window.catalogue.add_folder(root)
    window.catalogue.ingest(folder, [{"path": str(path), "game": "VALORANT"}])
    clip_id = window.catalogue.clips()[0]["clip_id"]
    project_id = window.catalogue.save_project("Project")
    window.refresh_references()
    window.start_atomic_edit(clip_id, "Home")
    history = list(window.catalogue.undo_stack)
    window.membership(True, project_id)
    window.command.setText("jett")
    window.submit()
    assert project_id in window.effective_memberships()
    assert not window.catalogue.member_ids(project_id)
    assert window.history[clip_id] == []
    assert window.atomic_edit.history == ["jett"]
    window.save_atomic_edit()
    assert window.catalogue.member_ids(project_id) == {clip_id}
    assert len(window.catalogue.undo_stack) == len(history) + 1
    assert len(window.editing_histories[clip_id].undo_stack) == 2

    window.start_atomic_edit(clip_id, "Home")
    window.command.setText("jett")
    window.submit()
    window.edit({"rating": 2})
    window.close()
    assert wait_for(application, lambda: window.atomic_edit is None)
    assert window.catalogue.clip(clip_id)["rating"] is None
    assert window.history[clip_id] == ["jett"]


def test_browse_library_is_read_only(window, application, tmp_path, monkeypatch):
    root = tmp_path / "browse-captures"
    root.mkdir()
    folder = window.catalogue.add_folder(root)
    window.catalogue.ingest(
        folder,
        [
            {"path": str(root / f"clip-{index}.mp4"), "game": "VALORANT" if index else None}
            for index in range(3)
        ],
    )
    ids = [clip["clip_id"] for clip in window.catalogue.clips()]
    window.catalogue.patch(ids[0], {"triage": "keep"})
    window.catalogue.patch(ids[1], {"triage": "discard"})
    for index, clip in enumerate(window.catalogue.clips()):
        window.media_info[clip["source_path"]] = {"created": f"2026-09-{index + 1:02}T00:00:00Z"}
    window.refresh_references()
    before = catalogue_dump(window)
    history = list(window.catalogue.undo_stack)
    window.panel("Browse")
    assert list(window.nav) == ["Home", "Browse", "Session", "Editing", "Export", "Config"]
    assert list(window.pages) == list(window.nav)
    assert window.catalogue.state("session") is None
    assert window.library.count() == 0
    window.unavailable_toggle.click()
    assert window.library.count() == 2
    window.clip_filter.menu().actions()[0].trigger()
    assert window.library.count() == 3
    for index in range(window.library.count()):
        item = window.library.item(index)
        assert "undefined" not in item.text().lower()
        assert "2026-09-" not in item.data(CLIP_ROLE)["browse_details"]
        assert "Captured: 2026-09-" in item.toolTip()
        assert "browse-captures" in item.data(CLIP_ROLE)["browse_details"]
        assert str(root) not in item.data(CLIP_ROLE)["browse_details"]
    assert window.browse_id == ids[2]
    assert window.browse.clip["clip_id"] == ids[2]
    assert window.browse.player.status.text() == "Source unavailable"
    assert not window.browse.player.play.isEnabled()
    assert not window.browse.share_button.isEnabled()
    assert not window.filters.isHidden() and window.search.isHidden()
    assert not window.browse_filters.isHidden()
    assert window.command_area.isHidden() and window.splitter.count() == 2
    assert not window.undo_button.isEnabled()
    assert not hasattr(window, "projects_toggle")
    window.toggle_browse_sort()
    assert window.library.item(0).data(Qt.ItemDataRole.UserRole) == ids[0]
    assert window.browse_id == ids[0]
    window.navigate(1)
    assert window.browse_id == ids[1]
    window.browse.custom_title.setText("Disposable")
    window.browse.in_ms = 120
    window.navigate(-1)
    assert window.browse_id == ids[0]
    assert not window.browse.custom_title.text()
    assert window.browse.in_ms is None
    window.navigate(-1)
    assert window.browse_id == ids[0]
    for action in [
        lambda: window.edit({"triage": "discard"}),
        window.undo,
        lambda: window.undo(True),
        window.reset_metadata,
        window.edit_tag,
        window.new_project,
        window.delete_project,
        lambda: window.membership(True, "absent"),
        lambda: window.create_session("all"),
        window.end_session,
        window.delete_rejected,
        lambda: window.save_range(10, 20),
    ]:
        action()
    for action in window.game_filter.menu().actions():
        if action.text() == "Uncategorized":
            action.trigger()
            break
    assert window.library.count() == 2
    window.browse_search.setText("missing text")
    window.refresh_library()
    assert window.library.count() == 0
    assert window.browse.clip is None
    assert window.browse.player.status.text() == "No clip selected"
    window.panel("Home")
    assert window.clip_filter.all_selected()
    assert catalogue_dump(window) == before
    assert window.catalogue.undo_stack == history


def test_browse_relative_time_refreshes_without_rebuilding_library(window, tmp_path):
    clip_id = add_clips(window, tmp_path)[0]
    clip = window.catalogue.clip(clip_id)
    now = datetime.now(timezone.utc)
    window.media_info[clip["source_path"]] = {"created": (now - timedelta(days=2)).isoformat()}
    window.panel("Browse")
    assert window.browse_time_timer.isActive()
    item = window.library.currentItem()
    assert item.data(CLIP_ROLE)["browse_details"].startswith("2 days ago")
    assert "Captured:" in item.toolTip()
    window.request_visible_thumbnails()

    window.media_info[clip["source_path"]] = {"created": (now - timedelta(minutes=2)).isoformat()}
    window.browse_time_timer.timeout.emit()
    assert window.library.currentItem() is item
    assert item.data(CLIP_ROLE)["browse_details"].startswith("2 minutes ago")
    window.panel("Home")
    assert not window.browse_time_timer.isActive()


def test_home_and_session_cards_show_compact_time_without_rebuilding(
    window, tmp_path, monkeypatch
):
    clip_id = add_clips(window, tmp_path)[0]
    clip = window.catalogue.clip(clip_id)
    now = datetime.now(timezone.utc)
    label = {"value": "2 minutes ago"}
    monkeypatch.setattr(
        "dfsorter.overview.relative_capture_time",
        lambda captured, current_time=None: label["value"],
    )
    window.media_info[clip["source_path"]] = {"created": (now - timedelta(minutes=2)).isoformat()}
    window.panel("Home")
    item = window.library.item(0)
    assert window.library_time_timer.isActive()
    assert item.data(CLIP_ROLE)["compact_time"] == "2m ago"
    assert "Captured:" in item.toolTip()
    label["value"] = "4 minutes ago"
    window.library_time_timer.timeout.emit()
    assert window.library.item(0) is item
    assert item.data(CLIP_ROLE)["compact_time"] == "4m ago"
    window.panel("Session")
    assert window.library.item(0).data(CLIP_ROLE)["compact_time"] == "4m ago"
    window.panel("Browse")
    assert not window.library_time_timer.isActive()
    assert window.library.item(0).data(CLIP_ROLE)["compact_time"] is None


def test_browse_temporary_range_and_share(window, application, tmp_path, monkeypatch):
    ids = add_clips(window, tmp_path, valid=True)
    window.catalogue.patch(ids[0], {"in_ms": 500, "out_ms": 1500})
    before = catalogue_dump(window)
    window.panel("Browse")
    browse = window.browse
    assert wait_for(application, lambda: not browse.player.awaiting_frame)
    assert browse.player.media.position() == 500
    assert browse.mode.currentData() is True
    browse.destination.setText(str(tmp_path / "shares"))
    browse.custom_title.setText(" ")
    assert not browse.share_button.isEnabled()
    browse.custom_title.setText("My Custom 中文 Clip")
    assert browse.share_button.isEnabled()
    browse.player.media.setPosition(800)
    window.mark_in()
    assert browse.in_ms == 800
    window.toggle_browse_sort()
    assert browse.in_ms == 800
    assert browse.custom_title.text() == "My Custom 中文 Clip"
    calls = []
    monkeypatch.setattr(
        "dfsorter.browse.share_clip", lambda *args, **kwargs: calls.append((args, kwargs))
    )
    work = []
    monkeypatch.setattr(
        window.activities, "submit",
        lambda kind, title, function, **kwargs: work.append(function),
    )
    window.settings["share_quality"] = "web_1080p"
    browse.share()
    assert browse.share_button.property("shareAccepted") is True
    browse.custom_title.setText("Changed after snapshot")
    browse.in_ms = 1000
    window.settings["share_quality"] = "native"
    work[0](lambda: False, lambda percent, text: None)
    args, kwargs = calls[0]
    assert args[0]["in_ms"] == 800
    assert args[0]["out_ms"] == 1500
    assert kwargs["custom"] == "My Custom 中文 Clip"
    assert kwargs["selected_range"] is True
    assert kwargs["quality"] == "web_1080p"
    window.clear_range()
    browse.player.media.setPosition(1800)
    window.mark_in()
    assert not browse.valid_range()
    assert browse.mode.currentData() is False
    assert browse.share_button.isEnabled()  # Whole clip needs no valid markers.
    window.panel("Home")
    assert browse.clip is None
    assert not browse.custom_title.text()
    assert catalogue_dump(window) == before
    window.panel("Browse")
    assert wait_for(application, lambda: not browse.player.awaiting_frame)
    assert (browse.in_ms, browse.out_ms) == (500, 1500)
    assert not browse.custom_title.text()


def test_search_updates_live_and_invalid_query_preserves_results(window, application, tmp_path):
    add_clips(window, tmp_path)
    window.catalogue.patch(
        window.catalogue.clips()[0]["clip_id"],
        {"mainline": "Ace", "metadata": {"agent": "Jett"}, "tag": "Highlight", "rating": 4},
    )
    window.refresh_library()
    for panel, search in (("Home", window.search), ("Browse", window.browse_search)):
        window.panel(panel)
        search.setText("highlight")
        application.processEvents()
        assert window.library.count() == 1
        search.setText("agent:")
        application.processEvents()
        assert window.library.count() == 1
        assert not window.library_error.isHidden()
        search.setText("jett")
        application.processEvents()
        assert window.library.count() == 1
        assert window.library_error.isHidden()
        for expression in ("rating:4", "r4", "rating:>=4"):
            search.setText(expression)
            application.processEvents()
            assert window.library.count() == 1
            assert window.library_error.isHidden()
        search.setText("rating:6")
        application.processEvents()
        assert window.library.count() == 1
        assert not window.library_error.isHidden()


@pytest.mark.parametrize("pane", ["Editing", "Export"])
def test_generated_share_quality_is_frozen(window, tmp_path, monkeypatch, pane):
    ids = add_clips(window, tmp_path)
    monkeypatch.setattr(window, "selected_clip", lambda: window.catalogue.clip(ids[0]))
    window.current_panel = pane
    window.settings.update(share_quality="web_1080p", share_folder=str(tmp_path / "shares"))
    work, calls = [], []
    monkeypatch.setattr(
        window.activities, "submit", lambda kind, title, function, **kwargs: work.append(function)
    )
    monkeypatch.setattr("dfsorter.ui.share_clip", lambda *args, **kwargs: calls.append(kwargs))

    def confirm(dialog):
        dialog.findChild(QLineEdit, "shareCustomFilename").setText("web clip")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", confirm)
    window.share()
    assert len(work) == 1
    window.settings["share_quality"] = "native"
    work[0](lambda: False, lambda *args: None)
    assert calls[0]["quality"] == "web_1080p"


def test_share_quality_settings_use_theme_selector(window, application):
    window.set_theme("dark")
    settings = SettingsDialog(window)
    settings.show()
    application.processEvents()
    combo = settings.share_quality
    assert combo.currentData() == "native"
    assert type(combo) is type(settings.theme) is QComboBox
    assert not combo.isEditable() and not settings.theme.isEditable()
    assert combo.font() == settings.theme.font()
    combo.showPopup()
    application.processEvents()
    QTest.keyClick(combo, Qt.Key.Key_Down)
    QTest.keyClick(combo, Qt.Key.Key_Enter)
    assert combo.currentData() == "web_1080p"
    assert window.settings["share_quality"] == "web_1080p"
    assert yaml.safe_load(window.settings_path.read_text(encoding="utf-8"))["share_quality"] == "web_1080p"
    settings.close()
    restarted = Window(window.root)
    try:
        reopened = SettingsDialog(restarted)
        assert reopened.share_quality.currentData() == "web_1080p"
        reopened.close()
    finally:
        restarted.close()
        application.processEvents()
    window.settings["share_quality"] = "invalid"
    settings = SettingsDialog(window)
    assert settings.share_quality.currentData() == "native"
    settings.close()


def test_generated_share_dialog_defaults_and_master_toggle(
    window, application, tmp_path, monkeypatch
):
    add_clips(window, tmp_path)
    window.panel("Editing")

    def inspect(dialog):
        custom = dialog.findChild(QLineEdit, "shareCustomFilename")
        all_fields = dialog.findChild(QCheckBox, "shareAllFields")
        prefix = dialog.findChild(QCheckBox, "shareGamePrefix")
        fields = [check for check in dialog.findChildren(QCheckBox) if check.objectName().startswith("shareField_")]
        confirm = dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok)
        assert not custom.text() and not all_fields.isChecked() and not prefix.isChecked()
        assert fields and not any(check.isChecked() for check in fields)
        assert not confirm.isEnabled()
        custom.setText("   ")
        assert not confirm.isEnabled()
        all_fields.setChecked(True)
        assert all(check.isChecked() for check in fields) and confirm.isEnabled()
        fields[0].setChecked(False)
        assert not all_fields.isChecked()
        prefix.setChecked(True)
        for check in fields:
            check.setChecked(False)
        assert prefix.isChecked() and confirm.isEnabled()
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", inspect)
    window.share()


def test_all_players_mix_tracks_and_ignore_stale_loads(window, application, tmp_path):
    ids = add_clips(window, tmp_path, valid=True)
    window.preload_timer.stop()
    window.schedule_preload = lambda: None
    original = window.catalogue.clip(ids[0])
    sources = []
    for count in (0, 2):
        target = tmp_path / f"tracks-{count}.mp4"
        args = ["ffmpeg", "-v", "error", "-i", original["source_path"], "-map", "0:v"]
        for _ in range(count):
            args += ["-map", "0:a:0"]
        subprocess.run(args + ["-c", "copy", str(target)], check=True, capture_output=True)
        sources.append({**original, "source_path": str(target), "in_ms": None, "out_ms": None})
    for player in (window.player, window.export_player, window.browse.player):
        player.audio.setMuted(True)
        player.load(sources[0])
        assert wait_for(application, lambda: not player.awaiting_frame)
        assert player.media.duration() > 0
        assert not player.media.hasAudio()
        assert not player.media.engine.lavfi_complex
        for clip in [sources[1], sources[0], sources[1]]:
            player.load(clip)
        assert wait_for(application, lambda: not player.awaiting_frame)
        assert Path(player.media.source().toLocalFile()) == Path(sources[1]["source_path"])
        assert player.media.hasAudio()
        assert "amix=inputs=2" in player.media.engine.lavfi_complex
        assert player.media.engine.audio_params["channel-count"] == 2
        assert not player.media.frame_image().isNull()
        status = player.media.mediaStatus()
        player.media._receive(player.media.generation - 1, "error", "obsolete source failure")
        assert player.media.mediaStatus() == status
        assert not player.status.text()
        player.load(None)


def test_browse_runtime_failure_reveals_page(window, application, tmp_path, monkeypatch):
    add_clips(window, tmp_path, valid=True)

    def missing():
        raise OSError("Playback runtime missing. Run setup-playback.ps1.")

    monkeypatch.setattr("dfsorter.mpv_backend.load_mpv", missing)
    window.panel("Browse")
    assert wait_for(application, lambda: not window.transition_pending)
    assert window.browse.player.status.text() == "Playback runtime missing. Run setup-playback.ps1."
    assert not window.browse.player.awaiting_frame
    assert not window.browse.player.play.isEnabled()


def test_browse_layout(window, application, tmp_path):
    ids = add_clips(window, tmp_path, valid=True)
    clip = window.catalogue.clip(ids[0])
    window.catalogue.patch(
        ids[0],
        {
            "mainline": "残局 中文 English — accurate shot",
            "triage": "keep",
            "metadata": {"agent": "Jett", "weapon": ["Vandal", "Sheriff"], "kill": 3},
            "in_ms": 500,
            "out_ms": 1500,
        },
    )
    window.catalogue.ingest(
        window.catalogue.folders()[0]["folder_id"],
        [
            {"path": str(tmp_path / "captures" / "unavailable.mp4"), "game": None},
        ],
    )
    window.media_info[clip["source_path"]] = {"created": "2026-09-20T00:00:00Z"}
    window.panel("Browse")
    window.browse.custom_title.setText("Weekend highlights — 精选")
    window.browse.destination.setText(str(tmp_path / "share-output"))
    assert wait_for(application, lambda: not window.transition_pending)
    scale = os.environ.get("QT_SCALE_FACTOR", "1")
    artifact = ROOT / "cache/verification/browse" / scale
    artifact.mkdir(parents=True, exist_ok=True)
    for name, show in [("normal", window.showNormal), ("maximized", window.showMaximized)]:
        show()
        window.activateWindow()
        window.raise_()
        QTest.qWait(200)
        browse = window.browse
        assert browse.player.video.height() >= 150
        assert browse.player.media._video_size == (320, 180)
        surface = browse.player.video.geometry()
        assert abs(surface.width() * 180 - surface.height() * 320) <= 320
        assert (
            browse.share_button.mapTo(browse, QPoint(0, browse.share_button.height())).y()
            <= browse.height()
        )
        assert browse.custom_title.width() > 200
        assert window.splitter.count() == 2
        # Capture the composed desktop region: HWND capture omits D3D child surfaces.
        rect = window.geometry()
        window.screen().grabWindow(0, rect.x(), rect.y(), rect.width(), rect.height()).save(
            str(artifact / f"{name}.png")
        )


def test_export_player_grows_with_window(window, application, tmp_path):
    ids = add_clips(window, tmp_path)
    project = window.catalogue.save_project("Export layout")
    window.catalogue.patch(ids[0], {}, membership=(project, True))
    window.refresh_references()
    window.export_project.setCurrentIndex(window.export_project.findData(project))
    window.panel("Export")
    window.resize(1400, 900)
    application.processEvents()
    normal_height = window.export_player.video.height()
    window.resize(1400, 1200)
    application.processEvents()
    assert window.export_player.video.height() >= normal_height + 250
    assert window.export_button.geometry().bottom() < window.pages["Export"][0].height()
    artifact = ROOT / "cache/verification/export-layout"
    artifact.mkdir(parents=True, exist_ok=True)
    for state, show in [("maximized", window.showMaximized), ("fullscreen", window.showFullScreen)]:
        show()
        QTest.qWait(150)
        assert window.export_player.height() > 300
        window.grab().save(str(artifact / f"{state}.png"))


def test_deletion_confirmation_and_settings(window, application, tmp_path, monkeypatch):
    ids = add_clips(window, tmp_path)
    window.catalogue.patch(ids[0], {"triage": "discard"})
    window.refresh_references()
    dialog = DeletionDialog(preview(window.catalogue), window)
    dialog.show()
    application.processEvents()
    assert dialog.tree.topLevelItemCount() == 1
    assert dialog.tree.topLevelItem(0).child(0).text(0).endswith("libx264.mp4")
    assert dialog.delete_button.isEnabled()
    dialog.reject()
    assert Path(window.catalogue.clip(ids[0])["source_path"]).exists()
    project_id = window.catalogue.save_project("Example")
    window.refresh_references()
    settings = SettingsDialog(window)
    assert not hasattr(settings, "folders")
    assert window.pages["Home"][0].isAncestorOf(window.folders)
    assert not hasattr(settings, "projects")
    window.folders.setCurrentRow(0)
    window.toggle_folder()
    assert not window.catalogue.folders()[0]["enabled"]
    monkeypatch.setattr(window, "confirm", lambda message: True)
    window.panel("Export")
    window.workspace.select_project(project_id)
    window.delete_project()
    assert not window.catalogue.projects()
    assert Path(window.catalogue.clip(ids[0])["source_path"]).exists()
    assert not window.settings_button.icon().isNull()
    settings.close()


@pytest.mark.parametrize("enabled", [True, False])
def test_home_folder_context_toggle(window, application, tmp_path, enabled):
    ids = add_clips(window, tmp_path)
    session = window.catalogue.state("session")
    target = window.catalogue.folders()[0]["folder_id"]
    other_path = tmp_path / "other-captures"
    other_path.mkdir()
    other = window.catalogue.add_folder(other_path)
    window.catalogue.enable_folder(target, enabled)
    window.refresh_references()
    window.panel("Home")
    items = {
        window.folders.item(i).data(Qt.ItemDataRole.UserRole): window.folders.item(i)
        for i in range(window.folders.count())
    }
    window.folders.setCurrentItem(items[other])
    position = window.folders.visualItemRect(items[target]).center()
    window.folders.customContextMenuRequested.emit(position)
    application.processEvents()
    menu = window.folder_context_menu
    assert menu.isVisible()
    assert window.selected_id(window.folders) == target
    assert [action.text() for action in menu.actions()] == [
        "Pause scanning" if enabled else "Resume scanning",
        "Relink folder…",
        "Remove folder…",
    ]
    assert all(action.isEnabled() for action in menu.actions())
    assert "Relink folder…" not in [action.text() for action in window.folder_menu.actions()]
    assert "Remove folder…" not in [action.text() for action in window.folder_menu.actions()]
    action = menu.actions()[0]
    assert action.isEnabled()
    QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(action).center())
    folders = {folder["folder_id"]: folder for folder in window.catalogue.folders()}
    assert bool(folders[target]["enabled"]) is not enabled
    assert folders[other]["enabled"]
    assert window.catalogue.clip(ids[0]) is not None
    assert window.catalogue.state("session") == session
    assert window.folders.currentItem().data(FOLDER_ROLE)["status"] == (
        "Paused" if enabled else "Enabled"
    )


def test_home_folder_context_guards(window, application, tmp_path):
    add_clips(window, tmp_path)
    window.panel("Home")
    menu = window.folder_context_menu
    window.folders.customContextMenuRequested.emit(QPoint(-1, -1))
    assert not menu.isVisible()
    item = window.folders.item(0)
    position = window.folders.visualItemRect(item).center()
    window.worker = object()
    try:
        window.folders.customContextMenuRequested.emit(position)
        assert menu.isVisible()
        assert all(not action.isEnabled() for action in menu.actions())
        menu.hide()
    finally:
        window.worker = None
    item.setData(Qt.ItemDataRole.UserRole, "__unlinked__")
    window.folders.customContextMenuRequested.emit(position)
    assert not menu.isVisible()
    window.folders.setCurrentItem(item)
    window.update_folder_actions()
    assert window.folder_unlinked_remove_action.isVisible()
    assert window.folder_unlinked_remove_action.isEnabled()


def test_home_folder_hierarchy_and_summary(window, application, tmp_path):
    first = tmp_path / "MEDAL-EXP"
    second = tmp_path / "NVIDIA"
    first.mkdir()
    second.mkdir()
    (first / "other.bin").write_bytes(b"non-video content")
    first_id = window.catalogue.add_folder(first)
    second_id = window.catalogue.add_folder(second)
    window.catalogue.ingest(
        first_id,
        [
            {"path": str(first / "valorant-1.mp4"), "game": "VALORANT"},
            {"path": str(first / "valorant-2.mp4"), "game": "VALORANT"},
            {"path": str(first / "eft.mp4"), "game": "Escape from Tarkov"},
        ],
    )
    window.catalogue.ingest(
        second_id,
        [{"path": str(second / "unknown.mp4"), "game": None}],
    )
    window.catalogue.enable_folder(second_id, False)
    for index, clip in enumerate(window.catalogue.clips(), start=1):
        window.media_info[clip["source_path"]] = {"duration": float(index * 10)}
    window.refresh_references()
    window.panel("Home")
    assert wait_for(application, lambda: window.folder_sizes.get(str(first)) is not None)

    assert isinstance(window.folders.itemDelegate(), CaptureFolderDelegate)
    assert window.folder_summary.text() == "2 folders · 4 clips"
    assert window.folder_more.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextOnly
    assert window.folder_more.text() == "More…"
    assert window.folder_more.icon().isNull()
    assert window.add_folder_button.property("role") == "prominentNeutral"
    assert window.add_folder_button.property("iconColorRole") == "accent_default"
    assert all(
        control.property("captureFolderAction")
        for control in (window.add_folder_button, window.game_configs_button,
                        window.rescan_button, window.folder_more)
    )
    assert len({control.height() for control in (
        window.add_folder_button, window.game_configs_button,
        window.rescan_button, window.folder_more,
    )}) == 1
    home_layout = window.add_folder_button.parentWidget().layout()
    controls = next(
        item.layout() for index in range(home_layout.count())
        if (item := home_layout.itemAt(index)).layout()
        and item.layout().indexOf(window.add_folder_button) >= 0
    )
    assert controls.itemAt(controls.indexOf(window.add_folder_button) + 1).widget() is window.game_configs_button
    items = {
        window.folders.item(row).data(Qt.ItemDataRole.UserRole): window.folders.item(row)
        for row in range(window.folders.count())
    }
    first_data = items[first_id].data(FOLDER_ROLE)
    second_data = items[second_id].data(FOLDER_ROLE)
    assert first_data == {
        "path": str(first),
        "status": "Enabled",
        "enabled": True,
        "summary": "3 clips · 0.00 GB",
        "summary_new": "",
        "details": "VALORANT: 2 (2 new)   Escape from Tarkov: 1 (1 new)",
        "game_details": [
            {"text": "VALORANT: 2", "new": 2, "deleted": 0},
            {"text": "Escape from Tarkov: 1", "new": 1, "deleted": 0},
        ],
    }
    assert second_data["status"] == "Paused"
    assert second_data["details"] == "Unknown: 1 (1 new)"
    assert (FONT_SIZES["md"], FONT_SIZES["sm"], FONT_SIZES["xs"]) == (13, 12, 11)

    artifact = ROOT / "cache/verification/home-folders"
    artifact.mkdir(parents=True, exist_ok=True)
    window.resize(1100, 720)
    window.grab().save(str(artifact / "hierarchy-light.png"))
    window.set_theme("dark")
    application.processEvents()
    window.grab().save(str(artifact / "hierarchy-dark.png"))


def test_home_folder_new_counts_use_opening_catalogue_baseline(window, application, tmp_path):
    folder = tmp_path / "captures"
    folder.mkdir()
    folder_id = window.catalogue.add_folder(folder)
    existing = folder / "existing.mp4"
    with existing.open("wb") as source:
        source.truncate(16 * 1024 * 1024)
    window.catalogue.ingest(folder_id, [{"path": str(existing), "game": "VALORANT"}])
    window.opening_clip_ids.add(window.catalogue.clips()[0]["clip_id"])
    added = folder / "added.mp4"
    with added.open("wb") as source:
        source.truncate(8 * 1024 * 1024)
    with (folder / "notes.txt").open("wb") as source:
        source.truncate(16 * 1024 * 1024)
    window.catalogue.ingest(folder_id, [{"path": str(added), "game": "VALORANT"}])

    window.refresh_references()
    assert wait_for(application, lambda: window.folder_sizes.get(str(folder)) is not None)

    data = window.folders.item(0).data(FOLDER_ROLE)
    assert data["summary"].endswith("0.04 GB")
    assert data["summary_new"] == " (+0.01 GB new)"
    assert data["details"] == "VALORANT: 2 (1 new)"
    assert data["game_details"] == [{"text": "VALORANT: 2", "new": 1, "deleted": 0}]


def test_home_shows_deleted_and_new_counts_separately(window, application, tmp_path):
    folder = tmp_path / "captures"
    folder.mkdir()
    folder_id = window.catalogue.add_folder(folder, forced_game="VALORANT")
    deleted = folder / "deleted.mp4"
    deleted.write_bytes(b"video")
    window.catalogue.ingest(folder_id, [{"path": str(deleted), "game": "VALORANT"}])
    deleted.unlink()
    added = folder / "added.mp4"
    added.write_bytes(b"video")
    window.rescan(quiet=True)
    assert wait_for(application, lambda: window.worker is None and len(window.catalogue.clips()) == 1)
    data = window.folders.item(0).data(FOLDER_ROLE)
    assert data["details"] == "VALORANT: 1 (1 new) (1 deleted)"
    assert data["game_details"] == [
        {"text": "VALORANT: 1", "new": 1, "deleted": 1},
    ]


def test_home_removes_folder_entries_after_confirmation(window, application, tmp_path, monkeypatch):
    ids = add_clips(window, tmp_path)
    source = Path(window.catalogue.clip(ids[0])["source_path"])
    window.panel("Home")
    window.folders.setCurrentRow(0)
    window.update_folder_actions()
    assert window.folder_toggle_action.text() == "Pause scanning"
    assert window.folder_remove_action.isEnabled()
    monkeypatch.setattr(window, "confirm_folder_removal", lambda folder, clips: False)
    window.remove_folder()
    assert len(window.catalogue.clips()) == 1
    monkeypatch.setattr(window, "confirm_folder_removal", lambda folder, clips: True)
    window.remove_folder()
    assert not window.catalogue.clips() and not window.catalogue.folders()
    assert window.catalogue.state("session") is None
    assert not window.nav["Editing"].isEnabled()
    assert source.read_bytes() == b"test"
    backup = next((window.root / "data/backups").glob("*.db"))
    assert Catalogue(backup).clip(ids[0])["source_path"] == str(source.resolve())
    artifact = ROOT / "cache/verification/home-folders"
    artifact.mkdir(parents=True, exist_ok=True)
    application.processEvents()
    window.grab().save(str(artifact / "home.png"))


def test_settings_preserves_capture_folder_case(window, tmp_path):
    captures = tmp_path / "My Captures 游戏"
    captures.mkdir()
    window.catalogue.add_folder(captures)
    window.catalogue = Catalogue(window.catalogue.path)
    window.refresh_references()
    settings = SettingsDialog(window)
    assert str(captures.resolve()) in window.folders.item(0).text()
    settings.close()


def test_manage_unavailable_dialog_groups_paths_and_dismisses_one_row(
    window, application, tmp_path
):
    root = tmp_path / "old"
    root.mkdir()
    (root / "A").mkdir()
    folder_id = window.catalogue.add_folder(root)
    window.catalogue.ingest(folder_id, [
        {"path": str(root / "root.mp4"), "game": "VALORANT"},
        {"path": str(root / "A" / "child.mp4"), "game": "VALORANT"},
    ])
    dialog = UnavailableClipsDialog(window)
    dialog.show()
    application.processEvents()

    buttons = [button.text() for button in dialog.findChildren(QPushButton)]
    assert buttons.count("Do nothing") == 2
    assert buttons.count("Delete…") == 2
    assert buttons.count("Reassociate…") == 2
    assert any("1 video · 0 Keep · 0 Discard · 1 Pending" in label.text()
               for label in dialog.findChildren(QLabel))
    dialog.dismiss(str(root / "A"))
    application.processEvents()
    assert str(root / "A") in dialog.dismissed
    assert len(window.catalogue.clips()) == 2
    dialog.close()


def test_playback_preferences_persist(window, application):
    settings = SettingsDialog(window)
    tabs = settings.findChild(QTabWidget)
    assert [tabs.tabText(index) for index in range(tabs.count())] == [
        "General",
        "Appearance",
    ]
    assert tabs.currentIndex() == 0
    group_headings = {
        label.text()
        for group in settings.findChildren(QWidget)
        if group.property("role") == "group"
        for label in group.findChildren(QLabel)
        if label.property("settingsGroupHeading")
    }
    assert group_headings == {"Browse · Editing · Export", "Editing", "Share"}
    assert settings.start_near_end.isChecked()
    assert not settings.separate_start.isChecked()
    assert settings.start_offset.value() == 40
    assert settings.start_offset.singleStep() == 5
    settings.start_offset.stepUp()
    assert settings.start_offset.value() == 45
    settings.start_offset.stepDown()
    assert settings.start_offset.value() == 40
    assert settings.paused_typing.isChecked()
    settings.paused_typing.setChecked(False)
    settings.start_offset.setValue(17)
    settings.start_near_end.setChecked(False)
    assert not settings.start_offset.isEnabled()
    settings.close()
    restarted = Window(window.root)
    try:
        restored = SettingsDialog(restarted)
        assert restored.start_offset.value() == 17
        assert not restored.start_near_end.isChecked()
        assert not restored.paused_typing.isChecked()
        assert restarted.player.settings["start_near_end_seconds"] == 17
        assert restarted.browse.player.settings["start_near_end_seconds"] == 17
        assert restarted.export_player.settings["start_near_end_enabled"] is False
        assert not restored.separate_start.isChecked()
        restored.close()
    finally:
        restarted.close()
        application.processEvents()


def test_separate_playback_preferences_persist(window, application):
    from dfsorter.playback import playback_start_settings, start_offset_seconds

    settings = SettingsDialog(window)
    assert settings.start_offset.property("playbackOffset") is True
    assert settings.start_offset.sizeHint().height() <= 29
    assert settings.start_offset.width() == 52
    assert settings.start_offset.maximum() == 999
    assert settings.start_offset.lineEdit().textMargins().bottom() == 1
    assert start_offset_seconds({"start_near_end_seconds": 86400}) == 999
    assert playback_start_settings(
        {
            "start_near_end_separate": True,
            "start_near_end_browse_seconds": 86400,
        },
        "Browse",
    ) == (True, 999)
    settings.start_offset.setValue(17)
    settings.separate_start.setChecked(True)
    assert settings.start_near_end.isHidden()
    assert settings.start_offset.isHidden()
    assert not settings.separate_start_group.isHidden()
    for check, offset in settings.pane_start_controls.values():
        assert check.isChecked()
        assert offset.value() == 17
        assert offset.width() == 52
        assert offset.maximum() == 999
        assert offset.lineEdit().textMargins().bottom() == 1
        assert offset.sizeHint().height() == settings.start_offset.sizeHint().height()
    browse_check, browse_offset = settings.pane_start_controls["Browse"]
    editing_check, editing_offset = settings.pane_start_controls["Editing"]
    export_check, export_offset = settings.pane_start_controls["Export"]
    browse_check.setChecked(False)
    editing_offset.setValue(23)
    export_offset.setValue(31)
    settings.separate_start.setChecked(False)
    assert settings.start_offset.value() == 17
    settings.start_offset.setValue(19)
    settings.separate_start.setChecked(True)
    assert not browse_check.isChecked()
    assert browse_offset.value() == 17
    assert editing_check.isChecked() and editing_offset.value() == 23
    assert export_check.isChecked() and export_offset.value() == 31
    assert not browse_offset.isEnabled()
    assert (window.browse.player.pane, window.player.pane, window.export_player.pane) == (
        "Browse", "Editing", "Export"
    )
    assert playback_start_settings(window.settings, "Browse") == (False, 17)
    assert playback_start_settings(window.settings, "Editing") == (True, 23)
    assert playback_start_settings(window.settings, "Export") == (True, 31)
    settings.close()
    restarted = Window(window.root)
    try:
        restored = SettingsDialog(restarted)
        assert restored.separate_start.isChecked()
        assert restored.start_offset.value() == 19
        assert not restored.pane_start_controls["Browse"][0].isChecked()
        assert restored.pane_start_controls["Editing"][1].value() == 23
        assert restored.pane_start_controls["Export"][1].value() == 31
        assert playback_start_settings(restarted.settings, "Browse") == (False, 17)
        restored.close()
    finally:
        restarted.close()
        application.processEvents()


def test_settings_empty_space_clears_checkbox_focus(window, application):
    settings = SettingsDialog(window)
    settings.show()
    application.processEvents()
    settings.separate_start.setChecked(True)
    settings.separate_start.setFocus()
    assert settings.separate_start.hasFocus()
    tabs = settings.findChild(QTabWidget)
    general = tabs.widget(0)
    assert general.focusPolicy() == Qt.FocusPolicy.NoFocus
    QTest.mouseClick(general, Qt.MouseButton.LeftButton, pos=QPoint(general.width() - 8, 8))
    assert not settings.separate_start.hasFocus()
    settings.separate_start.setFocus()
    QTest.mouseClick(settings, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
    assert not settings.separate_start.hasFocus()
    settings.close()


def test_main_window_close_ends_open_settings_dialog(window, application):
    import yaml
    window.open_settings()
    dialog = window.settings_dialog
    dialog.start_offset.setValue(27)
    assert window.close()
    assert not dialog.isVisible()
    assert not window.isVisible()
    assert window.settings_dialog is None
    assert yaml.safe_load(window.settings_path.read_text(encoding="utf-8"))[
        "start_near_end_seconds"
    ] == 27


def test_settings_dialog_blocks_main_window_controls(window, application):
    window.open_settings()
    dialog = window.settings_dialog
    assert dialog.isVisible()
    QTest.mouseClick(window.nav["Browse"], Qt.MouseButton.LeftButton)
    assert window.current_panel == "Home"
    dialog.start_offset.setValue(26)
    assert window.settings["start_near_end_seconds"] == 26
    dialog.close()
    application.processEvents()
    assert window.settings_dialog is None


@pytest.mark.skipif(os.name != "nt", reason="Windows taskbar close behavior")
def test_windows_close_message_ends_open_settings_dialog(window, application):
    import ctypes

    import yaml
    window.open_settings()
    window.settings_dialog.start_offset.setValue(29)
    assert ctypes.windll.user32.PostMessageW(int(window.winId()), 0x0112, 0xF060, 0)
    assert wait_for(application, lambda: not window.isVisible())
    assert not window.isVisible()
    assert window.settings_dialog is None
    assert yaml.safe_load(window.settings_path.read_text(encoding="utf-8"))[
        "start_near_end_seconds"
    ] == 29


def test_theme_switching_and_persistence(window, application):
    import yaml

    from dfsorter.theme import COLORS, THEMES

    settings = SettingsDialog(window)
    assert settings.theme.currentData() == "light"
    assert COLORS["surface_canvas"] == THEMES["light"]["surface_canvas"]
    assert (
        len(
            {
                COLORS["surface_canvas"],
                COLORS["surface_workspace"],
                COLORS["surface_sidebar"],
            }
        )
        == 3
    )
    assert window.left.property("role") == "sidebar"
    assert window.splitter.count() == 2
    assert window.shortcut_hint.property("role") == "helper"
    assert window.theme_button.toolTip() == "Switch to dark mode"

    settings.theme.setCurrentIndex(settings.theme.findData("dark"))
    application.processEvents()
    assert COLORS["surface_canvas"] == THEMES["dark"]["surface_canvas"]
    assert window.theme_button.toolTip() == "Switch to light mode"
    assert yaml.safe_load(window.settings_path.read_text(encoding="utf-8"))["theme"] == "dark"
    settings.close()

    restarted = Window(window.root)
    try:
        assert restarted.settings["theme"] == "dark"
        assert restarted.theme_button.toolTip() == "Switch to light mode"
        assert COLORS["surface_canvas"] == THEMES["dark"]["surface_canvas"]
    finally:
        restarted.close()
        application.processEvents()

    window.set_theme("light")
    settings = SettingsDialog(window)
    settings.theme.setCurrentIndex(settings.theme.findData("system"))
    assert window.settings["theme"] == "system"
    resolved_before_toggle = COLORS["surface_canvas"]
    settings.close()
    window.theme_button.click()
    assert window.settings["theme"] in {"light", "dark"}
    assert COLORS["surface_canvas"] != resolved_before_toggle
    window.set_theme("light")


def add_clips(window, tmp_path, valid=False, codec="libx264"):
    captures = tmp_path / "captures"
    captures.mkdir(exist_ok=True)
    path = captures / f"{codec}.mp4"
    if valid:
        cached = ROOT / "cache/test-videos" / f"{codec}.mp4"
        if not cached.is_file():
            if not shutil.which("ffmpeg"):
                pytest.skip("ffmpeg required for playback fixtures")
            cached.parent.mkdir(parents=True, exist_ok=True)
            codec_options = ["-cpu-used", "8"] if codec == "libaom-av1" else []
            subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc2=size=320x180:rate=24",
                    "-f",
                    "lavfi",
                    "-i",
                    # Keep an audio track for playback coverage without audible test tones.
                    "anullsrc=channel_layout=mono:sample_rate=44100",
                    "-t",
                    "3",
                    "-c:v",
                    codec,
                    *codec_options,
                    "-threads",
                    "2",
                    "-c:a",
                    "aac",
                    str(cached),
                ],
                check=True,
                capture_output=True,
            )
        shutil.copyfile(cached, path)
    else:
        path.write_bytes(b"test")
    folder_id = window.catalogue.add_folder(captures)
    window.catalogue.ingest(folder_id, [{"path": str(path), "game": "VALORANT"}])
    ids = [clip["clip_id"] for clip in window.catalogue.clips()]
    window.catalogue.create_session(ids)
    window.refresh_references()
    return ids


def test_editing_f_maximizes_only_in_review_mode(window, application, tmp_path):
    add_clips(window, tmp_path)
    window.panel("Editing")
    application.processEvents()
    window.showNormal()
    window.review_mode()

    QTest.keyClick(window.player, Qt.Key.Key_F)
    assert window.isMaximized()
    assert application.focusWidget() is not window.command
    assert window.command.text() == ""

    QTest.keyClick(window.player, Qt.Key.Key_F)
    assert window.isMaximized()

    window.showNormal()
    window.command.setFocus()
    QTest.keyClick(window.command, Qt.Key.Key_F)
    assert not window.isMaximized()
    assert window.command.text() == "f"


def test_keyboard_and_session_ui(window, application, tmp_path):
    assert not window.nav["Editing"].isEnabled()
    ids = add_clips(window, tmp_path)
    window.panel("Editing")
    application.processEvents()
    shortcut_document = QTextDocument()
    shortcut_document.setHtml(window.shortcut_hint.text())
    assert shortcut_document.toPlainText() == (
        "Space Play/pause · I/O Range · Enter Metadata · "
        "Shift+Enter Verdict + next · F Maximize · ? All shortcuts"
    )
    window.command.setFocus()
    window.command.setText("jett vandal R4")
    QTest.keyClick(window.command, Qt.Key.Key_Return)
    assert window.catalogue.clip(ids[0])["triage"] is None
    assert window.catalogue.clip(ids[0])["rating"] == 4
    assert application.focusWidget() is window.command
    window.command.setFocus()
    window.command.setText("sage jett")
    QTest.keyClick(window.command, Qt.Key.Key_Return)
    assert window.command.text() == "sage jett"
    assert window.catalogue.clip(ids[0])["metadata"]["agent"] == "Jett"
    window.command.setText("abc")
    QTest.keyClick(window.command, Qt.Key.Key_Backspace)
    assert window.command.text() == "ab"
    window.command.setText("jettvandal")
    window.command.setCursorPosition(4)
    QTest.keyClick(window.command, Qt.Key.Key_Equal)
    assert window.command.text() == "jett -- vandal"
    assert window.command.cursorPosition() == 8
    QTest.keyClick(window.command, Qt.Key.Key_Backspace)
    assert window.command.text() == "jettvandal"
    assert window.command.cursorPosition() == 4
    QTest.keyClick(window.command, Qt.Key.Key_Equal)
    QTest.keyClick(window.command, Qt.Key.Key_Left)
    QTest.keyClick(window.command, Qt.Key.Key_Right)
    QTest.keyClick(window.command, Qt.Key.Key_Backspace)
    assert window.command.text() == "jett --vandal"
    for original, inserted, restored in (
        ("jett", "jett -- ", "jett"),
        ("jett ", "jett -- ", "jett "),
        ("jett   ", "jett -- ", "jett "),
        ("jett -- title ", "jett -- title  -- ", "jett -- title "),
    ):
        window.command.setText(original)
        QTest.keyClick(window.command, Qt.Key.Key_Equal)
        assert window.command.text() == inserted
        assert window.command.cursorPosition() == len(inserted)
        QTest.keyClick(window.command, Qt.Key.Key_Backspace)
        assert window.command.text() == restored
        assert window.command.cursorPosition() == len(restored)
        QTest.keyClick(window.command, Qt.Key.Key_Space)
        assert window.command.text() == restored + " "
    window.command.setText("jett ")
    QTest.keyClick(window.command, Qt.Key.Key_Equal)
    QTest.keyClick(window.command, Qt.Key.Key_Space)
    assert window.command.text() == "jett -- "
    QTest.keyClick(window.command, Qt.Key.Key_Backspace)
    assert window.command.text() == "jett "
    QTest.keyClick(window.command, Qt.Key.Key_Space)
    assert window.command.text() == "jett  "
    QTest.keyClick(window.command, Qt.Key.Key_Equal)
    QTest.keyClick(window.command, Qt.Key.Key_Space)
    QTest.keyClick(window.command, Qt.Key.Key_Space)
    assert window.command.text() == "jett --  "
    QTest.keyClick(window.command, Qt.Key.Key_Backspace)
    assert window.command.text() == "jett -- "
    window.command.setText("jett")
    QTest.keyClick(window.command, Qt.Key.Key_Equal)
    QTest.keyClicks(window.command, "title ")
    assert window.command.text() == "jett -- title "
    window.command.clear()
    QTest.keyClick(window.command, Qt.Key.Key_Backspace)
    assert window.catalogue.clip(ids[0])["triage"] is None
    QTest.keyClick(window.command, Qt.Key.Key_Escape)
    QTest.keyClick(window.player, Qt.Key.Key_Backspace)
    assert window.catalogue.clip(ids[0])["triage"] == "discard"
    window.command.setFocus()
    QTest.keyClick(window.command, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert window.catalogue.clip(ids[0])["triage"] == "discard"
    window.edit({"triage": None})
    window.command.setFocus()
    QTest.keyClick(window.command, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert window.catalogue.clip(ids[0])["triage"] == "keep"
    QTest.keyClick(window.command, Qt.Key.Key_Escape)
    QTest.keyClick(window.player, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert window.catalogue.clip(ids[0])["triage"] == "keep"
    assert window.search.isHidden() and window.filters.isHidden()
    window.panel("Export")
    assert window.splitter.count() == 2 and window.command_area.isHidden()
    window.panel("Session")
    assert not window.filters.isHidden()


def test_completed_session_ends_without_confirmation_and_decided_clips_do_not_reenter(
    window, application, tmp_path, monkeypatch
):
    add_clips(window, tmp_path)
    second = tmp_path / "captures" / "second.mp4"
    second.write_bytes(b"test")
    window.catalogue.ingest(
        window.catalogue.folders()[0]["folder_id"],
        [{"path": str(second), "game": "VALORANT"}],
    )
    ids = [clip["clip_id"] for clip in window.catalogue.clips()]
    window.catalogue.create_session(ids, replace=True)
    for clip_id in ids:
        window.catalogue.patch(clip_id, {"triage": "keep"})
    window.panel("Editing")
    monkeypatch.setattr(
        window,
        "confirm",
        lambda *_args: (_ for _ in ()).throw(AssertionError("confirmation shown")),
    )

    window.end_session()

    assert window.catalogue.state("session") is None
    assert window.current_panel == "Session"
    assert window.clip_filter.selected_values() == {None}
    pending = tmp_path / "captures" / "pending.mp4"
    pending.write_bytes(b"test")
    window.catalogue.ingest(
        window.catalogue.folders()[0]["folder_id"],
        [{"path": str(pending), "game": "VALORANT"}],
    )
    window.refresh_library()
    pending_id = next(
        clip["clip_id"] for clip in window.catalogue.clips() if clip["triage"] is None
    )
    window.create_session("all")
    assert window.catalogue.state("session")["ids"] == [pending_id]


def test_session_scopes_filter_decided_clips_before_selection_and_first_n(
    window, application, tmp_path
):
    add_clips(window, tmp_path)
    folder_id = window.catalogue.folders()[0]["folder_id"]
    for index in range(3):
        source = tmp_path / "captures" / f"scope-{index}.mp4"
        source.write_bytes(b"test")
        window.catalogue.ingest(folder_id, [{"path": str(source), "game": "VALORANT"}])
    clips = window.catalogue.clips()
    window.catalogue.patch(clips[0]["clip_id"], {"triage": "keep"})
    window.catalogue.patch(clips[2]["clip_id"], {"triage": "discard"})
    window.catalogue.set_state("session", None)
    window.panel("Session")
    window.clip_filter.set_selected_values({None, "keep", "discard"})
    window.session_count.setValue(2)

    window.create_session("first")

    pending_ids = [clip["clip_id"] for clip in clips if clip["triage"] is None]
    visible_ids = [
        window.library.item(index).data(Qt.ItemDataRole.UserRole)
        for index in range(window.library.count())
    ]
    expected = [clip_id for clip_id in visible_ids if clip_id in pending_ids][:2]
    assert window.catalogue.state("session")["ids"] == expected


def test_review_advance_is_separate_from_submission(window, application, tmp_path):
    ids = add_clips(window, tmp_path)
    captures = tmp_path / "captures"
    second = captures / "second.mp4"
    second.write_bytes(b"test")
    window.catalogue.ingest(
        window.catalogue.folders()[0]["folder_id"], [{"path": str(second), "game": "VALORANT"}]
    )
    next_id = next(
        clip["clip_id"] for clip in window.catalogue.clips() if clip["clip_id"] != ids[0]
    )
    window.catalogue.create_session([ids[0], next_id], replace=True)
    window.panel("Editing")
    QTest.keyClick(window.player, Qt.Key.Key_Return)
    assert application.focusWidget() is window.command
    assert window.command.text() == ""
    assert window.catalogue.clip(ids[0])["triage"] is None
    QTest.keyClick(window.command, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert window.current_id == ids[0]
    assert application.focusWidget() is window.command
    assert "at least one metadata field or mainline" in window.command_error.text()
    QTest.keyClick(window.command, Qt.Key.Key_Escape)
    QTest.keyClick(window.player, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert window.current_id == ids[0]
    assert "at least one metadata field or mainline" in window.command_error.text()
    window.command.setFocus()
    window.command.setText("jett vandal")
    QTest.keyClick(window.command, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert window.catalogue.clip(ids[0])["metadata"] == {}
    assert window.command.text() == "jett vandal"
    QTest.keyClick(window.command, Qt.Key.Key_Escape)
    window.edit({"triage": "discard"})
    QTest.keyClick(window.player, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert window.current_id == ids[0]
    assert "submit existing commands" in window.command_error.text()
    window.command.clear()
    window.command.setFocus()
    window.command.setText(" ")
    QTest.keyClick(window.command, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert window.current_id == ids[0]
    assert window.command.text() == " "
    window.command.clear()
    QTest.keyClick(window.command, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert window.current_id == next_id
    assert window.catalogue.clip(ids[0])["triage"] == "discard"
    window.command.setFocus()
    window.command.setText("jett vandal")
    QTest.keyClick(window.command, Qt.Key.Key_Return)
    assert window.current_id == next_id
    assert window.catalogue.clip(next_id)["triage"] is None
    QTest.keyClick(window.command, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert window.catalogue.clip(next_id)["triage"] == "keep"
    assert "Session complete" in window.statusBar().currentMessage()


def test_field_checklist_previews_commands_without_saving(window, application, tmp_path):
    ids = add_clips(window, tmp_path)
    window.panel("Editing")
    saved = window.catalogue.clip(ids[0])
    original = window.field_reminder.text()
    window.command.setFocus()
    QTest.keyClicks(window.command, "jett R3 -- Example")
    for key in ("agent", "rating", "mainline"):
        assert f"✓</span>&nbsp;{key}" in window.field_reminder.text()
    assert symbol_text("✓") in window.field_reminder.text()
    assert "press Enter to save" in window.field_reminder.toolTip()
    assert window.catalogue.clip(ids[0]) == saved
    window.render_clip()
    assert "✓</span>&nbsp;agent" in window.field_reminder.text()
    window.command.setText('jett tag:"unfinished')
    assert "✓</span>&nbsp;agent" in window.field_reminder.text()
    assert window.command.property("validationState") == "incomplete"
    assert window.command_error.isHidden()
    window.command.clear()
    assert window.field_reminder.text() == original
    window.command.setText("jett tag:Example")
    window.submit()
    assert window.catalogue.clip(ids[0])["metadata"]["agent"] == "Jett"
    window.command.setText('tag:""')
    assert "o&nbsp;tag" in window.field_reminder.text()
    assert "✓</span>&nbsp;agent" in window.field_reminder.text()
    assert window.catalogue.clip(ids[0])["tag"] == "Example"
    window.command.clear()
    assert "✓</span>&nbsp;tag" in window.field_reminder.text()


def test_checklist_symbols_use_font_with_glyph_coverage(application):
    from PySide6.QtGui import QFont, QRawFont

    from dfsorter.theme import SYMBOL_FONT_FAMILY

    if os.name != "nt":
        pytest.skip("Windows first-use font fallback regression")
    assert SYMBOL_FONT_FAMILY == "Segoe UI Symbol"
    raw_font = QRawFont.fromFont(QFont(SYMBOL_FONT_FAMILY))
    for glyph in ("✓", "◇"):
        assert raw_font.supportsCharacter(ord(glyph))
        document = QTextDocument()
        document.setDefaultFont(application.font())
        document.setHtml(symbol_text(glyph) + " agent")
        fragment = document.begin().begin().fragment()
        assert fragment.text() == glyph
        assert fragment.charFormat().fontFamilies() == [SYMBOL_FONT_FAMILY]


def test_chinese_text_uses_windows_ui_font_fallback(application):
    from PySide6.QtGui import QTextLayout

    if os.name != "nt":
        pytest.skip("Windows Chinese UI font fallback")
    chinese_families = [
        family for family in application.font().families()
        if family in {"Microsoft YaHei UI", "Microsoft JhengHei UI"}
    ]
    if not chinese_families:
        pytest.skip("Windows Chinese UI fonts are not installed")

    layout = QTextLayout("Segoe 中文", application.font())
    layout.beginLayout()
    line = layout.createLine()
    line.setLineWidth(500)
    layout.endLayout()
    rendered_families = {run.rawFont().familyName() for run in layout.glyphRuns()}
    assert "Segoe UI" in rendered_families
    assert chinese_families[0] in rendered_families
    assert "SimSun" not in rendered_families


def test_field_checklist_hover_shows_all_overwatch_options(window, application, tmp_path):
    ids = add_clips(window, tmp_path)
    window.catalogue.patch(ids[0], {"game": "Overwatch"})
    window.panel("Editing")
    application.processEvents()
    checklist = window.field_reminder
    assert checklist.isVisible()
    checklist.linkHovered.emit("field:hero")
    assert window.field_reminder_hover == "hero"
    tooltip = QTextDocument()
    tooltip.setHtml(checklist.toolTip())
    plain = tooltip.toPlainText()
    assert "Saved metadata." in plain
    assert "Valid options (53):" in plain
    assert "D.Va (dva)" in plain
    assert "D.Va (<i>dva</i>)" in checklist.toolTip()
    assert "Zenyatta" in plain
    assert all(value in plain for value in window.registry.game("Overwatch").fields["hero"]["values"])
    assert "Multiple values can be entered in order." in plain
    assert "<table>" in checklist.toolTip()
    assert "Chamber (<i>ch</i>)" in window.field_options_tooltip(
        window.registry.game("VALORANT"), "agent", "Saved metadata."
    )

    checklist.linkHovered.emit("field:map")
    tooltip.setHtml(checklist.toolTip())
    plain = tooltip.toPlainText()
    assert "Valid options (30):" in plain
    assert "Watchpoint: Gibraltar (gibraltar)" in plain
    assert "Suravasa" in plain
    assert all(value in plain for value in window.registry.game("Overwatch").fields["map"]["values"])

    checklist.linkHovered.emit("")
    assert "✓ populated" in checklist.toolTip()
    window.command.setText("dva unknown ")
    checklist.linkHovered.emit("field:hero")
    assert "Partial command preview" in checklist.toolTip()


def test_inferred_field_preview_and_history(window, application, tmp_path):
    ids = add_clips(window, tmp_path)
    window.panel("Editing")
    window.command.setText("hh")
    assert symbol_text('◇', 12) + '&nbsp;agent' in window.field_reminder.text()
    assert COLORS["accent_default"] in window.field_reminder.text()
    assert window.catalogue.clip(ids[0])["metadata"] == {}
    window.submit()
    application.processEvents()
    assert window.catalogue.clip(ids[0])["metadata"] == {
        "weapon": ["Headhunter"],
        "agent": "Chamber",
    }
    document = QTextDocument()
    document.setHtml(window.command_history.text())
    assert document.toPlainText() == "hh (Inferred: Agent = Chamber)"
    assert "font-size:11px" in window.command_history.text()
    assert "✓</span>&nbsp;agent" in window.field_reminder.text()

    window.command.setText("jett tdf")
    window.submit()
    document.setHtml(window.command_history.text())
    assert "jett tdf (Inferred:" not in document.toPlainText()


def test_bracket_tag_rating_preview_and_third_party_title(window, application, tmp_path):
    ids = add_clips(window, tmp_path)
    window.catalogue.patch(ids[0], {"tag": "3RD", "mainline": "Player clutch"})
    window.panel("Editing")
    window.render_clip()
    assert "!&nbsp;agent" in window.field_reminder.text()
    assert "!&nbsp;weapon" in window.field_reminder.text()
    assert "<u>player</u> clutch" in window.working_title.text().lower()
    assert "<u>player</u> clutch" in window.library.item(0).data(CLIP_ROLE)["rich_title"].lower()
    assert "font-size:15px" in window.working_title.text()
    assert "font-size:13px" in window.library.item(0).data(CLIP_ROLE)["rich_title"]
    assert "font-style:italic" not in window.working_title.text()
    assert "font-style:italic" not in window.library.item(0).data(CLIP_ROLE)["rich_title"]
    window.command.setText("[3rd] R4")
    document = QTextDocument()
    document.setHtml(window.command_feedback.text())
    assert document.toPlainText() == "[3rd] Known tag"
    assert "font-weight:600" in window.command_feedback.text()
    window.command.setText("[fresh] R4")
    document.setHtml(window.command_feedback.text())
    assert document.toPlainText() == "[fresh] New tag"
    assert COLORS["accent_default"] in window.command_feedback.text()
    original_clips = window.catalogue.clips
    try:
        window.catalogue.clips = lambda: (_ for _ in ()).throw(AssertionError("full scan"))
        window.command.setText("[3RD] R4")
        document.setHtml(window.command_feedback.text())
        assert document.toPlainText() == "[3RD] Known tag"
    finally:
        window.catalogue.clips = original_clips
    assert window.rating.command_preview == 4
    assert not window.rating_clear.isEnabled()
    assert window.rating_clear.toolTip() == "Rating pending · press Enter"
    window.command.setText("[3rd] R9")
    assert window.rating.command_preview is None
    assert window.rating_clear.isEnabled()
    window.command.setText("[3rd] R4")
    window.panel("Session")
    assert window.rating.command_preview is None
    window.panel("Editing")
    assert window.rating.command_preview == 4
    window.submit()
    assert window.catalogue.clip(ids[0])["rating"] == 4
    assert window.rating.command_preview is None
    window.panel("Home")
    tagged = next(
        window.library.item(index)
        for index in range(window.library.count())
        if window.library.item(index).data(Qt.ItemDataRole.UserRole) == ids[0]
    )
    assert "font-size:13px" in tagged.data(CLIP_ROLE)["rich_title"]


def test_clip_card_title_sizes_are_shared_with_export(window, tmp_path):
    clip_id = add_clips(window, tmp_path)[0]
    window.catalogue.patch(clip_id, {"mainline": "Player clutch"})
    project = window.catalogue.save_project("Typography check")
    window.catalogue.patch(clip_id, {}, membership=(project, True))
    window.refresh_references()
    window.export_project.setCurrentIndex(window.export_project.findData(project))

    for panel, compact, metadata_size, mainline_size, weight in (
        ("Home", True, 13, 14, 600),
        ("Session", True, 13, 14, 600),
        ("Editing", True, 13, 14, 600),
        ("Browse", False, 13, 14, 700),
        ("Export", True, 13, 14, 600),
    ):
        window.panel(panel)
        card = next(
            window.library.item(index).data(CLIP_ROLE)
            for index in range(window.library.count())
            if window.library.item(index).data(Qt.ItemDataRole.UserRole) == clip_id
        )
        assert card["compact_card"] is compact
        assert f"font-size:{metadata_size}px; font-weight:400" in card["rich_title"]
        assert f"font-size:{mainline_size}px; font-weight:{weight}" in card["rich_title"]


def test_reject_then_enter_is_one_shot(window, application, tmp_path):
    ids = add_clips(window, tmp_path)
    second = tmp_path / "captures" / "second.mp4"
    second.write_bytes(b"test")
    window.catalogue.ingest(
        window.catalogue.folders()[0]["folder_id"], [{"path": str(second), "game": "VALORANT"}]
    )
    next_id = next(
        clip["clip_id"] for clip in window.catalogue.clips() if clip["clip_id"] != ids[0]
    )
    window.catalogue.create_session([ids[0], next_id], replace=True)
    window.panel("Editing")
    QTest.keyClick(window.player, Qt.Key.Key_Backspace)
    assert window.reject_enter_armed
    QTest.keyClick(window.player, Qt.Key.Key_Return)
    assert window.current_id == next_id
    assert not window.reject_enter_armed
    QTest.keyClick(window.player, Qt.Key.Key_Backspace)
    QTest.keyClick(window.player, Qt.Key.Key_Left)
    assert not window.reject_enter_armed
    QTest.keyClick(window.player, Qt.Key.Key_Return)
    assert application.focusWidget() is window.command


def test_editing_undo_restores_commands_and_preserves_existing_drafts(window, tmp_path):
    ids = add_clips(window, tmp_path)
    window.panel("Editing")
    window.command.setText("jett")
    window.submit()
    window.undo()
    assert window.catalogue.clip(ids[0])["metadata"] == {}
    assert window.history[ids[0]] == []
    assert window.command.text() == "jett"
    window.undo(True)
    assert window.catalogue.clip(ids[0])["metadata"] == {"agent": "Jett"}
    assert window.history[ids[0]] == ["jett"]
    assert window.command.text() == ""
    window.command.setText("vandal")
    window.undo()
    assert window.command.text() == "vandal"
    window.undo(True)
    assert window.command.text() == "vandal"
    window.edit({"rating": 4})
    window.undo()
    assert window.catalogue.clip(ids[0])["rating"] is None
    window.undo(True)
    assert window.catalogue.clip(ids[0])["rating"] == 4


def test_editing_undo_is_per_clip_and_disabled_on_other_pages(window, tmp_path):
    ids = add_clips(window, tmp_path)
    second = tmp_path / "captures/second.mp4"
    second.write_bytes(b"test")
    window.catalogue.ingest(window.catalogue.folders()[0]["folder_id"],
                            [{"path": str(second), "game": "VALORANT"}])
    second_id = next(clip["clip_id"] for clip in window.catalogue.clips()
                     if clip["clip_id"] != ids[0])
    window.catalogue.create_session([ids[0], second_id], replace=True)
    window.panel("Editing")
    window.edit({"rating": 4})
    window.switch_editing_clip(second_id)
    assert not window.undo_button.isEnabled()
    window.edit({"rating": 2})
    window.undo()
    assert window.catalogue.clip(second_id)["rating"] is None
    assert window.catalogue.clip(ids[0])["rating"] == 4
    window.switch_editing_clip(ids[0])
    window.undo()
    assert window.catalogue.clip(ids[0])["rating"] is None
    project = window.catalogue.save_project("Clip history")
    window.catalogue.set_state("review_destination", project)
    window.add_to_project_next()
    assert window.current_id == second_id
    assert window.catalogue.member_ids(project) == {ids[0]}
    window.switch_editing_clip(ids[0])
    session = window.catalogue.state("session")
    window.undo()
    assert window.catalogue.member_ids(project) == set()
    assert window.catalogue.state("session") == session
    window.panel("Home")
    assert not window.undo_button.isEnabled() and not window.redo_button.isEnabled()


@pytest.mark.parametrize("staged", [False, True])
def test_editing_undo_covers_each_range_press(window, tmp_path, monkeypatch, staged):
    ids = add_clips(window, tmp_path)
    if staged:
        window.start_atomic_edit(ids[0], "Home")
    else:
        window.panel("Editing")
    position = [100]
    monkeypatch.setattr(window.player.media, "position", lambda: position[0])
    window.mark_in()
    assert window.pending_in == 100
    window.undo()
    assert window.pending_in is None
    window.undo(True)
    assert window.pending_in == 100
    position[0] = 500
    window.mark_out()
    assert window.effective_clip()["in_ms"] == 100
    assert window.effective_clip()["out_ms"] == 500
    window.undo()
    assert window.effective_clip()["in_ms"] is None
    assert window.pending_in == 100
    assert window.pending_out is None
    window.undo(True)
    assert window.effective_clip()["out_ms"] == 500
    assert window.pending_in is None
    if staged:
        assert window.catalogue.clip(ids[0])["in_ms"] is None
        window.discard_atomic_edit()


def test_staged_undo_keeps_changes_in_draft_and_covers_membership(window, tmp_path):
    clip_id = add_clips(window, tmp_path)[0]
    project = window.catalogue.save_project("Undo project")
    window.refresh_references()
    window.start_atomic_edit(clip_id, "Home")
    window.membership(True, project)
    window.undo()
    assert project not in window.effective_memberships()
    window.undo(True)
    assert project in window.effective_memberships()
    window.command.setText("jett")
    window.submit()
    window.undo()
    assert window.effective_clip()["metadata"] == {}
    assert window.command.text() == "jett"
    assert window.atomic_edit.history == []
    window.undo(True)
    assert window.command.text() == ""
    assert window.effective_clip()["metadata"] == {"agent": "Jett"}
    assert window.catalogue.clip(clip_id)["metadata"] == {}
    assert window.catalogue.member_ids(project) == set()
    window.edit({"triage": "keep"})
    window.undo()
    assert window.effective_clip()["triage"] is None
    window.discard_atomic_edit()


def test_command_validation_colors_and_save_feedback(window, application, tmp_path):
    ids = add_clips(window, tmp_path)
    window.panel("Editing")
    window.command.setFocus()
    artifact = ROOT / "cache/verification/command-validation"
    artifact.mkdir(parents=True, exist_ok=True)
    for text, state in [
        ("", "empty"),
        ("je", "typing"),
        ("jett", "valid"),
        ("jett va", "typing"),
        ("jett tag:", "incomplete"),
        ("jett nonsense ", "invalid"),
        ("R6", "invalid"),
    ]:
        window.command.setText(text)
        window.update_command_state()
        assert window.command.property("validationState") == state
        application.processEvents()
        window.command_area.grab().save(str(artifact / f"{state}.png"))
    window.command.setText("je")
    window.submit()
    assert window.command.property("validationState") == "invalid"
    assert "Unknown metadata" in window.command_feedback.text()
    window.command.setText("jett")
    assert window.command_error.isHidden()
    assert window.command.property("validationState") == "valid"
    window.submit()
    assert window.command.property("validationState") == "saved"
    assert window.command_feedback.text() == "Saved"
    window.command_area.grab().save(str(artifact / "saved.png"))
    assert window.catalogue.clip(ids[0])["metadata"]["agent"] == "Jett"
    assert wait_for(application, lambda: window.command.property("validationState") == "empty", 3)
    assert window.command_feedback.text() == ""


def test_session_pending_reminder_after_final_verdict(window, application, tmp_path, monkeypatch):
    monkeypatch.setattr(window, "auto_scan", lambda: None)
    captures = tmp_path / "pending-reminder"
    captures.mkdir()
    folder = window.catalogue.add_folder(captures)
    paths = [captures / f"clip-{index}.mp4" for index in range(3)]
    for path in paths:
        path.write_bytes(b"video")
    window.catalogue.ingest(folder, [{"path": str(path), "game": "VALORANT"} for path in paths])
    ids = [clip["clip_id"] for clip in window.catalogue.clips()]
    window.catalogue.create_session(ids)
    window.refresh_references()
    window.panel("Editing")
    button = window.next_undefined_button
    window.switch_editing_clip(ids[-1])
    assert window.session_counts.text() == "0/3 (0 rejected)"
    assert not button.pulsing

    # An unavailable pending source still needs a verdict.
    paths[0].unlink()
    window.edit({"triage": "discard"})
    application.processEvents()
    assert button.pulsing
    assert button.pulse_animation.state() == button.pulse_animation.State.Running
    assert window.session_counts.text() == (
        f'1/3 (1 rejected) · <span style="color: {COLORS["status_danger"]}">'
        '2 still pending</span>'
    )
    button.pulse_animation.setCurrentTime(0)
    bright = button.grab().toImage()
    button.pulse_animation.setCurrentTime(1500)
    faint = button.grab().toImage()
    assert bright != faint
    assert button.outline_opacity == pytest.approx(0.25)

    for mode in ("dark", "light"):
        window.set_theme(mode, persist=False)
        assert f'color: {COLORS["status_danger"]}' in window.session_counts.text()
        assert button.pulsing
        assert wait_for(application, lambda: not window.transition_pending)
        artifact = ROOT / "cache/verification/pending-reminder"
        artifact.mkdir(parents=True, exist_ok=True)
        button.pulse_animation.setCurrentTime(0)
        window.left.grab().save(str(artifact / f"{mode}.png"))

    window.undo()
    assert not button.pulsing
    assert window.session_counts.text() == "0/3 (0 rejected)"
    window.undo(True)
    assert button.pulsing
    window.switch_editing_clip(ids[0])
    assert button.pulsing
    window.edit({"triage": "keep"})
    assert "1 still pending" in window.session_counts.text()
    window.switch_editing_clip(ids[1])
    window.edit({"triage": "discard"})
    assert window.session_counts.text() == "3/3 (2 rejected)"
    assert not button.pulsing
    window.undo()
    assert button.pulsing
    window.panel("Session")
    assert button.pulse_animation.state() == button.pulse_animation.State.Stopped
    window.panel("Editing")
    assert button.pulse_animation.state() == button.pulse_animation.State.Running
    window.catalogue.set_state("session", None)
    window.refresh_session_status()
    assert not button.pulsing
    assert window.session_counts.text() == ""


def test_editing_session_counts_and_list_height(window, application, tmp_path):
    ids = add_clips(window, tmp_path)
    folder = window.catalogue.folders()[0]
    window.catalogue.ingest(
        folder["folder_id"],
        [{"path": str(tmp_path / "captures" / "outside-session.mp4"), "game": None}],
    )
    window.panel("Editing")
    application.processEvents()
    assert window.session_position.text() == "1 / 1"
    assert window.session_counts.text() == "0/1 (0 rejected)"
    item = window.library.item(0)
    window.edit({"triage": "keep"})
    assert window.session_counts.text() == "1/1 (0 rejected)"
    window.edit({"triage": "discard"})
    assert window.session_counts.text() == "1/1 (1 rejected)"
    assert window.library.item(0) is item
    window.undo()
    assert "1/1 (0 rejected)" in window.session_counts.text()
    window.undo()
    assert "0/1 (0 rejected)" in window.session_counts.text()
    assert window.catalogue.state("session")["ids"] == ids
    assert window.description.isHidden()
    assert window.command_history.isHidden()
    assert window.command_error.isHidden()
    command_y = window.command.mapTo(window.center_column, QPoint(0, 0)).y()
    area_y = window.command_area.y()
    window.command.setText("-- Example title -- Notes <keep literal>")
    window.submit()
    application.processEvents()
    assert not window.command_history.isHidden()
    assert abs(window.command.mapTo(window.center_column, QPoint(0, 0)).y() - command_y) <= 1
    assert window.command_area.y() < area_y
    assert window.command_area.height() - window.field_reminder.geometry().bottom() <= 5
    assert window.description.text() == "Notes <keep literal>"
    assert not window.description.isHidden()
    assert window.catalogue.clip(ids[0])["description"] == "Notes <keep literal>"
    window.edit({"description": None})
    assert window.description.isHidden()
    assert window.add_project_next.parentWidget() is window.player.control_bar
    application.processEvents()
    assert window.library_error.isHidden()
    assert window.left.objectName() == "clipLibraryPane"
    assert window.splitter.objectName() == "workspaceSplitter"
    assert window.splitter.handleWidth() == 5
    assert window.next_undefined_button.property("sessionAction") is True
    assert (
        window.session_header.mapTo(window.left, QPoint(0, window.session_header.height())).y()
        <= window.library.mapTo(window.left, QPoint()).y()
    )
    assert window.left.height() == window.center_column.height()
    assert (
        window.session_counts.mapTo(window.left, QPoint(0, window.session_counts.height())).y()
        >= window.left.height() - 8
    )
    assert window.left.mapTo(window, QPoint(0, 0)).x() == 13
    heading = window.session_header.findChild(QLabel)
    heading_x = heading.mapTo(window.left, QPoint(0, 0)).x()
    footer_x = window.session_counts.mapTo(window.left, QPoint(0, 0)).x() + 8
    assert heading_x == 12
    assert footer_x == 8
    artifact = ROOT / "cache/verification/session-counts"
    artifact.mkdir(parents=True, exist_ok=True)
    assert wait_for(application, lambda: not window.transition_pending)
    window.grab().save(str(artifact / "editing.png"))
    window.set_theme("dark")
    application.processEvents()
    window.grab().save(str(artifact / "editing-dark.png"))
    window.panel("Export")
    assert window.session_counts.isHidden()
    window.panel("Session")
    application.processEvents()
    toolbar_x = window.library_toolbar.mapTo(window, QPoint(0, 0)).x() + 8
    assert window.search.mapTo(window, QPoint(0, 0)).x() == toolbar_x
    assert window.clip_filter.mapTo(window, QPoint(0, 0)).x() == toolbar_x
    window.panel("Browse")
    application.processEvents()
    toolbar_x = window.library_toolbar.mapTo(window, QPoint(0, 0)).x() + 8
    assert window.browse_search.mapTo(window, QPoint(0, 0)).x() == toolbar_x
    assert window.clip_filter.mapTo(window, QPoint(0, 0)).x() == toolbar_x
    assert wait_for(application, lambda: not window.transition_pending)
    window.grab().save(str(artifact / "browse-dark.png"))


def test_review_advance_skips_verdicts_without_wrapping(window, application, tmp_path):
    add_clips(window, tmp_path)
    folder = window.catalogue.folders()[0]
    window.catalogue.ingest(
        folder["folder_id"],
        [
            {"path": str(tmp_path / "captures" / f"extra-{index}.mp4"), "game": None}
            for index in range(4)
        ],
    )
    ids = [clip["clip_id"] for clip in window.catalogue.clips()]
    window.catalogue.create_session(ids, replace=True)
    for index, triage in [(0, "discard"), (1, "keep"), (2, "discard"), (4, "keep")]:
        window.catalogue.patch(ids[index], {"triage": triage})
    window.panel("Editing")
    QTest.keyClick(window.player, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert window.current_id == ids[3]
    assert window.catalogue.state("session")["index"] == 3
    assert window.catalogue.clip(ids[0])["triage"] == "discard"
    window.catalogue.patch(ids[1], {"triage": None})
    window.edit({"triage": "discard"})
    window.advance_review()
    assert window.current_id == ids[3]
    assert "earlier" in window.statusBar().currentMessage()
    window.catalogue.patch(ids[1], {"triage": "keep"})
    window.advance_review()
    assert window.current_id == ids[3]
    assert "Session complete" in window.statusBar().currentMessage()
    assert window.catalogue.state("session")["ids"] == ids


def test_startup_rescans_enabled_folders(application, tmp_path):
    from dfsorter.catalogue import Catalogue

    shutil.copytree(ROOT / "configs/shipped", tmp_path / "configs/games")
    shutil.copytree(ROOT / "configs/tips", tmp_path / "configs/tips")
    catalogue = Catalogue(tmp_path / "data/dfsorter.db")
    enabled = tmp_path / "VALORANT"
    disabled = tmp_path / "disabled"
    enabled.mkdir()
    disabled.mkdir()
    enabled_id = catalogue.add_folder(enabled)
    disabled_id = catalogue.add_folder(disabled)
    catalogue.enable_folder(disabled_id, False)
    original = enabled / "original.mp4"
    original.write_bytes(b"test")
    catalogue.ingest(enabled_id, [{"path": str(original), "game": "VALORANT"}])
    clip_id = catalogue.clips()[0]["clip_id"]
    catalogue.create_session([clip_id])
    catalogue.patch(clip_id, {"triage": "discard", "mainline": "Preserved"})
    original.unlink()
    (enabled / "new.mp4").write_bytes(b"test")
    (disabled / "ignored.mp4").write_bytes(b"test")
    result = Window(tmp_path)
    result.show()
    try:
        assert wait_for(
            application, lambda: result.worker is None and len(result.catalogue.clips()) == 2
        )
        assert result.catalogue.clip(clip_id)["mainline"] == "Preserved"
        assert result.catalogue.clip(clip_id)["triage"] == "discard"
        assert result.catalogue.state("session")["ids"] == [clip_id]
        assert all(
            Path(clip["source_path"]).name != "ignored.mp4" for clip in result.catalogue.clips()
        )
    finally:
        result.close()
        application.processEvents()


@pytest.mark.parametrize("panel", ["Home", "Browse", "Session", "Editing", "Export"])
def test_hdr_clip_card_label(window, tmp_path, panel):
    ids = add_clips(window, tmp_path)
    clip = window.catalogue.clip(ids[0])
    window.media_info[clip["source_path"]] = {"hdr": 1}
    window.panel(panel)
    item = next(
        (window.library.item(index) for index in range(window.library.count())
         if window.library.item(index).data(Qt.ItemDataRole.UserRole) == ids[0]),
        None,
    )
    if item is None:
        pytest.skip("Panel does not list this clip")
    assert item.data(CLIP_ROLE)["hdr"] is True
    assert "captures HDR" in item.toolTip()


def test_cards_and_verdict_state(window, application, tmp_path):
    ids = add_clips(window, tmp_path)
    window.panel("Editing")
    window.edit({"mainline": "discard keep 中文 title", "triage": None})
    window.refresh_library()
    item = window.library.item(0)
    assert item.data(Qt.ItemDataRole.UserRole) == ids[0]
    assert item.data(CLIP_ROLE)["triage"] is None
    assert item.data(CLIP_ROLE)["rating"] is None
    assert "discard keep" in item.data(CLIP_ROLE)["title"]
    assert item.text().endswith("VALORANT · captures")
    assert "R–" not in item.text()
    assert "pending" not in item.text().splitlines()[1].lower()
    assert window.triage_buttons[None].isChecked()
    assert window.triage_buttons[None].text() == "Pending"
    assert window.triage_buttons[None].toolTip() == "Clear verdict and mark as pending"
    QTest.mouseClick(window.triage_buttons["keep"], Qt.MouseButton.LeftButton)
    assert window.catalogue.clip(ids[0])["triage"] == "keep"
    assert window.triage_buttons["keep"].isChecked()
    assert not window.triage_buttons[None].isChecked()
    window.edit({"triage": "discard"})
    assert window.triage_buttons["discard"].isChecked()
    window.undo()
    assert window.triage_buttons["keep"].isChecked()
    window.undo(True)
    assert window.triage_buttons["discard"].isChecked()
    window.edit({"rating": 2})
    application.processEvents()
    assert window.library.item(0).data(CLIP_ROLE)["rating"] == 2
    assert window.library.item(0).text().endswith("VALORANT · R2 · captures")
    assert "discard" not in window.library.item(0).text().splitlines()[1].lower()
    position = QPointF(window.rating.step * 3 + 4, 10)
    application.sendEvent(
        window.rating,
        QMouseEvent(
            QEvent.Type.MouseMove,
            position,
            position,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    assert window.rating.preview == 4
    assert window.catalogue.clip(ids[0])["rating"] == 2
    QTest.mouseClick(
        window.rating, Qt.MouseButton.LeftButton, pos=QPoint(window.rating.step * 3 + 4, 10)
    )
    assert window.catalogue.clip(ids[0])["rating"] == 4
    QTest.mouseClick(window.rating, Qt.MouseButton.RightButton)
    assert window.catalogue.clip(ids[0])["rating"] is None
    assert window.catalogue.clip(ids[0])["triage"] == "discard"


def test_clip_card_rating_scope(window, tmp_path):
    clip_id = add_clips(window, tmp_path)[0]
    window.catalogue.patch(clip_id, {"rating": 4, "triage": "keep"})
    clip = window.catalogue.clip(clip_id)
    window.clip_folder_names = window.catalogue.clip_folder_names()
    item = QListWidgetItem()

    for panel in ("Home", "Session", "Editing", "Export"):
        window.current_panel = panel
        window.render_card(item, clip)
        assert item.text().endswith("VALORANT · R4 · captures")
        assert "keep" not in item.text().lower()

    window.current_panel = "Browse"
    window.render_card(item, clip)
    assert "R4" not in item.text()
    assert item.data(CLIP_ROLE)["browse_details"] is not None


@pytest.mark.parametrize("codec", ["libx264", "libaom-av1"])
def test_real_playback(window, application, tmp_path, codec):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg required for playback fixtures")
    ids = add_clips(window, tmp_path, valid=True, codec=codec)
    window.preload_timer.stop()
    window.schedule_preload = lambda: None
    window.panel("Editing")
    player = window.player
    assert wait_for(application, lambda: player.media.duration() > 0 and not player.awaiting_frame)
    assert not player.media.frame_image().isNull()
    assert player.media.playbackState() == QMediaPlayer.PlaybackState.PausedState
    window.catalogue.patch(ids[0], {"in_ms": 500, "out_ms": 1500})
    clip = window.catalogue.clip(ids[0])
    for preview_player in [window.player, window.export_player]:
        preview_player.load(clip)
        assert wait_for(application, lambda: not preview_player.awaiting_frame)
        assert preview_player.media.position() == 500
        assert preview_player.seek.value() == 500
        assert preview_player.media.playbackState() == QMediaPlayer.PlaybackState.PausedState
        for start, end in [(None, None), (500, None), (1500, 500), (500, 999999)]:
            preview_player.load({**clip, "in_ms": start, "out_ms": end})
            assert wait_for(application, lambda: not preview_player.awaiting_frame)
            assert preview_player.media.position() == 0
        # A smaller offset exercises seeking from the end with the short real fixture.
        settings = SettingsDialog(window)
        settings.start_offset.setValue(1)
        for start, end in [(None, None), (500, None), (1500, 500), (500, 999999)]:
            preview_player.load({**clip, "in_ms": start, "out_ms": end})
            assert wait_for(application, lambda: not preview_player.awaiting_frame)
            assert preview_player.media.position() == preview_player.media.duration() - 1000
            assert preview_player.media.playbackState() == QMediaPlayer.PlaybackState.PausedState
        preview_player.load(clip)
        assert wait_for(application, lambda: not preview_player.awaiting_frame)
        assert preview_player.media.position() == 500
        settings.start_near_end.setChecked(False)
        preview_player.load({**clip, "in_ms": None, "out_ms": None})
        assert wait_for(application, lambda: not preview_player.awaiting_frame)
        assert preview_player.media.position() == 0
        # Natural completion must not leave either player unable to seek/resume.
        for drag in (False, True):
            preview_player.media.setPosition(preview_player.media.duration() - 200)
            preview_player.media.play()
            assert wait_for(application, lambda: preview_player.ended)
            if drag:
                preview_player.begin_scrub()
                preview_player.queue_seek(700)
                preview_player.preview_seek()
                assert (
                    preview_player.media.playbackState() == QMediaPlayer.PlaybackState.PausedState
                )
                preview_player.seek.setSliderPosition(700)
                preview_player.end_scrub()
            else:
                preview_player.seek_to(700)
            assert wait_for(
                application,
                lambda: (
                    preview_player.media.playbackState() == QMediaPlayer.PlaybackState.PlayingState
                    and 700 < preview_player.media.position() < 2000
                    and not preview_player.media.frame_image().isNull()
                ),
            )
            preview_player.media.pause()
        preview_player.seek_to(500)
        assert preview_player.media.playbackState() == QMediaPlayer.PlaybackState.PausedState
        settings.start_offset.setValue(40)
        settings.start_near_end.setChecked(True)
        settings.close()
    window.export_player.load(None)
    window.command.setFocus()
    window.command.setText("jett")
    QTest.keyClick(window.command, Qt.Key.Key_Space)
    assert window.command.text() == "jett "
    assert player.media.playbackRate() == 1
    window.command.clear()
    QTest.keyClick(window.command, Qt.Key.Key_Space)
    assert window.command.text() == " "
    QTest.keyClick(window.command, Qt.Key.Key_Escape)
    QTest.keyPress(window.player, Qt.Key.Key_Space)
    QTest.qWait(250)
    assert player.media.playbackRate() == 3
    QTest.keyRelease(window.player, Qt.Key.Key_Space)
    assert player.media.playbackRate() == 1
    assert player.media.hasAudio()
    player.media.setPosition(500)
    assert wait_for(application, lambda: player.media.position() >= 450)
    window.mark_in()
    player.media.setPosition(1500)
    assert wait_for(application, lambda: player.media.position() >= 1450)
    window.mark_out()
    assert window.catalogue.clip(ids[0])["out_ms"] > window.catalogue.clip(ids[0])["in_ms"]
    player.fast(True)
    assert player.media.playbackRate() == 3
    player.fast(False)
    assert player.media.playbackRate() == 1
    assert player.media.playbackState() == QMediaPlayer.PlaybackState.PausedState
    player.mute.setChecked(True)
    assert player.audio.isMuted()
    player.media.setPosition(1000)
    QTest.qWait(300)
    artifact = ROOT / "cache/verification"
    artifact.mkdir(parents=True, exist_ok=True)
    window.grab().save(str(artifact / f"editing-{codec}.png"))
    window.screen().grabWindow(int(window.winId())).save(str(artifact / f"screen-{codec}.png"))
    player.media.frame_image().save(str(artifact / f"decoded-video-{codec}.png"))
    left_width, _, right_width = window.splitter.sizes()
    window.showMaximized()
    QTest.qWait(300)
    assert abs(window.splitter.sizes()[0] - left_width) < 10
    assert right_width == 0
    assert window.splitter.count() == 2
    window.grab().save(str(artifact / f"maximized-{codec}.png"))


@pytest.mark.parametrize("review", [True, False], ids=["review", "command"])
@pytest.mark.parametrize(
    "draft,cursor,expanded,restored",
    [
        ("", 0, "-- ", ""),
        ("title", 0, "-- title", "title"),
        ("jett   ", 7, "jett -- ", "jett "),
    ],
)
def test_equal_expands_when_entering_command_input(
    window, application, tmp_path, monkeypatch, review, draft, cursor, expanded, restored
):
    add_clips(window, tmp_path)
    window.panel("Editing")
    monkeypatch.setattr(window, "editing_paused", lambda: True)
    window.command.setText(draft)
    window.command.setCursorPosition(cursor)
    if review:
        window.review_mode()
        target = window.player
    else:
        window.command.setFocus()
        target = window.command
    QTest.keyClick(target, Qt.Key.Key_Equal)
    assert application.focusWidget() is window.command
    assert window.command.text() == expanded
    assert window.command.cursorPosition() == (3 if cursor == 0 else len(expanded))
    QTest.keyClick(window.command, Qt.Key.Key_Space)
    assert window.command.text() == expanded
    QTest.keyClick(window.command, Qt.Key.Key_Backspace)
    assert window.command.text() == restored


def test_paused_typing_and_submit_resume(window, application, tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg required for playback fixtures")
    ids = add_clips(window, tmp_path, valid=True)
    window.panel("Editing")
    assert wait_for(application, window.editing_paused)
    window.review_mode()
    assert window.command.property("commandState") == "paused"
    artifact = ROOT / "cache/verification/command-states"
    artifact.mkdir(parents=True, exist_ok=True)
    window.grab().save(str(artifact / "paused.png"))
    QTest.keyClick(window.player, Qt.Key.Key_I)
    assert application.focusWidget() is window.player
    QTest.keyClick(window.player, Qt.Key.Key_R)
    assert application.focusWidget() is window.command
    QTest.keyClick(window.command, Qt.Key.Key_4)
    assert window.command.text() == "r4"
    assert window.catalogue.clip(ids[0])["rating"] is None
    QTest.keyClick(window.command, Qt.Key.Key_Return)
    assert window.catalogue.clip(ids[0])["rating"] == 4
    QTest.keyClick(window.command, Qt.Key.Key_Escape)
    QTest.keyClick(window.player, Qt.Key.Key_B)
    assert window.command.text() == "b"
    assert window.command.property("commandState") == "input"
    window.grab().save(str(artifact / "input.png"))
    QTest.keyClicks(window.command, "rim tag:LOW_FPS")
    QTest.keyClick(window.command, Qt.Key.Key_Return)
    assert application.focusWidget() is window.command
    assert window.command.property("commandState") == "resume"
    window.grab().save(str(artifact / "resume.png"))
    assert window.library.item(0).data(CLIP_ROLE)["title"].startswith("[LOW_FPS] VAL_")
    assert window.catalogue.clip(ids[0])["metadata"]["agent"] == "Brimstone"
    QTest.keyPress(window.command, Qt.Key.Key_Space)
    QTest.qWait(250)
    QTest.keyRelease(window.player, Qt.Key.Key_Space)
    assert window.command.text() == ""
    assert application.focusWidget() is window.player
    assert window.player.media.playbackRate() == 1
    assert window.player.media.playbackState() == QMediaPlayer.PlaybackState.PlayingState
    window.player.media.pause()
    QTest.keyClick(window.player, Qt.Key.Key_J)
    QTest.keyClicks(window.command, "ett")
    QTest.keyClick(window.command, Qt.Key.Key_Return)
    QTest.keyClick(window.command, Qt.Key.Key_V)
    QTest.keyClick(window.command, Qt.Key.Key_Space)
    assert window.command.text() == "v "
    assert window.command.property("commandState") == "input"
    assert window.editing_paused()
    window.command.setText("invalid command")
    QTest.keyClick(window.command, Qt.Key.Key_Return)
    assert not window.submit_resume
    assert window.command.text() == "invalid command"
    QTest.keyClick(window.command, Qt.Key.Key_Escape)
    window.settings["paused_typing_enabled"] = False
    window.update_command_state()
    assert window.command.property("commandState") == "review"
    QTest.keyClick(window.player, Qt.Key.Key_B)
    assert application.focusWidget() is window.player
    window.settings["paused_typing_enabled"] = True
    window.command.setCursorPosition(0)
    QTest.keyClick(window.player, Qt.Key.Key_B)
    assert window.command.text() == "binvalid command"
    for cancel in ("mouse", "focus", "playback", "paste"):
        window.command.setText("R3")
        window.command.setFocus()
        QTest.keyClick(window.command, Qt.Key.Key_Return)
        assert window.submit_resume
        if cancel == "mouse":
            QTest.mouseClick(window.command, Qt.MouseButton.LeftButton)
        elif cancel == "focus":
            window.player.setFocus()
            window.command.setFocus()
        elif cancel == "playback":
            window.player.media.play()
            window.player.media.pause()
        else:
            # Exercise the same insertion path as paste without changing the system clipboard.
            window.command.insert("jett")
        assert not window.submit_resume
        QTest.keyClick(window.command, Qt.Key.Key_Space)
        assert window.command.text().endswith(" ")
        assert window.editing_paused()


def test_session_arrow_navigation_and_tag_display(window, application, tmp_path):
    ids = add_clips(window, tmp_path)
    folder = window.catalogue.folders()[0]["folder_id"]
    for name in ("kept", "rejected"):
        path = tmp_path / "captures" / f"{name}.mp4"
        path.write_bytes(b"test")
        window.catalogue.ingest(folder, [{"path": str(path), "game": "VALORANT"}])
    ids += [clip["clip_id"] for clip in window.catalogue.clips() if clip["clip_id"] not in ids]
    window.catalogue.create_session(ids, replace=True)
    window.catalogue.patch(ids[1], {"triage": "keep"})
    window.catalogue.patch(ids[2], {"triage": "discard"})
    window.catalogue.patch(ids[0], {"tag": "<bad>"})
    window.panel("Editing")
    data = window.library.item(0).data(CLIP_ROLE)
    assert data["title"].startswith("[<bad>] VAL_")
    assert "[&lt;bad&gt;]" in data["rich_title"]
    assert "[&lt;bad&gt;]" in window.working_title.text()
    window.command.setFocus()
    window.command.setText("draft")
    QTest.keyClick(window.command, Qt.Key.Key_Down)
    assert window.current_id == ids[0]
    QTest.keyClick(window.command, Qt.Key.Key_Escape)
    for target in (ids[1], ids[2], ids[2]):
        QTest.keyClick(window.player, Qt.Key.Key_Down)
        assert window.current_id == target
    for target in (ids[1], ids[0], ids[0]):
        QTest.keyClick(window.player, Qt.Key.Key_Up)
        assert window.current_id == target
    assert window.command.text() == "draft"


def test_submitted_command_up_down_navigates_session_from_input(
    window, application, tmp_path
):
    ids = add_clips(window, tmp_path)
    folder_id = window.catalogue.folders()[0]["folder_id"]
    second = tmp_path / "captures" / "second.mp4"
    second.write_bytes(b"test")
    window.catalogue.ingest(folder_id, [{"path": str(second), "game": "VALORANT"}])
    ids = [clip["clip_id"] for clip in window.catalogue.clips()]
    window.catalogue.create_session(ids, replace=True)
    window.panel("Editing")
    window.command.setFocus()
    window.command.setText("R4")
    QTest.keyClick(window.command, Qt.Key.Key_Return)
    assert window.command.text() == ""
    assert application.focusWidget() is window.command

    QTest.keyClick(window.command, Qt.Key.Key_Down)
    assert window.current_id == ids[1]
    assert application.focusWidget() is window.player
    window.command.setFocus()
    window.command.setText("R3")
    QTest.keyClick(window.command, Qt.Key.Key_Return)
    QTest.keyClick(window.command, Qt.Key.Key_Up)
    assert window.current_id == ids[0]
    assert window.catalogue.clip(ids[0])["rating"] == 4
    assert window.catalogue.clip(ids[1])["rating"] == 3

    window.command.setFocus()
    window.command.setText("invalid command")
    QTest.keyClick(window.command, Qt.Key.Key_Return)
    QTest.keyClick(window.command, Qt.Key.Key_Down)
    assert window.current_id == ids[0]
    assert window.command.text() == "invalid command"


def test_review_drafts_rating_and_panes(window, application, tmp_path):
    ids = add_clips(window, tmp_path)
    window.panel("Editing")
    window.settings["paused_typing_enabled"] = False
    QTest.keyClick(window.player, Qt.Key.Key_R)
    QTest.keyClick(window.player, Qt.Key.Key_3)
    assert window.catalogue.clip(ids[0])["rating"] is None
    assert application.focusWidget() is window.player
    QTest.keyClick(window.player, Qt.Key.Key_Slash)
    assert application.focusWidget() is window.command
    assert window.command.text() == ""
    window.command.setText("unfinished")
    QTest.keyClick(window.command, Qt.Key.Key_Escape)
    window.panel("Session")
    window.panel("Editing")
    assert window.command.text() == "unfinished"
    assert application.focusWidget() is window.player
    assert window.splitter.count() == 2


def test_input_undo_and_title_presentation(window, application, tmp_path):
    ids = add_clips(window, tmp_path)
    window.panel("Editing")
    window.edit(
        {
            "mainline": "<great aim> " * 8,
            "metadata": {"agent": "Chamber", "weapon": ["Operator", "Headhunter"], "kill": 3},
            "tag": "LOW_FPS",
            "rating": 4,
        }
    )
    assert "&lt;great aim&gt;" in window.working_title.text()
    assert "[LOW_FPS]" in window.working_title.text()
    assert not hasattr(window, "tag")
    window.command.setFocus()
    QTest.keyClicks(window.command, "jett")
    QTest.keyClick(window.command, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert window.command.text() == ""
    QTest.keyClick(
        window.command,
        Qt.Key.Key_Z,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
    )
    assert window.command.text() == "jett"
    assert window.catalogue.clip(ids[0])["rating"] == 4
    window.refresh_library()
    application.processEvents()
    assert window.library.horizontalScrollBar().maximum() == 0
    artifact = ROOT / "cache/verification"
    artifact.mkdir(parents=True, exist_ok=True)
    window.grab().save(str(artifact / "editing-populated.png"))
    assert window.splitter.count() == 2
    window.showMaximized()
    application.processEvents()
    assert window.splitter.count() == 2
    window.showNormal()
    application.processEvents()
    assert window.splitter.count() == 2
    window.reset_layout()
    assert window.splitter.count() == 2


def test_editing_mouse_click_returns_to_review_without_losing_draft(
    window, application, tmp_path
):
    ids = add_clips(window, tmp_path)
    window.panel("Editing")
    window.settings["paused_typing_enabled"] = False
    window.command.setText("unfinished")

    for target in (window.triage_buttons["discard"], window.pages["Editing"][0]):
        window.command.setFocus()
        assert application.focusWidget() is window.command
        QTest.mouseClick(target, Qt.MouseButton.LeftButton)
        application.processEvents()
        assert application.focusWidget() is not window.command
        assert window.command.property("commandState") == "review"
        assert window.command.text() == "unfinished"
    assert window.catalogue.clip(ids[0])["triage"] == "discard"

    window.command.setFocus()
    QTest.mouseClick(window.command, Qt.MouseButton.LeftButton)
    assert application.focusWidget() is window.command


@pytest.mark.parametrize("field_name", ["custom_title", "destination"])
@pytest.mark.parametrize("target_name", ["filename", "details"])
def test_browse_outside_click_releases_text_focus_and_restores_hotkeys(
    window, application, monkeypatch, field_name, target_name
):
    window.panel("Browse")
    field = getattr(window.browse, field_name)
    target = getattr(window.browse, target_name)
    field.setText("draft")
    field.setFocus()
    application.processEvents()
    QTest.mouseClick(field, Qt.MouseButton.LeftButton)
    assert application.focusWidget() is field
    toggles = []
    monkeypatch.setattr(window.browse.player, "toggle", lambda: toggles.append(True))
    QTest.keyClick(field, Qt.Key.Key_Space)
    assert not toggles
    draft = field.text()

    QTest.mouseClick(target, Qt.MouseButton.LeftButton, pos=QPoint(1, 1))
    assert application.focusWidget() is not field
    assert field.text() == draft
    QTest.keyClick(window, Qt.Key.Key_Space)
    assert toggles == [True]


@pytest.mark.parametrize(
    "field_type", [QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox]
)
def test_dialog_text_fields_release_focus_on_outside_click(window, application, field_type):
    dialog = QDialog(window)
    dialog.setModal(True)
    layout = QVBoxLayout(dialog)
    field = field_type()
    if isinstance(field, QComboBox):
        field.setEditable(True)
        field.setEditText("draft")
    elif isinstance(field, (QSpinBox, QDoubleSpinBox)):
        field.setValue(42)
    else:
        if isinstance(field, (QPlainTextEdit, QTextEdit)):
            field.setPlainText("draft")
        else:
            field.setText("draft")
    layout.addWidget(field)
    label = QLabel("Outside the text field")
    layout.addWidget(label)
    button = QPushButton("Action")
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    layout.addWidget(button)
    clicks = []
    button.clicked.connect(lambda: clicks.append(True))
    dialog.show()
    dialog.activateWindow()
    application.processEvents()
    try:
        for target in (label, button):
            field.setFocus()
            application.processEvents()
            focused = application.focusWidget()
            assert focused is field or field.isAncestorOf(focused)
            editor = field.lineEdit() if isinstance(field, QComboBox) else focused
            text = editor.toPlainText() if hasattr(editor, "toPlainText") else editor.text()
            inside = field.viewport() if hasattr(field, "viewport") else editor
            QTest.mouseClick(inside, Qt.MouseButton.LeftButton)
            assert application.focusWidget() is focused
            QTest.mouseClick(target, Qt.MouseButton.LeftButton)
            assert application.focusWidget() is not focused
            assert (editor.toPlainText() if hasattr(editor, "toPlainText") else editor.text()) == text
        assert clicks == [True]
    finally:
        dialog.close()
        dialog.deleteLater()
        application.processEvents()


def test_inline_table_editor_commits_on_outside_label_click(window, application):
    dialog = QDialog(window)
    layout = QVBoxLayout(dialog)
    table = QTableWidget(1, 1)
    table.setItem(0, 0, QTableWidgetItem("original"))
    layout.addWidget(table)
    label = QLabel("Outside the table")
    layout.addWidget(label)
    dialog.show()
    dialog.activateWindow()
    application.processEvents()
    try:
        table.editItem(table.item(0, 0))
        application.processEvents()
        editor = application.focusWidget()
        assert isinstance(editor, QLineEdit)
        editor.setText("changed")
        QTest.mouseClick(label, Qt.MouseButton.LeftButton)
        application.processEvents()
        assert application.focusWidget() is not editor
        assert table.item(0, 0).text() == "changed"
    finally:
        dialog.close()
        dialog.deleteLater()
        application.processEvents()


def test_filename_fallback_deduplicates_game_prefix(window, application, tmp_path):
    captures = tmp_path / "captures"
    captures.mkdir()
    source = captures / "Counter-strike 2 2026.09.22.DVR.mp4"
    source.write_bytes(b"test")
    folder = window.catalogue.add_folder(captures)
    window.catalogue.ingest(folder, [{"path": str(source), "game": "Counter-strike 2"}])
    window.refresh_references()
    window.catalogue.create_session([window.catalogue.clips()[0]["clip_id"]])
    window.panel("Editing")
    application.processEvents()

    document = QTextDocument()
    document.setHtml(window.working_title.text())
    assert "CS2_2026.09.22.DVR.mp4" in document.toPlainText()
    assert "Counter-strike 2 2026" not in document.toPlainText()
    assert window.filename.text() == source.name
    assert window.library.item(0).data(CLIP_ROLE)["title"] == "CS2_2026.09.22.DVR"


@pytest.mark.parametrize("first", ["in", "out"])
def test_range_markers_in_either_order(window, tmp_path, monkeypatch, first):
    ids = add_clips(window, tmp_path)
    window.panel("Editing")
    assert window.range_warning.isHidden()
    assert window.range_warning_icon.isHidden()
    position = [0]
    monkeypatch.setattr(window.player.media, "position", lambda: position[0])

    def mark(endpoint, milliseconds):
        position[0] = milliseconds
        (window.mark_in if endpoint == "in" else window.mark_out)()

    mark(first, 0 if first == "in" else 3000)
    assert window.has_pending_range()
    assert not window.range_warning.isHidden()
    assert window.range_warning.text() == "I/O not set"
    assert window.player.controls.itemAt(1).layout() is window.range_warning_slot
    assert window.range_warning.mapToGlobal(QPoint(0, 0)).x() < (
        window.player.controls.itemAt(2).widget().mapToGlobal(QPoint(0, 0)).x()
    )
    assert window.command_error.isHidden()
    assert not window.ensure_range_complete()
    assert "Clear range" in window.command_feedback.text()
    assert window.command.property("validationState") == "invalid"
    assert window.catalogue.clip(ids[0])["in_ms"] is None
    assert window.catalogue.clip(ids[0])["out_ms"] is None
    assert getattr(window.player.seek, f"pending_{first}") == position[0]
    mark("out" if first == "in" else "in", 3000 if first == "in" else 0)
    assert not window.has_pending_range()
    assert window.ensure_range_complete()
    assert "Clear range" not in window.command_feedback.text()
    assert window.catalogue.clip(ids[0])["in_ms"] == 0
    assert window.range_warning.isHidden()
    assert window.catalogue.clip(ids[0])["out_ms"] == 3000
    mark("in", 500)
    assert not window.has_pending_range()
    assert window.catalogue.clip(ids[0])["in_ms"] == 500
    mark("out", 4000)
    assert not window.has_pending_range()
    assert window.catalogue.clip(ids[0])["out_ms"] == 4000
    mark("in", 4500)
    assert window.has_pending_range()
    assert window.range_warning.text() == "I/O invalid"
    assert window.command_error.isHidden()
    assert window.catalogue.clip(ids[0])["in_ms"] == 500
    mark("out", 4500)
    assert window.has_pending_range()
    assert window.catalogue.clip(ids[0])["out_ms"] == 4000
    mark("out", 5000)
    assert not window.has_pending_range()
    assert window.catalogue.clip(ids[0])["in_ms"] == 4500
    window.clear_range()
    mark("out", 1000)
    window.clear_range()
    assert window.ensure_range_complete()
    assert window.range_warning.isHidden()
    assert window.range_warning_icon.isHidden()
    assert window.player.seek.pending_out is None
    assert window.catalogue.clip(ids[0])["out_ms"] is None


def test_pending_range_blocks_clip_and_session_changes(window, application, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QStyle

    ids = add_clips(window, tmp_path)
    folder = window.catalogue.folders()[0]["folder_id"]
    second = tmp_path / "captures/second.mp4"
    second.write_bytes(b"test")
    window.catalogue.ingest(folder, [{"path": str(second), "game": "VALORANT"}])
    next_id = next(
        clip["clip_id"] for clip in window.catalogue.clips() if clip["clip_id"] != ids[0]
    )
    window.catalogue.create_session([ids[0], next_id], replace=True)
    project = window.catalogue.save_project("No premature membership")
    window.catalogue.set_state("review_destination", project)
    window.catalogue.patch(ids[0], {"metadata": {"agent": "Jett", "weapon": ["Vandal"]}})
    window.panel("Editing")
    position = [1000]
    monkeypatch.setattr(window.player.media, "position", lambda: position[0])
    window.mark_out()
    original_session = window.catalogue.state("session")
    confirmations = []
    monkeypatch.setattr(window, "confirm", lambda message: confirmations.append(message) or True)
    for action in (
        lambda: window.navigate(1),
        lambda: window.library.setCurrentRow(1),
        window.navigate_next_undefined,
        window.advance_review,
        window.add_to_project_next,
        lambda: window.panel("Home"),
        window.end_session,
        lambda: window.create_session("all"),
        lambda: window.load_clip(next_id),
    ):
        action()
        assert window.current_id == ids[0]
        assert window.current_panel == "Editing"
        assert window.catalogue.state("session") == original_session
        assert window.selected_id(window.library) == ids[0]
    assert not confirmations
    assert window.catalogue.clip(ids[0])["triage"] is None
    assert not window.catalogue.member_ids(project)
    assert window.player.play.style().styleHint(QStyle.StyleHint.SH_ToolTip_WakeUpDelay) == 200
    position[0] = 0
    window.mark_in()
    window.navigate(1)
    assert window.current_id == next_id
    window.mark_in()
    window.clear_range()
    window.panel("Home")
    assert window.current_panel == "Home"


def test_scrub_coalesces_and_finishes_exactly(window, monkeypatch):
    player = window.player
    calls = []
    monkeypatch.setattr(player.media, "setPosition", calls.append)
    monkeypatch.setattr(player.media, "duration", lambda: 10000)
    player.seek.setMaximum(10000)
    player.begin_scrub()
    for position in range(1000, 1235):
        player.queue_seek(position)
    assert calls == []
    player.preview_seek()
    assert calls == [1200]
    player.seek.setSliderPosition(1234)
    player.end_scrub()
    assert calls == [1200, 1234]
    assert not player.seek_timer.isActive()


def test_page_reveal_waits_and_delays_indicator(window, application):
    application.processEvents()
    window.current_panel = "Editing"
    window.player.awaiting_frame = True
    window.begin_page_transition()
    generation = window.transition_generation
    window.queue_page_reveal()
    application.processEvents()
    assert window.transition_pending
    assert window.player.video.isHidden()
    assert window.loading_label.isHidden()
    QTest.qWait(1100)
    assert window.loading_label.isVisible()
    window.begin_page_transition()
    window.player.awaiting_frame = False
    window.reveal_page(generation)
    assert window.transition_pending
    window.queue_page_reveal()
    application.processEvents()
    assert not window.transition_pending
    assert window.transition_cover.isHidden()
    assert not window.player.video.isHidden()
    window.player.awaiting_frame = True
    window.begin_page_transition()
    window.player.load_error(None, "Invalid media")
    application.processEvents()
    assert not window.transition_pending
    assert window.player.status.text() == "Invalid media"


def test_page_reveal_clips_native_surface_during_warmup(window, application):
    window.panel("Browse")
    application.processEvents()
    player = window.browse.player
    window.begin_page_transition("clip")
    assert player.video.isHidden()

    player.preview_render_ready.emit()
    assert window.transition_cover.isVisible()
    assert player.video.isVisible()
    assert player.video.mask().boundingRect().size() == QSize(1, 1)

    window.begin_page_transition("clip")
    assert player.video.isHidden()
    assert player.video.mask().isEmpty()
    window.reveal_page(window.transition_generation)
    assert not window.transition_pending


def test_non_video_page_switch_skips_transition_cover(window, application):
    window.panel("Session")
    assert not window.transition_pending
    assert window.transition_cover.isHidden()
    window.panel("Browse")
    window.panel("Session")
    assert not window.transition_pending
    assert window.transition_cover.isHidden()
    window.panel("Home")
    assert not window.transition_pending
    assert window.transition_cover.isHidden()


def test_page_cover_keeps_outgoing_content_visible(window, application):
    window.set_theme("dark", persist=False)
    application.processEvents()
    window.begin_page_transition()
    try:
        assert window.transition_image.isVisible()
        assert not window.transition_image.pixmap().isNull()
        assert window.loading_label.isHidden()
    finally:
        window.cancel_page_transition()
    assert window.transition_image.isHidden()


def test_returning_to_page_reuses_unchanged_library_items(window, tmp_path):
    add_clips(window, tmp_path)
    window.refresh_library()
    first = window.library.item(0)
    window.panel("Session")
    window.panel("Home")
    assert window.library.item(0) is first


def test_clicking_active_tab_does_not_reload_media_or_library(
    window, tmp_path, monkeypatch
):
    add_clips(window, tmp_path)
    window.panel("Browse")
    monkeypatch.setattr(window, "refresh_library", lambda **kwargs: pytest.fail("library rebuilt"))
    monkeypatch.setattr(window.browse.player, "load", lambda clip: pytest.fail("clip reloaded"))
    window.nav["Browse"].click()
    assert window.current_panel == "Browse"


def test_export_return_reuses_loaded_preview(window, application, tmp_path):
    clip_id = add_clips(window, tmp_path, valid=True)[0]
    project_id = window.catalogue.save_project("Navigation preview")
    with window.catalogue.connection() as database:
        database.execute("INSERT INTO members VALUES (?, ?)", (project_id, clip_id))
    window.refresh_references()
    window.export_project.setCurrentIndex(window.export_project.findData(project_id))
    window.panel("Export")
    assert wait_for(application, lambda: not window.export_player.awaiting_frame)
    generation = window.export_player.media.generation
    window.panel("Home")
    window.panel("Export")
    assert window.export_player.media.generation == generation
    assert not window.transition_pending


def test_selected_export_preview_preloads_while_page_is_inactive(
    window, tmp_path, monkeypatch
):
    clip_id = add_clips(window, tmp_path)[0]
    project_id = window.catalogue.save_project("Preview project")
    with window.catalogue.connection() as database:
        database.execute("INSERT INTO members VALUES (?, ?)", (project_id, clip_id))
    window.refresh_references()
    window.export_project.setCurrentIndex(window.export_project.findData(project_id))
    window.preload_timer.stop()
    player = window.export_player
    loads = []

    def record_load(clip):
        loads.append(clip["clip_id"])
        player.loaded_clip = clip
        player.awaiting_frame = False

    monkeypatch.setattr(player, "load", record_load)
    window.prepare_inactive_clips()
    assert loads == [clip_id]
    window.panel("Export")
    assert loads == [clip_id]


def test_navigation_waits_on_outgoing_page_and_ignores_cancelled_preview(
    window, application, tmp_path, monkeypatch
):
    add_clips(window, tmp_path)
    window.preload_timer.stop()
    monkeypatch.setattr(window, "schedule_preload", lambda: None)
    player = window.browse.player

    def pending_load(clip):
        player.loaded_clip = clip
        player.awaiting_frame = True

    monkeypatch.setattr(player, "load", pending_load)
    window.nav["Browse"].click()
    assert window.current_panel == "Home"
    assert window.pages["Home"][0].isVisible()
    assert window.pending_page["name"] == "Browse"
    assert window.nav["Home"].isChecked()
    window.nav["Session"].click()
    assert window.current_panel == "Session"
    assert window.pending_page is None
    player.awaiting_frame = False
    player.loading_finished.emit()
    application.processEvents()
    assert window.current_panel == "Session"
    assert not window.nav["Browse"].isChecked()
    player.loaded_clip = None
    window.nav["Browse"].click()
    assert window.current_panel == "Session"
    player.awaiting_frame = False
    player.loading_finished.emit()
    assert wait_for(application, lambda: window.current_panel == "Browse")


def test_browse_is_hidden_before_player_cleanup(window, application, tmp_path, monkeypatch):
    add_clips(window, tmp_path)
    window.panel("Browse")
    application.processEvents()
    assert window.browse.clip is not None
    assert window.browse.isVisible()
    original_leave = window.browse.leave
    cleanup_state = []

    def record_leave():
        cleanup_state.append((window.center.currentWidget(), window.browse.isVisible()))
        original_leave()

    monkeypatch.setattr(window.browse, "leave", record_leave)
    window.panel("Home")

    assert cleanup_state == [(window.pages["Home"][0], False)]
    assert window.browse.clip is None


@pytest.mark.parametrize("player_name", ["player", "export_player", "browse_player"])
@pytest.mark.parametrize("size_at_ready", [False, True])
def test_preview_reveal_waits_for_display_size(
    window, application, player_name, size_at_ready
):
    player = window.browse.player if player_name == "browse_player" else getattr(window, player_name)
    player.video_container.set_video_size(0, 0)
    player.media._video_size = (0, 0)
    player.media._prepared = True
    player.awaiting_frame = True
    player.initial_seek_done = True
    player.preview_frame_ready = False
    finished = []
    player.loading_finished.connect(lambda: finished.append(player.video.geometry()))

    player.media._receive(player.media.generation, "ready", (320, 180) if size_at_ready else (0, 0))
    assert player.preview_frame_ready
    if not size_at_ready:
        assert player.awaiting_frame
        assert finished == []
        player.media._receive(
            player.media.generation, "video-out-params", {"dw": 320, "dh": 180}
        )

    assert player.awaiting_frame
    assert player.preview_reveal_timer.isActive()
    QTest.qWait(player.preview_reveal_timer.interval() + 20)
    application.processEvents()
    assert not player.awaiting_frame
    assert len(finished) == 1
    assert player.video_container.aspect_ratio == pytest.approx(16 / 9)
    assert abs(finished[0].width() * 180 - finished[0].height() * 320) <= 320
    assert not player.native_surface_warmed


@pytest.mark.parametrize("panel", ["Editing", "Export"])
def test_clip_click_keeps_list_and_viewport(
    window, application, tmp_path, monkeypatch, panel
):
    root = tmp_path / "LongLibrary"
    root.mkdir()
    folder = window.catalogue.add_folder(root)
    window.catalogue.ingest(
        folder,
        [{"path": str(root / f"clip-{index:03}.mp4"), "game": "VALORANT"} for index in range(80)],
    )
    ids = [clip["clip_id"] for clip in window.catalogue.clips()]
    if panel == "Editing":
        window.catalogue.create_session(ids)
    else:
        project = window.catalogue.save_project("Long project")
        for clip_id in ids:
            window.catalogue.patch(clip_id, {}, membership=(project, True))
        window.refresh_references()
        window.export_project.setCurrentIndex(window.export_project.findData(project))
    window.panel(panel)
    application.processEvents()
    player = window.active_player()
    loads = []

    def slow_load(clip):
        loads.append(clip["clip_id"])
        player.awaiting_frame = True
        player.loading_started.emit()

    monkeypatch.setattr(player, "load", slow_load)
    monkeypatch.setattr(window, "refresh_library", lambda: pytest.fail("Rebuilt clip list"))
    monkeypatch.setattr(window, "refresh_references", lambda: pytest.fail("Rebuilt references"))
    item = window.library.item(65)
    window.library.scrollToItem(item, window.library.ScrollHint.PositionAtCenter)
    application.processEvents()
    scroll = window.library.verticalScrollBar().value()
    for row in (65, 66, 67):
        target = window.library.item(row)
        QTest.mouseClick(
            window.library.viewport(),
            Qt.MouseButton.LeftButton,
            pos=window.library.visualItemRect(target).center(),
        )
        application.processEvents()
        assert window.library.verticalScrollBar().value() == scroll
        assert window.library.item(65) is item
        assert window.transition_scope == "clip"
        assert not window.transition_cover.geometry().intersects(window.left.geometry())
        assert window.transition_pending
    assert loads == ids[65:68]
    QTest.mouseClick(
        window.library.viewport(),
        Qt.MouseButton.LeftButton,
        pos=window.library.visualItemRect(window.library.item(67)).center(),
    )
    assert len(loads) == 3
    old_generation = window.transition_generation - 1
    player.awaiting_frame = False
    window.reveal_page(old_generation)
    assert window.transition_pending
    player.loading_finished.emit()
    application.processEvents()
    assert not window.transition_pending
    if panel == "Editing":
        window.navigate(1)
        assert window.current_id == ids[68]
        assert window.catalogue.state("session")["index"] == 68
        assert window.library.item(65) is item
        assert window.library.verticalScrollBar().value() == scroll


@pytest.mark.parametrize("panel", ["Browse", "Session", "Editing", "Export"])
def test_clip_list_positions_only_on_first_page_open(
    window, application, tmp_path, monkeypatch, panel
):
    root = tmp_path / "SelectionLibrary"
    root.mkdir()
    paths = [root / f"clip-{index:03}.mp4" for index in range(50)]
    for path in paths:
        path.touch()
    folder = window.catalogue.add_folder(root)
    window.catalogue.ingest(
        folder,
        [{"path": str(path), "game": "VALORANT"} for path in paths],
    )
    ids = [clip["clip_id"] for clip in window.catalogue.clips()]
    if panel == "Editing":
        window.catalogue.create_session(ids)
    elif panel == "Export":
        project = window.catalogue.save_project("Selection project")
        for clip_id in ids:
            window.catalogue.patch(clip_id, {}, membership=(project, True))
        window.refresh_references()
        window.export_project.setCurrentIndex(window.export_project.findData(project))
    window.panel(panel)
    application.processEvents()
    if window.library.currentRow() != 0:
        window.library.setCurrentRow(0)
    application.processEvents()
    assert window.library.visualItemRect(window.library.item(0)).top() == 0
    assert window.library_top_fade.isHidden()
    assert window.library_bottom_fade.isVisible()
    assert window.library_top_fade.testAttribute(
        Qt.WidgetAttribute.WA_TransparentForMouseEvents
    )
    assert window.library_bottom_fade.testAttribute(
        Qt.WidgetAttribute.WA_TransparentForMouseEvents
    )
    window.library.scrollToItem(window.library.item(30), window.library.ScrollHint.PositionAtCenter)
    application.processEvents()
    scroll = window.library.verticalScrollBar().value()
    window.library.setCurrentRow(30)
    application.processEvents()
    assert window.library.verticalScrollBar().value() == scroll
    assert window.library_top_fade.isVisible()
    assert window.library_bottom_fade.isVisible()
    assert window.library_top_fade.height() == 16
    assert window.library_bottom_fade.geometry().bottom() == (
        window.library.viewport().rect().bottom()
    )
    if panel == "Editing":
        assert window.session_position.text() == "31 / 50"
    assert panel in window.positioned_clip_pages
    monkeypatch.setattr(
        window,
        "position_selected_clip",
        lambda: pytest.fail("Repositioned after the page's first opening"),
    )
    window.refresh_library()
    application.processEvents()
    assert window.library.verticalScrollBar().value() == scroll
    window.panel("Home")
    window.panel(panel)
    application.processEvents()
    window.resize(window.width() + 1, window.height() + 1)
    application.processEvents()


def test_home_clip_left_click_retains_inert_highlight_without_context_menu(
    window, application, tmp_path, monkeypatch
):
    add_clips(window, tmp_path)
    window.panel("Home")
    # Synthetic catalogue ingestion bypasses Home's normal scan-result refresh.
    window.refresh_library()
    application.processEvents()
    item = window.library.item(0)
    assert item is not None
    popups = []
    monkeypatch.setattr(window.clip_context_menu, "popup", popups.append)

    position = window.library.visualItemRect(item).center()
    QTest.mousePress(
        window.library.viewport(),
        Qt.MouseButton.LeftButton,
        pos=position,
    )

    assert not popups
    assert window.library.currentItem() is item
    assert item.isSelected()
    QTest.mouseRelease(
        window.library.viewport(),
        Qt.MouseButton.LeftButton,
        pos=position,
    )
    assert window.library.currentItem() is item
    assert window.library.selectedItems() == [item]
    assert window.current_id is None
    assert not popups


@pytest.mark.parametrize("origin", ["Home", "Session"])
@pytest.mark.parametrize("target_row", [0, 1])
def test_double_click_library_clip_opens_it_in_browse(
    window, application, tmp_path, origin, target_row
):
    captures = tmp_path / "captures"
    captures.mkdir()
    paths = [captures / f"clip-{index}.mp4" for index in range(2)]
    for path in paths:
        path.write_bytes(b"video")
    folder_id = window.catalogue.add_folder(captures)
    window.catalogue.ingest(
        folder_id, [{"path": str(path), "game": None} for path in paths]
    )
    window.panel("Browse")
    window.browse_search.setText("does not match")
    window.panel(origin)
    item = window.library.item(target_row)
    clip_id = item.data(Qt.ItemDataRole.UserRole)
    window.library.setCurrentItem(window.library.item(0))
    assert (window.library.currentItem() is item) == (target_row == 0)

    position = window.library.visualItemRect(item).center()
    QTest.mouseClick(window.library.viewport(), Qt.MouseButton.LeftButton, pos=position)
    QTest.mouseDClick(
        window.library.viewport(),
        Qt.MouseButton.LeftButton,
        pos=position,
    )
    application.processEvents()

    assert window.current_panel == "Browse"
    assert window.browse_search.text() == ""
    assert window.browse_id == clip_id
    assert window.selected_id(window.library) == clip_id


def test_library_rebuild_keeps_viewport(window, application, tmp_path):
    root = tmp_path / "LongLibrary"
    root.mkdir()
    folder = window.catalogue.add_folder(root)
    window.catalogue.ingest(
        folder, [{"path": str(root / f"clip-{index:03}.mp4"), "game": None} for index in range(80)]
    )
    window.refresh_library()
    window.library.scrollToItem(window.library.item(65))
    application.processEvents()
    scroll = window.library.verticalScrollBar().value()
    window.refresh_library()
    application.processEvents()
    assert window.library.verticalScrollBar().value() == scroll


def test_navigation_keeps_selection_and_viewport_per_clip_pane(
    window, application, tmp_path
):
    root = tmp_path / "PaneStateLibrary"
    root.mkdir()
    paths = [root / f"clip-{index:03}.mp4" for index in range(50)]
    for path in paths:
        path.touch()
    folder = window.catalogue.add_folder(root)
    window.catalogue.ingest(
        folder, [{"path": str(path), "game": "VALORANT"} for path in paths]
    )
    ids = [clip["clip_id"] for clip in window.catalogue.clips()]
    window.catalogue.create_session(ids)

    window.panel("Browse")
    application.processEvents()
    window.library.setCurrentRow(8)
    window.library.scrollToItem(
        window.library.item(8), window.library.ScrollHint.PositionAtCenter
    )
    application.processEvents()
    browse_id = window.selected_id(window.library)
    browse_scroll = window.library.verticalScrollBar().value()

    window.panel("Editing")
    application.processEvents()
    window.library.setCurrentRow(40)
    window.library.scrollToItem(
        window.library.item(40), window.library.ScrollHint.PositionAtCenter
    )
    application.processEvents()
    editing_id = window.selected_id(window.library)
    editing_scroll = window.library.verticalScrollBar().value()
    assert editing_id != browse_id
    assert editing_scroll != browse_scroll

    window.panel("Browse")
    application.processEvents()
    assert window.selected_id(window.library) == browse_id
    assert window.library.verticalScrollBar().value() == browse_scroll

    window.panel("Editing")
    application.processEvents()
    assert window.selected_id(window.library) == editing_id
    assert window.library.verticalScrollBar().value() == editing_scroll


def test_replacement_session_rearms_first_editing_position(window, application, tmp_path):
    root = tmp_path / "ReplacementSession"
    root.mkdir()
    paths = [root / f"clip-{index:03}.mp4" for index in range(40)]
    for path in paths:
        path.touch()
    folder = window.catalogue.add_folder(root)
    window.catalogue.ingest(
        folder, [{"path": str(path), "game": "VALORANT"} for path in paths]
    )
    ids = [clip["clip_id"] for clip in window.catalogue.clips()]
    window.catalogue.create_session(ids)
    window.panel("Editing")
    application.processEvents()
    window.library.scrollToItem(window.library.item(30), window.library.ScrollHint.PositionAtCenter)
    application.processEvents()
    assert window.library.verticalScrollBar().value() > 0
    window.panel("Session")
    window.library.setCurrentRow(0)
    window.library.selectAll()
    window.confirm = lambda message: True
    window.create_session("all")
    application.processEvents()
    assert window.library.currentRow() == 0
    assert window.library.visualItemRect(window.library.item(0)).top() == 0
    scroll = window.library.verticalScrollBar().value()
    window.panel("Home")
    window.panel("Editing")
    application.processEvents()
    assert window.library.verticalScrollBar().value() == scroll


def test_real_clip_switch_reveals_local_preview(window, application, tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg required for playback fixtures")
    ids = add_clips(window, tmp_path, valid=True)
    source = Path(window.catalogue.clip(ids[0])["source_path"])
    second = source.with_name("second.mp4")
    shutil.copyfile(source, second)
    window.catalogue.ingest(
        window.catalogue.folders()[0]["folder_id"], [{"path": str(second), "game": "VALORANT"}]
    )
    ids = [clip["clip_id"] for clip in window.catalogue.clips()]
    window.catalogue.create_session(ids, replace=True)
    project = window.catalogue.save_project("Preview project")
    for clip_id in ids:
        window.catalogue.patch(clip_id, {}, membership=(project, True))
    window.refresh_references()
    window.export_project.setCurrentIndex(window.export_project.findData(project))
    for panel in ("Editing", "Export"):
        window.panel(panel)
        assert wait_for(application, lambda: not window.transition_pending)
        row = 1 - window.library.currentRow()
        expected = window.catalogue.clip(ids[row])["source_path"]
        window.library.setCurrentRow(row)
        assert window.transition_pending
        assert window.transition_scope == "clip"
        artifact = ROOT / "cache/verification/clip-navigation"
        artifact.mkdir(parents=True, exist_ok=True)
        window.grab().save(str(artifact / f"{panel.lower()}-loading.png"))
        assert wait_for(application, lambda: not window.transition_pending)
        assert wait_for(application, lambda: window.active_player().media.duration() > 0)
        assert not window.active_player().media.frame_image().isNull()
        assert Path(window.active_player().media.source().toLocalFile()) == Path(expected)
        window.grab().save(str(artifact / f"{panel.lower()}-ready.png"))


def test_background_completion(window, application):
    results = []
    window.background(lambda cancelled, progress: 42, results.append)
    assert wait_for(application, lambda: window.worker is None)
    assert results == [42]


@pytest.mark.parametrize("quiet", [True, False])
def test_close_during_background_operation_finishes_after_cancellation(
    window, application, quiet
):
    release = threading.Event()
    results = []

    def operation(cancelled, progress):
        release.wait(5)
        return cancelled()

    window.background(operation, results.append, quiet=quiet)
    worker = window.worker
    try:
        assert not window.close()
        assert window.isVisible()
        assert worker.cancelled.is_set()
        assert window.close_requested
        assert not window.scan_timer.isActive()
        assert not window.scan_retry_timer.isActive()
    finally:
        release.set()
    assert wait_for(application, lambda: not window.isVisible())
    assert window.worker is None
    assert results == []


def test_background_locks_immediately_until_cancel_finishes(window, application):
    release = threading.Event()
    results = []

    def operation(cancelled, progress):
        release.wait(5)
        return cancelled()

    window.background(operation, results.append)
    dialog = QApplication.activeModalWidget()
    assert isinstance(dialog, QProgressDialog)
    assert dialog.isVisible()
    worker = window.worker
    window.background(lambda cancelled, progress: "duplicate", results.append)
    assert window.worker is worker
    dialog.canceled.emit()
    assert dialog.isVisible()
    assert dialog.labelText() == "Cancelling… Please wait."
    release.set()
    assert wait_for(application, lambda: window.worker is None)
    assert results == [True]
    assert QApplication.activeModalWidget() is None


def test_export_dialog_submits_frozen_manifest(window, application, tmp_path, monkeypatch):
    ids = add_clips(window, tmp_path)
    project = window.catalogue.save_project("Frozen export")
    window.catalogue.patch(
        ids[0], {"triage": "keep", "metadata": {"agent": "Jett"}},
        membership=(project, True),
    )
    window.refresh_references()
    window.export_project.setCurrentIndex(window.export_project.findData(project))
    from dfsorter.project_export_dialog import ProjectExportDialog
    dialog = ProjectExportDialog(window, project)
    dialog.destination.setText(str(tmp_path / "output"))
    submitted = []
    monkeypatch.setattr(
        window.activities, "submit",
        lambda kind, title, function, **kwargs: submitted.append((kind, title, kwargs)),
    )
    dialog.submit()
    assert submitted and submitted[0][0] == "Export"
    assert QApplication.activeModalWidget() is None
    record = window.catalogue.export_jobs()[0]
    assert record["manifest"]["choices"]["project_id"] == project
    item = record["manifest"]["items"][0]
    assert item["source_path"] == window.catalogue.clip(ids[0])["source_path"]
    assert item["stem"]
    window.catalogue.patch(ids[0], {"mainline": "Changed later"})
    assert window.catalogue.export_jobs()[0]["manifest"]["items"][0] == item


def test_share_preparation_progress_states(window, application):
    window.set_theme("dark")
    activities = window.activities
    job = activities.submit("Share", "Late range", lambda *args: None, paused=True)
    job.state = "Queued"
    activities._refresh(job)
    assert job.status.text() == "Queued · 0%"
    job.state = "Running"
    for phase in ("Inspecting source…", "Starting encoding…", "Retrying with software encoding…"):
        activities._progress(job, -1, phase)
        assert job.bar.maximum() == 0
        assert job.status.text() == "Running"
        assert job.phase.text() == phase
        activities._progress(job, 0, "Encoding recording.mp4")
        assert job.status.text() == "Running · <1%"
        assert job.bar.maximum() == 100
        activities._progress(job, 25, "Encoding recording.mp4")
        assert job.bar.value() == 25
        assert job.status.text() == "Running · 25%"
    activities._progress(job, 90, "Validating output")
    assert job.bar.value() == 90
    activities._progress(job, 98, "Saving shared clip")
    assert job.bar.value() == 98
    job.state, job.percent = "Completed", 100
    activities._refresh(job)
    assert job.status.text() == "Completed · 100%"
    for state in ("Cancelling", "Cancelled", "Failed"):
        job.state, job.percent = state, -1
        activities._refresh(job)
        assert job.status.text() == state
        assert job.bar.maximum() == (0 if state == "Cancelling" else 100)
    export = activities.submit("Export", "Export", lambda *args: None, paused=True)
    export.state = "Running"
    activities._progress(export, -1, "Preparing…")
    assert export.status.text() == "Running"
    assert export.bar.maximum() == 0
    export.state = "Cancelled"


def test_export_preparation_progress_states(window, application):
    window.set_theme("dark")
    activities = window.activities
    job = activities.submit(
        "Export", "Export · Project progress", lambda *args: None, paused=True,
        record_id="progress-states", subtitle="2 clips", destination=str(window.root),
    )
    artifact = ROOT / "cache/verification/export-progress"
    artifact.mkdir(parents=True, exist_ok=True)

    def capture(name):
        application.processEvents()
        assert job.row.grab().save(str(artifact / f"{name}.png"))

    assert job.status.text() == "Paused · 0%"
    assert job.bar.maximum() == 100
    assert job.action.text() == "Resume export"
    capture("paused")
    job.state = "Queued"
    job.detail = "Waiting to resume"
    activities._refresh(job)
    assert job.status.text() == "Queued · 0%"
    assert job.action.text() == "Cancel"
    capture("queued")
    job.state = "Running"
    for name, phase in (
        ("preparing", "Preparing export…"),
        ("destination", "Checking destination…"),
        ("recovery", "Recovering previous output…"),
    ):
        activities._progress(job, -1, phase)
        assert job.status.text() == "Running"
        assert job.bar.maximum() == 0
        assert job.phase.text() == phase
        capture(name)
    activities._progress(job, 0, "Copying recording.mp4")
    assert job.status.text() == "Running · <1%"
    assert job.bar.maximum() == 100
    capture("early-copy")
    activities._progress(job, 25, "Verifying recording.mp4")
    assert job.status.text() == "Running · 25%"
    capture("verifying")
    activities._progress(job, 50, "Copying recording-2.mp4")
    assert job.bar.value() == 50
    capture("copying")
    activities._progress(job, 50, "Recovering previous output…")
    assert job.bar.value() == 50 and job.bar.maximum() == 100
    capture("measured-cleanup")
    activities._progress(job, 100, "Copying recording-2.mp4")
    assert job.bar.value() == 99
    for state in ("Failed", "Cancelled"):
        job.state, job.percent = state, -1
        job.detail = "Export failed" if state == "Failed" else "Export cancelled"
        activities._refresh(job)
        assert job.status.text() == state and job.bar.maximum() == 100
        assert job.action.text() == "Resume export"
        capture(f"{state.lower()}-preparation")
        job.percent = 50
        activities._refresh(job)
        assert job.status.text() == f"{state} · 50%"
        capture(state.lower())
    job.state, job.percent, job.detail = "Completed", 100, "Export complete"
    activities._refresh(job)
    assert job.status.text() == "Completed · 100%" and job.bar.value() == 100
    capture("completed")


def test_activities_bound_parallel_jobs_and_confirm_exit(window, application, monkeypatch):
    release = threading.Event()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)

    def operation(cancelled, progress):
        progress(25, "Working")
        release.wait(5)
        if cancelled():
            raise InterruptedError("Cancelled")
        return "done"

    first = window.activities.submit("Share", "Share first", operation)
    second = window.activities.submit("Share", "Share second", operation)
    export = window.activities.submit("Export", "Export project", operation)
    try:
        assert wait_for(application, lambda: first.state == "Running" and export.state == "Running")
        assert second.state == "Queued"
        assert window.activities_button.toolTip() == "Output Jobs (3)"
        assert window.activities_button.property("iconColorRole") == "accent_default"
        assert QApplication.activeModalWidget() is None

        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
        assert not window.close()
        assert window.isVisible() and not window.close_requested
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
        assert not window.close()
        assert window.close_requested and second.state == "Cancelled"
        assert first.worker.cancelled.is_set() and export.worker.cancelled.is_set()
    finally:
        release.set()
        window.activities.cancel_all()
        wait_for(application, lambda: not window.activities.busy(), timeout=2)
    assert wait_for(application, lambda: not window.isVisible())


def test_share_is_single_per_clip_across_browse_and_editing(window, application, tmp_path):
    clip_id = add_clips(window, tmp_path)[0]
    window.panel("Browse")
    browse = window.browse
    browse.custom_title.setText("Example")
    browse.destination.setText(str(tmp_path / "shares"))
    assert browse.share_button.isEnabled()
    release = threading.Event()

    def operation(cancelled, progress):
        release.wait(5)
        return "done"

    job = window.activities.submit("Share", "Share example", operation, clip_id=clip_id)
    try:
        assert wait_for(application, lambda: job.state == "Running")
        assert not browse.share_button.isEnabled()
        assert browse.share_button.text() == "Share in progress"
        assert not browse.share_button.icon().isNull()
        assert not browse.fullscreen_share_button.isEnabled()
        frame = browse.share_button.icon().cacheKey()
        assert wait_for(application, lambda: browse.share_button.icon().cacheKey() != frame)
        assert window.activities.submit(
            "Share", "Duplicate", operation, clip_id=clip_id,
        ) is job
        assert len(window.activities.jobs) == 1
        window.start_atomic_edit(clip_id, "Browse")
        assert window.current_panel == "Editing"
        assert not window.edit_share_button.isEnabled()
        assert window.edit_share_button.toolTip().startswith("Share in progress")
        assert not window.edit_share_button.icon().isNull()
    finally:
        release.set()
        try:
            assert wait_for(application, lambda: job.state == "Completed", timeout=6)
            assert window.edit_share_button.isEnabled()
            assert window.edit_share_button.toolTip() == "Share"
            assert window.edit_share_button.property("shareCompleted") is False
        finally:
            window.discard_atomic_edit()
    assert wait_for(application, lambda: job.state == "Completed")
    window.panel("Browse")
    browse.custom_title.setText("Example again")
    assert browse.share_button.isEnabled()
    assert browse.share_button.text() == "Share"
    assert browse.share_button.icon().isNull()


def test_completed_share_clears_after_browse_clip_change(window, application, tmp_path):
    clip_id = add_clips(window, tmp_path)[0]
    window.panel("Browse")
    browse = window.browse
    browse.custom_title.setText("Example")
    browse.destination.setText(str(tmp_path / "shares"))
    job = window.activities.submit(
        "Share", "Share example", lambda cancelled, progress: "done", clip_id=clip_id,
    )
    assert wait_for(application, lambda: job.state == "Completed")
    assert browse.share_button.text() == "Shared"
    assert not browse.share_button.isEnabled()
    assert browse.share_button.property("shareCompleted") is True
    assert browse.share_button.icon().isNull() is False
    assert browse.fullscreen_share_button.property("shareCompleted") is True
    assert not browse.fullscreen_share_button.isEnabled()
    browse.load(None)
    browse.load(window.catalogue.clip(clip_id))
    browse.custom_title.setText("Example")
    assert browse.share_button.text() == "Share"
    assert browse.share_button.isEnabled()
    assert browse.share_button.property("shareCompleted") is False


def test_failed_share_restores_share_control(window, application, tmp_path):
    clip_id = add_clips(window, tmp_path)[0]
    window.panel("Browse")
    browse = window.browse
    browse.custom_title.setText("Example")
    browse.destination.setText(str(tmp_path / "shares"))

    def fail(cancelled, progress):
        raise ValueError("failed")

    job = window.activities.submit("Share", "Share example", fail, clip_id=clip_id)
    assert wait_for(application, lambda: job.state == "Failed")
    assert browse.share_button.text() == "Share"
    assert browse.share_button.isEnabled()


def test_editing_share_completion_clears_on_pane_change(window, application, tmp_path):
    clip_id = add_clips(window, tmp_path)[0]
    window.start_atomic_edit(clip_id, "Home")
    job = window.activities.submit(
        "Share", "Share example", lambda cancelled, progress: "done", clip_id=clip_id,
    )
    assert wait_for(application, lambda: job.state == "Completed")
    assert not window.edit_share_button.isEnabled()
    assert window.edit_share_button.toolTip() == "Shared"
    assert window.edit_share_button.property("shareCompleted") is True
    window.discard_atomic_edit()
    window.panel("Home")
    window.start_atomic_edit(clip_id, "Home")
    assert window.edit_share_button.isEnabled()
    assert window.edit_share_button.toolTip() == "Share"


def test_activities_auto_open_close_and_repeat_after_idle(window, application):
    release = threading.Event()

    def operation(cancelled, progress):
        release.wait(5)
        return type("Result", (), {"completed": []})()

    first = window.activities.submit("Share", "First", operation)
    try:
        assert wait_for(application, lambda: window.activities.menu.isVisible())
        assert window.activities.auto_close_timer.isActive()
        assert window.activities.close_button.isVisible()
        window.activities.auto_close_timer.timeout.emit()
        assert not window.activities.menu.isVisible()
        window.activities.menu.popup(
            window.activities_button.mapToGlobal(QPoint(0, window.activities_button.height()))
        )
        window.activities.close_button.click()
        assert not window.activities.menu.isVisible()
        assert not window.activities.auto_close_timer.isActive()
    finally:
        release.set()
        wait_for(application, lambda: first.state == "Completed", timeout=6)
    assert wait_for(application, lambda: first.state == "Completed")

    release.clear()
    second = window.activities.submit("Share", "Second", operation)
    try:
        assert wait_for(application, lambda: window.activities.menu.isVisible())
        assert window.activities.auto_close_timer.isActive()
        QCoreApplication.sendEvent(
            window.activities.close_button,
            QMouseEvent(
                QEvent.Type.MouseMove, QPointF(6, 6), QPointF(6, 6), QPointF(6, 6),
                Qt.MouseButton.NoButton,
                Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            ),
        )
        assert not window.activities.auto_close_timer.isActive()
        window.activities.menu.hide()
        window.activities.menu.popup(
            window.activities_button.mapToGlobal(QPoint(0, window.activities_button.height()))
        )
        assert window.activities.menu.isVisible()
        assert not window.activities.auto_close_timer.isActive()
        window.activities.menu.hide()
    finally:
        release.set()
        wait_for(application, lambda: second.state == "Completed", timeout=6)
    assert wait_for(application, lambda: second.state == "Completed")


def test_export_jobs_popup_stays_open_on_start_finish_and_resume(window, application):
    release = threading.Event()

    def operation(cancelled, progress):
        release.wait(5)
        return type("Result", (), {"completed": []})()

    activities = window.activities
    job = activities.submit("Export", "Export example", operation)
    try:
        assert wait_for(application, lambda: activities.menu.isVisible())
        assert not activities.auto_close_timer.isActive()
        release.set()
        assert wait_for(application, lambda: job.state == "Completed")
        assert activities.menu.isVisible()
        activities.close_button.click()
        assert not activities.menu.isVisible()
        release.clear()
        resumed = activities.submit("Export", "Resume example", operation,
                                    paused=True, record_id="saved-job")
        activities.resume(resumed)
        assert wait_for(application, lambda: activities.menu.isVisible())
        assert not activities.auto_close_timer.isActive()
    finally:
        release.set()
        wait_for(application, lambda: not activities.busy(), timeout=6)
        activities.menu.hide()


@pytest.mark.parametrize("kind", ["Share", "Export"])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_output_completion_outline_waits_for_icon_click(window, application, kind, theme):
    window.set_theme(theme, persist=False)
    activities = window.activities
    release = threading.Event()

    def running(cancelled, progress):
        release.wait(5)
        return "done"

    background = activities.submit("Export", "Still running", running)
    try:
        assert wait_for(application, lambda: activities.menu.isVisible())
        complete = activities.submit(kind, "Finished", lambda cancelled, progress: "done")
        assert wait_for(application, lambda: complete.state == "Completed")
        assert background.state == "Running"
        assert activities.button.property("activityBusy")
        assert activities.button.property("activityCompleted")
        picture = activities.button.grab().toImage()
        assert picture.pixelColor(0, picture.height() // 2).name() == COLORS["status_success"].lower()
        activities.menu.hide()
        assert activities.button.property("activityCompleted")
        activities.button.clicked.emit()
        assert not activities.button.property("activityCompleted")
    finally:
        release.set()
        wait_for(application, lambda: background.state == "Completed", timeout=6)
        activities.menu.hide()
    assert activities.button.property("activityCompleted")
    activities.eventFilter(activities.button, QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier,
    ))
    assert not activities.button.property("activityCompleted")

    def fail(cancelled, progress):
        raise ValueError("Failed output")

    failed = activities.submit(kind, "Failed", fail)
    assert wait_for(application, lambda: failed.state == "Failed")
    assert not activities.button.property("activityCompleted")
    assert activities.button.property("activityAttention")
    activities.menu.hide()


def test_output_jobs_empty_state_and_theme(window, application):
    activities = window.activities
    empty_widget = activities.empty.defaultWidget()
    labels = [label.text() for label in empty_widget.findChildren(QLabel)]
    assert labels == ["", "No active jobs", "Exports and shared clips will appear here."]
    assert activities.empty.isVisible()
    assert not activities.header_divider.isHidden()
    assert empty_widget.minimumHeight() >= 156
    empty_icon = empty_widget.findChildren(QLabel)[0]
    assert empty_icon.property("headingIcon") == "inbox"
    assert empty_widget.findChildren(QLabel)[1].property("role") == "paneHeading"
    assert empty_widget.findChildren(QLabel)[2].property("role") == "secondary"
    assert any(widget.property("role") == "divider" for widget in
               activities.menu.actions()[0].defaultWidget().findChildren(QWidget))

    window.set_theme("dark")
    dark_icon = empty_icon.pixmap().cacheKey()
    window.set_theme("light")
    assert empty_icon.property("headingIconColorRole") == "text_muted"
    assert not empty_icon.pixmap().isNull()
    assert empty_icon.pixmap().cacheKey() != dark_icon

    job = activities.submit("Export", "Example", lambda cancelled, progress: "done", paused=True)
    assert not activities.empty.isVisible()
    assert activities.header_divider.isHidden()
    activities.dismiss(job)
    assert activities.empty.isVisible()
    assert not activities.header_divider.isHidden()


def test_output_job_cards_stack_and_show_state(window, application):
    activities = window.activities
    first = activities.submit("Share", "Share · Escape From Tarkov", lambda cancelled, progress: "done",
                              subtitle="raid.mp4", paused=True)
    second = activities.submit("Export", "Export · Highlights", lambda cancelled, progress: "done",
                               subtitle="3 clips", paused=True)
    assert not activities.empty.isVisible()
    assert [job.title for job in activities.jobs] == ["Share · Escape From Tarkov",
                                                      "Export · Highlights"]
    assert [job.menu_action for job in activities.jobs] == activities.menu.actions()[2:]
    assert first.row.findChild(QLabel, "outputJobSubtitle").text() == "raid.mp4"
    assert second.row.findChild(QLabel, "outputJobSubtitle").text() == "3 clips"
    assert first.row.findChild(QWidget, "outputJobCard") is not None
    assert first.bar.objectName() == "outputJobProgress"
    assert not first.bar.isTextVisible()

    for state, color in (("Running", "accent_default"), ("Completed", "status_success"),
                         ("Failed", "status_danger"), ("Queued", "text_muted"),
                         ("Cancelled", "text_muted")):
        first.state = state
        first.percent = 42
        first.detail = "Validating output"
        activities._refresh(first)
        assert first.status.text() == f"{state} · 42%"
        assert first.status_dot.property("statusColor") == color
        assert first.phase.text() == "Validating output"

    activities.dismiss(first)
    activities.dismiss(second)
    assert activities.empty.isVisible()


def test_output_job_explorer_buttons_open_folder_or_select_shared_file(
    window, application, tmp_path, monkeypatch,
):
    from dfsorter import activities as activities_module

    opened_folders = []
    selected_files = []
    monkeypatch.setattr(activities_module.QDesktopServices, "openUrl",
                        lambda url: opened_folders.append(url.toLocalFile()) or True)
    monkeypatch.setattr(activities_module.subprocess, "Popen",
                        lambda command: selected_files.append(command))
    monkeypatch.setattr(activities_module.sys, "platform", "win32")

    destination = tmp_path / "shares"
    share = window.activities.submit(
        "Share", "Share example", lambda cancelled, progress: None,
        paused=True, destination=str(destination),
    )
    assert share.open_button.property("iconName") == "folder-open"
    share.open_button.click()
    assert [Path(folder) for folder in opened_folders] == [destination]
    assert destination.is_dir()

    output = destination / "shared.mp4"
    output.write_bytes(b"video")
    share.result = str(output)
    share.state = "Completed"
    window.activities._refresh(share)
    assert share.open_button.property("iconName") == "file-search"
    share.open_button.click()
    assert selected_files == [["explorer.exe", "/select,", str(output)]]

    export_folder = tmp_path / "export"
    export = window.activities.submit(
        "Export", "Export example", lambda cancelled, progress: None,
        paused=True, destination=str(export_folder),
    )
    export.state = "Completed"
    window.activities._refresh(export)
    assert export.open_button.property("iconName") == "folder-open"
    export.open_button.click()
    assert Path(opened_folders[-1]) == export_folder
    assert len(selected_files) == 1


def test_unfinished_export_is_offered_for_resume_after_restart(window, application, tmp_path):
    from dfsorter.output import prepare_export_manifest

    ids = add_clips(window, tmp_path)
    window.catalogue.patch(ids[0], {"triage": "keep", "metadata": {"agent": "Jett"}})
    manifest = prepare_export_manifest(
        [window.catalogue.clip(ids[0])], window.registry,
        tmp_path / "resumed-export", window.catalogue.folders(),
    )
    manifest["project_name"] = "Saved project"
    window.catalogue.save_export_job("restart-job", manifest, "Cancelled")
    window.close()
    restarted = Window(tmp_path)
    restarted.show()
    application.processEvents()
    try:
        job = next(job for job in restarted.activities.jobs if job.record_id == "restart-job")
        assert job.state == "Paused" and job.action.text() == "Resume export"
        assert restarted.activities_button.toolTip() == "Output Jobs (1)"
        job.action.click()
        assert wait_for(application, lambda: job.state == "Completed")
        assert len(list((tmp_path / "resumed-export").glob("*.mp4"))) == 1
        assert restarted.catalogue.export_jobs() == []
    finally:
        restarted.close()


def test_game_change_confirmation_and_undo(window, application, tmp_path, monkeypatch):
    ids = add_clips(window, tmp_path)
    window.panel("Editing")
    window.edit({"metadata": {"agent": "Jett"}, "mainline": "Note", "rating": 2})
    monkeypatch.setattr(QInputDialog, "getItem", lambda *args, **kwargs: ("Battlefield 6", True))
    monkeypatch.setattr(window, "confirm", lambda message: False)
    window.change_game()
    assert window.catalogue.clip(ids[0])["game"] == "VALORANT"
    monkeypatch.setattr(window, "confirm", lambda message: True)
    window.change_game()
    clip = window.catalogue.clip(ids[0])
    assert clip["game"] == "Battlefield 6" and not clip["metadata"]
    assert clip["mainline"] == "Note" and clip["rating"] == 2
    window.undo()
    assert window.catalogue.clip(ids[0])["metadata"] == {"agent": "Jett"}


@pytest.mark.parametrize(
    "folder_name, forced_game, game",
    [("VALORANT", None, "VALORANT"), ("NVIDIA", None, None),
     ("NVIDIA", "Battlefield 6", "Battlefield 6")],
)
def test_folder_dialogs_and_background_scan(
    window, application, tmp_path, monkeypatch, folder_name, forced_game, game
):
    from PySide6.QtWidgets import QFileDialog

    from dfsorter.folder_preview_dialog import FolderPreviewDialog

    captures = tmp_path / folder_name
    captures.mkdir()
    (captures / "clip.mp4").write_bytes(b"test")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(captures))
    def preview(dialog):
        assert "1 video found" in dialog.summary.text()
        assert ("VALORANT" if folder_name == "VALORANT" else "Unclassified") in [
            label.text() for label in dialog.composition.findChildren(QLabel)
        ]
        assert dialog.parent_folder_tip.isHidden() == (folder_name != "VALORANT")
        assert dialog.override_section.isHidden() == (folder_name == "VALORANT")
        if forced_game:
            dialog.game.setCurrentText(forced_game)
            assert dialog.forced_game == forced_game
            assert "Unclassified" in [
                label.text() for label in dialog.composition.findChildren(QLabel)
            ]
        # Reproduce a modal dialog processing worker-finished events.
        QTest.qWait(100)
        application.processEvents()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(FolderPreviewDialog, "exec", preview)
    window.panel("Home")
    window.add_folder()
    assert wait_for(application, lambda: window.worker is None)
    assert len(window.catalogue.clips()) == 1
    assert window.catalogue.clips()[0]["game"] == game
    assert Path(window.catalogue.folders()[0]["path"]) == captures
    assert window.catalogue.folders()[0]["forced_game"] is None
    window.rescan()
    assert wait_for(application, lambda: window.worker is None)
    assert len(window.catalogue.clips()) == 1


def test_folder_preview_groups_mixed_scan_and_optional_assignment(window, application, tmp_path):
    from dfsorter.folder_preview_dialog import FolderPreviewDialog

    found = [
        {"game": "VALORANT", "error": None},
        {"game": None, "error": None},
    ]
    dialog = FolderPreviewDialog(str(tmp_path), found, window.registry.games, window)
    dialog.show()
    application.processEvents()
    try:
        assert dialog.summary.text() == "2 videos found"
        assert dialog.findChild(QWidget, "folderPreviewPath") is not None
        assert dialog.folder_path.toolTip() == str(tmp_path)
        assert [
            tuple(label.text() for label in row.findChildren(QLabel))
            for row in dialog.composition.findChildren(QWidget, "folderPreviewResultRow")
        ] == [("VALORANT", "1"), ("Unclassified", "1")]
        labels = [label.text() for label in dialog.findChildren(QLabel)]
        assert "Additional games can be added from Game configs… on Home." in labels
        assert dialog.game.currentText() == "Keep unclassified"
        assert dialog.forced_game is None
        assert dialog.assignment_note.text() == "1 unidentified video will remain unclassified."
        assert len([
            widget for widget in dialog.findChildren(QWidget)
            if widget.property("role") == "divider"
        ]) == 1
        folder_heading = next(label for label in dialog.findChildren(QLabel) if label.text() == "Folder")
        override_heading = next(label for label in dialog.findChildren(QLabel) if label.text() == "Unclassified videos")
        assert folder_heading.font().pixelSize() == dialog.summary.font().pixelSize()
        assert override_heading.font().pixelSize() == dialog.summary.font().pixelSize()
        assert dialog.override_section.isVisible()
        assert dialog.game.isEnabled()
        dialog.game.setCurrentText("Battlefield 6")
        assert dialog.forced_game == dialog.game.currentText()
        assert "Unclassified" in {
            label.text() for label in dialog.composition.findChildren(QLabel)
        }
        assert dialog.assignment_note.text() == (
            "1 unidentified video will be assigned to Battlefield 6 during import."
        )
        assert [
            tuple(label.text() for label in row.findChildren(QLabel))
            for row in dialog.composition.findChildren(QWidget, "folderPreviewResultRow")
        ] == [("VALORANT", "1"), ("Unclassified", "1")]
    finally:
        dialog.close()


def test_folder_preview_handles_empty_games_and_long_results(window, application, tmp_path):
    from dfsorter.folder_preview_dialog import FolderPreviewDialog

    directory = str(tmp_path / "A long recordings folder name")
    found = [{"game": f"Game {index}", "error": None} for index in range(12)]
    found.append({"game": None, "error": "inspection failed"})
    dialog = FolderPreviewDialog(directory, found, [], window)
    dialog.show()
    application.processEvents()
    try:
        assert dialog.folder_path.toolTip() == directory
        assert dialog.folder_path.text() != directory
        assert dialog.folder_path.text().endswith("name")
        assert dialog.game.count() == 1
        assert dialog.forced_game is None
        assert dialog.results_scroll.verticalScrollBar().maximum() > 0
        assert dialog.results_scroll.height() < dialog.composition.sizeHint().height()
        assert any(
            label.text() == "1 media inspection warning"
            for label in dialog.findChildren(QLabel)
        )
    finally:
        dialog.close()


@pytest.mark.parametrize("same_folder", [False, True])
def test_edit_folder_restarts_preview_after_inspection(
    window, application, tmp_path, monkeypatch, same_folder
):
    from PySide6.QtWidgets import QFileDialog

    from dfsorter.folder_preview_dialog import FolderPreviewDialog

    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "first.mp4").write_bytes(b"test")
    (second / "second.mp4").write_bytes(b"test")
    initial_picks = []
    selection = str(first if same_folder else second)

    def pick(parent, title, start=""):
        initial_picks.append(start)
        return str(first) if len(initial_picks) == 1 else selection

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", pick)
    previews = []

    def preview(dialog):
        previews.append(dialog.directory)
        if len(previews) == 1:
            dialog.choose_folder()
            return QDialog.DialogCode.Rejected
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(FolderPreviewDialog, "exec", preview)
    window.add_folder_button.click()
    assert wait_for(application, lambda: window.worker is None and len(previews) == 2)
    assert previews == [str(first), selection]
    assert initial_picks == ["", str(first)]
    assert Path(window.catalogue.folders()[0]["path"]) == Path(selection)
    assert Path(window.catalogue.clips()[0]["source_path"]).parent == Path(selection)


def test_folder_assignment_only_changes_unidentified_videos_on_import(
    window, application, tmp_path, monkeypatch
):
    from PySide6.QtWidgets import QFileDialog

    from dfsorter.folder_preview_dialog import FolderPreviewDialog

    captures = tmp_path / "captures"
    recognized = captures / "VALORANT"
    unidentified = captures / "unknown"
    recognized.mkdir(parents=True)
    unidentified.mkdir()
    (recognized / "known.mp4").write_bytes(b"test")
    (unidentified / "unknown.mp4").write_bytes(b"test")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(captures))

    def preview(dialog):
        dialog.game.setCurrentText("Battlefield 6")
        assert {label.text() for label in dialog.composition.findChildren(QLabel)} >= {
            "VALORANT", "Unclassified", "1"
        }
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(FolderPreviewDialog, "exec", preview)
    window.add_folder()
    assert wait_for(application, lambda: window.worker is None)
    clips = {Path(clip["source_path"]).name: clip for clip in window.catalogue.clips()}
    assert clips["known.mp4"]["game"] == "VALORANT"
    assert clips["unknown.mp4"]["game"] == "Battlefield 6"
    assert window.catalogue.folders()[0]["forced_game"] is None
    (unidentified / "later.mp4").write_bytes(b"test")
    window.rescan()
    assert wait_for(application, lambda: window.worker is None)
    clips = {Path(clip["source_path"]).name: clip for clip in window.catalogue.clips()}
    assert clips["later.mp4"]["game"] is None


def test_rescan_modal_cache_restart(window, application, tmp_path, monkeypatch):
    from dfsorter.scanning import ScanCoordinator

    add_clips(window, tmp_path)
    calls = []

    def probe(path, *args):
        calls.append(path)
        return dict(duration=15, created="2026-09-17", error=None)

    monkeypatch.setattr("dfsorter.scanning.inspect_media", probe)
    monkeypatch.setattr("dfsorter.scanning.tool", lambda name: "ffprobe")
    ScanCoordinator(window.catalogue, window.registry).run(window.catalogue.folders())
    restarted = Window(tmp_path)
    assert next(iter(restarted.media_info.values()))["duration"] == 15
    restarted.show()
    application.processEvents()
    assert isinstance(QApplication.activeModalWidget(), QProgressDialog)
    assert wait_for(application, lambda: restarted.worker is None)
    assert len(calls) == 1
    restarted.reinspect()
    assert isinstance(QApplication.activeModalWidget(), QProgressDialog)
    assert wait_for(application, lambda: restarted.worker is None)
    assert len(calls) == 2
    restarted.close()


def test_disabled_folder_session_selection(window, application, tmp_path):
    ids = add_clips(window, tmp_path)
    original_session = window.catalogue.state("session")
    window.panel("Session")
    assert window.library.count() == 1
    window.folders.setCurrentRow(0)
    window.toggle_folder()
    assert window.library.count() == 0
    assert window.catalogue.state("session") == original_session
    window.panel("Editing")
    assert window.library.count() == len(ids)
    window.panel("Session")
    window.toggle_folder()
    assert window.library.count() == 1


def test_all_panel_layouts(window, application, tmp_path):
    add_clips(window, tmp_path)
    project = window.catalogue.save_project("Example montage")
    clip = window.catalogue.clips()[0]
    window.catalogue.patch(clip["clip_id"], {}, membership=(project, True))
    window.refresh_references()
    artifact = ROOT / "cache/verification"
    artifact.mkdir(parents=True, exist_ok=True)
    for name in ["Home", "Session", "Export", "Config"]:
        window.panel(name)
        if name == "Export":
            window.export_project.setCurrentIndex(window.export_project.findData(project))
            assert window.export_button.isEnabled()
        application.processEvents()
        window.grab().save(str(artifact / f"{name.lower()}.png"))


def test_add_project_next_requires_destination_and_preserves_triage(window, application, tmp_path):
    add_clips(window, tmp_path)
    folder = window.catalogue.folders()[0]
    window.catalogue.ingest(
        folder["folder_id"], [{"path": str(tmp_path / "captures" / "extra.mp4"), "game": None}]
    )
    ids = [clip["clip_id"] for clip in window.catalogue.clips()]
    window.catalogue.create_session(ids, replace=True)
    window.catalogue.patch(ids[0], {"triage": "keep"})
    window.catalogue.patch(ids[1], {"triage": "discard"})
    window.panel("Editing")
    project = window.catalogue.save_project("Shortlist")
    window.refresh_references()
    assert not window.add_project_next.isEnabled()
    QTest.keyClick(window.player, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert window.current_id == ids[0]
    assert not window.catalogue.member_ids(project)
    window.catalogue.set_state("review_destination", project)
    window.refresh_references()
    assert window.add_project_next.isEnabled()
    window.command.setFocus()
    window.command.setText("unfinished note")
    QTest.keyClick(window.command, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert not window.catalogue.member_ids(project)
    QTest.keyClick(window.command, Qt.Key.Key_Escape)
    QTest.keyClick(window.player, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert window.current_id == ids[1]
    assert window.catalogue.member_ids(project) == {ids[0]}
    window.add_project_next.click()
    window.add_project_next.click()
    assert window.current_id == ids[1]
    assert window.catalogue.member_ids(project) == set(ids)
    assert [window.catalogue.clip(i)["triage"] for i in ids] == ["keep", "discard"]
    window.navigate(-1)
    assert window.command.text() == "unfinished note"
    window.catalogue.set_state("review_destination", None)
    window.update_collection_controls()
    assert not window.add_project_next.isEnabled()


def test_next_undefined_navigation_is_editing_only(window, application, tmp_path):
    add_clips(window, tmp_path)
    folder = window.catalogue.folders()[0]
    window.catalogue.ingest(
        folder["folder_id"],
        [{"path": str(tmp_path / "captures" / f"next-{i}.mp4"), "game": None} for i in range(3)],
    )
    ids = [clip["clip_id"] for clip in window.catalogue.clips()]
    window.catalogue.create_session(ids, replace=True)
    window.catalogue.patch(ids[1], {"triage": "keep"})
    window.catalogue.patch(ids[2], {"triage": "discard"})
    window.panel("Editing")
    assert not window.session_header.isHidden()
    assert window.next_undefined_button.toolTip() == "Next pending clip"
    window.command.setText("draft")
    window.next_undefined_button.click()
    assert window.current_id == ids[3]
    assert window.catalogue.clip(ids[0])["triage"] is None
    window.next_undefined_button.click()
    assert window.current_id == ids[3]
    assert "No pending clips ahead" in window.statusBar().currentMessage()
    window.navigate(-3)
    assert window.command.text() == "draft"
    for panel in ["Home", "Session", "Export", "Config"]:
        window.panel(panel)
        assert window.session_header.isHidden()


def test_settings_cog_preserves_actions_without_menu_bar(window, application, tmp_path):
    from PySide6.QtWidgets import QMenuBar

    assert not window.findChildren(QMenuBar)
    assert window.settings_button.popupMode() == QToolButton.ToolButtonPopupMode.InstantPopup
    actions = {action.text(): action for action in window.settings_menu.actions()}
    assert {
        "Settings…",
        "Capture folders…",
        "Reset clip metadata…",
        "Edit tag…",
        "Delete rejected originals…",
        "Manage unavailable clips…",
        "Reset window and panes",
        "Exit",
    } <= actions.keys()
    window.panel("Session")
    actions["Capture folders…"].trigger()
    assert window.current_panel == "Home"
    assert window.folders.isVisible()
    assert actions["Exit"].shortcut().toString() == "Ctrl+Q"
    ids = add_clips(window, tmp_path)
    window.panel("Editing")
    window.edit({"rating": 4})
    window.review_mode()
    QTest.keyClick(window.player, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert window.catalogue.clip(ids[0])["rating"] is None
    QTest.keyClick(
        window.player,
        Qt.Key.Key_Z,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
    )
    assert window.catalogue.clip(ids[0])["rating"] == 4
    assert "Undo" not in actions and "Redo" not in actions
    window.undo_button.click()
    assert window.catalogue.clip(ids[0])["rating"] is None
    window.redo_button.click()
    assert window.catalogue.clip(ids[0])["rating"] == 4
    utilities = [
        window.undo_button,
        window.redo_button,
        window.theme_button,
        window.settings_button,
    ]
    assert {control.height() for control in utilities} == {28}
    assert len({control.geometry().center().y() for control in utilities}) == 1
    assert window.activities_button.size() == QSize(26, 26)
    assert window.activities_button.geometry().center().y() == utilities[0].geometry().center().y()
    assert window.undo_button.property("navUtilityStyle") == "ghost"
    assert window.redo_button.property("navUtilityStyle") == "ghost"
    assert window.activities_button.property("navUtilityStyle") == "ghost"
    assert window.activities_button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
    assert window.activities_button.iconSize() == window.theme_button.iconSize()
    assert window.activities_button.property("iconRenderSize") == window.theme_button.property("iconRenderSize")
    assert window.activities_button.property("iconYOffset") == -1
    assert window.activities_button.text() == ""
    assert window.activities_button.popupMode() == QToolButton.ToolButtonPopupMode.InstantPopup
    assert window.undo_button.property("iconYOffset") == -2
    assert window.redo_button.property("iconYOffset") == -2
    assert window.theme_button.property("iconYOffset") == -2
    assert window.settings_button.property("iconYOffset") == -2
    assert window.theme_button.property("navUtilityStyle") == "ghost"
    assert window.settings_button.property("navUtilityStyle") == "ghost"

    def painted_icon_height(control):
        image = control.icon().pixmap(control.iconSize()).toImage()
        rows = [
            y
            for y in range(image.height())
            if any(image.pixelColor(x, y).alpha() for x in range(image.width()))
        ]
        return max(rows) - min(rows) + 1

    window.set_theme("dark", persist=False)
    assert window.theme_button.property("iconName") == "sun"
    assert painted_icon_height(window.theme_button) > 0


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_facelift_heading_icons_share_title_centerline(window, application, theme):
    window.set_theme(theme, persist=False)
    for panel, names in (
        ("Home", ("Capture folders",)),
        ("Session", ("Library overview", "No active session")),
    ):
        window.panel(panel)
        application.processEvents()
        for name in names:
            label = next(
                child for child in window.findChildren(QLabel)
                if child.text() == name and child.isVisible()
            )
            glyph = next(
                child for child in window.findChildren(QLabel)
                if child.parent() is label.parent() and child.property("headingIcon")
            )
            assert abs(
                glyph.mapToGlobal(glyph.rect().center()).y()
                - label.mapToGlobal(label.rect().center()).y()
            ) <= 1
            assert glyph.property("headingIconSize") == 24
            assert label.font().pixelSize() == 22
            image = label.grab().toImage()
            painted_rows = [
                y for y in range(image.height())
                if any(image.pixelColor(x, y).alpha() > 128 for x in range(image.width()))
            ]
            assert painted_rows
            painted_center = (
                label.mapToGlobal(QPoint(0, 0)).y()
                + (min(painted_rows) + max(painted_rows)) / (2 * image.devicePixelRatio())
            )
            assert abs(painted_center - glyph.mapToGlobal(glyph.rect().center()).y()) <= 2


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_heading_icons_are_unbacked_centered_and_unclipped(window, application, theme):
    window.set_theme(theme, persist=False)
    for panel, names in (
        ("Home", ("Capture folders",)),
        ("Session", ("Library overview", "No active session")),
    ):
        window.panel(panel)
        application.processEvents()
        for name in names:
            label = next(child for child in window.findChildren(QLabel) if child.text() == name)
            glyph = next(
                child for child in window.findChildren(QLabel)
                if child.parent() is label.parent() and child.property("headingIcon")
            )
            assert glyph.property("role") is None
            expected_size = QSize(32, 32)
            if name == "Library overview":
                expected_size.setHeight(min(32, window.search.sizeHint().height()))
            assert glyph.size() == expected_size
            assert glyph.grab().toImage().pixelColor(0, 0).alpha() == 0
            pixmap = glyph.pixmap().toImage()
            painted = [
                (x, y)
                for x in range(pixmap.width()) for y in range(pixmap.height())
                if pixmap.pixelColor(x, y).alpha() > 128
            ]
            assert painted
            assert abs(
                (min(y for _, y in painted) + max(y for _, y in painted)) / 2
                - (pixmap.height() - 1) / 2
            ) <= pixmap.devicePixelRatio()
            expected_color = QColor("#000000" if theme == "light" else "#FFFFFF")
            assert any(pixmap.pixelColor(x, y) == expected_color for x, y in painted)


def test_settings_remain_available_in_browse(window):
    actions = {action.text(): action for action in window.settings_menu.actions()}
    window.panel("Browse")
    assert actions["Settings…"].isEnabled()
    assert not actions["Reset clip metadata…"].isEnabled()
    assert not actions["Edit tag…"].isEnabled()
    assert not actions["Delete rejected originals…"].isEnabled()


def test_history_controls_availability(window, tmp_path):
    from PySide6.QtGui import QIcon

    from dfsorter.theme import COLORS

    def available(undo, redo):
        assert window.undo_button.isEnabled() is undo
        assert window.redo_button.isEnabled() is redo

    available(False, False)
    for control in (window.undo_button, window.redo_button):
        for mode, color in [
            (QIcon.Mode.Normal, COLORS["text_secondary"]),
            (QIcon.Mode.Disabled, COLORS["text_disabled"]),
        ]:
            image = control.icon().pixmap(16, 16, mode).toImage()
            pixels = [image.pixelColor(x, y) for x in range(16) for y in range(16)]
            assert max(pixels, key=lambda pixel: pixel.alpha()).name() == color.lower()
    add_clips(window, tmp_path)
    window.panel("Editing")
    window.edit({"rating": 4})
    available(True, False)
    window.undo_button.click()
    available(False, True)
    window.redo_button.click()
    available(True, False)
    window.edit({"rating": 5})
    window.undo()
    available(True, True)
    window.edit({"rating": 3})
    available(True, False)
    while window.editing_history().undo_stack:
        window.undo()
    window.panel("Home")
    project = window.catalogue.save_project("History controls")
    window.refresh_references()
    window.panel("Export")
    window.workspace.select_project(project, new=True)
    window.workspace.verdict.setCurrentIndex(0)
    window.library.setCurrentRow(0)
    window.workspace.selected_action.click()
    available(True, False)
    window.panel("Home")
    available(False, False)
    window.catalogue.delete_project(project)
    window.refresh_references()
    available(False, False)


def test_title_casing_settings_refresh(window, application, tmp_path, monkeypatch):
    import yaml
    from PySide6.QtGui import QTextDocument

    ids = add_clips(window, tmp_path)
    window.panel("Editing")
    window.edit(
        {
            "metadata": {"agent": "Clove", "weapon": ["Phantom"], "kill": 4},
            "mainline": "My BEST 中文",
            "tag": "LOW_FPS",
        }
    )
    before = window.catalogue.clip(ids[0])
    selected = window.library.currentRow()
    scroll = window.library.verticalScrollBar().value()
    position = window.player.media.position()
    monkeypatch.setattr(
        window, "load_clip", lambda *args: pytest.fail("Title toggle reloaded clip")
    )
    dialog = SettingsDialog(window)
    assert dialog.lowercase_titles.isChecked()
    for enabled, expected in [
        (True, "4k clove phantom | my best 中文"),
        (False, "4K Clove Phantom | My BEST 中文"),
        (True, "4k clove phantom | my best 中文"),
    ]:
        dialog.lowercase_titles.setChecked(enabled)
        document = QTextDocument()
        document.setHtml(window.working_title.text())
        assert document.toPlainText() == "[LOW_FPS] VAL_" + expected
        data = window.library.item(selected).data(CLIP_ROLE)
        assert data["title"] == document.toPlainText()
        assert data["title"] in window.library.item(selected).toolTip()
        assert window.catalogue.clip(ids[0]) == before
        assert window.library.currentRow() == selected
        assert window.library.verticalScrollBar().value() == scroll
        assert window.player.media.position() == position
    assert yaml.safe_load(window.settings_path.read_text(encoding="utf-8"))[
        "lowercase_generated_titles"
    ]
    dialog.close()


@pytest.mark.parametrize("panel", ["Home", "Browse", "Session"])
def test_library_controls_select_first_visible_clip(window, tmp_path, panel):
    captures = tmp_path / "captures"
    captures.mkdir()
    paths = [captures / f"clip-{index}.mp4" for index in range(3)]
    for path in paths:
        path.write_bytes(b"test")
    folder = window.catalogue.add_folder(captures)
    window.catalogue.ingest(folder, [{"path": str(path), "game": None} for path in paths])
    for index, clip in enumerate(window.catalogue.clips()):
        window.media_info[clip["source_path"]] = {
            "created": f"2026-09-{index + 1:02}T12:00:00Z"
        }
    window.panel(panel)
    assert window.library.count() == 3

    def assert_first_only():
        first = window.library.item(0)
        assert window.library.currentItem() is first
        assert window.library.selectedItems() == [first]
        if panel == "Browse":
            assert window.browse_id == first.data(Qt.ItemDataRole.UserRole)

    window.library.setCurrentRow(2)
    if panel == "Session":
        window.library.item(1).setSelected(True)
    window.toggle_time_sort()
    assert_first_only()

    window.library.setCurrentRow(2)
    search = window.browse_search if panel == "Browse" else window.search
    search.setText("clip-1")
    assert window.library.count() == 1
    assert_first_only()
    search.clear()
    assert window.library.count() == 3
    assert_first_only()

    window.library.setCurrentRow(2)
    window.catalogue.patch(
        window.library.item(0).data(Qt.ItemDataRole.UserRole), {"triage": "keep"}
    )
    window.clip_filter.set_selected_values({"keep"})
    assert window.library.count() == 1
    assert_first_only()

    window.clip_filter.set_selected_values({None, "keep"})
    window.library.setCurrentRow(1)
    preserved = window.library.currentItem().data(Qt.ItemDataRole.UserRole)
    window.refresh_library()
    assert window.library.currentItem().data(Qt.ItemDataRole.UserRole) == preserved


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_library_selection_reaches_both_row_boundaries(
    window, application, tmp_path, theme
):
    captures = tmp_path / "captures"
    captures.mkdir()
    paths = [captures / f"clip-{index}.mp4" for index in range(3)]
    for path in paths:
        path.write_bytes(b"test")
    folder = window.catalogue.add_folder(captures)
    window.catalogue.ingest(folder, [{"path": str(path), "game": None} for path in paths])
    ids = [clip["clip_id"] for clip in window.catalogue.clips()]
    window.set_theme(theme)
    window.refresh_library()
    window.library.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    for panel in ("Home", "Browse", "Session"):
        window.panel(panel)
        application.processEvents()
        window.library.clearSelection()
        window.library.setCurrentRow(1)
        application.processEvents()
        rect = window.library.visualItemRect(window.library.item(1))
        image = window.library.viewport().grab().toImage()
        x = rect.center().x()
        assert rect.height() == (65 if panel == "Browse" else 54)
        corner = image.pixelColor(rect.right() - 1, rect.top())
        if panel == "Browse":
            assert corner != QColor(COLORS["accent_selection"])
        else:
            assert corner == QColor(COLORS["accent_selection"])
        assert image.pixelColor(x, rect.top() - 1) != QColor(COLORS["accent_selection"])
        assert image.pixelColor(x, rect.top()) == QColor(COLORS["accent_selection"])
        assert image.pixelColor(x, rect.bottom()) == QColor(COLORS["accent_selection"])
        next_rect = window.library.visualItemRect(window.library.item(2))
        assert image.pixelColor(x, next_rect.top()) != QColor(COLORS["border_subtle"])
        indicator_x = rect.left() + 2
        if panel == "Browse":
            for y in (rect.top(), rect.center().y(), rect.bottom()):
                assert image.pixelColor(indicator_x, y) != QColor(COLORS["accent_default"])
            assert image.pixelColor(indicator_x, rect.center().y()) != QColor(
                COLORS["accent_selection"]
            )
            assert image.pixelColor(rect.left() + 8, rect.center().y()) == QColor(
                COLORS["accent_selection"]
            )
            thumbnail_left = rect.left() + 16
            assert image.pixelColor(thumbnail_left, rect.center().y()) != image.pixelColor(
                thumbnail_left,
                window.library.visualItemRect(window.library.item(0)).center().y(),
            )
        else:
            for y in (rect.top(), rect.top() + 3, rect.bottom() - 3, rect.bottom()):
                assert image.pixelColor(indicator_x, y) == QColor(COLORS["accent_default"])
            assert image.pixelColor(rect.left() + 1, rect.top()) == QColor(COLORS["accent_default"])
        assert image.pixelColor(rect.left() + 3, rect.center().y()) != QColor(
            COLORS["accent_default"]
        )
        if panel == "Session":
            window.library.item(0).setSelected(True)
            application.processEvents()
            image = window.library.viewport().grab().toImage()
            assert image.pixelColor(x, rect.top() - 1) == QColor(COLORS["accent_selection"])
            assert image.pixelColor(x, rect.top()) == QColor(COLORS["accent_selection"])
        window.library.clearSelection()
        window.library.setCurrentRow(2)
        window.library.item(2).setSelected(True)
        application.processEvents()
        assert window.library.selectedItems() == [window.library.item(2)]
        image = window.library.viewport().grab().toImage()
        assert image.pixelColor(x, rect.top() - 1) != QColor(COLORS["accent_selection"])

    window.catalogue.create_session(ids)
    window.panel("Editing")
    application.processEvents()
    window.library.clearSelection()
    window.library.setCurrentRow(1)
    application.processEvents()
    rect = window.library.visualItemRect(window.library.currentItem())
    image = window.library.viewport().grab().toImage()
    x = rect.center().x()
    assert rect.height() == 54
    assert image.pixelColor(rect.right() - 1, rect.top()) == QColor(COLORS["accent_selection"])
    assert image.pixelColor(x, rect.top()) == QColor(COLORS["accent_selection"])
    assert image.pixelColor(x, rect.bottom()) == QColor(COLORS["accent_selection"])
    assert image.pixelColor(x, window.library.visualItemRect(window.library.item(2)).top()) != QColor(
        COLORS["border_subtle"]
    )
    for y in (rect.top(), rect.bottom()):
        assert image.pixelColor(rect.left() + 2, y) == QColor(COLORS["accent_default"])
    assert image.pixelColor(rect.left() + 3, rect.center().y()) != QColor(
        COLORS["accent_default"]
    )
    heading_x = window.session_heading.mapTo(window.left, QPoint(0, 0)).x()
    footer_x = window.session_counts.mapTo(window.left, QPoint(0, 0)).x() + 8
    assert heading_x == 12
    assert footer_x == 8

    project = window.catalogue.save_project("Card alignment")
    for clip_id in ids:
        window.catalogue.patch(clip_id, {}, membership=(project, True))
    window.refresh_references()
    window.export_project.setCurrentIndex(window.export_project.findData(project))
    window.panel("Export")
    window.library.clearSelection()
    window.library.setCurrentRow(1)
    application.processEvents()
    rect = window.library.visualItemRect(window.library.item(1))
    image = window.library.viewport().grab().toImage()
    x = rect.center().x()
    assert 54 < rect.height() < 85
    assert image.pixelColor(rect.right() - 1, rect.top()) == QColor(COLORS["accent_selection"])
    assert image.pixelColor(x, rect.top()) == QColor(COLORS["accent_selection"])
    assert image.pixelColor(x, rect.bottom()) == QColor(COLORS["accent_selection"])
    assert image.pixelColor(x, window.library.visualItemRect(window.library.item(2)).top()) != QColor(
        COLORS["border_subtle"]
    )


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_library_hover_covers_owned_separator(window, application, tmp_path, theme):
    captures = tmp_path / "captures"
    captures.mkdir()
    paths = [captures / f"clip-{index}.mp4" for index in range(3)]
    for path in paths:
        path.write_bytes(b"test")
    folder = window.catalogue.add_folder(captures)
    window.catalogue.ingest(folder, [{"path": str(path), "game": None} for path in paths])
    window.catalogue.create_session([clip["clip_id"] for clip in window.catalogue.clips()])
    window.set_theme(theme)
    for panel in ("Home", "Browse", "Editing"):
        window.panel(panel)
        window.library.clearSelection()
        application.processEvents()
        viewport = window.library.viewport()
        assert viewport.hasMouseTracking()
        rect = window.library.visualItemRect(window.library.item(1))
        point = rect.center()
        QCoreApplication.sendEvent(
            viewport,
            QMouseEvent(
                QEvent.Type.MouseMove, QPointF(point), QPointF(viewport.mapToGlobal(point)),
                Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            ),
        )
        application.processEvents()
        assert window.library.library_hover_row == 1
        image = viewport.grab().toImage()
        x = rect.center().x()
        assert image.pixelColor(rect.right() - 1, rect.top()) != QColor(COLORS["surface_hover"])
        assert image.pixelColor(x, rect.top() - 1) != QColor(COLORS["surface_hover"])
        for y in (rect.top(), rect.bottom()):
            assert image.pixelColor(x, y) == QColor(COLORS["surface_hover"])
        if panel == "Browse":
            assert image.pixelColor(rect.left() + 2, rect.center().y()) != QColor(
                COLORS["surface_hover"]
            )
            assert image.pixelColor(rect.left() + 8, rect.center().y()) == QColor(
                COLORS["surface_hover"]
            )
        assert image.pixelColor(x, window.library.visualItemRect(window.library.item(2)).top()) != QColor(
            COLORS["border_subtle"]
        )

        point = window.library.visualItemRect(window.library.item(2)).center()
        QCoreApplication.sendEvent(
            viewport,
            QMouseEvent(
                QEvent.Type.MouseMove, QPointF(point), QPointF(viewport.mapToGlobal(point)),
                Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            ),
        )
        application.processEvents()
        assert window.library.library_hover_row == 2
        image = viewport.grab().toImage()
        assert image.pixelColor(x, rect.top() - 1) != QColor(COLORS["surface_hover"])


def test_browse_entry_selects_newest(window, tmp_path, application):
    add_clips(window, tmp_path)
    second = tmp_path / "captures" / "second.mp4"
    second.write_bytes(b"test")
    window.catalogue.ingest(
        window.catalogue.folders()[0]["folder_id"],
        [{"path": str(second), "game": None}],
    )
    clips = window.catalogue.clips()
    for index, clip in enumerate(clips):
        window.media_info[clip["source_path"]] = {"created": f"2026-09-{index + 1:02}T12:00:00Z"}
    window.catalogue.patch(clips[-1]["clip_id"], {"triage": "keep"})
    window.panel("Home")
    application.processEvents()
    assert window.library.count() == 2
    window.nav["Browse"].click()
    newest = clips[-1]["clip_id"]
    assert wait_for(application, lambda: window.current_panel == "Browse")
    assert window.browse_id == newest
    assert window.browse_selected_id is None
    assert window.library.count() == 2
    window.panel("Home")
    window.media_info[clips[0]["source_path"]] = {"created": "2026-09-30T12:00:00Z"}
    window.panel("Browse")
    newest = clips[0]["clip_id"]
    assert window.browse_id == newest
    window.toggle_browse_sort()
    window.library.setCurrentRow(0)
    assert window.browse_id != newest
    selected = window.browse_id
    window.panel("Home")
    window.panel("Browse")
    assert window.browse_id == selected
    assert window.browse.clip["clip_id"] == selected
    assert window.browse_newest
    assert window.library.visualItemRect(window.library.currentItem()).intersects(
        window.library.viewport().rect()
    )
    # A fresh window has no remembered manual selection.
    restarted = Window(tmp_path)
    try:
        restarted.media_info = window.media_info.copy()
        restarted.panel("Browse")
        assert restarted.browse_id == newest
    finally:
        restarted.close()
    Path(window.catalogue.clip(selected)["source_path"]).unlink()
    with window.catalogue.connection() as database:
        database.execute("INSERT INTO deleted_sources VALUES (?)", (selected,))
    window.panel("Home")
    window.panel("Browse")
    assert window.browse_id == newest


def test_inactive_players_reuse_prepared_clips(window, tmp_path, monkeypatch):
    ids = add_clips(window, tmp_path)
    window.preload_timer.stop()
    loads = {"Browse": [], "Editing": []}

    for panel, player in (("Browse", window.browse.player), ("Editing", window.player)):
        def fake_load(clip, *, panel=panel, player=player):
            loads[panel].append(clip["clip_id"] if clip else None)
            player.loaded_clip = clip
            player.awaiting_frame = False

        monkeypatch.setattr(player, "load", fake_load)

    window.prepare_inactive_clips()
    assert loads == {"Browse": [ids[0]], "Editing": [ids[0]]}
    window.panel("Browse")
    assert loads["Browse"] == [ids[0]]
    window.panel("Editing")
    assert loads["Editing"] == [ids[0]]


def test_preload_tracks_changed_browse_and_session_targets(window, tmp_path, monkeypatch):
    ids = add_clips(window, tmp_path)
    window.preload_timer.stop()
    loads = {"Browse": [], "Editing": []}
    for panel, player in (("Browse", window.browse.player), ("Editing", window.player)):
        def fake_load(clip, *, panel=panel, player=player):
            loads[panel].append(clip["clip_id"] if clip else None)
            player.loaded_clip = clip
            player.awaiting_frame = False

        monkeypatch.setattr(player, "load", fake_load)

    window.prepare_inactive_clips()
    second = tmp_path / "captures" / "second.mp4"
    second.write_bytes(b"test")
    folder_id = window.catalogue.folders()[0]["folder_id"]
    window.catalogue.ingest(folder_id, [{"path": str(second), "game": "VALORANT"}])
    second_id = next(
        clip["clip_id"] for clip in window.catalogue.clips()
        if clip["source_path"] == str(second)
    )
    window.media_info[str(second)] = {"created": "2099-01-01T00:00:00Z"}
    window.catalogue.create_session([second_id], replace=True)
    window.prepare_inactive_clips()
    assert loads == {"Browse": [ids[0], second_id], "Editing": [ids[0], second_id]}
    window.panel("Browse")
    assert window.browse_id == second_id
    assert loads["Browse"] == [ids[0], second_id]
    window.panel("Home")
    second.unlink()
    window.prepare_inactive_clips()
    assert loads["Browse"][-1] == ids[0]
    assert loads["Editing"][-1] == second_id
    window.panel("Browse")
    assert window.browse_id == ids[0]


def test_prepared_video_frame_survives_tab_entry(window, application, tmp_path):
    add_clips(window, tmp_path, valid=True)
    window.preload_timer.stop()
    window.prepare_inactive_clips()
    browse = window.browse.player
    editing = window.player
    assert wait_for(
        application,
        lambda: all(
            player.media.mediaStatus() == QMediaPlayer.MediaStatus.LoadedMedia
            and not player.awaiting_frame
            for player in (browse, editing)
        ),
    )
    generations = (browse.media.generation, editing.media.generation)
    window.panel("Browse")
    assert window.transition_cover.isHidden()
    application.processEvents()
    assert browse.media.generation == generations[0]
    assert not window.transition_pending
    assert not window.page_needs_cover("Editing")
    window.panel("Editing")
    assert window.transition_cover.isHidden()
    application.processEvents()
    assert editing.media.generation == generations[1]
    assert not window.transition_pending


def test_prepared_video_first_show_uses_final_size(window, application, tmp_path):
    add_clips(window, tmp_path, valid=True)
    window.preload_timer.stop()
    window.prepare_inactive_clips()
    players = {"Browse": window.browse.player, "Editing": window.player}
    assert wait_for(application, lambda: all(not player.awaiting_frame for player in players.values()))

    class ShowGeometry(QObject):
        def __init__(self):
            super().__init__()
            self.sizes = []

        def eventFilter(self, watched, event):
            if event.type() == QEvent.Type.Show:
                self.sizes.append(watched.size())
            return False

    for panel in ("Browse", "Editing", "Session", "Browse"):
        if panel == "Session":
            window.panel(panel)
            continue
        player = players[panel]
        assert wait_for(application, lambda: not window.page_needs_cover(panel))
        observer = ShowGeometry()
        player.video.installEventFilter(observer)
        try:
            window.panel(panel)
            application.processEvents()
            assert observer.sizes, panel
            QTest.qWait(50)
            assert observer.sizes[0] == player.video.size()
        finally:
            player.video.removeEventFilter(observer)


def test_prepared_video_warms_behind_frame_before_reveal(window, application, tmp_path):
    add_clips(window, tmp_path, valid=True)
    window.preload_timer.stop()
    window.prepare_inactive_clips()
    players = {"Browse": window.browse.player, "Editing": window.player}
    assert wait_for(application, lambda: all(not player.awaiting_frame for player in players.values()))

    for panel in ("Browse", "Editing"):
        player = players[panel]
        generation = player.media.generation
        window.panel(panel)
        application.processEvents()
        assert player.media.generation == generation
        assert window.transition_cover.isHidden()
        assert player.video_container.prepared_frame.isVisible()
        assert not player.video_container.prepared_frame.pixmap().isNull()
        assert not player.video.mask().isEmpty()
        assert wait_for(application, lambda: player.video.mask().isEmpty())
        assert not player.video_container.prepared_frame.isVisible()
        assert player.warmed_video_geometry == (
            player.video.size(), player.video.devicePixelRatioF()
        )


def test_hdr_preloaded_browse_reveals_live_surface(window, application, tmp_path):
    clip_id = add_clips(window, tmp_path, valid=True)[0]
    clip = window.catalogue.clip(clip_id)
    window.media_info[clip["source_path"]] = {"hdr": 1}
    window.preload_timer.stop()
    window.prepare_inactive_clips()
    player = window.browse.player
    assert wait_for(application, lambda: not player.awaiting_frame)

    window.panel("Browse")
    assert wait_for(application, lambda: player.video.isVisible() and player.video.mask().isEmpty())
    assert player.video_container.prepared_frame.isHidden()
    assert window.transition_cover.isHidden()


def test_prepared_video_reveal_is_cancelled_on_page_change(window, application, tmp_path):
    add_clips(window, tmp_path, valid=True)
    window.preload_timer.stop()
    window.prepare_inactive_clips()
    player = window.browse.player
    assert wait_for(application, lambda: not player.awaiting_frame)

    window.panel("Browse")
    application.processEvents()
    assert player.video_container.prepared_frame.isVisible()
    window.panel("Browse")
    assert player.video_container.prepared_frame.isVisible()
    assert not player.video.mask().isEmpty()
    window.panel("Session")
    assert not player.video_container.prepared_frame.isVisible()
    QTest.qWait(150)
    assert window.current_panel == "Session"
    assert not player.video.isVisible()


def test_prepared_video_reveal_is_cancelled_on_clip_change(window, application, tmp_path):
    add_clips(window, tmp_path, valid=True)
    window.preload_timer.stop()
    window.prepare_inactive_clips()
    player = window.browse.player
    assert wait_for(application, lambda: not player.awaiting_frame)

    window.panel("Browse")
    application.processEvents()
    previous_generation = player.media.generation
    reveal_generation = window.prepared_reveal_generation
    attempt = window.prepared_reveal_attempt
    geometry = (player.video.size(), player.video.devicePixelRatioF())
    player.load(player.loaded_clip)
    assert player.media.generation != previous_generation
    assert window.transition_pending
    assert player.video_container.prepared_frame.isHidden()
    window.finish_ready_video(
        "Browse", player, previous_generation, reveal_generation, attempt, geometry
    )
    assert window.transition_pending
    assert wait_for(application, lambda: not player.awaiting_frame)


def test_prepared_video_rewarms_after_layout_resize(window, application, tmp_path):
    add_clips(window, tmp_path, valid=True)
    window.preload_timer.stop()
    window.prepare_inactive_clips()
    player = window.browse.player
    assert wait_for(application, lambda: not player.awaiting_frame)

    window.panel("Browse")
    application.processEvents()
    first_size = player.video.size()
    window.resize(window.width() + 150, window.height() + 80)
    application.processEvents()
    assert player.video.size() != first_size
    assert player.video_container.prepared_frame.isVisible()
    assert wait_for(application, lambda: player.video.mask().isEmpty())
    assert player.warmed_video_geometry == (
        player.video.size(), player.video.devicePixelRatioF()
    )


def test_empty_browse_entry_does_not_warm_video(window, application):
    window.panel("Browse")
    application.processEvents()
    assert window.transition_cover.isHidden()
    assert window.browse.player.video_container.prepared_frame.isHidden()
    assert window.browse.player.video.mask().isEmpty()


def test_library_filter_menus_and_unavailable_persistence(window, tmp_path, application):
    captures = tmp_path / "filter-captures"
    captures.mkdir()
    available = captures / "available.mp4"
    available.write_bytes(b"test")
    missing = captures / "missing.mp4"
    folder_id = window.catalogue.add_folder(captures)
    window.catalogue.ingest(
        folder_id,
        [
            {"path": str(available), "game": "VALORANT"},
            {"path": str(missing), "game": None},
        ],
    )
    ids = [clip["clip_id"] for clip in window.catalogue.clips()]
    window.catalogue.patch(ids[0], {"triage": "discard"})
    window.refresh_references()
    window.panel("Home")

    assert window.clip_filter.text() == "Clips: pending, keep"
    assert window.game_filter.text() == f"Games ({len(window.registry.games) + 1})"
    assert window.project_filter.text() == "Projects (0)"
    assert window.clip_filter.selected_values() == {None, "keep"}
    assert window.game_filter.all_selected()
    assert window.project_filter.all_selected()
    assert [action.text() for action in window.project_filter.menu().actions()] == [
        "All clips",
        "",
        "No projects",
    ]
    assert window.library.count() == 0

    for action in window.clip_filter.menu().actions():
        if action.text() == "Discard":
            action.trigger()
            break
    assert window.clip_filter.text() == "Clips: all"
    assert window.library.count() == 1
    window.unavailable_toggle.click()
    assert window.settings["show_unavailable_clips"] is True
    assert window.library.count() == 2
    assert window.library.currentItem() is window.library.item(0)
    assert window.library.selectedItems() == [window.library.item(0)]

    restarted = Window(tmp_path)
    try:
        restarted.show()
        application.processEvents()
        assert restarted.unavailable_toggle.isChecked()
        assert restarted.unavailable_toggle.property("iconName") == "eye"
    finally:
        restarted.close()


@pytest.mark.parametrize("panel", ["Home", "Browse", "Session"])
def test_project_filter_all_clips_is_separate_from_all_named_projects(window, tmp_path, panel):
    captures = tmp_path / "project-filter-captures"
    captures.mkdir()
    paths = [captures / f"clip-{number}.mp4" for number in range(3)]
    for path in paths:
        path.write_bytes(b"test")
    folder_id = window.catalogue.add_folder(captures)
    window.catalogue.ingest(folder_id, [{"path": str(path), "game": None} for path in paths])
    ids = [clip["clip_id"] for clip in window.catalogue.clips()]
    first = window.catalogue.save_project("First")
    second = window.catalogue.save_project("Second")
    window.catalogue.batch_membership(first, [ids[0]], True)
    window.catalogue.batch_membership(second, [ids[1]], True)
    window.refresh_references()
    control = window.project_filter

    def actions():
        return {action.text(): action for action in control.menu().actions() if action.text()}

    def visible_ids():
        return {clip["clip_id"] for clip in window.filtered_clips(window.catalogue.clips(), panel)}

    assert actions()["All clips"].isChecked()
    assert not actions()["First"].isChecked()
    assert not actions()["Second"].isChecked()
    assert visible_ids() == set(ids)
    actions()["All clips"].trigger()
    assert control.all_selected()
    actions()["First"].trigger()
    assert not actions()["All clips"].isChecked()
    assert visible_ids() == {ids[0]}
    actions()["Second"].trigger()
    assert not control.all_selected()
    assert control.selected_values() == {first, second}
    assert visible_ids() == set(ids[:2])
    actions()["First"].trigger()
    assert visible_ids() == {ids[1]}
    actions()["Second"].trigger()
    assert actions()["All clips"].isChecked()
    assert visible_ids() == set(ids)
    control.set_selected_values({first, second})
    assert not control.all_selected()
    assert visible_ids() == set(ids[:2])
    actions()["All clips"].trigger()
    assert not actions()["First"].isChecked()
    assert not actions()["Second"].isChecked()
    assert visible_ids() == set(ids)
    control.set_selected_values({first})
    control.set_options([("Second", second)])
    assert control.all_selected()
    assert actions()["All clips"].isChecked()
    assert visible_ids() == set(ids)


def test_filter_button_labels_follow_selected_options(window, application):
    window.panel("Home")
    window.clip_filter.set_selected_values({None})
    assert window.clip_filter.text() == "Clips: pending"
    narrow_width = window.clip_filter.sizeHint().width()
    window.clip_filter.set_selected_values({None, "discard"})
    assert window.clip_filter.text() == "Clips: pending, discard"
    application.processEvents()
    assert window.clip_filter.sizeHint().width() > narrow_width
    assert window.clip_filter.width() >= window.clip_filter.sizeHint().width()
    window.clip_filter.set_selected_values(set())
    assert window.clip_filter.text() == "Clips: none"

    window.game_filter.set_selected_values({""})
    assert window.game_filter.text() == "Games (1)"
    window.game_filter.set_selected_values(set())
    assert window.game_filter.text() == "Games (0)"

    first_project = window.catalogue.save_project("First")
    second_project = window.catalogue.save_project("Second")
    window.refresh_references()
    assert window.project_filter.text() == "Projects (2)"
    window.project_filter.set_selected_values({first_project})
    assert window.project_filter.text() == "Projects (1)"
    window.panel("Browse")
    application.processEvents()
    assert window.project_filter.text() == "Projects (1)"
    assert window.project_filter.selected_values() == {first_project}
    assert second_project not in window.project_filter.selected_values()


@pytest.mark.parametrize("remaining", [False, True])
def test_browse_delete_confirmation(window, application, tmp_path, monkeypatch, remaining):
    from PySide6.QtWidgets import QMessageBox

    add_clips(window, tmp_path)
    if remaining:
        second = tmp_path / "second"
        second.mkdir()
        second_source = second / "second.mp4"
        second_source.write_bytes(b"video")
        folder = window.catalogue.add_folder(second)
        window.catalogue.ingest(folder, [{"path": str(second_source), "game": None}])
    window.panel("Browse")
    source = Path(window.browse.clip["source_path"])
    deleted_id = window.browse_id
    count = window.library.count()
    before = catalogue_dump(window)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Cancel)
    window.browse.delete_button.click()
    assert source.exists()
    assert catalogue_dump(window) == before
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Yes)
    window.browse.delete_button.click()
    assert wait_for(application, lambda: window.worker is None)
    assert not source.exists()
    assert [
        line
        for line in catalogue_dump(window)
        if not line.startswith('INSERT INTO "deleted_sources"')
    ] == before
    assert window.library.count() == count - 1
    assert deleted_id not in {
        window.library.item(index).data(Qt.ItemDataRole.UserRole)
        for index in range(window.library.count())
    }
    assert window.browse_id != deleted_id
    if remaining:
        assert window.browse.clip["clip_id"] == window.browse_id
    else:
        assert window.browse.clip is None
        assert window.browse_id is None
        assert not window.browse.delete_button.isEnabled()
    window.panel("Home")
    window.catalogue = Catalogue(window.catalogue.path)
    window.panel("Browse")
    assert window.library.count() == count - 1
    restarted = Window(tmp_path)
    restarted.show()
    try:
        application.processEvents()
        assert wait_for(application, lambda: restarted.worker is None)
        restarted.panel("Browse")
        assert restarted.library.count() == count - 1
        assert restarted.browse_id != deleted_id
    finally:
        restarted.close()
    source.write_bytes(b"restored")
    window.refresh_library()
    assert window.library.count() == count


def test_auto_scan_discovers_without_modal_or_selection_reset(window, application, tmp_path):
    ids = add_clips(window, tmp_path)
    folder = window.catalogue.folders()[0]
    sources = []
    for index in range(25):
        path = tmp_path / "captures" / f"existing-{index}.mp4"
        path.write_bytes(b"video")
        sources.append({"path": str(path), "game": None})
    window.catalogue.ingest(folder["folder_id"], sources)
    window.panel("Browse")
    application.processEvents()
    window.library.setCurrentRow(15)
    window.library.scrollToItem(window.library.currentItem())
    anchor = window.library.itemAt(1, 1)
    anchor_id = anchor.data(Qt.ItemDataRole.UserRole)
    anchor_offset = window.library.visualItemRect(anchor).top()
    selected_id = window.browse_id
    window.browse.custom_title.setText("Keep draft")
    original_clip = window.browse.clip
    new_source = tmp_path / "captures" / "new.mp4"
    new_source.write_bytes(b"new video")
    assert window.scan_timer.interval() == 30_000
    assert window.scan_timer.isActive()
    window.statusBar().clearMessage()
    window.scan_timer.timeout.emit()
    assert window.scan_retry_timer.isActive()
    assert wait_for(application, lambda: window.worker is None and window.library.count() == 27)
    assert QApplication.activeModalWidget() is None
    assert window.statusBar().currentMessage() == ""
    assert window.browse_id == selected_id
    anchor = window.library.itemAt(1, 1)
    assert anchor.data(Qt.ItemDataRole.UserRole) == anchor_id
    assert window.library.visualItemRect(anchor).top() == anchor_offset
    assert window.browse.clip is original_clip
    assert window.browse.custom_title.text() == "Keep draft"
    assert window.catalogue.state("session")["ids"] == ids


def test_auto_scan_defers_busy_and_modal_and_runs_on_focus(window, application, monkeypatch):
    calls = []
    monkeypatch.setattr(window, "rescan", lambda **kwargs: calls.append(kwargs))
    window.worker = object()
    window.auto_scan()
    assert not calls
    assert window.scan_retry_timer.isActive()
    window.worker = None
    monkeypatch.setattr(QApplication, "activeModalWidget", lambda: window)
    window.auto_scan()
    assert not calls
    monkeypatch.setattr(QApplication, "activeModalWidget", lambda: None)
    window.scan_retry_timer.stop()
    window.eventFilter(application, QEvent(QEvent.Type.ApplicationActivate))
    assert window.scan_retry_timer.isActive()
    assert wait_for(application, lambda: bool(calls))
    assert calls == [{"quiet": True}]


def test_browse_form_alignment_and_title_style(window, application):
    window.panel("Browse")
    application.processEvents()
    browse = window.browse
    for width in (1100, 1600):
        window.resize(width, 900)
        application.processEvents()
        title_left = browse.custom_title.mapTo(browse, QPoint(0, 0)).x()
        title_right = title_left + browse.custom_title.width()
        mode_right = browse.mode.mapTo(browse, QPoint(0, 0)).x() + browse.mode.width()
        assert title_right == mode_right
        assert browse.custom_title.width() > browse.destination.width() == 480
        assert browse.working_title.font() == window.working_title.font()
        browse.mode.setCurrentIndex(1)
        option = QStyleOptionComboBox()
        browse.mode.initStyleOption(option)
        text_rect = browse.mode.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox,
            option,
            QStyle.SubControl.SC_ComboBoxEditField,
            browse.mode,
        )
        assert text_rect.width() >= browse.mode.fontMetrics().horizontalAdvance("Selected range")


def test_browse_fullscreen_clip_and_volume_keys(window, application, tmp_path):
    captures = tmp_path / "captures"
    captures.mkdir()
    paths = [captures / f"clip-{index}.mp4" for index in range(3)]
    for path in paths:
        path.write_bytes(b"video")
    folder = window.catalogue.add_folder(captures)
    window.catalogue.ingest(folder, [{"path": str(path), "game": None} for path in paths])
    window.panel("Browse")
    window.library.setCurrentRow(1)
    player = window.browse.player

    QTest.keyClick(player, Qt.Key.Key_Up)
    assert window.library.currentRow() == 0
    window.library.setCurrentRow(1)
    window.browse.set_fullscreen(True)
    assert window.isFullScreen()

    QTest.keyClick(player, Qt.Key.Key_BracketLeft)
    assert window.library.currentRow() == 0
    QTest.keyClick(player, Qt.Key.Key_BracketLeft)
    assert window.library.currentRow() == 0
    QTest.keyClick(player, Qt.Key.Key_BracketRight)
    assert window.library.currentRow() == 1

    player.volume.setValue(60)
    QTest.keyClick(player, Qt.Key.Key_Up)
    assert window.library.currentRow() == 1
    assert player.volume.value() == 65
    assert window.player.volume.value() == 65
    QTest.keyClick(player, Qt.Key.Key_Down)
    assert player.volume.value() == 60
    player.volume.setValue(92)
    QTest.keyClick(player, Qt.Key.Key_Up)
    assert player.volume.value() == 95
    player.volume.setValue(92)
    QTest.keyClick(player, Qt.Key.Key_Down)
    assert player.volume.value() == 90
    window.browse.set_fullscreen(False)
    QTest.keyClick(player, Qt.Key.Key_BracketRight)
    assert window.library.currentRow() == 1


def test_browse_fullscreen_frame_step_keys(window, application, tmp_path, monkeypatch):
    add_clips(window, tmp_path, valid=True)
    window.panel("Browse")
    player = window.browse.player
    assert wait_for(application, lambda: player.media.duration() > 0 and not player.awaiting_frame)
    calls = []
    monkeypatch.setattr(player.media, "stepFrame", calls.append)

    QTest.keyClick(player, Qt.Key.Key_Period)
    assert calls == []
    window.browse.set_fullscreen(True)
    player.media.pause()
    QTest.keyClick(player, Qt.Key.Key_Period)
    QTest.keyClick(player, Qt.Key.Key_Comma)
    repeat = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Period,
                       Qt.KeyboardModifier.NoModifier, ".", True)
    QCoreApplication.sendEvent(player, repeat)
    assert calls == [True, False, True]
    assert player.media.playbackState() == QMediaPlayer.PlaybackState.PausedState

    player.media.play()
    QTest.keyClick(player, Qt.Key.Key_Period)
    assert calls == [True, False, True, True]
    window.browse.set_fullscreen(False)
    QTest.keyClick(player, Qt.Key.Key_Comma)
    assert calls == [True, False, True, True]


def test_browse_fullscreen_chrome_and_share_flow(window, application, tmp_path):
    original_cursor_position = QCursor.pos()
    add_clips(window, tmp_path, valid=True)
    window.panel("Browse")
    application.processEvents()
    browse = window.browse
    player = browse.player
    assert wait_for(application, lambda: player.media.duration() > 0 and not player.awaiting_frame)
    normal_seek_parent = player.seek.parent()
    normal_bar_parent = player.control_bar.parent()

    browse.set_fullscreen(True)
    application.processEvents()
    assert player.chrome_enabled
    assert player.chrome_title.text() == browse.fullscreen_title()
    assert COLORS["player_chrome_muted"] in player.chrome_title.text()
    assert player.seek.parent() is player.chrome_bottom.content
    assert player.control_bar.parent() is player.chrome_bottom.content
    assert player.seek.isVisible() and player.control_bar.isVisible()
    assert player.chrome_top.isVisible() and player.chrome_bottom.isVisible()
    assert player.chrome_timer.interval() == 1700
    assert not player.chrome_top.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert not player.chrome_bottom.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert player.chrome_top.updatesEnabled() and player.chrome_bottom.updatesEnabled()
    assert player.chrome_top.y() == 0
    assert player.chrome_bottom.height() >= 60
    assert player.chrome_bottom.geometry().bottom() == player.video_container.height() - 1
    QCoreApplication.sendEvent(application, QEvent(QEvent.Type.ApplicationDeactivate))
    assert not player.chrome_top.isVisible() and not player.chrome_bottom.isVisible()
    QCoreApplication.sendEvent(application, QEvent(QEvent.Type.ApplicationActivate))
    assert player.chrome_top.isVisible() and player.chrome_bottom.isVisible()
    assert player.chrome_top.animation.duration() == 60
    assert player.chrome_bottom.animation.duration() == 60
    assert player.previous_button.x() < player.play.x() < player.next_button.x()
    assert browse.fullscreen_share_button.isVisible()

    player.media.play()
    assert wait_for(application, lambda: player.media.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
    QTest.qWait(100)
    player.cursor_timer.stop()
    player.chrome_timer.setInterval(80)
    player.chrome_timer.start()
    assert wait_for(
        application,
        lambda: not player.chrome_top.isVisible() and not player.chrome_bottom.isVisible(),
        timeout=1,
    )
    assert player.chrome_top.animation.duration() == 180
    assert player.chrome_bottom.animation.duration() == 180
    player.chrome_timer.setInterval(1700)
    player.last_cursor_position = QCursor.pos()
    target = player.video.mapToGlobal(QPoint(100, 100))
    if target == player.last_cursor_position:
        target = player.video.mapToGlobal(QPoint(120, 100))
    QCursor.setPos(target)
    player.check_cursor_motion()
    assert player.chrome_top.isVisible() and player.chrome_bottom.isVisible()
    assert player.chrome_top.animation.duration() == 60
    assert player.chrome_bottom.animation.duration() == 60
    assert wait_for(application, lambda: player.chrome_top.effect.opacity() > 0.95, timeout=1)
    assert player.chrome_top.content.grab().toImage().pixelColor(24, 8).alpha() > 0
    player.media.pause()
    application.processEvents()
    assert player.chrome_timer.isActive()
    player.chrome_timer.setInterval(80)
    player.chrome_timer.start()
    assert wait_for(
        application,
        lambda: not player.chrome_top.isVisible() and not player.chrome_bottom.isVisible(),
        timeout=1,
    )
    QTest.mouseClick(player.video_container, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    player.chrome_timer.setInterval(1700)
    assert wait_for(
        application,
        lambda: player.media.playbackState() == QMediaPlayer.PlaybackState.PlayingState,
    )
    assert player.fullscreen_feedback.isVisible()
    assert player.fullscreen_feedback.icon_name == "play"
    feedback_image = player.fullscreen_feedback.grab().toImage()
    assert QColor(feedback_image.pixelColor(0, 0)).alpha() == 0
    assert QColor(feedback_image.pixelColor(20, 56)).alpha() > 0
    assert player.chrome_top.isVisible() and player.chrome_bottom.isVisible()
    assert wait_for(application, lambda: not player.fullscreen_feedback.isVisible(), timeout=2)
    QTest.mouseClick(player.video, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    assert wait_for(
        application,
        lambda: player.media.playbackState() == QMediaPlayer.PlaybackState.PausedState,
    )
    assert player.fullscreen_feedback.icon_name == "pause"
    QTest.keyClick(player, Qt.Key.Key_Up)
    assert player.fullscreen_feedback.icon_name == "volume-2"
    readout = player.fullscreen_volume_readout
    assert readout.isVisible()
    assert player.fullscreen_feedback.timer.interval() == 330
    assert readout.timer.interval() == 330
    assert player.fullscreen_feedback.animation.duration() == 150
    assert readout.animation.duration() == 150
    assert readout.text == f"{player.volume.value()}%"
    assert abs(readout.geometry().center().x() - player.video_container.mapToGlobal(
        player.video_container.rect().center()
    ).x()) <= 1
    assert abs(readout.geometry().center().y() - (
        player.video_container.mapToGlobal(player.video_container.rect().topLeft()).y()
        + player.video_container.height() // 5
    )) <= 1
    readout_image = readout.grab().toImage()
    assert readout.width() == readout.height()
    assert 0 < readout_image.pixelColor(0, 0).alpha() < 100
    assert wait_for(application, lambda: not readout.isVisible(), timeout=2)
    player.chrome_timer.setInterval(80)
    player.chrome_timer.start()
    assert wait_for(
        application,
        lambda: not player.chrome_top.isVisible() and not player.chrome_bottom.isVisible(),
        timeout=1,
    )
    QTest.keyClick(player, Qt.Key.Key_Down)
    assert player.fullscreen_feedback.icon_name == "volume-1"
    assert readout.text == f"{player.volume.value()}%"
    assert not player.chrome_top.isVisible() and not player.chrome_bottom.isVisible()
    QTest.keyClick(player, Qt.Key.Key_Left)
    assert player.chrome_top.isVisible() and player.chrome_bottom.isVisible()
    assert player.chrome_top.animation.duration() == 60
    assert player.chrome_bottom.animation.duration() == 60
    assert player.fullscreen_feedback.icon_name == "rewind"
    QTest.keyClick(player, Qt.Key.Key_Right)
    assert player.fullscreen_feedback.icon_name == "fast-forward"
    player.chrome_timer.setInterval(1700)
    QTest.keyClick(player, Qt.Key.Key_Space)
    assert wait_for(
        application,
        lambda: player.media.playbackState() == QMediaPlayer.PlaybackState.PlayingState,
    )
    assert player.fullscreen_feedback.icon_name == "play"
    QTest.mouseClick(player.mute, Qt.MouseButton.LeftButton)
    assert player.media.playbackState() == QMediaPlayer.PlaybackState.PlayingState
    window.set_theme("dark", persist=False)
    application.processEvents()
    assert player.chrome_title.text() == browse.fullscreen_title()
    assert player.chrome_top.isVisible() and player.chrome_bottom.isVisible()

    browse.fullscreen_share_button.click()
    application.processEvents()
    assert not window.isFullScreen()
    assert browse.custom_title.hasFocus()
    assert player.seek.parent() is normal_seek_parent
    assert player.control_bar.parent() is normal_bar_parent
    QCursor.setPos(original_cursor_position)


@pytest.mark.parametrize("maximized", [False, True])
def test_browse_fullscreen_restores_player_and_window(window, application, tmp_path, maximized):
    add_clips(window, tmp_path, valid=True)
    if maximized:
        window.showMaximized()
        application.processEvents()
    window.panel("Browse")
    application.processEvents()
    browse = window.browse
    player = browse.player
    assert wait_for(application, lambda: player.media.duration() > 0 and not player.awaiting_frame)
    surface_id = int(player.video.winId())
    clip_id = browse.clip["clip_id"]
    browse.custom_title.setText("Share draft")
    browse.in_ms, browse.out_ms = 100, 200
    sizes = window.splitter.sizes()
    geometry = window.geometry()
    playback_state = player.media.playbackState()
    position = player.media.position()
    browse.fullscreen_button.click()
    assert window.updatesEnabled()
    assert not browse.fullscreen_transition_cover.isVisible()
    assert window.isFullScreen()
    assert window.navigation_strip.isHidden() and window.left.isHidden()
    assert browse.details.isHidden() and window.statusBar().isHidden()
    assert player.isVisible() and browse.fullscreen_button.isVisible()
    assert int(player.video.winId()) == surface_id
    assert player.media.playbackState() == playback_state
    assert player.media.position() == position
    QTest.keyClick(player, Qt.Key.Key_Escape)
    assert window.updatesEnabled()
    assert not browse.fullscreen_transition_cover.isVisible()
    restored_layout = (window.geometry(), window.splitter.sizes(), player.geometry())
    application.processEvents()
    assert (window.geometry(), window.splitter.sizes(), player.geometry()) == restored_layout
    assert not window.isFullScreen()
    assert window.isMaximized() == maximized
    assert window.geometry() == geometry
    assert window.splitter.sizes() == sizes
    assert player.video.geometry().bottomRight().x() <= player.video_container.width()
    assert player.video.geometry().bottomRight().y() <= player.video_container.height()
    assert window.navigation_strip.isVisible() and window.left.isVisible()
    assert browse.details.isVisible()
    assert browse.custom_title.text() == "Share draft"
    assert (browse.in_ms, browse.out_ms) == (100, 200)
    assert browse.clip["clip_id"] == clip_id
    QTest.keyClick(player, Qt.Key.Key_F11)
    assert window.isFullScreen()
    QTest.keyClick(player, Qt.Key.Key_F)
    assert not window.isFullScreen()
    browse.fullscreen_button.click()
    application.processEvents()
    assert window.isFullScreen() and window.updatesEnabled()
    QTest.keyClick(player, Qt.Key.Key_Escape)
    application.processEvents()
    browse.custom_title.setFocus()
    QTest.keyClicks(browse.custom_title, "f")
    assert browse.custom_title.text().endswith("f")
    assert not window.isFullScreen()
    browse.fullscreen_button.click()
    window.panel("Home")
    assert not window.isFullScreen()
    assert browse.fullscreen_state is None
    for panel in ["Editing", "Export"]:
        window.panel(panel)
        QTest.keyClick(window.active_player(), Qt.Key.Key_F11)
        assert not window.isFullScreen()
