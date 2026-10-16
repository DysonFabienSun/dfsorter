import pytest
from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from dfsorter.theme import apply_theme
from dfsorter.ui import FilterMenuButton


@pytest.fixture
def application():
    app = QApplication.instance() or QApplication([])
    apply_theme(app, "dark")
    return app


@pytest.mark.parametrize("label", ["Clips", "Games", "Projects"])
def test_exclusive_all_applies_once_without_empty_intermediate_result(application, label):
    control = FilterMenuButton(label, "All", [("First", 1), ("Second", 2)])
    all_action, _, first, second = control.menu().actions()
    changes = []
    control.selectionChanged.connect(lambda: changes.append(control.selected_values()))
    try:
        assert all_action.isChecked()
        assert not first.isChecked() and not second.isChecked()
        all_action.trigger()
        assert all_action.isChecked() and not changes
        first.trigger()
        assert changes == [{1}]
        assert not all_action.isChecked() and first.isChecked()
        second.trigger()
        assert changes[-1] == {1, 2}
        assert not all_action.isChecked()
        control.set_options([("First", 1), ("Second", 2), ("Third", 3)])
        assert control.selected_values() == {1, 2}
        assert not control.menu().actions()[-1].isChecked()
        control.set_options([("First", 1), ("Second", 2)])
        first.trigger()
        assert changes[-1] == {2}
        second.trigger()
        assert changes[-1] == {1, 2}
        assert all_action.isChecked()
        assert not first.isChecked() and not second.isChecked()
        first.trigger()
        all_action.trigger()
        assert all_action.isChecked() and not first.isChecked()
        assert all(changes)
    finally:
        control.close()
        control.deleteLater()


class MenuEvents(QObject):
    def __init__(self):
        super().__init__()
        self.disruptions = []

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.ActionAdded, QEvent.Type.ActionRemoved, QEvent.Type.Resize):
            self.disruptions.append(event.type())
        return False


def test_open_menu_preserves_actions_hover_and_geometry(application):
    options = [("Uncategorized", ""), ("VALORANT", "VALORANT")]
    control = FilterMenuButton("Games", "All games", options)
    menu = control.menu()
    observer = MenuEvents()
    menu.installEventFilter(observer)
    try:
        menu.popup(QPoint(20, 20))
        application.processEvents()
        actions = menu.actions()
        valorant = actions[-1]
        position = menu.actionGeometry(valorant).center()
        menu.setActiveAction(valorant)
        application.processEvents()
        assert menu.activeAction() is valorant
        geometry = menu.geometry()
        observer.disruptions.clear()

        control.set_options(list(options))
        QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=position)
        application.processEvents()
        assert control.selected_values() == {"VALORANT"}
        assert menu.isVisible()
        assert menu.actions() == actions
        assert menu.activeAction() is valorant
        assert menu.geometry() == geometry
        assert not observer.disruptions

        control.set_options([*options, ("Other", "Other")])
        assert menu.actions()[:len(actions)] == actions
        assert menu.activeAction() is valorant
        control.set_options([("Renamed", "VALORANT"), ("Other", "Other")])
        assert menu.actions()[2] is valorant
        assert valorant.text() == "Renamed" and valorant.isChecked()
        control.set_options([("Other", "Other")])
        assert control.all_selected()
        control.set_options([])
        assert control.all_selected() and len(menu.actions()) == 1
    finally:
        menu.close()
        control.deleteLater()
