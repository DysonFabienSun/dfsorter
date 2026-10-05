"""Modal project output setup. Only successful enqueueing persists choices."""

import sqlite3
from copy import deepcopy
from uuid import uuid4

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .output import check_destination, prepare_export_manifest
from .project_workspace import project_readiness
from .theme import role


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
        self.resize(640, 540)
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
        self.game = QComboBox()
        self.game.setAccessibleName("Filename options for game")
        self.game.addItems(
            sorted({clip["game"] for clip in self.clips() if window.registry.game(clip["game"])})
        )
        body.addWidget(self.game)
        self.fields = QWidget()
        self.field_layout = QGridLayout(self.fields)
        self.field_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.fields)
        body.addWidget(scroll)
        self.group_rating = QCheckBox("Group by Rating")
        self.group_rating.setChecked(self.options["group_rating"])
        body.addWidget(self.group_rating)
        self.readiness = QLabel()
        self.readiness.setWordWrap(True)
        body.addWidget(self.readiness)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setAccessibleName("Project readiness details")
        body.addWidget(self.details, 1)
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
        self.destination.textChanged.connect(self.refresh_readiness)
        self.show_fields()
        self.refresh_readiness()

    def clips(self):
        ids = self.window.catalogue.member_ids(self.project_id)
        return [clip for clip in self.window.catalogue.clips() if clip["clip_id"] in ids]

    def show_fields(self):
        while self.field_layout.count():
            item = self.field_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        game = self.window.registry.game(self.game.currentText())
        if not game:
            return
        options = self.options["formats"][game.name]
        prefix = QCheckBox("Game code prefix")
        prefix.setChecked(options["prefix"])
        prefix.toggled.connect(lambda checked: options.update(prefix=checked))
        self.field_layout.addWidget(prefix, 0, 0, 1, 2)
        for index, field in enumerate(game.display_order):
            control = QCheckBox(field)
            control.setChecked(field in options["fields"])

            def toggle(checked, field=field):
                chosen = set(options["fields"])
                chosen.add(field) if checked else chosen.discard(field)
                options["fields"] = [name for name in game.display_order if name in chosen]

            control.toggled.connect(toggle)
            self.field_layout.addWidget(control, index // 3 + 1, index % 3)

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Export folder", self.destination.text())
        if folder:
            self.destination.setText(folder)

    def refresh_readiness(self):
        categories, errors = project_readiness(self.clips(), self.window.registry)
        self.readiness.setText(" · ".join(f"{name} {len(ids)}" for name, ids in categories.items()))
        self.details.setPlainText("\n".join(errors.values()) or "No blocking clips.")
        role(self.details, "error" if errors else "secondary")
        self.submit_button.setEnabled(
            bool(categories["Ready"]) and not errors and bool(self.destination.text().strip())
        )

    def submit(self):
        window = self.window
        self.refresh_readiness()
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
            )
            manifest["project_name"] = self.project["name"]
            manifest["choices"] = {
                "project_id": self.project_id,
                "formats": options["formats"],
                "group_rating": options["group_rating"],
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
