"""Structured editor for game YAML definitions."""

import re
from copy import deepcopy

from PySide6.QtCore import QEvent, QRect, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QFontMetrics, QPalette
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QApplication,
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
    QStyle,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .config import GLOBAL_FIELDS
from .config_store import GameFile, new_game_path, validate_candidate, yaml_parser
from .history import EditHistory
from .theme import COLORS, font, role
from .widgets import heading, tool

GAME_SUMMARY_ROLE = Qt.ItemDataRole.UserRole + 1
GAME_SIZE_ROLE = Qt.ItemDataRole.UserRole + 2
GAME_ADDITIONS_ROLE = Qt.ItemDataRole.UserRole + 3


def yaml_size_text(size):
    return f"{size / 1024:.1f} KB" if size >= 1024 else f"{size} B"


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


class TableEditDelegate(QStyledItemDelegate):
    def __init__(self, changed, add_row, search_text, parent):
        super().__init__(parent)
        self.changed = changed
        self.add_row = add_row
        self.search_text = search_text

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        query = self.search_text().casefold()
        if query and query in str(index.data() or "").casefold():
            option.backgroundBrush = QBrush(QColor(COLORS["status_warning_soft"]))

    def createEditor(self, parent, option, index):
        editor = super().createEditor(parent, option, index)
        if isinstance(editor, QLineEdit):
            editor.textEdited.connect(lambda _text: self.changed())
        return editor

    def eventFilter(self, watched, event):
        if isinstance(watched, QLineEdit) and event.type() == QEvent.Type.KeyPress:
            self.parent().ensure_row_visible(self.parent().currentIndex())
        add_after_commit = (
            isinstance(watched, QLineEdit)
            and event.type() == QEvent.Type.KeyPress
            and event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
            and self.parent().currentRow() == self.parent().rowCount() - 1
        )
        if add_after_commit:
            self.commitData.emit(watched)
            self.closeEditor.emit(watched, QAbstractItemDelegate.EndEditHint.NoHint)
            self.add_row()
            return True
        return super().eventFilter(watched, event)


class ConfigTable(QTableWidget):
    def __init__(self, columns, changed, parent=None):
        super().__init__(0, columns, parent)
        self.changed = changed
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

    def ensure_row_visible(self, index):
        if not index.isValid():
            return
        self.scrollTo(index, QAbstractItemView.ScrollHint.EnsureVisible)
        ancestor = self.parentWidget()
        while ancestor is not None:
            if isinstance(ancestor, QScrollArea) and ancestor.widget() is not None:
                rect = self.visualRect(index)
                center = self.viewport().mapTo(ancestor.widget(), rect.center())
                ancestor.ensureVisible(
                    center.x(), center.y(), (rect.width() + 1) // 2, (rect.height() + 1) // 2
                )
            ancestor = ancestor.parentWidget()

    def edit(self, index, trigger=QAbstractItemView.EditTrigger.AllEditTriggers, event=None):
        started = super().edit(index, trigger, event)
        if started:
            self.ensure_row_visible(index)
        return started

    def dropEvent(self, event):
        if event.source() is not self or self.currentRow() < 0:
            event.ignore()
            return
        source = self.currentRow()
        index = self.indexAt(event.position().toPoint())
        target = index.row() if index.isValid() else self.rowCount()
        if self.dropIndicatorPosition() == QAbstractItemView.DropIndicatorPosition.BelowItem:
            target += 1
        if target > source:
            target -= 1
        self.move_row(source, target)
        event.acceptProposedAction()

    def move_row(self, source, target):
        if source == target:
            return
        column = self.currentColumn()
        blocked = self.blockSignals(True)
        items = [self.takeItem(source, offset) for offset in range(self.columnCount())]
        self.removeRow(source)
        self.insertRow(target)
        for offset, item in enumerate(items):
            self.setItem(target, offset, item)
        self.setCurrentCell(target, column)
        self.blockSignals(blocked)
        self.changed()


class GameListDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        title_height = QFontMetrics(font("md", "medium", base=option.font)).height()
        summary_height = QFontMetrics(font("sm", base=option.font)).height()
        return QSize(100, title_height + summary_height + 18)

    def paint(self, painter, option, index):
        painter.save()
        painter.setClipRect(option.rect)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        focused = bool(option.state & QStyle.StateFlag.State_HasFocus)
        row = option.rect
        if selected or hovered:
            painter.fillRect(row, QColor(COLORS["accent_soft" if selected else "surface_hover"]))
        if selected:
            painter.fillRect(QRect(row.left(), row.top(), 3, row.height()), QColor(COLORS["accent_default"]))
        if focused:
            painter.setPen(QColor(COLORS["focus"]))
            painter.drawRect(row.adjusted(0, 0, -1, -1))

        left = row.left() + 12
        width = max(0, row.right() - left - 8)
        title_font = font("md", "medium", base=option.font)
        summary_font = font("sm", base=option.font)
        title_metrics = QFontMetrics(title_font)
        summary_metrics = QFontMetrics(summary_font)
        top = row.top() + (row.height() - title_metrics.height() - summary_metrics.height() - 2) // 2 - 1
        painter.setFont(title_font)
        painter.setPen(QColor(COLORS["text_primary"]))
        painter.drawText(
            QRect(left, top, width, title_metrics.height()),
            Qt.AlignmentFlag.AlignVCenter,
            title_metrics.elidedText(index.data(), Qt.TextElideMode.ElideRight, width),
        )
        painter.setFont(summary_font)
        painter.setPen(QColor(COLORS["text_secondary"]))
        summary = f"{index.data(GAME_SUMMARY_ROLE)} · {index.data(GAME_SIZE_ROLE)}"
        additions = index.data(GAME_ADDITIONS_ROLE) or ""
        additions_width = min(width, summary_metrics.horizontalAdvance(additions)) if additions else 0
        summary_width = max(0, width - additions_width - (4 if additions else 0))
        visible_summary = summary_metrics.elidedText(summary, Qt.TextElideMode.ElideRight, summary_width)
        summary_top = top + title_metrics.height() + 2
        painter.drawText(
            QRect(left, summary_top, summary_width, summary_metrics.height()),
            Qt.AlignmentFlag.AlignVCenter,
            visible_summary,
        )
        if additions:
            painter.setPen(QColor(COLORS["accent_default"]))
            painter.drawText(
                QRect(left + summary_metrics.horizontalAdvance(visible_summary) + 4,
                      summary_top, additions_width, summary_metrics.height()),
                Qt.AlignmentFlag.AlignVCenter,
                summary_metrics.elidedText(additions, Qt.TextElideMode.ElideRight, additions_width),
            )
        painter.restore()


class Rows(QWidget):
    def __init__(self, headings, changed, parent=None, hint=""):
        super().__init__(parent)
        body = QVBoxLayout(self)
        body.setContentsMargins(0, 0, 0, 0)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.table = ConfigTable(len(headings), self.rows_changed)
        self.table.setItemDelegate(
            TableEditDelegate(changed, self.add, lambda: self.search.text(), self.table)
        )
        self.table.setHorizontalHeaderLabels(headings)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setDragEnabled(True)
        self.table.setAcceptDrops(True)
        self.table.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.table.setDragDropOverwriteMode(False)
        self.table.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        self.table.setFixedHeight(128)
        self.table.setToolTip(
            "Add row or double-click empty table space to start a new entry; "
            "click a selected cell or double-click a cell to edit it. "
            "Enter on the last row adds another row."
        )
        self.table.viewport().installEventFilter(self)
        self.table.installEventFilter(self)
        self.table.itemChanged.connect(lambda _: self.rows_changed())
        body.addWidget(self.table)
        self.remove_button = action("Remove row", self.remove)
        self.remove_button.setEnabled(False)
        self.table.itemSelectionChanged.connect(self.update_remove_button)
        self.search = QLineEdit()
        self.search.setProperty("configRowSearch", True)
        self.search.setFixedHeight(self.remove_button.sizeHint().height())
        self.search.setPlaceholderText("Search rows")
        self.search.textChanged.connect(self.update_search)
        self.previous_match = tool("chevron-up", "Previous match", lambda: self.move_match(-1))
        self.next_match = tool("chevron-down", "Next match", lambda: self.move_match(1))
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(4)
        actions.addWidget(action("Add row", self.add))
        actions.addWidget(self.remove_button)
        actions.addWidget(self.search, 1)
        actions.addWidget(self.previous_match)
        actions.addWidget(self.next_match)
        body.addLayout(actions)
        self.hint = QLabel(hint, self)
        self.hint.setWordWrap(True)
        role(self.hint, "secondary")
        self.hint.setVisible(bool(hint))
        body.addWidget(self.hint)
        self.changed = changed
        self.update_search()

    def rows_changed(self):
        self.changed()
        self.update_search()

    def matches(self):
        query = self.search.text().casefold()
        if not query:
            return []
        return [
            (row, column)
            for row in range(self.table.rowCount())
            for column in range(self.table.columnCount())
            if query in self.table.item(row, column).text().casefold()
        ]

    def update_search(self):
        matches = self.matches()
        self.previous_match.setEnabled(bool(matches))
        self.next_match.setEnabled(bool(matches))
        self.table.viewport().update()

    def move_match(self, direction):
        matches = self.matches()
        if not matches:
            return
        current = (self.table.currentRow(), self.table.currentColumn())
        position = matches.index(current) if current in matches else (-1 if direction > 0 else 0)
        row, column = matches[(position + direction) % len(matches)]
        self.table.setCurrentCell(row, column)
        self.table.scrollToItem(self.table.item(row, column))

    def eventFilter(self, watched, event):
        if (
            watched is self.table
            and event.type() == QEvent.Type.KeyPress
            and event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
            and self.table.currentRow() == self.table.rowCount() - 1
            and self.table.isEnabled()
        ):
            self.add(append=True)
            return True
        if (
            watched is self.table.viewport()
            and event.type() == QEvent.Type.MouseButtonDblClick
            and event.button() == Qt.MouseButton.LeftButton
            and self.table.isEnabled()
            and not self.table.indexAt(event.position().toPoint()).isValid()
        ):
            self.table.setFocus()
            self.add(append=True)
            return True
        return super().eventFilter(watched, event)

    def values(self):
        return [[value.strip() for value in entry] for entry in self.raw_values()]

    def set_invalid_cells(self, errors):
        blocked = self.table.blockSignals(True)
        editor = QApplication.focusWidget()
        active = (
            (self.table.currentRow(), self.table.currentColumn())
            if isinstance(editor, QLineEdit) and self.table.isAncestorOf(editor)
            and editor.isVisible() else None
        )
        for row in range(self.table.rowCount()):
            for column in range(self.table.columnCount()):
                if (row, column) == active:
                    continue
                item = self.table.item(row, column)
                invalid = errors.get((row, column))
                if item.font().underline() != bool(invalid) or item.toolTip() != (invalid or ""):
                    item.setForeground(
                        QBrush(QColor(COLORS["status_danger"])) if invalid else QBrush()
                    )
                    item_font = item.font()
                    item_font.setUnderline(bool(invalid))
                    item.setFont(item_font)
                    item.setToolTip(invalid or "")
        self.table.blockSignals(blocked)
        if active is not None:
            invalid = errors.get(active)
            palette = editor.palette()
            palette.setColor(
                QPalette.ColorRole.Text,
                QColor(COLORS["status_danger" if invalid else "text_primary"]),
            )
            editor.setPalette(palette)
            if editor.font().underline() != bool(invalid):
                cursor = editor.cursorPosition()
                selection_start = editor.selectionStart()
                selection_length = len(editor.selectedText())
                editor_font = editor.font()
                editor_font.setUnderline(bool(invalid))
                editor.setFont(editor_font)
                if selection_start >= 0:
                    editor.setSelection(selection_start, selection_length)
                else:
                    editor.setCursorPosition(cursor)

    def raw_values(self):
        result = [
            [self.table.item(row, column).text() if self.table.item(row, column) else ""
             for column in range(self.table.columnCount())]
            for row in range(self.table.rowCount())
        ]
        editor = QApplication.focusWidget()
        if isinstance(editor, QLineEdit) and self.table.isAncestorOf(editor):
            row, column = self.table.currentRow(), self.table.currentColumn()
            if row >= 0 and column >= 0:
                result[row][column] = editor.text()
        return result

    def set_values(self, values):
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for values_row in values:
            self.add(values_row)
        self.table.blockSignals(False)
        self.clear_selection()
        self.update_search()

    def clear_selection(self):
        self.table.clearSelection()
        self.table.setCurrentItem(None)

    def update_remove_button(self):
        self.remove_button.setEnabled(bool(self.table.selectedItems()))

    def add(self, values_row=None, *, append=False):
        begin_edit = not isinstance(values_row, (tuple, list))
        if begin_edit:
            values_row = []
        selected = self.table.selectedItems() if begin_edit and not append else []
        index = selected[0].row() + 1 if selected else self.table.rowCount()
        blocked = self.table.blockSignals(True)
        self.table.insertRow(index)
        for column in range(self.table.columnCount()):
            self.table.setItem(
                index,
                column,
                QTableWidgetItem(str(values_row[column]) if column < len(values_row) else ""),
            )
        if begin_edit:
            self.table.setCurrentCell(index, 0)
        self.table.blockSignals(blocked)
        if begin_edit:
            self.update_remove_button()
        self.changed()
        self.update_search()
        if begin_edit:
            self.table.setFocus()
            self.table.editItem(self.table.item(index, 0))

    def remove(self):
        selected = self.table.selectedItems()
        if selected:
            self.table.removeRow(selected[0].row())
            self.changed()
            self.update_search()


class ConfigEditor(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.directory = window.root / "configs/games"
        self.source = None
        self.draft = None
        self.field_key = None
        self.dirty = False
        self.histories = {}
        self.initial_states = {}
        self.saved_states = {}
        self.saved_histories = {}
        self.last_state = None
        self.revert_armed = False
        self.loading = False
        self.sidebar_header = QWidget(window.left)
        self.sidebar_header.setObjectName("configSidebarHeader")
        header_layout = QVBoxLayout(self.sidebar_header)
        header_layout.setContentsMargins(8, 8, 8, 12)
        header_layout.setSpacing(8)
        heading_row = QHBoxLayout()
        heading_row.setContentsMargins(6, 0, 0, 0)
        heading_row.setSpacing(4)
        self.games_heading = QLabel("Existing game configs")
        role(self.games_heading, "paneHeading")
        heading_row.addWidget(self.games_heading, 0, Qt.AlignmentFlag.AlignVCenter)
        heading_row.addStretch()
        self.new_game_button = tool("plus", "New game", self.new_game)
        self.reload_button = tool("refresh-cw", "Reload game configurations", self.reload)
        heading_row.addWidget(self.new_game_button)
        heading_row.addWidget(self.reload_button)
        header_layout.addLayout(heading_row)
        self.game_search = QLineEdit()
        self.game_search.setPlaceholderText("Search games")
        self.game_search.setProperty("librarySearch", True)
        self.game_search.textChanged.connect(self.filter_games)
        header_layout.addWidget(self.game_search)
        self.sidebar = QWidget(window.left)
        role(self.sidebar, "transparent")
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(0, 0, 0, 4)
        self.games = QListWidget()
        self.games.setObjectName("configGames")
        self.games.setItemDelegate(GameListDelegate(self.games))
        self.games.setMouseTracking(True)
        self.games.currentItemChanged.connect(self.select_game)
        side.addWidget(self.games, 1)

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
        self.validation_message = QLabel()
        self.validation_message.setWordWrap(True)
        role(self.validation_message, "error")
        self.validation_message.hide()
        actions.addWidget(self.validation_message, 1)
        self.save_button = action("Save", self.save)
        role(self.save_button, "primary")
        actions.addWidget(self.save_button)
        body.addLayout(actions)
        QApplication.instance().installEventFilter(self)
        for rows in self.findChildren(Rows):
            rows.table.itemSelectionChanged.connect(
                lambda rows=rows: self.select_table(rows)
            )
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
        self.table_edit_hint = QLabel(
            "Add row or double-click empty table space to start a new entry; "
            "click a selected cell or double-click a cell to edit it. "
            "Tab moves to the next cell; Enter on the last row adds another row. "
            "Click outside the tables to clear the selection."
        )
        self.table_edit_hint.setWordWrap(True)
        role(self.table_edit_hint, "secondary")
        form.addRow("", self.table_edit_hint)
        self.prefixes = Rows(
            ["Input prefix"], self.mark_dirty,
            hint="Field names already work as prefixes. Add abbreviations here, such as wpn for weapon.",
        )
        self.values = Rows(["Canonical value"], self.mark_dirty)
        self.aliases = Rows(
            ["Alias", "Canonical value"], self.mark_dirty,
            hint="Map shorthand to a value listed above, such as mp5navy → mp5. "
            "Values and aliases are case-insensitive and cannot match field names or prefixes.",
        )
        self.links = Rows(
            ["Source value", "Target field", "Target value"], self.mark_dirty,
            hint="A source value can fill another field automatically. Use one link row per target value. "
            "Repeated target fields build a multiple-value link; explicit or existing values take priority.",
        )
        form.addRow("Prefix aliases", self.prefixes)
        form.addRow("Enum values", self.values)
        form.addRow("Value aliases", self.aliases)
        form.addRow("Inference links", self.links)
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

    def edit_history(self):
        if self.source is None:
            return None
        return self.histories.setdefault(self.source.path.name, EditHistory())

    def break_history_group(self):
        history = self.edit_history()
        if history:
            history.group = None

    @staticmethod
    def definition_state(definition):
        links = [
            [str(source), target, str(part)]
            for source, targets in definition.get("links", {}).items()
            for target, value in targets.items()
            for part in (value if isinstance(value, list) else [value])
        ]
        return {
            "extra": {key: deepcopy(value) for key, value in definition.items()
                      if key not in {"type", "multiple", "prefixes", "values", "aliases", "links"}},
            "type": definition.get("type", "enum"),
            "multiple": bool(definition.get("multiple", False)),
            "prefixes": [[value] for value in definition.get("prefixes", [])],
            "values": [[value] for value in definition.get("values", [])],
            "aliases": [[key, value] for key, value in definition.get("aliases", {}).items()],
            "links": links,
        }

    def history_state(self):
        repair = not self.tabs.isTabEnabled(0)
        definition = {} if repair else self.draft.get("fields", {}).get(self.field_key, {})
        field = self.definition_state(definition)
        field.update({
            "type": self.field_type.currentText(), "multiple": self.multiple.isChecked(),
            **{key: getattr(self, key).raw_values()
               for key in ("prefixes", "values", "aliases", "links")},
        })
        return deepcopy({
            "draft": self.draft, "field_key": self.field_key, "field": field,
            "name": self.name.text(), "code": self.code.text(), "example": self.example.text(),
            "game_aliases": self.game_aliases.raw_values(),
            "order": [(self.order.item(index).text(), self.order.item(index).checkState())
                      for index in range(self.order.count())],
            "suggested": [(self.suggested.item(index).text(), self.suggested.item(index).checkState())
                          for index in range(self.suggested.count())],
            "repair": repair, "yaml": self.recovery.toPlainText(),
            "tab": self.tabs.currentIndex(),
        })

    def state_content(self, state):
        if state["repair"]:
            return {"yaml": state["yaml"]}
        fields = {key: self.definition_state(value)
                  for key, value in state["draft"].get("fields", {}).items()}
        if state["field_key"] in fields and state["field_key"] not in {"kill", "clutch"}:
            fields[state["field_key"]] = state["field"]
        return {**{key: state[key] for key in
                   ("name", "code", "example", "game_aliases", "order", "suggested")},
                "fields": fields}

    def update_dirty(self):
        if self.source is None or self.loading:
            return
        name = self.source.path.name
        content = self.state_content(self.last_state)
        self.dirty = self.source.digest is None or content != self.state_content(self.saved_states[name])
        self.validate_draft()
        self.save_button.setEnabled(self.dirty and not self.validation_message.text())
        self.revert_button.setEnabled(content != self.state_content(self.initial_states[name]))
        self.window.update_history_controls()

    def validate_draft(self):
        errors = {self.prefixes: {}, self.values: {}, self.aliases: {}, self.links: {}}
        if self.tabs.currentIndex() != 3 and self.field_key in self.draft.get("fields", {}):
            fields = self.draft["fields"]
            canonical = {entry[0] for entry in self.values.values() if entry[0]}
            seen_prefixes = {self.field_key.casefold()}
            for row, (prefix,) in enumerate(self.prefixes.values()):
                if prefix:
                    folded = prefix.casefold()
                    if folded in seen_prefixes:
                        errors[self.prefixes][(row, 0)] = f"Duplicate prefix alias: {prefix}"
                    seen_prefixes.add(folded)
            seen_values = set()
            for row, (value,) in enumerate(self.values.values()):
                if value:
                    folded = value.casefold()
                    if folded in seen_values:
                        errors[self.values][(row, 0)] = f"Duplicate named value: {value}"
                    seen_values.add(folded)
            seen_aliases = set(seen_values)
            for row, (alias, value) in enumerate(self.aliases.values()):
                if alias:
                    folded = alias.casefold()
                    if folded in seen_aliases:
                        errors[self.aliases][(row, 0)] = f"Duplicate value alias: {alias}"
                    seen_aliases.add(folded)
                if alias and value and value not in canonical:
                    errors[self.aliases][(row, 1)] = f"Unknown canonical value: {value}"
            for row, (source, target, value) in enumerate(self.links.values()):
                if not (source or target or value):
                    continue
                if not source:
                    errors[self.links][(row, 0)] = "Link source value is required"
                elif self.field_type.currentText() == "enum" and source not in canonical:
                    errors[self.links][(row, 0)] = f"Unknown source value: {source}"
                if not target:
                    errors[self.links][(row, 1)] = "Link target field is required"
                elif target not in fields:
                    errors[self.links][(row, 1)] = f"Unknown target field: {target}"
                if not value:
                    errors[self.links][(row, 2)] = "Link target value is required"
                elif target in {"kill", "clutch"}:
                    try:
                        number = int(value)
                        if number < (0 if target == "kill" else 1):
                            raise ValueError
                    except ValueError:
                        errors[self.links][(row, 2)] = f"Invalid {target} link value: {value}"
                elif target in fields and fields[target].get("type") == "enum":
                    target_values = (
                        {entry[0] for entry in self.values.values() if entry[0]}
                        if target == self.field_key else set(fields[target].get("values", []))
                    )
                    if value not in target_values:
                        errors[self.links][(row, 2)] = f"Unknown {target} value: {value}"
        for rows, invalid in errors.items():
            rows.set_invalid_cells(invalid)
        try:
            if self.tabs.currentIndex() == 3:
                candidate = yaml_parser().load(self.recovery.toPlainText())
                if not isinstance(candidate, dict):
                    raise ValueError("Game YAML must contain a mapping")
            else:
                candidate = self.collect()
            if (
                self.source.digest is not None
                and isinstance(self.source.document, dict)
                and candidate.get("name") != self.source.document.get("name")
            ):
                raise ValueError("Canonical names of existing games cannot be changed")
            error = next((message for invalid in errors.values() for message in invalid.values()), "")
            if not error:
                validate_candidate(self.directory, self.source.path.name, candidate)
        except Exception as failure:
            error = str(failure)
        self.validation_message.setText(error)
        self.validation_message.setToolTip(error)
        self.validation_message.setVisible(bool(error))
        return error

    def restore_state(self, state):
        self.cancel_revert()
        self.commit_table_edit()
        self.loading = True
        self.draft = deepcopy(state["draft"])
        if state["repair"]:
            self.recovery.setPlainText(state["yaml"])
            for index in range(3):
                self.tabs.setTabEnabled(index, False)
            self.tabs.setTabEnabled(3, True)
            self.tabs.setTabVisible(3, True)
            self.tabs.setCurrentIndex(3)
            self.loading = False
            self.last_state = self.history_state()
            self.update_dirty()
            return
        self.show_draft()
        for index in range(self.fields.count()):
            if self.fields.item(index).text() == state["field_key"]:
                self.fields.setCurrentRow(index)
                break
        self.field_type.setCurrentText(state["field"]["type"])
        self.multiple.setChecked(state["field"]["multiple"])
        for key in ("prefixes", "values", "aliases", "links"):
            getattr(self, key).set_values(state["field"][key])
        self.name.setText(state["name"])
        self.code.setText(state["code"])
        self.example.setText(state["example"])
        self.game_aliases.set_values(state["game_aliases"])
        for key in ("order", "suggested"):
            widget = getattr(self, key)
            widget.clear()
            for text, checked in state[key]:
                item = QListWidgetItem(text)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(checked)
                widget.addItem(item)
        self.recovery.setPlainText(state["yaml"])
        for index in range(3):
            self.tabs.setTabEnabled(index, not state["repair"])
        self.tabs.setTabEnabled(3, state["repair"])
        self.tabs.setTabVisible(3, state["repair"])
        self.tabs.setCurrentIndex(state["tab"])
        self.update_field_rows()
        self.loading = False
        self.last_state = self.history_state()
        self.update_dirty()

    def undo(self, redo=False):
        self.commit_table_edit()
        self.break_history_group()
        history = self.edit_history()
        operation = history.pending(redo) if history else None
        if operation:
            self.restore_state(operation.after if redo else operation.before)
            history.finish(redo)
            self.window.update_history_controls()

    def cancel_revert(self):
        if not self.revert_armed:
            return
        self.revert_armed = False
        self.revert_button.setText("Revert")
        role(self.revert_button, "secondary")

    def select_table(self, selected):
        if not selected.table.selectedItems():
            return
        focus = QApplication.focusWidget()
        if focus is not None and not selected.table.isAncestorOf(focus):
            self.commit_table_edit()
        for rows in self.findChildren(Rows):
            if rows is not selected:
                rows.clear_selection()

    def eventFilter(self, watched, event):
        if (
            self.isVisible()
            and event.type() == QEvent.Type.MouseButtonPress
            and isinstance(watched, QWidget)
        ):
            tables = self.findChildren(Rows)
            target = next(
                (rows for rows in tables
                 if watched is rows.table or rows.table.isAncestorOf(watched)),
                None,
            )
            # Row actions need the current cell until their clicked signal runs.
            row_action = isinstance(watched, QPushButton) and any(
                rows.isAncestorOf(watched) for rows in tables
            )
            if not row_action:
                focus = QApplication.focusWidget()
                if target is None or focus is None or not target.table.isAncestorOf(focus):
                    self.commit_table_edit()
                for rows in tables:
                    if rows is not target:
                        rows.clear_selection()
                if target is not None and watched is target.table.viewport():
                    if not target.table.indexAt(event.position().toPoint()).isValid():
                        self.commit_table_edit()
                        target.clear_selection()
        if self.revert_armed:
            if event.type() == QEvent.Type.MouseButtonPress and watched is not self.revert_button:
                self.cancel_revert()
            elif event.type() == QEvent.Type.KeyPress:
                self.cancel_revert()
                if event.key() == Qt.Key.Key_Escape:
                    return True
        return super().eventFilter(watched, event)

    def mark_dirty(self, *_):
        if not self.loading and self.source is not None:
            self.cancel_revert()
            state = self.history_state()
            if self.last_state and self.state_content(state) != self.state_content(self.last_state):
                focus = QApplication.focusWidget()
                group = focus if isinstance(focus, (QLineEdit, QPlainTextEdit)) else None
                self.edit_history().record(self.last_state, state, group=group)
            self.last_state = state
            self.update_dirty()

    def refresh_files(self, select=None):
        self.games.blockSignals(True)
        self.games.clear()
        for path in sorted(self.directory.glob("*.yaml"), key=lambda value: value.name.casefold()):
            errors = [error for error in self.window.registry.errors if error.startswith(path.name + ":")]
            game = None
            if not errors:
                try:
                    game = self.window.registry.game(GameFile(path).draft()["name"])
                except (OSError, ValueError, TypeError, KeyError, AttributeError):
                    pass
            item = QListWidgetItem(game.name if game else path.stem)
            item.setData(
                GAME_SUMMARY_ROLE,
                f"{game.code} · {len(game.fields)} {'field' if len(game.fields) == 1 else 'fields'}"
                if game else "Invalid configuration",
            )
            item.setData(GAME_SIZE_ROLE, yaml_size_text(path.stat().st_size))
            item.setData(Qt.ItemDataRole.UserRole, path.name)
            self.set_named_value_row(item, game.name if game else None)
            self.games.addItem(item)
            if path.name == select:
                self.games.setCurrentItem(item)
        if self.games.currentItem() is None and self.games.count():
            self.games.setCurrentRow(0)
        self.games.blockSignals(False)
        self.filter_games()
        if self.games.currentItem():
            self.load_game(self.games.currentItem().data(Qt.ItemDataRole.UserRole))
        else:
            self.source = None
            self.tabs.setEnabled(False)
            self.save_button.setEnabled(False)
            self.revert_button.setEnabled(False)

    def set_named_value_row(self, item, game_name):
        count = self.window.named_value_additions[game_name]
        additions = f"(+{count} named {'value' if count == 1 else 'values'})" if count else ""
        item.setData(GAME_ADDITIONS_ROLE, additions)
        item.setToolTip(
            f'{item.text()}\n{item.data(GAME_SUMMARY_ROLE)} · {item.data(GAME_SIZE_ROLE)}'
            + (f" {additions}" if additions else "")
        )

    def refresh_named_value_rows(self):
        # Refresh metadata without switching or replacing an open Config draft.
        for index in range(self.games.count()):
            item = self.games.item(index)
            path = self.directory / item.data(Qt.ItemDataRole.UserRole)
            game = self.window.registry.game(item.text())
            if path.exists():
                item.setData(GAME_SIZE_ROLE, yaml_size_text(path.stat().st_size))
            self.set_named_value_row(item, game.name if game else None)

    def rebase_named_value(self, filename, candidate):
        """Keep registrations in existing snapshots without creating an undo step."""
        def update(state):
            definition = state["draft"].get("fields", {}).get(candidate.field)
            if definition and definition.get("type") == "freeform":
                values = definition.setdefault("values", [])
                if candidate.value.casefold() not in {value.casefold() for value in values}:
                    values.append(candidate.value)
            if state["field_key"] == candidate.field and state["field"]["type"] == "freeform":
                rows = state["field"]["values"]
                if candidate.value.casefold() not in {row[0].casefold() for row in rows if row}:
                    rows.append([candidate.value])

        for states in (self.initial_states, self.saved_states):
            if filename in states:
                update(states[filename])
        for histories in (self.histories, self.saved_histories):
            history = histories.get(filename)
            if history:
                for change in [*history.undo_stack, *history.redo_stack]:
                    update(change.before)
                    update(change.after)
        if self.source and self.source.path.name == filename:
            self.load_game(filename)

    def filter_games(self):
        query = self.game_search.text().strip().casefold()
        for index in range(self.games.count()):
            item = self.games.item(index)
            searchable = (
                item.text(), item.data(GAME_SUMMARY_ROLE) or "",
                item.data(Qt.ItemDataRole.UserRole) or "",
            )
            item.setHidden(bool(query) and not any(query in value.casefold() for value in searchable))

    def confirm_discard(self):
        self.cancel_revert()
        self.commit_table_edit()
        if not self.dirty:
            return True
        self.validate_draft()
        choice = QMessageBox(self)
        choice.setWindowTitle("Unsaved configuration")
        choice.setText("Save changes to the current game configuration?")
        choice.setStandardButtons(
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel
        )
        choice.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if self.validation_message.text():
            choice.button(QMessageBox.StandardButton.Save).setEnabled(False)
            choice.setInformativeText(self.validation_message.text())
        result = choice.exec()
        if result == QMessageBox.StandardButton.Save:
            if self.validation_message.text():
                return False
            return self.save()
        if result == QMessageBox.StandardButton.Discard:
            self.reload_saved()
            return True
        return False

    def commit_table_edit(self):
        editor = QApplication.focusWidget()
        if isinstance(editor, QLineEdit):
            for rows in self.findChildren(Rows):
                if rows.table.isAncestorOf(editor):
                    rows.table.itemDelegate().commitData.emit(editor)
                    rows.table.itemDelegate().closeEditor.emit(
                        editor, QAbstractItemDelegate.EndEditHint.NoHint
                    )
                    break

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
        self.cancel_revert()
        self.loading = True
        self.message("")
        self.source = None
        self.draft = {}
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
        self.loading = False
        self.last_state = self.history_state()
        self.saved_states[filename] = deepcopy(self.last_state)
        self.initial_states.setdefault(filename, deepcopy(self.last_state))
        self.break_history_group()
        if filename not in self.saved_histories:
            self.saved_histories[filename] = deepcopy(self.edit_history())
        self.update_dirty()

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
        was_loading = self.loading
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
        if self.field_key == "kill":
            self.reserved_note.setText(
                "Kill count is a single number entered as XK, such as 3K. "
                "DFSorter parses and displays the count automatically. "
                "Its format and aliases cannot be edited."
            )
        elif self.field_key == "clutch":
            self.reserved_note.setText(
                "Clutch is a single opponent count entered as 1vX, such as 1v4. "
                "It is available when this game includes the clutch field. "
                "Its format and aliases cannot be edited."
            )
        self.field_form.setRowVisible(self.reserved_note, reserved)
        self.field_form.setRowVisible(self.field_type, not reserved)
        self.field_form.setRowVisible(self.multiple, not reserved)
        self.field_form.setRowVisible(self.table_edit_hint, not reserved)
        self.field_type.setCurrentText(definition.get("type", "enum"))
        self.multiple.setChecked(bool(definition.get("multiple", False)))
        self.field_type.setEnabled(not reserved and bool(item))
        self.multiple.setEnabled(not reserved and bool(item))
        self.prefixes.setEnabled(not reserved and bool(item))
        self.values.setEnabled(not reserved and bool(item))
        self.aliases.setEnabled(not reserved and bool(item))
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
        self.loading = was_loading
        if not self.loading:
            self.last_state = self.history_state()
            self.break_history_group()
            self.update_dirty()

    def field_type_changed(self):
        self.update_field_rows()
        self.mark_dirty()

    def update_field_rows(self):
        reserved = self.field_key in {"kill", "clutch"}
        self.field_form.setRowVisible(self.prefixes, not reserved)
        self.field_form.setRowVisible(self.values, not reserved)
        self.field_form.setRowVisible(self.aliases, not reserved)
        freeform = self.field_type.currentText() == "freeform"
        self.field_form.labelForField(self.values).setText(
            "Named values" if freeform else "Enum values"
        )
        self.values.setToolTip(
            "Optional named values accepted without a field prefix. "
            "Other text remains accepted with a field prefix."
            if freeform else "Canonical values accepted for this field."
        )
        self.values.hint.setText(
            "Optional shortcuts: Add mp5 to accept mp5 without a prefix. "
            "Other weapons still accept weapon:othergun."
            if freeform and self.field_key == "weapon" else
            "Optional named values work without a prefix. Other text remains accepted with a prefix."
            if freeform else
            "List accepted values in their stored spelling. Commands accept these values without a prefix."
        )
        self.values.hint.show()
        self.aliases.setToolTip("Accepted shorthand mapped to a configured canonical value.")
        self.field_form.setRowVisible(self.links, not reserved)

    def capture_field(self, draft=None):
        if draft is None:
            draft = self.draft
        if not self.field_key or self.field_key not in draft.get("fields", {}):
            return
        old = draft["fields"][self.field_key]
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
            values = [entry[0] for entry in self.values.values() if entry[0]]
            if values or self.field_type.currentText() == "enum":
                definition["values"] = values
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
            destination = draft["fields"].get(target, {})
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
        draft["fields"][self.field_key] = definition

    def add_field(self):
        before = self.history_state()
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
        definition = {} if key == "clutch" else {"type": "enum", "values": []}
        if key == "weapon":
            definition["prefixes"] = ["wpn"]
        self.draft["fields"][key] = definition
        self.fields.addItem(key)
        self.fields.setCurrentRow(self.fields.count() - 1)
        self.refresh_order()
        self.last_state = before
        self.mark_dirty()

    def remove_field(self):
        before = self.history_state()
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
        self.last_state = before
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
        draft = deepcopy(self.draft)
        self.capture_field(draft)
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
            self.commit_table_edit()
            self.break_history_group()
            self.validate_draft()
            if self.validation_message.text():
                raise ValueError(self.validation_message.text())
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
            history = self.edit_history()
            operation = history.pending()
            self.dirty = False
            self.window.reload_configs()
            self.refresh_files(select=filename)
            if operation:
                operation.after = deepcopy(self.last_state)
            self.saved_histories[filename] = deepcopy(history)
            self.message("Configuration saved.")
            return True
        except Exception as error:
            self.message(str(error), True)
            return False

    def revert(self):
        self.commit_table_edit()
        if self.source is None or not self.revert_button.isEnabled():
            return
        if not self.revert_armed:
            self.revert_armed = True
            self.revert_button.setText("Confirm revert")
            role(self.revert_button, "danger")
            return
        before = self.history_state()
        self.restore_state(self.initial_states[self.source.path.name])
        self.edit_history().record(before, self.last_state)
        self.window.update_history_controls()
        self.message("Initial configuration restored as a draft. Save to apply it.")

    def reload_saved(self):
        self.cancel_revert()
        if self.source is None:
            return
        filename = self.source.path.name
        self.histories[filename] = deepcopy(self.saved_histories.get(filename, EditHistory()))
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
        filename = self.source.path.name
        self.last_state = self.history_state()
        self.histories[filename] = EditHistory()
        self.initial_states[filename] = deepcopy(self.last_state)
        self.saved_states[filename] = deepcopy(self.last_state)
        self.update_dirty()
        self.message("New game draft. Add a two- or three-character uppercase display code before saving.")
