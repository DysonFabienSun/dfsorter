"""Structured editor for game YAML definitions."""

import re
from copy import deepcopy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .config import GLOBAL_FIELDS
from .config_store import GameFile, new_game_path
from .theme import role
from .widgets import heading


def action(label, callback):
    button = QPushButton(label)
    button.clicked.connect(callback)
    return button


def row(*widgets):
    layout = QHBoxLayout()
    layout.setContentsMargins(0, 0, 0, 0)
    for widget in widgets:
        layout.addWidget(widget)
    layout.addStretch()
    return layout


class Rows(QWidget):
    def __init__(self, headings, changed, parent=None):
        super().__init__(parent)
        body = QVBoxLayout(self)
        body.setContentsMargins(0, 0, 0, 0)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.table = QTableWidget(0, len(headings))
        self.table.setHorizontalHeaderLabels(headings)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setFixedHeight(128)
        self.table.itemChanged.connect(lambda _: changed())
        body.addWidget(self.table)
        body.addLayout(row(action("Add row", self.add), action("Remove row", self.remove)))
        self.changed = changed

    def values(self):
        return [
            [
                self.table.item(index, column).text().strip()
                if self.table.item(index, column)
                else ""
                for column in range(self.table.columnCount())
            ]
            for index in range(self.table.rowCount())
        ]

    def set_values(self, values):
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for values_row in values:
            self.add(values_row)
        self.table.blockSignals(False)

    def add(self, values_row=None):
        if not isinstance(values_row, (tuple, list)):
            values_row = []
        index = self.table.rowCount()
        self.table.insertRow(index)
        for column in range(self.table.columnCount()):
            self.table.setItem(
                index,
                column,
                QTableWidgetItem(str(values_row[column]) if column < len(values_row) else ""),
            )
        self.table.setCurrentCell(index, 0)
        self.changed()

    def remove(self):
        index = self.table.currentRow()
        if index >= 0:
            self.table.removeRow(index)
            self.changed()


class ConfigEditor(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.directory = window.root / "configs/games"
        self.source = None
        self.draft = None
        self.field_key = None
        self.dirty = False
        self.loading = False
        self.sidebar_header = QWidget(window.left)
        self.sidebar_header.setObjectName("configSidebarHeader")
        header_layout = QHBoxLayout(self.sidebar_header)
        header_layout.setContentsMargins(16, 8, 8, 8)
        games_heading = QLabel("Games")
        role(games_heading, "paneHeading")
        header_layout.addWidget(games_heading)
        self.sidebar = QWidget(window.left)
        role(self.sidebar, "transparent")
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(8, 4, 8, 4)
        self.games = QListWidget()
        self.games.currentItemChanged.connect(self.select_game)
        side.addWidget(self.games, 1)
        side.addLayout(row(action("New game", self.new_game), action("Reload", self.reload)))

        body = QVBoxLayout(self)
        body.setContentsMargins(0, 0, 0, 0)
        heading_row, self.config_heading = heading("Game configurations", "file-cog")
        body.addLayout(heading_row)
        description = QLabel("Edit game definitions stored in configs/games.")
        role(description, "secondary")
        body.addWidget(description)
        self.tabs = QTabWidget()
        body.addWidget(self.tabs, 1)
        self.build_identity()
        self.build_fields()
        self.build_title()
        self.recovery = QPlainTextEdit()
        self.recovery.setPlaceholderText(
            "Repair the YAML, then save to return to the structured editor."
        )
        self.recovery.textChanged.connect(self.mark_dirty)
        self.tabs.addTab(self.recovery, "Repair YAML")
        self.tabs.setTabVisible(3, False)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.hide()
        body.addWidget(self.status)
        self.revert_button = action("Revert", self.revert)
        actions = row(action("Open YAML folder", window.open_configs), self.revert_button)
        self.save_button = action("Save", self.save)
        role(self.save_button, "primary")
        actions.addWidget(self.save_button)
        body.addLayout(actions)
        self.refresh_files()

    def build_identity(self):
        page = QWidget()
        form = QFormLayout(page)
        self.name = QLineEdit()
        self.code = QLineEdit()
        self.code.setMaxLength(3)
        self.example = QLineEdit()
        for control in (self.name, self.code, self.example):
            control.textChanged.connect(self.mark_dirty)
        form.addRow("Canonical name", self.name)
        form.addRow("Display code", self.code)
        form.addRow("Command example", self.example)
        self.game_aliases = Rows(["Accepted game alias"], self.mark_dirty)
        form.addRow("Game aliases", self.game_aliases)
        self.tabs.addTab(page, "Identity")

    def build_fields(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        split = QSplitter()
        self.fields = QListWidget()
        self.fields.currentItemChanged.connect(self.select_field)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.fields, 1)
        self.remove_field_button = action("Remove field", self.remove_field)
        left_layout.addLayout(row(action("Add field", self.add_field), self.remove_field_button))
        split.addWidget(left)
        detail = QWidget()
        form = QFormLayout(detail)
        self.field_form = form
        self.field_type = QComboBox()
        self.field_type.addItems(["enum", "freeform"])
        self.field_type.currentIndexChanged.connect(self.field_type_changed)
        self.multiple = QCheckBox("Allow multiple ordered values")
        self.multiple.toggled.connect(self.mark_dirty)
        self.reserved_note = QLabel(
            "Reserved engine field. Parsing and value format are controlled by DFSorter."
        )
        self.reserved_note.setWordWrap(True)
        role(self.reserved_note, "secondary")
        form.addRow("", self.reserved_note)
        form.addRow("Type", self.field_type)
        form.addRow("", self.multiple)
        self.prefixes = Rows(["Input prefix"], self.mark_dirty)
        self.values = Rows(["Canonical value"], self.mark_dirty)
        self.aliases = Rows(["Alias", "Canonical value"], self.mark_dirty)
        self.links = Rows(["Source value", "Target field", "Target value"], self.mark_dirty)
        form.addRow("Prefix aliases", self.prefixes)
        form.addRow("Enum values", self.values)
        form.addRow("Value aliases", self.aliases)
        form.addRow("Inference links", self.links)
        hint = QLabel(
            "Use one link row per target value. Repeated target fields build a multiple-value link."
        )
        hint.setWordWrap(True)
        role(hint, "secondary")
        self.link_hint = hint
        form.addRow("", hint)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(detail)
        split.addWidget(scroll)
        split.setStretchFactor(1, 1)
        outer.addWidget(split)
        self.tabs.addTab(page, "Fields")

    def build_title(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        title = QLabel("Working title order")
        role(title, "paneHeading")
        outer.addWidget(title)
        hint = QLabel(
            "Checked entries appear in the working title. Mainline is ordinary text in filenames."
        )
        role(hint, "secondary")
        outer.addWidget(hint)
        self.order = QListWidget()
        self.order.setFixedHeight(170)
        self.order.itemChanged.connect(self.mark_dirty)
        outer.addWidget(self.order, 1)
        outer.addLayout(
            row(
                action("Move up", lambda: self.move_order(-1)),
                action("Move down", lambda: self.move_order(1)),
            )
        )
        suggestion = QLabel("Suggested review fields")
        role(suggestion, "paneHeading")
        outer.addWidget(suggestion)
        self.suggested = QListWidget()
        self.suggested.setFixedHeight(140)
        self.suggested.itemChanged.connect(self.mark_dirty)
        outer.addWidget(self.suggested, 1)
        outer.addStretch()
        self.tabs.addTab(page, "Title && review")

    def message(self, value, error=False):
        self.status.setText(value)
        role(self.status, "error" if error else "secondary")
        self.status.setVisible(bool(value))

    def mark_dirty(self, *_):
        if not self.loading and self.source is not None:
            self.dirty = True
            self.save_button.setEnabled(True)
            self.revert_button.setEnabled(True)

    def refresh_files(self, select=None):
        self.games.blockSignals(True)
        self.games.clear()
        for path in sorted(self.directory.glob("*.yaml"), key=lambda value: value.name.casefold()):
            item = QListWidgetItem(path.stem)
            item.setData(Qt.ItemDataRole.UserRole, path.name)
            if any(error.startswith(path.name + ":") for error in self.window.registry.errors):
                item.setText(path.stem + " · Error")
            self.games.addItem(item)
            if path.name == select:
                self.games.setCurrentItem(item)
        if self.games.currentItem() is None and self.games.count():
            self.games.setCurrentRow(0)
        self.games.blockSignals(False)
        if self.games.currentItem():
            self.load_game(self.games.currentItem().data(Qt.ItemDataRole.UserRole))
        else:
            self.source = None
            self.tabs.setEnabled(False)
            self.save_button.setEnabled(False)
            self.revert_button.setEnabled(False)

    def confirm_discard(self):
        if not self.dirty:
            return True
        choice = QMessageBox(self)
        choice.setWindowTitle("Unsaved configuration")
        choice.setText("Save changes to the current game configuration?")
        choice.setStandardButtons(
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel
        )
        choice.setDefaultButton(QMessageBox.StandardButton.Cancel)
        result = choice.exec()
        if result == QMessageBox.StandardButton.Save:
            return self.save()
        if result == QMessageBox.StandardButton.Discard:
            self.dirty = False
            return True
        return False

    def select_game(self, item, previous):
        if item is None:
            return
        filename = item.data(Qt.ItemDataRole.UserRole)
        if not self.confirm_discard():
            self.games.blockSignals(True)
            if previous is None:
                self.games.setCurrentRow(-1)
            else:
                self.games.setCurrentItem(previous)
            self.games.blockSignals(False)
            return
        for index in range(self.games.count()):
            candidate = self.games.item(index)
            if candidate.data(Qt.ItemDataRole.UserRole) == filename:
                self.games.blockSignals(True)
                self.games.setCurrentItem(candidate)
                self.games.blockSignals(False)
                break
        self.load_game(filename)

    def load_game(self, filename):
        self.loading = True
        self.message("")
        self.source = None
        try:
            self.source = GameFile(self.directory / filename)
            self.draft = self.source.draft()
            errors = [
                error for error in self.window.registry.errors if error.startswith(filename + ":")
            ]
            if errors:
                raise ValueError("\n".join(errors))
            self.show_draft()
            self.tabs.setCurrentIndex(0)
            self.tabs.setTabEnabled(0, True)
            self.tabs.setTabEnabled(1, True)
            self.tabs.setTabEnabled(2, True)
            self.tabs.setTabEnabled(3, False)
            self.tabs.setTabVisible(3, False)
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            self.recovery.setPlainText(
                self.source.text
                if self.source
                else (self.directory / filename).read_text(encoding="utf-8")
            )
            for index in range(3):
                self.tabs.setTabEnabled(index, False)
            self.tabs.setTabEnabled(3, True)
            self.tabs.setTabVisible(3, True)
            self.tabs.setCurrentIndex(3)
            self.message(str(error), True)
        self.tabs.setEnabled(True)
        self.dirty = False
        self.save_button.setEnabled(False)
        self.revert_button.setEnabled(False)
        self.loading = False

    def show_draft(self):
        self.name.setText(self.draft.get("name", ""))
        self.name.setReadOnly(self.source.digest is not None)
        self.code.setText(self.draft.get("code", ""))
        self.example.setText(self.draft.get("command_example", ""))
        self.game_aliases.set_values([[value] for value in self.draft.get("aliases", [])])
        self.fields.blockSignals(True)
        self.fields.clear()
        for key in self.draft.get("fields", {}):
            self.fields.addItem(key)
        if "kill" not in self.draft.get("fields", {}):
            self.draft.setdefault("fields", {})["kill"] = {}
            self.fields.insertItem(0, "kill")
        self.fields.blockSignals(False)
        self.field_key = None
        self.order.clear()
        self.suggested.clear()
        if self.fields.count():
            self.fields.setCurrentRow(
                next(
                    (
                        index
                        for index in range(self.fields.count())
                        if self.fields.item(index).text() not in {"kill", "clutch"}
                    ),
                    0,
                )
            )
        self.refresh_order()

    def refresh_order(self):
        old_order = [self.order.item(i).text() for i in range(self.order.count())]
        old_checked = {
            self.order.item(i).text()
            for i in range(self.order.count())
            if self.order.item(i).checkState() == Qt.CheckState.Checked
        }
        old_suggested = {
            self.suggested.item(i).text()
            for i in range(self.suggested.count())
            if self.suggested.item(i).checkState() == Qt.CheckState.Checked
        }
        keys = [*self.draft.get("fields", {}), "mainline"]
        if not old_order:
            old_order = self.draft.get("display_order", [])
            old_checked = set(old_order)
            old_suggested = set(
                self.draft.get("suggested_fields", self.draft.get("required_for_export", []))
            )
        self.order.blockSignals(True)
        self.suggested.blockSignals(True)
        self.order.clear()
        self.suggested.clear()
        for key in [
            *filter(lambda value: value in keys, old_order),
            *filter(lambda value: value not in old_order, keys),
        ]:
            item = QListWidgetItem(key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if key in old_checked else Qt.CheckState.Unchecked
            )
            self.order.addItem(item)
        for key in self.draft.get("fields", {}):
            item = QListWidgetItem(key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if key in old_suggested else Qt.CheckState.Unchecked
            )
            self.suggested.addItem(item)
        self.order.blockSignals(False)
        self.suggested.blockSignals(False)

    def select_field(self, item, previous):
        if not self.loading and previous is not None:
            try:
                self.capture_field()
            except ValueError as error:
                self.message(str(error), True)
                self.fields.blockSignals(True)
                self.fields.setCurrentItem(previous)
                self.fields.blockSignals(False)
                return
        self.field_key = item.text() if item else None
        self.remove_field_button.setEnabled(self.field_key not in {None, "kill"})
        self.loading = True
        definition = self.draft.get("fields", {}).get(self.field_key, {}) if self.draft else {}
        reserved = self.field_key in {"kill", "clutch"}
        self.field_form.setRowVisible(self.reserved_note, reserved)
        self.field_form.setRowVisible(self.field_type, not reserved)
        self.field_form.setRowVisible(self.multiple, not reserved)
        self.field_type.setCurrentText(definition.get("type", "enum"))
        self.multiple.setChecked(bool(definition.get("multiple", False)))
        self.field_type.setEnabled(not reserved and bool(item))
        self.multiple.setEnabled(not reserved and bool(item))
        self.prefixes.setEnabled(not reserved and bool(item))
        self.values.setEnabled(not reserved and bool(item) and definition.get("type") == "enum")
        self.aliases.setEnabled(not reserved and bool(item) and definition.get("type") == "enum")
        self.links.setEnabled(not reserved and bool(item))
        self.prefixes.set_values([[value] for value in definition.get("prefixes", [])])
        self.values.set_values([[value] for value in definition.get("values", [])])
        self.aliases.set_values(
            [[alias, value] for alias, value in definition.get("aliases", {}).items()]
        )
        link_rows = []
        for source, targets in definition.get("links", {}).items():
            for target, value in targets.items():
                for part in value if isinstance(value, list) else [value]:
                    link_rows.append([source, target, part])
        self.links.set_values(link_rows)
        self.update_field_rows()
        self.loading = False

    def field_type_changed(self):
        kind = self.field_type.currentText()
        self.values.setEnabled(kind == "enum")
        self.aliases.setEnabled(kind == "enum")
        self.update_field_rows()
        self.mark_dirty()

    def update_field_rows(self):
        reserved = self.field_key in {"kill", "clutch"}
        self.field_form.setRowVisible(self.prefixes, not reserved)
        self.field_form.setRowVisible(
            self.values, not reserved and self.field_type.currentText() == "enum"
        )
        self.field_form.setRowVisible(
            self.aliases, not reserved and self.field_type.currentText() == "enum"
        )
        self.field_form.setRowVisible(self.links, not reserved)
        self.field_form.setRowVisible(self.link_hint, not reserved)

    def capture_field(self):
        if not self.field_key or self.field_key not in self.draft.get("fields", {}):
            return
        old = self.draft["fields"][self.field_key]
        if self.field_key in {"kill", "clutch"}:
            definition = {
                key: value
                for key, value in old.items()
                if key not in {"type", "multiple", "prefixes", "values", "aliases"}
            }
        else:
            definition = {
                key: value
                for key, value in old.items()
                if key not in {"type", "multiple", "prefixes", "values", "aliases"}
            }
            definition["type"] = self.field_type.currentText()
            if self.multiple.isChecked():
                definition["multiple"] = True
            prefixes = [entry[0] for entry in self.prefixes.values() if entry[0]]
            if prefixes:
                definition["prefixes"] = prefixes
            if self.field_type.currentText() == "enum":
                definition["values"] = [entry[0] for entry in self.values.values() if entry[0]]
                aliases = {key: value for key, value in self.aliases.values() if key}
                if aliases:
                    definition["aliases"] = aliases
        links = {}
        for source, target, value in self.links.values():
            if not (source or target or value):
                continue
            if not source or not target or not value:
                raise ValueError(
                    "Each inference link needs a source, target field, and target value"
                )
            destination = self.draft["fields"].get(target, {})
            if target in {"kill", "clutch"}:
                try:
                    value = int(value)
                except ValueError as error:
                    raise ValueError(f"{target} link target must be a number") from error
            if destination.get("multiple"):
                links.setdefault(source, {}).setdefault(target, []).append(value)
            elif target in links.setdefault(source, {}):
                raise ValueError(f"Duplicate scalar link: {source} → {target}")
            else:
                links[source][target] = value
        if links:
            definition["links"] = links
        else:
            definition.pop("links", None)
        self.draft["fields"][self.field_key] = definition

    def add_field(self):
        key, accepted = QInputDialog.getText(self, "New field", "Stable field key:")
        if not accepted:
            return
        key = key.strip()
        if (
            not re.fullmatch(r"[a-z][a-z0-9_]*", key)
            or key in self.draft["fields"]
            or key in GLOBAL_FIELDS
        ):
            self.message("Enter a unique lowercase field key that is not reserved.", True)
            return
        try:
            self.capture_field()
        except ValueError as error:
            self.message(str(error), True)
            return
        self.draft["fields"][key] = {} if key == "clutch" else {"type": "enum", "values": []}
        self.fields.addItem(key)
        self.fields.setCurrentRow(self.fields.count() - 1)
        self.refresh_order()
        self.mark_dirty()

    def remove_field(self):
        key = self.field_key
        if not key or key == "kill":
            self.message("The reserved kill field cannot be removed.", True)
            return
        self.field_key = None
        del self.draft["fields"][key]
        for definition in self.draft["fields"].values():
            links = definition.get("links", {})
            for source_value in list(links):
                links[source_value].pop(key, None)
                if not links[source_value]:
                    del links[source_value]
            if not links:
                definition.pop("links", None)
        self.fields.takeItem(self.fields.currentRow())
        self.refresh_order()
        self.mark_dirty()

    def move_order(self, offset):
        index = self.order.currentRow()
        target = index + offset
        if index < 0 or not 0 <= target < self.order.count():
            return
        item = self.order.takeItem(index)
        self.order.insertItem(target, item)
        self.order.setCurrentRow(target)
        self.mark_dirty()

    def collect(self):
        self.capture_field()
        draft = deepcopy(self.draft)
        draft["name"] = self.name.text().strip()
        draft["code"] = self.code.text().strip()
        draft["command_example"] = self.example.text()
        draft["aliases"] = [entry[0] for entry in self.game_aliases.values() if entry[0]]
        draft["display_order"] = [
            self.order.item(i).text()
            for i in range(self.order.count())
            if self.order.item(i).checkState() == Qt.CheckState.Checked
        ]
        draft["suggested_fields"] = [
            self.suggested.item(i).text()
            for i in range(self.suggested.count())
            if self.suggested.item(i).checkState() == Qt.CheckState.Checked
        ]
        draft.pop("required_for_export", None)
        if self.source.digest is not None and isinstance(self.source.document, dict):
            previous = self.source.draft().get("fields", {})
            for key in set(previous) & set(draft["fields"]):
                removed = set(previous[key].get("values", [])) - set(
                    draft["fields"][key].get("values", [])
                )
                if not removed:
                    continue
                definition = draft["fields"][key]
                definition["aliases"] = {
                    alias: value
                    for alias, value in definition.get("aliases", {}).items()
                    if value not in removed
                }
                for field, other in draft["fields"].items():
                    links = other.get("links", {})
                    if field == key:
                        for value in removed:
                            links.pop(value, None)
                    for source_value, targets in list(links.items()):
                        if key in targets:
                            target = targets[key]
                            if isinstance(target, list):
                                targets[key] = [value for value in target if value not in removed]
                                if not targets[key]:
                                    del targets[key]
                            elif target in removed:
                                del targets[key]
                        if not targets:
                            del links[source_value]
                    if not links:
                        other.pop("links", None)
        return draft

    def impact(self, draft):
        if self.source.digest is None or not isinstance(self.source.document, dict):
            return ""
        original = self.source.draft()
        old_fields = original.get("fields", {})
        new_fields = draft.get("fields", {})
        affected = []
        clips = [
            clip for clip in self.window.catalogue.clips() if clip["game"] == original.get("name")
        ]
        for key in set(old_fields) - set(new_fields):
            count = sum(clip["metadata"].get(key) not in (None, "", []) for clip in clips)
            if count:
                affected.append(f"Field {key}: {count} clips")
        for key in set(old_fields) & set(new_fields):
            removed = set(old_fields[key].get("values", [])) - set(
                new_fields[key].get("values", [])
            )
            for value in sorted(removed):
                count = sum(
                    value
                    in (
                        clip["metadata"].get(key)
                        if isinstance(clip["metadata"].get(key), list)
                        else [clip["metadata"].get(key)]
                    )
                    for clip in clips
                )
                if count:
                    affected.append(f"{key} = {value}: {count} clips")
        return "\n".join(affected)

    def save(self):
        if self.source is None:
            return False
        try:
            if self.tabs.currentIndex() == 3:
                self.source.save(None, self.directory, raw_text=self.recovery.toPlainText())
            else:
                draft = self.collect()
                if self.source.digest is not None and draft["name"] != self.source.document.get(
                    "name"
                ):
                    raise ValueError("Canonical names of existing games cannot be changed")
                usage = self.impact(draft)
                if usage:
                    response = QMessageBox.warning(
                        self,
                        "Schema change",
                        "Existing clip metadata remains stored, but these values may no longer be accepted or shown:\n\n"
                        + usage
                        + "\n\nSave the configuration?",
                        QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel,
                        QMessageBox.StandardButton.Cancel,
                    )
                    if response != QMessageBox.StandardButton.Save:
                        return False
                self.source.save(draft, self.directory)
            filename = self.source.path.name
            self.dirty = False
            self.window.reload_configs()
            self.refresh_files(select=filename)
            self.message("Configuration saved.")
            return True
        except Exception as error:
            self.message(str(error), True)
            return False

    def revert(self):
        if self.source is None:
            return
        if self.source.digest is None:
            self.refresh_files()
        else:
            self.load_game(self.source.path.name)

    def reload(self):
        if not self.confirm_discard():
            return
        selected = self.source.path.name if self.source and self.source.digest is not None else None
        self.window.reload_configs()
        self.refresh_files(select=selected)

    def new_game(self):
        if not self.confirm_discard():
            return
        name, accepted = QInputDialog.getText(self, "New game", "Canonical game name:")
        if not accepted:
            return
        try:
            path = new_game_path(self.directory, name)
        except ValueError as error:
            self.message(str(error), True)
            return
        self.loading = True
        self.source = GameFile(path)
        self.games.blockSignals(True)
        self.games.setCurrentRow(-1)
        self.games.blockSignals(False)
        self.draft = {
            "name": name,
            "code": "",
            "aliases": [],
            "fields": {"kill": {}},
            "display_order": ["kill", "mainline"],
            "suggested_fields": [],
            "command_example": "",
        }
        self.show_draft()
        for index in range(3):
            self.tabs.setTabEnabled(index, True)
        self.tabs.setTabEnabled(3, False)
        self.tabs.setTabVisible(3, False)
        self.tabs.setCurrentIndex(0)
        self.tabs.setEnabled(True)
        self.loading = False
        self.dirty = True
        self.save_button.setEnabled(True)
        self.revert_button.setEnabled(True)
        self.message("New game draft. Add a three-character uppercase display code before saving.")
