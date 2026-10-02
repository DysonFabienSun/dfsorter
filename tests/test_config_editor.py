import shutil
from pathlib import Path

import PySide6
import pytest
from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QApplication, QComboBox, QInputDialog, QMessageBox

from dfsorter.config import Registry
from dfsorter.config_editor import GAME_SUMMARY_ROLE, Rows
from dfsorter.config_store import GameFile
from dfsorter.parsing import parse_command
from dfsorter.ui import ROOT, Window, style_application


def test_round_trip_save_preserves_comments_extras_and_reloads(tmp_path):
    target = tmp_path / "Example.yaml"
    target.write_text(
        "# Editorial note\nname: Example\ncode: EXM\ncustom_key: retained\n"
        "fields:\n  kill: {}\n  weapon:\n    type: enum\n    values: [Pistol]\n    custom_field: retained\n"
        "display_order: [kill, weapon, mainline]\n",
        encoding="utf-8",
    )
    source = GameFile(target)
    draft = source.draft()
    draft["fields"]["weapon"]["values"].append("Rifle")
    source.save(draft, tmp_path)
    saved = target.read_text(encoding="utf-8")
    assert "# Editorial note" in saved
    assert "custom_key: retained" in saved
    assert "custom_field: retained" in saved
    assert "Rifle" in Registry(tmp_path).game("Example").fields["weapon"]["values"]


def test_external_change_blocks_save(tmp_path):
    target = tmp_path / "Example.yaml"
    target.write_text(
        "name: Example\ncode: EXM\nfields: {kill: {}}\ndisplay_order: [kill, mainline]\n",
        encoding="utf-8",
    )
    source = GameFile(target)
    target.write_text(target.read_text(encoding="utf-8") + "# external edit\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed outside"):
        source.save(source.draft(), tmp_path)
    assert "# external edit" in target.read_text(encoding="utf-8")


@pytest.fixture
def editor_window(tmp_path, close_window):
    QCoreApplication.addLibraryPath(str(Path(PySide6.__file__).parent / "plugins"))
    application = QApplication.instance() or QApplication([])
    style_application(application)
    shutil.copytree(ROOT / "configs/shipped", tmp_path / "configs/games")
    shutil.copytree(ROOT / "configs/tips", tmp_path / "configs/tips")
    window = Window(tmp_path)
    window.show()
    application.processEvents()
    yield window
    window.config_editor.dirty = False
    close_window(window, application)


def test_table_add_row_starts_typing_and_tab_edits_next_cell(editor_window):
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QLineEdit, QPushButton

    application = QApplication.instance()
    rows = Rows(["Alias", "Canonical value"], lambda: None)
    rows.show()
    rows.activateWindow()
    application.processEvents()
    try:
        add = next(button for button in rows.findChildren(QPushButton) if button.text() == "Add row")
        QTest.mouseClick(add, Qt.MouseButton.LeftButton)
        assert isinstance(application.focusWidget(), QLineEdit)
        QTest.keyClicks(application.focusWidget(), "mp5navy")
        QTest.keyClick(application.focusWidget(), Qt.Key.Key_Tab)
        application.processEvents()
        assert isinstance(application.focusWidget(), QLineEdit)
        QTest.keyClicks(application.focusWidget(), "mp5")
        QTest.keyClick(application.focusWidget(), Qt.Key.Key_Return)
        application.processEvents()
        assert rows.values() == [["mp5navy", "mp5"], ["", ""]]
        rect = rows.table.visualItemRect(rows.table.item(0, 1))
        QTest.mouseClick(rows.table.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
        QTest.mouseDClick(rows.table.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
        application.processEvents()
        assert isinstance(application.focusWidget(), QLineEdit)
        QTest.keyClick(application.focusWidget(), Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClicks(application.focusWidget(), "mp5k")
        QTest.keyClick(application.focusWidget(), Qt.Key.Key_Return)
        application.processEvents()
        assert rows.values() == [["mp5navy", "mp5k"], ["", ""]]
    finally:
        rows.close()


@pytest.mark.parametrize("headings,column", [
    (["Value"], 0),
    (["Alias", "Canonical value"], 0),
    (["Alias", "Canonical value"], 1),
])
def test_enter_in_last_row_creates_next_row(editor_window, headings, column):
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QLineEdit

    application = QApplication.instance()
    rows = Rows(headings, lambda: None)
    rows.set_values([["first"] + [""] * (len(headings) - 1),
                     ["last"] + [""] * (len(headings) - 1)])
    rows.show()
    rows.activateWindow()
    application.processEvents()
    try:
        rows.table.setCurrentCell(0, 0)
        rows.table.editItem(rows.table.item(0, 0))
        application.processEvents()
        QTest.keyClick(application.focusWidget(), Qt.Key.Key_Return)
        application.processEvents()
        assert rows.table.rowCount() == 2

        rows.table.setCurrentCell(1, column)
        rows.table.editItem(rows.table.item(1, column))
        application.processEvents()
        QTest.keyClick(application.focusWidget(), Qt.Key.Key_Return)
        application.processEvents()
        assert rows.table.rowCount() == 3
        assert rows.table.currentRow() == 2
        assert rows.table.currentColumn() == 0
        assert isinstance(application.focusWidget(), QLineEdit)
        assert rows.values()[:2] == [["first"] + [""] * (len(headings) - 1),
                                     ["last"] + [""] * (len(headings) - 1)]
    finally:
        rows.close()


def test_enter_on_selected_last_row_creates_next_row(editor_window):
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QLineEdit

    application = QApplication.instance()
    rows = Rows(["Value"], lambda: None)
    rows.set_values([["existing"]])
    rows.show()
    rows.activateWindow()
    application.processEvents()
    try:
        rows.table.setCurrentCell(0, 0)
        rows.table.setFocus()
        QTest.keyClick(rows.table, Qt.Key.Key_Return)
        application.processEvents()
        assert rows.values() == [["existing"], [""]]
        assert isinstance(application.focusWidget(), QLineEdit)
    finally:
        rows.close()


def test_field_type_popup_shows_both_options_without_scrolling(editor_window):
    application = QApplication.instance()
    editor_window.panel("Config")
    combo = editor_window.config_editor.field_type
    closed_height = combo.height()
    combo.showPopup()
    application.processEvents()
    try:
        view = combo.view()
        assert view.sizeHintForRow(0) >= 20
        assert view.viewport().height() >= sum(view.sizeHintForRow(index) for index in range(combo.count()))
        assert not view.verticalScrollBar().isVisible()
        assert combo.height() == closed_height
    finally:
        combo.hidePopup()

    long_combo = QComboBox()
    long_combo.addItems([str(index) for index in range(20)])
    long_combo.show()
    long_combo.showPopup()
    application.processEvents()
    try:
        assert long_combo.view().verticalScrollBar().isVisible()
    finally:
        long_combo.hidePopup()
        long_combo.close()


def test_reserved_field_details_explain_syntax_and_remain_read_only(editor_window):
    editor_window.panel("Config")
    editor = editor_window.config_editor
    select_game(editor, "Counter-strike 2.yaml")
    editor.tabs.setCurrentIndex(1)

    for field, syntax in (("kill", "3K"), ("clutch", "1v4")):
        editor.fields.setCurrentRow(
            next(index for index in range(editor.fields.count())
                 if editor.fields.item(index).text() == field)
        )
        assert editor.reserved_note.isVisible()
        assert syntax in editor.reserved_note.text()
        assert not editor.field_type.isVisible()
        assert not editor.multiple.isVisible()
        assert not editor.prefixes.isVisible()
        assert not editor.values.isVisible()
        assert not editor.aliases.isVisible()
        assert not editor.links.isVisible()


def test_inference_link_note_has_no_blank_row_below_it(editor_window):
    application = QApplication.instance()
    editor_window.panel("Config")
    editor = editor_window.config_editor
    select_game(editor, "Counter-strike 2.yaml")
    editor.fields.setCurrentRow(
        next(index for index in range(editor.fields.count())
             if editor.fields.item(index).text() == "weapon")
    )
    editor.tabs.setCurrentIndex(1)
    application.processEvents()

    assert editor.links.hint.isVisible()
    assert editor.links.hint.height() == editor.links.hint.heightForWidth(editor.links.hint.width())
    assert editor.links.hint.geometry().bottom() == editor.links.height() - 1


def test_config_game_rows_have_nonoverlapping_vertical_space(editor_window):
    application = QApplication.instance()
    editor_window.panel("Config")
    games = editor_window.config_editor.games
    application.processEvents()
    assert games.count() >= 2
    first = games.visualItemRect(games.item(0))
    second = games.visualItemRect(games.item(1))
    assert first.height() >= games.fontMetrics().height() + 6
    assert second.top() >= first.bottom() + 1
    assert games.mapTo(editor_window.left, games.rect().topRight()).x() == editor_window.left.width() - 1
    assert games.mapTo(editor_window.left, games.rect().topLeft()).y() == (
        editor_window.config_editor.sidebar_header.geometry().bottom() + 1
    )


def test_config_game_navigator_shows_summary_and_invalid_files(editor_window):
    editor_window.panel("Config")
    editor = editor_window.config_editor
    apex = next(editor.games.item(index) for index in range(editor.games.count())
                if editor.games.item(index).data(Qt.ItemDataRole.UserRole) == "Apex Legends.yaml")
    assert apex.text() == "Apex Legends"
    assert apex.data(GAME_SUMMARY_ROLE) == "APX · 5 fields"

    invalid = editor.directory / "Invalid.yaml"
    invalid.write_text("name: [", encoding="utf-8")
    editor_window.reload_configs()
    editor.refresh_files(select="Invalid.yaml")
    broken = editor.games.currentItem()
    assert broken.text() == "Invalid"
    assert broken.data(GAME_SUMMARY_ROLE) == "Invalid configuration"
    assert not editor.tabs.isTabEnabled(0)


@pytest.mark.parametrize("existing", [False, True])
def test_table_empty_double_click_adds_editable_row(editor_window, existing):
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QLineEdit

    application = QApplication.instance()
    window = editor_window
    window.panel("Config")
    editor = window.config_editor
    editor.tabs.setCurrentIndex(0)
    rows = editor.game_aliases
    rows.set_values([["existing"]] if existing else [])
    editor.last_state = editor.history_state()
    editor.edit_history().undo_stack.clear()
    application.processEvents()
    blank = QPoint(10, rows.table.viewport().height() - 5)
    assert not rows.table.indexAt(blank).isValid()
    QTest.mouseClick(rows.table.viewport(), Qt.MouseButton.LeftButton, pos=blank)
    assert rows.table.rowCount() == int(existing)
    QTest.mouseDClick(rows.table.viewport(), Qt.MouseButton.LeftButton, pos=blank)
    application.processEvents()
    assert rows.table.rowCount() == int(existing) + 1
    assert rows.table.currentRow() == int(existing)
    assert rows.table.currentColumn() == 0
    assert isinstance(application.focusWidget(), QLineEdit)
    QTest.keyClicks(application.focusWidget(), "newalias")
    QTest.keyClick(application.focusWidget(), Qt.Key.Key_Return)
    application.processEvents()
    assert rows.values()[-2:] == [["newalias"], [""]]
    editor.undo()  # Enter-created row
    editor.undo()  # typing
    editor.undo()  # row creation
    assert rows.values() == ([["existing"]] if existing else [])


def test_table_selected_click_and_shared_selection(editor_window):
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QLineEdit, QPushButton

    application = QApplication.instance()
    window = editor_window
    window.panel("Config")
    editor = window.config_editor
    editor.load_game("Escape from Tarkov.yaml")
    editor.tabs.setCurrentIndex(1)
    editor.fields.setCurrentRow(next(
        index for index in range(editor.fields.count())
        if editor.fields.item(index).text() == "weapon"
    ))
    editor.aliases.set_values([["mp5navy", "mp5"]])
    editor.prefixes.set_values([["wpn"]])
    application.processEvents()

    def click(rows, column=0):
        rect = rows.table.visualItemRect(rows.table.item(0, column))
        QTest.mouseClick(rows.table.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
        application.processEvents()

    # Switching columns must highlight exactly the clicked cell, even in the same row.
    for column in (0, 1, 0):
        click(editor.aliases, column)
        assert editor.aliases.table.selectedItems() == [editor.aliases.table.item(0, column)]
        assert editor.aliases.table.currentColumn() == column
    click(editor.aliases)
    QTest.qWait(application.doubleClickInterval() + 50)
    assert isinstance(application.focusWidget(), QLineEdit)
    QTest.keyClick(application.focusWidget(), Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClicks(application.focusWidget(), "mp5k")

    # Crossing tables commits the active editor and removes both selection and current cell.
    click(editor.prefixes)
    assert editor.aliases.values() == [["mp5k", "mp5"]]
    assert not editor.aliases.table.selectedItems()
    assert editor.aliases.table.currentRow() == -1
    assert len(editor.prefixes.table.selectedItems()) == 1
    assert all(not rows.table.selectedItems() for rows in (editor.values, editor.links))

    editor.aliases.table.setFocus()
    QTest.keyClick(editor.aliases.table, Qt.Key.Key_Down)
    application.processEvents()
    assert len(editor.aliases.table.selectedItems()) == 1
    assert not editor.prefixes.table.selectedItems()

    QTest.mouseClick(editor.table_edit_hint, Qt.MouseButton.LeftButton)
    assert all(not rows.table.selectedItems() and rows.table.currentRow() == -1
               for rows in editor.findChildren(Rows))

    # Empty viewport space also deselects, while Remove row retains its target.
    click(editor.aliases)
    QTest.mouseClick(editor.aliases.table.viewport(), Qt.MouseButton.LeftButton,
                     pos=QPoint(10, editor.aliases.table.viewport().height() - 5))
    assert not editor.aliases.table.selectedItems()
    assert editor.aliases.table.currentRow() == -1
    click(editor.aliases)
    remove = next(button for button in editor.aliases.findChildren(QPushButton)
                  if button.text() == "Remove row")
    QTest.mouseClick(remove, Qt.MouseButton.LeftButton)
    assert editor.aliases.table.rowCount() == 0


def test_config_page_edits_game_and_refreshes_registry(editor_window):
    window = editor_window
    window.panel("Config")
    editor = window.config_editor
    assert editor.sidebar.isVisible()
    assert window.library.isHidden()
    for index in range(editor.games.count()):
        if editor.games.item(index).data(Qt.ItemDataRole.UserRole) == "VALORANT.yaml":
            editor.games.setCurrentRow(index)
            break
    editor.example.setText("jett vandal -- example")
    for index in range(editor.order.count()):
        if editor.order.item(index).text() == "weapon":
            editor.order.setCurrentRow(index)
            editor.move_order(-1)
            break
    for index in range(editor.suggested.count()):
        if editor.suggested.item(index).text() == "map":
            editor.suggested.item(index).setCheckState(Qt.CheckState.Checked)
            break
    assert editor.dirty and editor.save_button.isEnabled()
    assert editor.save(), editor.status.text()
    assert window.registry.game("VALORANT").command_example == "jett vandal -- example"
    assert window.registry.game("VALORANT").display_order.index("weapon") < window.registry.game(
        "VALORANT"
    ).display_order.index("map")
    assert "map" in window.registry.game("VALORANT").suggested_fields
    assert not editor.dirty


def select_game(editor, filename):
    for index in range(editor.games.count()):
        if editor.games.item(index).data(Qt.ItemDataRole.UserRole) == filename:
            editor.games.setCurrentRow(index)
            return
    raise AssertionError(filename)


def test_structured_values_aliases_and_new_game(editor_window, monkeypatch):
    window = editor_window
    window.panel("Config")
    editor = window.config_editor
    select_game(editor, "VALORANT.yaml")
    for index in range(editor.fields.count()):
        if editor.fields.item(index).text() == "weapon":
            editor.fields.setCurrentRow(index)
            break
    editor.values.add(["Ion Blade"])
    editor.aliases.add(["ion", "Ion Blade"])
    assert editor.save(), editor.status.text()
    assert parse_command("ion", "VALORANT", window.registry)["metadata"] == {
        "weapon": ["Ion Blade"]
    }
    monkeypatch.setattr(QInputDialog, "getText", lambda *args: ("New Game", True))
    editor.new_game()
    editor.code.setText("NEW")
    assert editor.save(), editor.status.text()
    assert window.registry.game("New Game").fields["kill"] == {}


def test_freeform_named_values_and_aliases_round_trip(editor_window):
    window = editor_window
    window.panel("Config")
    editor = window.config_editor
    select_game(editor, "Escape from Tarkov.yaml")
    editor.tabs.setCurrentIndex(1)
    for index in range(editor.fields.count()):
        if editor.fields.item(index).text() == "weapon":
            editor.fields.setCurrentRow(index)
            break
    assert editor.field_type.currentText() == "freeform"
    assert editor.values.isEnabled() and not editor.values.isHidden()
    assert editor.aliases.isEnabled() and not editor.aliases.isHidden()
    assert editor.field_form.labelForField(editor.values).text() == "Named values"
    editor.values.set_values([])
    editor.aliases.set_values([])
    editor.values.add(["MP5"])
    editor.aliases.add(["mp5navy", "MP5"])
    editor.field_type.setCurrentText("enum")
    assert editor.field_form.labelForField(editor.values).text() == "Enum values"
    editor.field_type.setCurrentText("freeform")
    assert editor.values.values() == [["MP5"]]
    assert editor.aliases.values() == [["mp5navy", "MP5"]]
    original = editor.source.path.read_bytes()
    editor.aliases.add(["MAP", "MP5"])
    assert not editor.save()
    assert "conflicts with a field name or prefix" in editor.status.text()
    assert editor.source.path.read_bytes() == original
    editor.aliases.table.setCurrentCell(1, 0)
    editor.aliases.remove()
    assert editor.save(), editor.status.text()
    assert parse_command("mp5 mp5navy customs", "Escape from Tarkov", window.registry) == {
        "metadata": {"weapon": ["MP5"], "map": "Customs"}
    }
    assert parse_command("wpn:OtherGun", "Escape from Tarkov", window.registry) == {
        "metadata": {"weapon": ["OtherGun"]}
    }
    editor.reload()
    for index in range(editor.fields.count()):
        if editor.fields.item(index).text() == "weapon":
            editor.fields.setCurrentRow(index)
            break
    assert editor.values.values() == [["MP5"]]
    assert editor.aliases.values() == [["mp5navy", "MP5"]]
    editor.example.setText("mp5 customs -- example")
    assert editor.save(), editor.status.text()
    assert window.registry.game("Escape from Tarkov").fields["weapon"]["values"] == ["MP5"]


def test_config_undo_crosses_save_without_writing_yaml(editor_window):
    window = editor_window
    window.panel("Config")
    editor = window.config_editor
    original = editor.example.text()
    filename = editor.source.path.name
    editor.example.setText("first change")
    assert window.undo_button.isEnabled()
    assert editor.save(), editor.status.text()
    saved = editor.source.path.read_bytes()
    assert not editor.dirty
    assert editor.revert_button.isEnabled()
    editor.example.setText("second change")
    window.undo()
    assert editor.example.text() == "first change"
    assert not editor.dirty
    window.undo()
    assert editor.example.text() == original
    assert editor.dirty
    assert editor.source.path.read_bytes() == saved
    window.undo(True)
    assert editor.example.text() == "first change"
    assert not editor.dirty
    select_game(editor, "Escape from Tarkov.yaml")
    assert not window.undo_button.isEnabled()
    select_game(editor, filename)
    assert window.undo_button.isEnabled()
    assert window.redo_button.isEnabled()
    assert editor.source.path.read_bytes() == saved


def test_config_revert_confirmation_restores_initial_draft(editor_window):
    from PySide6.QtTest import QTest

    window = editor_window
    window.panel("Config")
    editor = window.config_editor
    original = editor.example.text()
    assert not editor.revert_button.isEnabled()
    editor.example.setText("saved change")
    assert editor.save(), editor.status.text()
    saved = editor.source.path.read_bytes()
    QTest.mouseClick(editor.revert_button, Qt.MouseButton.LeftButton)
    assert editor.revert_armed
    assert editor.revert_button.text() == "Confirm revert"
    assert editor.revert_button.property("role") == "danger"
    QTest.mouseClick(editor.example, Qt.MouseButton.LeftButton)
    assert not editor.revert_armed
    QTest.mouseClick(editor.revert_button, Qt.MouseButton.LeftButton)
    QTest.keyClick(editor.revert_button, Qt.Key.Key_Escape)
    assert not editor.revert_armed
    QTest.mouseClick(editor.revert_button, Qt.MouseButton.LeftButton)
    QTest.mouseClick(editor.revert_button, Qt.MouseButton.LeftButton)
    assert editor.example.text() == original
    assert editor.dirty
    assert not editor.revert_button.isEnabled()
    assert editor.source.path.read_bytes() == saved
    window.undo()
    assert editor.example.text() == "saved change"
    assert not editor.dirty
    assert editor.source.path.read_bytes() == saved


def test_config_undo_retains_incomplete_table_entries(editor_window):
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QPushButton

    window = editor_window
    window.panel("Config")
    editor = window.config_editor
    select_game(editor, "Battlefield 6.yaml")
    editor.tabs.setCurrentIndex(1)
    add = next(button for button in editor.values.findChildren(QPushButton)
               if button.text() == "Add row")
    QTest.mouseClick(add, Qt.MouseButton.LeftButton)
    QTest.keyClicks(QApplication.focusWidget(), "mp5")
    window.undo()
    assert editor.values.values() == [[""]]
    window.undo()
    assert editor.values.values() == []
    window.undo(True)
    assert editor.values.values() == [[""]]
    window.undo(True)
    assert editor.values.values() == [["mp5"]]


def test_config_discard_keeps_saved_history_and_removes_unsaved_branch(editor_window, monkeypatch):
    window = editor_window
    window.panel("Config")
    editor = window.config_editor
    original = editor.example.text()
    editor.example.setText("saved example")
    assert editor.save(), editor.status.text()
    editor.example.setText("discarded example")
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Discard)
    window.panel("Home")
    window.panel("Config")
    assert editor.example.text() == "saved example"
    window.undo()
    assert editor.example.text() == original
    window.undo(True)
    assert editor.example.text() == "saved example"


def test_config_undo_restores_field_add_remove_and_selection_is_not_an_edit(editor_window, monkeypatch):
    window = editor_window
    window.panel("Config")
    editor = window.config_editor
    assert not window.undo_button.isEnabled()
    editor.fields.setCurrentRow(0)
    assert not window.undo_button.isEnabled()
    monkeypatch.setattr(QInputDialog, "getText", lambda *args: ("note", True))
    editor.add_field()
    assert "note" in editor.draft["fields"]
    window.undo()
    assert "note" not in editor.draft["fields"]
    window.undo(True)
    assert "note" in editor.draft["fields"]
    editor.remove_field()
    assert "note" not in editor.draft["fields"]
    window.undo()
    assert "note" in editor.draft["fields"]


def test_config_repair_undo_crosses_save_without_overwriting_saved_file(editor_window):
    window = editor_window
    target = window.root / "configs/games/VALORANT.yaml"
    invalid = "name: VALORANT\ncode: VAL\nfields: [weapon]\ndisplay_order: []\n"
    target.write_text(invalid, encoding="utf-8")
    window.reload_configs()
    window.panel("Config")
    editor = window.config_editor
    editor.refresh_files(select="VALORANT.yaml")
    assert editor.tabs.currentIndex() == 3
    editor.recovery.setPlainText(
        "name: VALORANT\ncode: VAL\nfields: {kill: {}}\ndisplay_order: [kill, mainline]\n"
    )
    assert editor.save(), editor.status.text()
    saved = target.read_bytes()
    assert editor.tabs.currentIndex() == 0
    window.undo()
    assert editor.tabs.currentIndex() == 3
    assert editor.recovery.toPlainText() == invalid
    assert target.read_bytes() == saved
    window.undo(True)
    assert editor.tabs.currentIndex() == 0
    assert not editor.dirty
    assert target.read_bytes() == saved


def test_invalid_yaml_recovery(editor_window):
    window = editor_window
    target = window.root / "configs/games/VALORANT.yaml"
    target.write_text("name: [broken\n", encoding="utf-8")
    window.reload_configs()
    window.panel("Config")
    editor = window.config_editor
    editor.refresh_files(select="VALORANT.yaml")
    assert editor.tabs.currentWidget() is editor.recovery
    editor.recovery.setPlainText(
        "name: VALORANT\ncode: VAL\nfields: {kill: {}}\ndisplay_order: [kill, mainline]\n"
    )
    assert editor.save(), editor.status.text()
    assert editor.tabs.currentIndex() == 0
    assert window.registry.game("VALORANT") is not None


@pytest.mark.parametrize("choice", ["Save", "Discard", "Cancel"])
def test_navigation_prompts_for_active_table_edit(editor_window, monkeypatch, choice):
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QLineEdit

    window = editor_window
    window.panel("Config")
    editor = window.config_editor
    select_game(editor, "Escape from Tarkov.yaml")
    editor.tabs.setCurrentIndex(1)
    for index in range(editor.fields.count()):
        if editor.fields.item(index).text() == "weapon":
            editor.fields.setCurrentRow(index)
            break
    table = editor.prefixes.table
    table.setFocus()
    table.editItem(table.item(0, 0))
    application = QApplication.instance()
    application.processEvents()
    assert isinstance(application.focusWidget(), QLineEdit)
    QTest.keyClick(application.focusWidget(), Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClicks(application.focusWidget(), "gun")
    prompts = []
    def respond(dialog):
        prompts.append(dialog.standardButtons())
        return getattr(QMessageBox.StandardButton, choice)
    monkeypatch.setattr(QMessageBox, "exec", respond)
    QTest.mouseClick(window.nav["Home"], Qt.MouseButton.LeftButton)
    assert prompts == [
        QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
        | QMessageBox.StandardButton.Cancel
    ]
    assert window.current_panel == ("Config" if choice == "Cancel" else "Home")
    if choice != "Cancel":
        window.panel("Config")
    game = window.registry.game("Escape from Tarkov")
    assert game.fields["weapon"]["prefixes"] == (["gun"] if choice == "Save" else ["wpn"])
    if choice == "Cancel":
        assert editor.prefixes.values() == [["gun"]]


def test_dirty_config_navigation_cancel_and_discard(editor_window, monkeypatch):
    window = editor_window
    window.panel("Config")
    editor = window.config_editor
    original = editor.example.text()
    editor.example.setText("unsaved example")
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Cancel)
    window.panel("Home")
    assert window.current_panel == "Config"
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Discard)
    window.panel("Home")
    assert window.current_panel == "Home"
    window.panel("Config")
    assert editor.example.text() == original
    editor.example.setText("saved on navigation")
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Save)
    window.panel("Home")
    assert window.current_panel == "Home"
    assert (
        window.registry.game(editor.source.document["name"]).command_example
        == "saved on navigation"
    )


def test_used_field_removal_preserves_clip_metadata(editor_window, monkeypatch, tmp_path):
    window = editor_window
    folder = tmp_path / "captures"
    folder.mkdir()
    clip_path = folder / "clip.mp4"
    clip_path.write_bytes(b"video")
    folder_id = window.catalogue.add_folder(folder)
    window.catalogue.ingest(folder_id, [{"path": str(clip_path), "game": "VALORANT"}])
    clip_id = window.catalogue.clips()[0]["clip_id"]
    window.catalogue.patch(clip_id, {"metadata": {"agent": "Jett"}})
    window.panel("Config")
    editor = window.config_editor
    select_game(editor, "VALORANT.yaml")
    for index in range(editor.fields.count()):
        if editor.fields.item(index).text() == "agent":
            editor.fields.setCurrentRow(index)
            break
    editor.remove_field()
    prompts = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *args: (prompts.append(args[2]), QMessageBox.StandardButton.Save)[1],
    )
    assert editor.save(), editor.status.text()
    assert "agent: 1 clips" in prompts[0]
    assert window.catalogue.clip(clip_id)["metadata"]["agent"] == "Jett"
    assert "agent" not in window.registry.game("VALORANT").fields


def test_removed_enum_value_clears_dependent_alias_and_link(editor_window):
    window = editor_window
    window.panel("Config")
    editor = window.config_editor
    select_game(editor, "VALORANT.yaml")
    for index in range(editor.fields.count()):
        if editor.fields.item(index).text() == "weapon":
            editor.fields.setCurrentRow(index)
            break
    for index, values in enumerate(editor.values.values()):
        if values[0] == "Headhunter":
            editor.values.table.setCurrentCell(index, 0)
            editor.values.remove()
            break
    assert editor.save(), editor.status.text()
    game = window.registry.game("VALORANT")
    assert "Headhunter" not in game.fields["weapon"]["values"]
    assert "hh" not in game.fields["weapon"].get("aliases", {})
    assert "headhunter" not in game.links["weapon"]
