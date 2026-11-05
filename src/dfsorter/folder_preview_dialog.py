from collections import Counter
from ntpath import basename, splitdrive

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .folder_assignment import MODES, assigned_game
from .theme import COLORS, font, role
from .widgets import icon


class AssignmentControls(QWidget):
    def __init__(self, games, mode="automatic", game=None):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        row = QHBoxLayout()
        label = QLabel("Game assignment")
        label.setFont(font("base", "semibold"))
        row.addWidget(label)
        self.mode = QComboBox()
        for value, label in MODES.items():
            self.mode.addItem(label, value)
        row.addWidget(self.mode, 1)
        layout.addLayout(row)
        self.game = QComboBox()
        self.game.addItem("Select a game…", None)
        for name in games:
            self.game.addItem(name, name)
        if game and game not in games:
            self.game.addItem(f"{game} (configuration unavailable)", game)
        self.games = games
        layout.addWidget(self.game)
        note = QLabel(
            "Applies to this folder, all subfolders, and future discoveries. "
            "Existing assigned games remain unchanged; missing games can be filled on later scans."
        )
        note.setWordWrap(True)
        role(note, "muted")
        layout.addWidget(note)
        guidance = QLabel("Additional games can be added from Game configs… on Home.")
        guidance.setWordWrap(True)
        role(guidance, "muted")
        layout.addWidget(guidance)
        self.mode.setCurrentIndex(self.mode.findData(mode))
        self.game.setCurrentIndex(max(0, self.game.findData(game)))
        self.mode.currentIndexChanged.connect(self.update_visibility)
        self.update_visibility()

    def update_visibility(self):
        self.game.setVisible(self.mode.currentData() == "single_game")

    @property
    def valid(self):
        return self.mode.currentData() != "single_game" or self.game.currentData() in self.games

    @property
    def selected_game(self):
        return self.game.currentData() if self.mode.currentData() == "single_game" else None


def icon_label(name, color="text_secondary"):
    label = QLabel()
    label.setPixmap(icon(name, COLORS[color], size=16).pixmap(16, 16))
    label.setFixedSize(16, 16)
    return label


class FolderPathLabel(QLabel):
    def __init__(self, directory):
        super().__init__()
        self.directory = directory
        self.setToolTip(directory)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_text()

    def update_text(self):
        width = self.contentsRect().width()
        metrics = self.fontMetrics()
        display = metrics.elidedText(self.directory, Qt.TextElideMode.ElideMiddle, width)
        folder_name = basename(self.directory.rstrip("/\\"))
        if folder_name and folder_name not in display:
            drive, _ = splitdrive(self.directory)
            separator = "\\" if "\\" in self.directory else "/"
            prefix = f"{drive}{separator}" if drive else separator
            candidate = f"{prefix}…{separator}{folder_name}"
            if metrics.horizontalAdvance(candidate) > width and drive:
                candidate = f"{drive}…{separator}{folder_name}"
            display = (
                candidate
                if metrics.horizontalAdvance(candidate) <= width
                else metrics.elidedText(folder_name, Qt.TextElideMode.ElideRight, width)
            )
        self.setText(display)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        copy_path = menu.addAction("Copy full path")
        if menu.exec(event.globalPos()) == copy_path:
            QApplication.clipboard().setText(self.directory)


class ResultScrollArea(QScrollArea):
    def __init__(self, row_count):
        super().__init__()
        self.row_count = row_count
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def sizeHint(self):
        row_height = self.fontMetrics().height() + 12
        return QSize(400, min(self.row_count, 6) * row_height + 2)


class FolderPreviewDialog(QDialog):
    def __init__(self, directory, found, games, parent=None, *, game_folder=False,
                 assignment_mode="automatic", selected_game=None, folder=None,
                 save_handler=None, remove_handler=None):
        super().__init__(parent)
        self.setWindowTitle("Manage capture folder" if folder else "Add capture folder")
        self.folder = folder
        self.save_handler = save_handler
        self.remove_handler = remove_handler
        self.setMinimumWidth(550)
        self.directory = directory
        self.edit_directory = None
        self.found = found
        self.unclassified_count = sum(item["game"] is None for item in found)
        self.warnings = sum(bool(item.get("error")) for item in found)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(0)

        content_scroll = QScrollArea()
        content_scroll.setWidgetResizable(True)
        content_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_scroll.setWidget(content)
        layout.addWidget(content_scroll, 1)

        folder_row = QHBoxLayout()
        folder_row.setSpacing(8)
        folder_label = QLabel("Folder")
        folder_label.setFont(font("base", "semibold"))
        folder_row.addWidget(folder_label)
        path_field = QWidget()
        path_field.setObjectName("folderPreviewPath")
        path_layout = QHBoxLayout(path_field)
        path_layout.setContentsMargins(10, 6, 10, 6)
        path_layout.setSpacing(8)
        path_layout.addWidget(icon_label("folder"))
        self.folder_path = FolderPathLabel(directory)
        path_layout.addWidget(self.folder_path, 1)
        folder_row.addWidget(path_field, 1)
        edit_folder = QPushButton("Relink folder…" if folder else "Edit folder…")
        edit_folder.clicked.connect(self.choose_folder)
        folder_row.addWidget(edit_folder)
        content_layout.addLayout(folder_row)
        content_layout.addSpacing(12)
        if folder:
            status = QLabel("Scanning: " + ("Enabled" if folder["enabled"] else "Paused"))
            role(status, "secondary")
            content_layout.addWidget(status)
            content_layout.addSpacing(12)
        self.assignment = AssignmentControls(games, assignment_mode, selected_game)
        self.game = self.assignment.game
        content_layout.addWidget(self.assignment)
        content_layout.addSpacing(12)

        result_heading = QHBoxLayout()
        result_heading.setSpacing(8)
        result_heading.addWidget(icon_label("video"))
        self.summary = QLabel(("Catalogue: " if folder else "") + f"{len(found)} video{'s' if len(found) != 1 else ''}" + (" saved" if folder else " found"))
        self.summary.setFont(font("base", "semibold"))
        result_heading.addWidget(self.summary, 1)
        content_layout.addLayout(result_heading)
        content_layout.addSpacing(4)

        counts = Counter(item["game"] or "Unclassified" for item in found)
        self.composition = QWidget()
        composition_layout = QVBoxLayout(self.composition)
        composition_layout.setContentsMargins(24, 0, 0, 0)
        composition_layout.setSpacing(0)
        self.result_rows = []
        for game, count in sorted(
            counts.items(), key=lambda item: (item[0] == "Unclassified", item[0])
        ):
            entry = QWidget()
            entry.setObjectName("folderPreviewResultRow")
            entry_layout = QHBoxLayout(entry)
            entry_layout.setContentsMargins(0, 5, 0, 5)
            entry_layout.setSpacing(12)
            name = QLabel(game)
            name.setWordWrap(True)
            role(name, "secondary")
            amount = QLabel(str(count))
            amount.setFont(font("md", "semibold"))
            entry_layout.addWidget(name, 1)
            entry_layout.addWidget(amount, 0, Qt.AlignmentFlag.AlignRight)
            composition_layout.addWidget(entry)
            self.result_rows.append((entry, name, amount))
        self.results_scroll = ResultScrollArea(len(counts))
        self.results_scroll.setWidget(self.composition)
        content_layout.addWidget(self.results_scroll)

        explanation = QLabel("Automatic detection uses the nearest recognized folder name, including the selected folder.")
        explanation.setWordWrap(True)
        role(explanation, "muted")
        content_layout.addSpacing(6)
        content_layout.addWidget(explanation)
        if self.warnings:
            warning = QLabel(
                f"{self.warnings} media inspection warning{'s' if self.warnings != 1 else ''}"
            )
            role(warning, "muted")
            content_layout.addSpacing(4)
            content_layout.addWidget(warning)

        self.parent_folder_tip = QWidget()
        self.parent_folder_tip.setObjectName("folderPreviewTip")
        tip_layout = QHBoxLayout(self.parent_folder_tip)
        tip_layout.setContentsMargins(10, 8, 10, 8)
        tip_layout.setSpacing(8)
        tip_layout.addWidget(icon_label("info", "accent_default"))
        tip_text = QLabel(
            "To include other game folders, use Edit folder… to select their parent recordings folder."
        )
        tip_text.setWordWrap(True)
        tip_layout.addWidget(tip_text, 1)
        self.game_folder = game_folder
        content_layout.addSpacing(12)
        content_layout.addWidget(self.parent_folder_tip)

        self.assignment_note = QLabel()
        self.assignment_note.setWordWrap(True)
        role(self.assignment_note, "muted")
        content_layout.addWidget(self.assignment_note)

        layout.addSpacing(12)
        layout.addWidget(self.divider())
        layout.addSpacing(12)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        if folder:
            self.remove_button = QPushButton("Remove folder…")
            role(self.remove_button, "danger")
            self.remove_button.clicked.connect(self.remove_saved_folder)
            actions.addWidget(self.remove_button)
            actions.addSpacing(24)
        actions.addStretch()
        add = QPushButton("Save" if folder else "Add folder")
        self.add_button = add
        role(add, "primary")
        add.setDefault(True)
        add.clicked.connect(self.save)
        actions.addWidget(add)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        layout.addLayout(actions)
        self.game.currentIndexChanged.connect(self.update_assignment_note)
        self.assignment.mode.currentIndexChanged.connect(self.update_assignment_note)
        self.update_assignment_note()

        screen = self.screen() or QApplication.primaryScreen()
        self.setMaximumHeight(int(screen.availableGeometry().height() * 0.85))

    def save(self):
        if self.assignment.valid and (self.save_handler is None or self.save_handler(self)):
            self.accept()

    def remove_saved_folder(self):
        if self.remove_handler and self.remove_handler():
            self.reject()

    @staticmethod
    def divider():
        line = QWidget()
        line.setProperty("role", "divider")
        line.setFixedHeight(1)
        return line

    @property
    def forced_game(self):
        return self.assignment.selected_game

    @property
    def assignment_mode(self):
        return self.assignment.mode.currentData()

    def assigned_items(self):
        return [
            {**item, "game": assigned_game(item["game"], self.assignment_mode, self.forced_game)}
            for item in self.found
        ]

    def choose_folder(self):
        directory = QFileDialog.getExistingDirectory(self, "Capture folder", self.directory)
        if directory:
            self.edit_directory = directory
            if self.folder:
                self.directory = directory
                self.folder_path.directory = directory
                self.folder_path.setToolTip(directory)
                self.folder_path.update_text()
            else:
                self.reject()

    def update_assignment_note(self):
        self.add_button.setEnabled(self.assignment.valid)
        self.parent_folder_tip.setVisible(not self.folder and self.game_folder and self.assignment_mode == "automatic")
        counts = Counter(item["game"] or "Unclassified" for item in (self.found if self.folder else self.assigned_items()))
        entries = sorted(counts.items(), key=lambda item: (item[0] == "Unclassified", item[0]))
        for index, (entry, name, amount) in enumerate(self.result_rows):
            entry.setVisible(index < len(entries))
            if index < len(entries):
                name.setText(entries[index][0])
                amount.setText(str(entries[index][1]))
        self.results_scroll.row_count = len(entries)
        self.results_scroll.updateGeometry()
        conflicts = sum(bool(item["game"]) and item["game"] != self.forced_game for item in self.found)
        self.assignment_note.setText(
            f"{conflicts} video{'s' if conflicts != 1 else ''} detected as other games will be assigned to {self.forced_game}."
            if not self.folder and self.forced_game and conflicts else ""
        )
