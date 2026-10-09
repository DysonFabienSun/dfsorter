"""Modal project output setup. Only successful enqueueing persists choices."""

import sqlite3
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .output import check_destination, export_title, prepare_export_manifest, safe_stem
from .theme import role
from .widgets import UNDERLINE_ROLE, FlowLayout, UnderlinedComboBox


def normalized_preferences(saved, games, registry, fallback_destination):
    options = deepcopy(saved)
    formats = options.setdefault("formats", {})
    # Keep choices for games no longer represented in this project, but drop removed fields.
    for name in set(formats) | set(games):
        game = registry.game(name)
        if not game:
            formats.pop(name, None)
            continue
        previous = formats.get(name)
        formats[name] = {
            "fields": [
                field
                for field in game.display_order
                if previous is None or field in previous.get("fields", game.display_order)
            ],
            "prefix": previous.get("prefix", True) if previous else True,
        }
    options.setdefault("destination", fallback_destination)
    options.setdefault("group_rating", False)
    options.setdefault("include_rating", True)
    return options


class ProjectExportDialog(QDialog):
    def __init__(self, window, project_id):
        super().__init__(window)
        self.window = window
        self.project_id = project_id
        self.project = next(
            project
            for project in window.catalogue.projects()
            if project["project_id"] == project_id
        )
        self.job_id = None
        self.setWindowTitle(f"Export · {self.project['name']}")
        self.resize(640, 320)
        self.options = normalized_preferences(
            self.project["output_preferences"],
            {clip["game"] for clip in self.clips()},
            window.registry,
            window.settings.get("export_folder", ""),
        )
        body = QVBoxLayout(self)
        explanation = QLabel(
            "Copy whole source files using the project's current memberships and verdicts."
        )
        explanation.setWordWrap(True)
        role(explanation, "secondary")
        body.addWidget(explanation)
        body.addWidget(QLabel("Output folder"))
        row = QHBoxLayout()
        self.destination = QLineEdit(self.options["destination"])
        self.destination.setAccessibleName("Export output folder")
        row.addWidget(self.destination, 1)
        choose = QPushButton("Choose…")
        choose.clicked.connect(self.choose_folder)
        row.addWidget(choose)
        body.addLayout(row)
        self.game = UnderlinedComboBox()
        self.game.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.game.setMinimumContentsLength(12)
        self.game.setAccessibleName("Filename options for game")
        self.examples = {}
        for clip in self.clips():
            if clip["triage"] == "keep" and window.registry.game(clip["game"]):
                self.examples.setdefault(clip["game"], clip)
        for name in sorted(self.examples):
            self.game.addItem(name, name)
        self.refresh_game_labels()
        body.addWidget(self.game)
        self.fields = QFrame()
        role(self.fields, "outlinedGroup")
        self.fields.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.field_layout = QVBoxLayout(self.fields)
        self.field_layout.setContentsMargins(12, 12, 12, 12)
        self.field_layout.setSpacing(8)
        body.addWidget(self.fields)
        self.include_rating = QCheckBox("Include rating in filename")
        self.include_rating.setChecked(self.options["include_rating"])
        self.include_rating.toggled.connect(self.toggle_rating)
        body.addWidget(self.include_rating)
        self.group_rating = QCheckBox("Group by Rating")
        self.group_rating.setChecked(self.options["group_rating"])
        body.addWidget(self.group_rating)
        body.addStretch()
        self.error = QLabel()
        self.error.setWordWrap(True)
        role(self.error, "error")
        body.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)
        self.submit_button = buttons.addButton("Export", QDialogButtonBox.ButtonRole.AcceptRole)
        role(self.submit_button, "primary")
        self.submit_button.clicked.connect(self.submit)
        body.addWidget(buttons)
        self.game.currentIndexChanged.connect(self.show_fields)
        self.destination.textChanged.connect(self.refresh_submission)
        self.show_fields()
        self.refresh_submission()

    def clips(self):
        ids = self.window.catalogue.member_ids(self.project_id)
        return [clip for clip in self.window.catalogue.clips() if clip["clip_id"] in ids]

    def show_fields(self):
        while self.field_layout.count():
            item = self.field_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        game = self.window.registry.game(self.game.currentData())
        if not game:
            return
        options = self.options["formats"][game.name]
        prefix = QCheckBox(f"Game code prefix [{game.code}]")
        prefix.setChecked(options["prefix"])

        def toggle_prefix(checked):
            options.update(prefix=checked)
            self.refresh_game_labels()

        prefix.toggled.connect(toggle_prefix)
        self.field_layout.addWidget(prefix)
        field_row = QWidget()
        flow = FlowLayout(field_row)
        self.field_layout.addWidget(field_row)
        for field in game.display_order:
            control = QCheckBox(field)
            control.setChecked(field in options["fields"])

            def toggle(checked, field=field):
                chosen = set(options["fields"])
                chosen.add(field) if checked else chosen.discard(field)
                options["fields"] = [name for name in game.display_order if name in chosen]
                self.refresh_game_labels()

            control.toggled.connect(toggle)
            flow.addWidget(control)

    def toggle_rating(self, checked):
        self.options["include_rating"] = checked
        self.refresh_game_labels()

    def refresh_game_labels(self):
        for index in range(self.game.count()):
            name = self.game.itemData(index)
            game = self.window.registry.game(name)
            clip = self.examples[name]
            options = self.options["formats"][name]
            spans = []
            stem = safe_stem(export_title(
                clip, self.window.registry, options["fields"], options["prefix"],
                lowercase=self.window.settings.get("lowercase_generated_titles", True),
                include_rating=self.options["include_rating"],
                text_spans=spans,
            ), text_spans=spans)
            filename = stem + Path(clip["source_path"]).suffix
            self.game.setItemText(index, f"{game.code} · {filename}")
            self.game.setItemData(index, [
                (start + len(game.code) + 3, length)
                for field, start, length in spans if field == "mainline"
            ], UNDERLINE_ROLE)
            self.game.setItemData(index, f"{game.name} · {filename}", Qt.ItemDataRole.ToolTipRole)

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Export folder", self.destination.text())
        if folder:
            self.destination.setText(folder)

    def refresh_submission(self):
        self.submit_button.setEnabled(
            any(clip["triage"] != "discard" for clip in self.clips())
            and bool(self.destination.text().strip())
        )

    def submit(self):
        window = self.window
        if not window.ensure_range_complete():
            return
        self.refresh_submission()
        if not self.submit_button.isEnabled():
            return
        if window.worker is not None or window.close_requested:
            self.error.setText("Wait for the current operation to finish")
            return
        try:
            destination = self.destination.text().strip()
            root = check_destination(destination, window.catalogue.folders())
            if root.exists() and not root.is_dir():
                raise ValueError("Output destination must be a folder")
            # Reject an existing file in any parent position without creating output folders.
            if any(parent.exists() and not parent.is_dir() for parent in root.parents):
                raise ValueError("Output destination has a file in its folder path")
            clips = self.clips()
            options = normalized_preferences(
                self.options,
                {clip["game"] for clip in clips},
                window.registry,
                destination,
            )
            options.update(destination=destination, group_rating=self.group_rating.isChecked())
            lowercase = window.settings.get("lowercase_generated_titles", True)
            manifest = prepare_export_manifest(
                clips,
                window.registry,
                destination,
                window.catalogue.folders(),
                options["formats"],
                options["group_rating"],
                lowercase=lowercase,
                include_rating=options["include_rating"],
                defer_validation=True,
            )
            manifest["project_name"] = self.project["name"]
            manifest["choices"] = {
                "project_id": self.project_id,
                "formats": options["formats"],
                "group_rating": options["group_rating"],
                "include_rating": options["include_rating"],
                "lowercase": lowercase,
            }
            job_id = str(uuid4())
            window.catalogue.enqueue_project_export(
                self.project_id,
                job_id,
                manifest,
                options,
                expected_clips=clips,
            )
        except (ValueError, OSError, sqlite3.Error) as error:
            self.error.setText(str(error))
            return
        self.job_id = job_id
        window.settings["export_folder"] = destination
        try:
            window.save_settings()
        except OSError as error:
            window.statusBar().showMessage(
                f"Job queued; application preferences could not be saved: {error}", 12000
            )
        self.accept()
        window.add_export_job(job_id, f"Export · {self.project['name']}")
