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

from .theme import COLORS, font, role
from .widgets import icon


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
    def __init__(self, directory, found, games, parent=None, *, game_folder=False):
        super().__init__(parent)
        self.setWindowTitle("Add capture folder")
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
        edit_folder = QPushButton("Edit folder…")
        edit_folder.clicked.connect(self.choose_folder)
        folder_row.addWidget(edit_folder)
        content_layout.addLayout(folder_row)
        content_layout.addSpacing(12)

        result_heading = QHBoxLayout()
        result_heading.setSpacing(8)
        result_heading.addWidget(icon_label("video"))
        self.summary = QLabel(f"{len(found)} video{'s' if len(found) != 1 else ''} found")
        self.summary.setFont(font("base", "semibold"))
        result_heading.addWidget(self.summary, 1)
        content_layout.addLayout(result_heading)
        content_layout.addSpacing(4)

        counts = Counter(item["game"] or "Unclassified" for item in found)
        self.composition = QWidget()
        composition_layout = QVBoxLayout(self.composition)
        composition_layout.setContentsMargins(24, 0, 0, 0)
        composition_layout.setSpacing(0)
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
        if counts:
            self.results_scroll = ResultScrollArea(len(counts))
            self.results_scroll.setWidget(self.composition)
            content_layout.addWidget(self.results_scroll)

        explanation = QLabel("Games are detected from the selected folder and its subfolders.")
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
        self.parent_folder_tip.setVisible(game_folder)
        if game_folder:
            content_layout.addSpacing(12)
            content_layout.addWidget(self.parent_folder_tip)

        self.override_section = QWidget()
        override_layout = QVBoxLayout(self.override_section)
        override_layout.setContentsMargins(0, 0, 0, 0)
        override_layout.setSpacing(4)
        override_row = QHBoxLayout()
        override_row.setSpacing(8)
        override_title = QLabel("Unclassified videos")
        override_title.setFont(font("base", "semibold"))
        override_row.addWidget(override_title)
        self.game = QComboBox()
        self.game.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.game.addItem("Keep unclassified", None)
        for game in games:
            self.game.addItem(game, game)
        override_row.addWidget(self.game, 1)
        override_layout.addLayout(override_row)
        self.assignment_note = QLabel()
        self.assignment_note.setWordWrap(True)
        role(self.assignment_note, "muted")
        override_layout.addWidget(self.assignment_note)
        game_configs_tip = QLabel("Additional games can be added from Game configs… on Home.")
        game_configs_tip.setWordWrap(True)
        role(game_configs_tip, "muted")
        override_layout.addWidget(game_configs_tip)
        if self.unclassified_count:
            content_layout.addSpacing(12)
            content_layout.addWidget(self.override_section)
        else:
            self.override_section.hide()
        self.game.currentIndexChanged.connect(self.update_assignment_note)
        self.update_assignment_note()

        layout.addSpacing(12)
        layout.addWidget(self.divider())
        layout.addSpacing(12)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        actions.addStretch()
        add = QPushButton("Add folder")
        role(add, "primary")
        add.setDefault(True)
        add.clicked.connect(self.accept)
        actions.addWidget(add)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        layout.addLayout(actions)

        screen = self.screen() or QApplication.primaryScreen()
        self.setMaximumHeight(int(screen.availableGeometry().height() * 0.85))

    @staticmethod
    def divider():
        line = QWidget()
        line.setProperty("role", "divider")
        line.setFixedHeight(1)
        return line

    @property
    def forced_game(self):
        return self.game.currentData()

    def choose_folder(self):
        directory = QFileDialog.getExistingDirectory(self, "Capture folder", self.directory)
        if directory:
            self.edit_directory = directory
            self.reject()

    def update_assignment_note(self):
        videos = f"{self.unclassified_count} unidentified video"
        if self.unclassified_count != 1:
            videos += "s"
        if self.forced_game:
            self.assignment_note.setText(
                f"{videos} will be assigned to {self.forced_game} during import."
            )
        else:
            self.assignment_note.setText(f"{videos} will remain unclassified.")
