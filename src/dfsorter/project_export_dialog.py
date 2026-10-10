"""Modal project output setup. Only successful enqueueing persists choices."""

import sqlite3
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
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
from .project_summary import SIZE_EXPLANATION, project_readiness, ready_source_bytes
from .theme import font, role
from .widgets import FilenamePreview, FlowLayout, MiddleElideComboBox, storage_gb


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
    options.setdefault("group_rating", True)
    options.setdefault("include_rating", True)
    options.setdefault("include_tag", True)
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
        self.resize(640, 480)
        self.options = normalized_preferences(
            self.project["output_preferences"],
            {clip["game"] for clip in self.clips()},
            window.registry,
            window.settings.get("export_folder", ""),
        )
        body = QVBoxLayout(self)
        body.setContentsMargins(16, 16, 16, 16)
        body.setSpacing(16)

        def section(title):
            layout = QVBoxLayout()
            layout.setSpacing(8)
            heading = QLabel(title)
            role(heading, "formHeading")
            layout.addWidget(heading)
            body.addLayout(layout)
            return layout

        destination = section("Destination")
        row = QHBoxLayout()
        row.setSpacing(8)
        self.destination = QLineEdit(self.options["destination"])
        self.destination.setAccessibleName("Export output folder")
        row.addWidget(self.destination, 1)
        choose = QPushButton("Choose…")
        choose.clicked.connect(self.choose_folder)
        row.addWidget(choose)
        destination.addLayout(row)

        formatting = section("Filename format")
        self.game_row = QWidget()
        game_row = QHBoxLayout(self.game_row)
        game_row.setContentsMargins(0, 0, 0, 0)
        game_row.setSpacing(8)
        game_row.addWidget(QLabel("Game"))
        self.game = MiddleElideComboBox()
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
            game = window.registry.game(name)
            label = f"{name} · {game.code}"
            self.game.addItem(label, name)
            self.game.setItemData(self.game.count() - 1, label, Qt.ItemDataRole.ToolTipRole)
        game_row.addWidget(self.game, 1)
        self.game_row.setVisible(bool(self.examples))
        formatting.addWidget(self.game_row)
        inclusion = QVBoxLayout()
        inclusion.setSpacing(8)
        inclusion.addSpacing(4)
        self.inclusion_heading = QLabel("Include in filename")
        role(self.inclusion_heading, "formHeading")
        inclusion.addWidget(self.inclusion_heading)
        self.fields = QWidget()
        self.fields.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.field_layout = QVBoxLayout(self.fields)
        self.field_layout.setContentsMargins(0, 0, 0, 0)
        self.field_layout.setSpacing(8)
        inclusion.addWidget(self.fields)
        formatting.addLayout(inclusion)
        self.include_rating = QCheckBox("Rating")
        self.include_rating.setAccessibleName("Include rating in filename")
        self.include_rating.setToolTip("Include rating in filenames for all games in this project")
        self.include_rating.setChecked(self.options["include_rating"])
        self.include_rating.toggled.connect(self.toggle_rating)
        self.include_tag = QCheckBox("Tag")
        self.include_tag.setAccessibleName("Include tag in filename")
        self.include_tag.setToolTip("Include a leading [tag] in filenames for tagged clips in all games in this project")
        self.include_tag.setChecked(self.options["include_tag"])
        self.include_tag.toggled.connect(self.toggle_tag)
        preview = QVBoxLayout()
        preview.setSpacing(8)
        preview.addSpacing(4)
        self.preview_heading = QLabel("Live filename preview")
        role(self.preview_heading, "formHeading")
        preview.addWidget(self.preview_heading)
        self.preview = FilenamePreview()
        preview.addWidget(self.preview)
        formatting.addLayout(preview)

        organization = section("Folder organization")
        row = QHBoxLayout()
        row.setSpacing(0)
        self.folder_structure = QButtonGroup(self)
        self.flat = QPushButton("Flat")
        self.group_rating = QPushButton("By rating")
        for index, control in enumerate((self.group_rating, self.flat)):
            control.setCheckable(True)
            control.setProperty("periodSegment", True)
            control.setProperty("periodPosition", "first" if index == 0 else "last")
            self.folder_structure.addButton(control, int(control is self.group_rating))
            row.addWidget(control)
        self.group_rating.setChecked(bool(self.options["group_rating"]))
        self.flat.setChecked(not self.options["group_rating"])
        row.addStretch()
        organization.addLayout(row)
        self.organization_hint = QLabel()
        self.organization_hint.setWordWrap(True)
        role(self.organization_hint, "secondary")
        organization.addWidget(self.organization_hint)
        self.group_rating.toggled.connect(self.refresh_organization)
        self.refresh_organization()
        body.addStretch()

        footer = QVBoxLayout()
        footer.setSpacing(8)
        self.blocker_notice = QFrame()
        role(self.blocker_notice, "warningNotice")
        notice = QVBoxLayout(self.blocker_notice)
        notice.setContentsMargins(12, 8, 12, 8)
        notice.setSpacing(4)
        notice_title = QLabel("Export unavailable")
        notice_title.setFont(font("md", "semibold"))
        role(notice_title, "warning")
        notice.addWidget(notice_title)
        self.blockers = QLabel()
        self.blockers.setWordWrap(True)
        role(self.blockers, "secondary")
        notice.addWidget(self.blockers)
        footer.addWidget(self.blocker_notice)
        self.error = QLabel()
        self.error.setWordWrap(True)
        role(self.error, "error")
        self.error.hide()
        footer.addWidget(self.error)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        footer.addWidget(self.summary)
        self.exclusions = QLabel()
        role(self.exclusions, "secondary")
        footer.addWidget(self.exclusions)
        explanation = QLabel("Export copies complete original files; In/Out ranges do not trim them.")
        explanation.setWordWrap(True)
        role(explanation, "helper")
        footer.addWidget(explanation)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.submit_button = QPushButton("Export")
        self.submit_button.setDefault(True)
        role(self.submit_button, "primary")
        self.submit_button.clicked.connect(self.submit)
        buttons.addWidget(self.submit_button)
        footer.addLayout(buttons)
        body.addLayout(footer)
        self.game.currentIndexChanged.connect(self.show_fields)
        self.destination.textChanged.connect(self.refresh_submission)
        self.show_fields()
        self.refresh_submission()

    def refresh_organization(self):
        self.organization_hint.setText(
            "Subfolders R1–R5 and unrated inside the destination folder."
            if self.group_rating.isChecked() else "All clips in the destination folder."
        )

    def clips(self):
        ids = self.window.catalogue.member_ids(self.project_id)
        return [clip for clip in self.window.catalogue.clips() if clip["clip_id"] in ids]

    def show_fields(self):
        # Keep project-wide choices alive when rebuilding game controls.
        self.include_rating.setParent(self.fields)
        self.include_rating.hide()
        self.include_tag.setParent(self.fields)
        self.include_tag.hide()
        while self.field_layout.count():
            item = self.field_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        game = self.window.registry.game(self.game.currentData())
        prefix_row = QWidget()
        prefix_layout = QHBoxLayout(prefix_row)
        prefix_layout.setContentsMargins(0, 0, 0, 0)
        prefix_layout.setSpacing(8)
        self.field_layout.addWidget(prefix_row)
        if game:
            self.prefix = QCheckBox(f"Game code [{game.code}]")
            prefix_layout.addWidget(self.prefix)
        prefix_layout.addWidget(self.include_rating)
        prefix_layout.addWidget(self.include_tag)
        prefix_layout.addStretch()
        self.include_rating.show()
        self.include_tag.show()
        if not game:
            self.refresh_game_labels()
            return
        options = self.options["formats"][game.name]
        self.prefix.setChecked(options["prefix"])

        def toggle_prefix(checked):
            options.update(prefix=checked)
            self.refresh_game_labels()

        self.prefix.toggled.connect(toggle_prefix)
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
        self.refresh_game_labels()

    def toggle_rating(self, checked):
        self.options["include_rating"] = checked
        self.refresh_game_labels()

    def toggle_tag(self, checked):
        self.options["include_tag"] = checked
        self.refresh_game_labels()

    def refresh_game_labels(self):
        name = self.game.currentData()
        if name not in self.examples:
            self.preview.set_filename("No configured Keep clips available for a filename preview.")
            return
        clip = {**self.examples[name], "tag": "TAG"}
        options = self.options["formats"][name]
        spans = []
        stem = safe_stem(export_title(
            clip, self.window.registry, options["fields"], options["prefix"],
            lowercase=self.window.settings.get("lowercase_generated_titles", True),
            include_rating=self.options["include_rating"],
            include_tag=self.options["include_tag"], text_spans=spans,
        ), text_spans=spans)
        # Keep the format placeholder uppercase regardless of generated-title casing.
        if self.options["include_tag"]:
            stem = "[TAG]" + stem[5:]
        self.preview.set_filename(
            stem + Path(clip["source_path"]).suffix,
            [(start, length) for field, start, length in spans if field == "mainline"],
            tag_spans=[(start, length) for field, start, length in spans if field == "tag"],
        )

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Export folder", self.destination.text())
        if folder:
            self.destination.setText(folder)

    def refresh_submission(self):
        clips = self.clips()
        categories, errors = project_readiness(clips, self.window.registry)
        ready = len(categories["Ready"])
        size = ready_source_bytes(clips, categories["Ready"])
        self.summary.setText(
            f"{ready} {'clip' if ready == 1 else 'clips'} ready · Estimated size: "
            + (storage_gb(size) if size is not None else "— GB")
        )
        self.summary.setToolTip(SIZE_EXPLANATION + (
            " Ready source sizes could not be read." if size is None else ""
        ))
        skipped = len(categories["Skipped"])
        self.exclusions.setText(f"{skipped} Discard {'clip' if skipped == 1 else 'clips'} excluded")
        self.exclusions.setVisible(bool(skipped))
        blocking = " · ".join(
            f"{name} {len(categories[name])}" for name in ("Pending", "Blocked") if categories[name]
        )
        self.blockers.setText(
            f"{blocking} — Resolve Pending and Blocked clips before export."
            if blocking else "No Ready clips to export." if not ready else ""
        )
        self.blocker_notice.setVisible(bool(self.blockers.text()))
        self.submit_button.setToolTip(self.blockers.text())
        self.submit_button.setEnabled(
            bool(ready) and not errors and bool(self.destination.text().strip())
        )

    def submit(self):
        window = self.window
        if not window.ensure_range_complete():
            return
        self.error.clear()
        self.error.hide()
        self.refresh_submission()
        if not self.submit_button.isEnabled():
            return
        if window.worker is not None or window.close_requested:
            self.error.setText("Wait for the current operation to finish")
            self.error.show()
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
                include_tag=options["include_tag"],
            )
            manifest["project_name"] = self.project["name"]
            manifest["choices"] = {
                "project_id": self.project_id,
                "formats": options["formats"],
                "group_rating": options["group_rating"],
                "include_rating": options["include_rating"],
                "include_tag": options["include_tag"],
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
            self.error.show()
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
