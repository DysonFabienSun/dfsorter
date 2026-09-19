"""Read-only library preview and disposable share controls."""

from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .config import title
from .deletion import delete_reviewed, preview
from .output import share_clip
from .playback import Player
from .theme import COLORS, role, title_styles
from .widgets import icon, tool


class BrowsePage(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.clip = None
        self.in_ms = self.out_ms = None
        self.initial_range = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.player = Player(window.settings)
        self.player.previous.connect(lambda: window.navigate(-1))
        self.player.next.connect(lambda: window.navigate(1))
        layout.addWidget(self.player, 1)
        self.working_title = QLabel()
        self.working_title.setWordWrap(True)
        self.working_title.setObjectName("workingTitle")
        self.working_title.setTextFormat(Qt.TextFormat.RichText)
        self.filename = QLabel()
        self.filename.setTextFormat(Qt.TextFormat.PlainText)
        self.filename.setWordWrap(True)
        role(self.filename, "secondary")
        title_row = QHBoxLayout()
        title_row.setSpacing(12)
        title_row.addWidget(self.working_title, 1)
        self.delete_button = tool("trash-2", "Delete source…", self.delete_source)
        self.delete_button.setIcon(icon("trash-2", COLORS["danger"]))
        self.delete_button.setStyleSheet(
            f"QToolButton {{ border: 1px solid {COLORS['danger']}; "
            f"background: {COLORS['danger_muted']}; border-radius: 4px; }}"
            f"QToolButton:hover {{ border-color: {COLORS['danger_hover']}; }}"
        )
        title_row.addWidget(self.delete_button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(title_row)
        layout.addWidget(self.filename)
        self.marker_buttons = []
        for icon_name, label, callback in [
            ("list-start", "Set In · I", lambda: self.mark("in")),
            ("list-end", "Set Out · O", lambda: self.mark("out")),
            ("brackets", "Clear range", self.clear_range),
        ]:
            control = tool(icon_name, label, callback)
            self.player.controls.addWidget(control)
            self.marker_buttons.append(control)
        form = QGridLayout()
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(6)
        form.setColumnStretch(5, 1)
        self.custom_title = QLineEdit()
        self.custom_title.setPlaceholderText("Required; .mp4 is appended")
        self.custom_title.setAccessibleName("Custom title")
        self.custom_title.textChanged.connect(self.update_share)
        form.addWidget(QLabel("Custom title"), 0, 0)
        form.addWidget(self.custom_title, 0, 1, 1, 4)
        self.destination = QLineEdit(window.settings.get("share_folder", ""))
        self.destination.setFixedWidth(480)
        self.destination.setAccessibleName("Share output folder")
        self.destination.textChanged.connect(self.update_share)
        form.addWidget(QLabel("Output folder"), 1, 0)
        form.addWidget(self.destination, 1, 1)
        choose = tool("folder-open", "Choose output folder…", self.choose_folder)
        form.addWidget(choose, 1, 2)
        self.mode = QComboBox()
        self.mode.addItem("Whole clip", False)
        self.mode.addItem("Selected range", True)
        self.mode.currentIndexChanged.connect(self.update_share)
        self.mode.setFixedWidth(140)
        mode_label = QLabel("Share")
        mode_label.setContentsMargins(12, 0, 0, 0)
        form.addWidget(mode_label, 1, 3)
        form.addWidget(self.mode, 1, 4)
        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background: {COLORS['border_subtle']};")
        layout.addWidget(divider)
        layout.addLayout(form)
        layout.addSpacing(10)
        self.range_status = QLabel()
        role(self.range_status, "secondary")
        layout.addWidget(self.range_status)
        footer = QHBoxLayout()
        info = QLabel("H.264 MP4 · All audio tracks mixed to stereo AAC")
        role(info, "secondary")
        footer.addWidget(info, 1)
        self.share_button = QPushButton("Share")
        self.share_button.clicked.connect(self.share)
        footer.addWidget(self.share_button)
        layout.addLayout(footer)
        self.player.loading_finished.connect(self.refresh_range)
        self.player.media.durationChanged.connect(self.refresh_range)
        self.refresh_range()

    def load(self, clip):
        if clip and self.clip and clip["clip_id"] == self.clip["clip_id"]:
            return
        self.clip = deepcopy(clip)
        self.in_ms = clip["in_ms"] if clip else None
        self.out_ms = clip["out_ms"] if clip else None
        self.initial_range = bool(clip)
        self.custom_title.clear()
        self.render_title()
        self.player.load(clip)
        self.refresh_range(default=True)

    def render_title(self):
        self.working_title.setText(
            title(self.clip, self.window.registry, rich=True, mainline_separator=" | ",
                  lowercase=self.window.settings.get("lowercase_generated_titles", True),
                  rich_styles=title_styles()) if self.clip else ""
        )
        self.filename.setText(Path(self.clip["source_path"]).name if self.clip else "")

    def leave(self):
        self.clip = None
        self.in_ms = self.out_ms = None
        self.custom_title.clear()
        self.player.load(None)
        self.render_title()
        self.refresh_range()

    def valid_range(self):
        return (
            isinstance(self.in_ms, int) and isinstance(self.out_ms, int)
            and 0 <= self.in_ms < self.out_ms <= self.player.media.duration()
        )

    def mark(self, endpoint):
        if not self.clip or not self.player.media.duration():
            return
        if endpoint == "in":
            self.in_ms = self.player.media.position()
        else:
            self.out_ms = self.player.media.position()
        self.refresh_range(default=True)

    def clear_range(self):
        self.in_ms = self.out_ms = None
        self.refresh_range(default=True)

    def refresh_range(self, *args, default=False):
        valid = self.valid_range()
        if self.initial_range and self.player.media.duration() > 0:
            default = True
            self.initial_range = False
        slider = self.player.seek
        slider.marker_range = (self.in_ms, self.out_ms) if valid else (None, None)
        slider.pending_in = None if valid else self.in_ms
        slider.pending_out = None if valid else self.out_ms
        slider.update()
        self.mode.model().item(1).setEnabled(valid)
        if default or (self.mode.currentData() and not valid):
            self.mode.setCurrentIndex(1 if valid else 0)
        if valid:
            self.range_status.setText(
                f"Temporary range · {self.in_ms / 1000:.3f}–{self.out_ms / 1000:.3f}s"
                f" · {(self.out_ms - self.in_ms) / 1000:.3f}s"
            )
        elif self.in_ms is not None or self.out_ms is not None:
            self.range_status.setText("I/O incomplete or invalid · correct markers to share range")
        else:
            self.range_status.setText("I/O changes apply to this preview only")
        self.update_share()

    def update_share(self, *args):
        # Signals may fire while controls are still being constructed.
        if not hasattr(self, "share_button"):
            return
        available = bool(self.clip and Path(self.clip["source_path"]).is_file())
        self.delete_button.setEnabled(available)
        for control in self.marker_buttons:
            control.setEnabled(available and self.player.media.duration() > 0)
        self.share_button.setEnabled(
            available and bool(self.custom_title.text().strip())
            and bool(self.destination.text().strip())
            and (not self.mode.currentData() or self.valid_range())
        )

    def delete_source(self):
        if not self.clip or self.window.worker is not None:
            return
        candidates = preview(self.window.catalogue, self.window.media_info, clip_id=self.clip["clip_id"])
        if not candidates:
            return
        candidate = candidates[0]
        if candidate.problem:
            self.window.error(candidate.problem)
            return
        answer = QMessageBox.warning(
            self, "Delete source permanently?",
            f"Permanently delete this video?\n{candidate.display_path or candidate.path}\n\n"
            "Bypasses the Recycle Bin and cannot be undone. "
            "Catalogue records and project/session references remain as unavailable.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.player.load(None)
        self.window.player.load(None)
        self.window.export_player.load(None)

        def done(results):
            self.leave()
            self.window.refresh_library()
            self.window.statusBar().showMessage(results[0][1], 12000)

        self.window.background(
            lambda cancelled, progress: delete_reviewed(
                self.window.catalogue, candidates, cancelled=cancelled,
                progress=progress, require_discard=False,
            ), done,
        )

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Share folder", self.destination.text())
        if folder:
            self.destination.setText(folder)

    def share(self):
        self.update_share()
        if not self.share_button.isEnabled():
            return
        clip = deepcopy(self.clip)
        clip.update(in_ms=self.in_ms, out_ms=self.out_ms)
        custom = self.custom_title.text().strip()
        destination = self.destination.text().strip()
        selected_range = self.mode.currentData()
        folders = self.window.catalogue.folders()
        self.window.settings["share_folder"] = destination
        self.window.save_settings()
        self.window.background(
            lambda cancelled, progress: share_clip(
                clip, self.window.registry, destination, folders, custom=custom,
                selected_range=selected_range, cancelled=cancelled, progress=progress,
            ),
            lambda target: QMessageBox.information(self, "Shared", f"Shared H.264 MP4 to:\n{target}"),
        )
