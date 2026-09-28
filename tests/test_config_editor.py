import shutil
from pathlib import Path

import PySide6
import pytest
from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

from dfsorter.config import Registry
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
    shutil.copytree(ROOT / "configs", tmp_path / "configs")
    window = Window(tmp_path)
    window.show()
    application.processEvents()
    yield window
    window.config_editor.dirty = False
    close_window(window, application)


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
