import html
import logging
import os
import sys
import threading
from collections import Counter, defaultdict
from pathlib import Path

os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")

import yaml
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .catalogue import Catalogue
from .config import Registry, title
from .media import discover
from .output import export_project, share_clip, validate
from .parsing import parse_command, query_clips, requests_discarded
from .playback import Player

ROOT = Path(__file__).resolve().parents[2]


class Worker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, function):
        super().__init__()
        self.function = function
        self.cancelled = threading.Event()

    def run(self):
        try:
            self.succeeded.emit(self.function(self.cancelled.is_set, self.progress.emit))
        except Exception as error:
            logging.exception("Background operation failed")
            self.failed.emit(str(error))


def button(text, callback):
    result = QPushButton(text)
    result.clicked.connect(callback)
    return result


def page():
    widget = QWidget()
    layout = QVBoxLayout(widget)
    return widget, layout


class Window(QMainWindow):
    def __init__(self, root=ROOT):
        super().__init__()
        self.root = Path(root)
        self.registry = Registry(self.root / "configs/games")
        self.catalogue = Catalogue(self.root / "data/dfsorter.db")
        self.settings_path = self.root / "data/settings.yaml"
        self.settings = {}
        if self.settings_path.exists():
            try:
                self.settings = yaml.safe_load(self.settings_path.read_text(encoding="utf-8")) or {}
                if not isinstance(self.settings, dict):
                    raise ValueError("Settings must be a mapping")
            except (OSError, ValueError, yaml.YAMLError) as error:
                self.registry.errors.append(f"Settings: {error}")
                self.settings = {}
        self.current_id = None
        self.current_panel = "Home"
        self.history = defaultdict(list)
        self.media_info = {}
        self.pending_in = None
        self.worker = None
        self.refreshing = False
        self.setWindowTitle("DFSorter")
        self.resize(1400, 900)
        central, outer = page()
        self.setCentralWidget(central)
        navigation = QHBoxLayout()
        self.nav = {}
        for name in ["Home", "Import", "Session", "Editing", "Export", "Config"]:
            self.nav[name] = button(name, lambda checked=False, name=name: self.panel(name))
            navigation.addWidget(self.nav[name])
        outer.addLayout(navigation)
        self.splitter = QSplitter()
        outer.addWidget(self.splitter, 1)
        self.left, left_layout = page()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search or game:VAL agent:Jett kill:>=4")
        self.search.returnPressed.connect(self.refresh_library)
        left_layout.addWidget(self.search)
        self.filters, filter_layout = page()
        self.triage_filter = QComboBox()
        self.triage_filter.addItems(
            ["Hide discarded", "All triage", "Undefined", "Keep", "Discard"]
        )
        self.game_filter = QComboBox()
        self.project_filter = QComboBox()
        self.sort = QComboBox()
        self.sort.addItems(
            ["Oldest first", "Newest first", "Filename", "Working title", "Modified"]
        )
        for control in [self.triage_filter, self.game_filter, self.project_filter, self.sort]:
            filter_layout.addWidget(control)
            control.currentIndexChanged.connect(self.refresh_library)
        left_layout.addWidget(self.filters)
        self.library_error = QLabel()
        self.library_error.setWordWrap(True)
        left_layout.addWidget(self.library_error)
        self.library = QListWidget()
        self.library.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.library.currentItemChanged.connect(self.select_clip)
        left_layout.addWidget(self.library, 1)
        self.splitter.addWidget(self.left)
        self.center = QStackedWidget()
        self.splitter.addWidget(self.center)
        self.pages = {}
        self.build_pages()
        self.right, right_layout = page()
        self.active_label = QLabel()
        self.active_label.setWordWrap(True)
        right_layout.addWidget(self.active_label)
        self.projects = QListWidget()
        right_layout.addWidget(self.projects)
        for text, callback in [
            ("New project", self.new_project),
            ("Rename", self.rename_project),
            ("Activate", self.activate_project),
            ("Deactivate", self.deactivate),
            ("Add selected clips", lambda: self.membership(True)),
            ("Remove selected clips", lambda: self.membership(False)),
            ("Delete project", self.delete_project),
        ]:
            right_layout.addWidget(button(text, callback))
        self.splitter.addWidget(self.right)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.command_area, command_layout = page()
        self.command_history = QLabel()
        self.command_history.setWordWrap(True)
        command_layout.addWidget(self.command_history)
        self.command = QLineEdit()
        self.command.setPlaceholderText("1v4 3k jett vandal R4 -- Mainline -- Description")
        command_layout.addWidget(self.command)
        self.command_error = QLabel()
        self.command_error.setWordWrap(True)
        command_layout.addWidget(self.command_error)
        outer.addWidget(self.command_area)
        self.build_menus()
        QApplication.instance().installEventFilter(self)
        self.refresh_references()
        self.panel("Home")
        self.reset_layout()
        if self.registry.errors:
            self.statusBar().showMessage("Configuration errors — see Config panel")

    def build_pages(self):
        for name in ["Home", "Import", "Session", "Editing", "Export", "Config"]:
            widget, layout = page()
            self.pages[name] = (widget, layout)
            self.center.addWidget(widget)
        home = self.pages["Home"][1]
        home.addWidget(
            QLabel("<h1>DFSorter</h1><p>Review clips. Keep your originals untouched.</p>")
        )
        for name in ["Import", "Session", "Editing"]:
            home.addWidget(
                button(f"Open {name}", lambda checked=False, name=name: self.panel(name))
            )
        home.addStretch()
        importing = self.pages["Import"][1]
        importing.addWidget(QLabel("<h2>Capture folders</h2>"))
        self.folders = QListWidget()
        importing.addWidget(self.folders)
        for text, callback in [
            ("Add folder / preview", self.add_folder),
            ("Refresh / rescan", self.rescan),
            ("Enable / disable", self.toggle_folder),
            ("Migrate source folder", self.migrate),
            ("Remove folder", self.remove_folder),
            ("Purge folder catalogue entries", self.purge),
        ]:
            importing.addWidget(button(text, callback))
        session = self.pages["Session"][1]
        self.session_status = QLabel()
        self.session_status.setWordWrap(True)
        session.addWidget(self.session_status)
        self.session_count = QSpinBox()
        self.session_count.setRange(1, 1000000)
        self.session_count.setValue(50)
        session.addWidget(self.session_count)
        for text, mode in [
            ("Session from selected", "selected"),
            ("Session from first N", "first"),
            ("Session from all results", "all"),
        ]:
            session.addWidget(
                button(text, lambda checked=False, mode=mode: self.create_session(mode))
            )
        session.addWidget(button("Resume session", lambda: self.panel("Editing")))
        session.addWidget(button("End session", self.end_session))
        session.addStretch()
        editing = self.pages["Editing"][1]
        self.player = Player()
        editing.addWidget(self.player, 1)
        self.working_title = QLabel()
        self.working_title.setWordWrap(True)
        self.working_title.setTextFormat(Qt.TextFormat.RichText)
        editing.addWidget(self.working_title)
        self.filename = QLabel()
        self.filename.setStyleSheet("color: #9aa4af;")
        self.filename.setWordWrap(True)
        editing.addWidget(self.filename)
        self.clip_status = QLabel()
        self.clip_status.setWordWrap(True)
        editing.addWidget(self.clip_status)
        triage = QHBoxLayout()
        for text, state in [("Keep", "keep"), ("Discard", "discard"), ("Undefined", None)]:
            triage.addWidget(
                button(text, lambda checked=False, state=state: self.edit({"triage": state}))
            )
        triage.addWidget(button("Change game", self.change_game))
        editing.addLayout(triage)
        stars = QHBoxLayout()
        self.star_buttons = []
        for rating in range(1, 6):
            star = button("☆", lambda checked=False, rating=rating: self.edit({"rating": rating}))
            self.star_buttons.append(star)
            stars.addWidget(star)
        stars.addWidget(button("Clear rating", lambda: self.edit({"rating": None})))
        editing.addLayout(stars)
        self.structured = QLabel()
        self.structured.setWordWrap(True)
        editing.addWidget(self.structured)
        self.description = QPlainTextEdit()
        self.description.setPlaceholderText(
            "Description — secondary notes, excluded from filenames"
        )
        self.description.setMaximumHeight(70)
        editing.addWidget(self.description)
        editing.addWidget(button("Save description", self.save_description))
        self.technical = QLineEdit()
        self.technical.setPlaceholderText("Technical condition (optional)")
        self.technical.editingFinished.connect(self.save_technical)
        editing.addWidget(self.technical)
        self.range_label = QLabel("No In/Out range")
        editing.addWidget(self.range_label)
        controls = QHBoxLayout()
        for text, callback in [
            ("Previous", lambda: self.navigate(-1)),
            ("Next", lambda: self.navigate(1)),
            ("Set In", self.mark_in),
            ("Set Out", self.mark_out),
            ("Clear range", self.clear_range),
            ("Share", self.share),
        ]:
            controls.addWidget(button(text, callback))
        editing.addLayout(controls)
        exporting = self.pages["Export"][1]
        self.export_project = QComboBox()
        self.export_project.currentIndexChanged.connect(self.export_selection)
        exporting.addWidget(self.export_project)
        self.export_player = Player()
        self.export_player.setMaximumHeight(300)
        exporting.addWidget(self.export_player)
        self.export_errors = QPlainTextEdit()
        self.export_errors.setReadOnly(True)
        self.export_errors.setMaximumHeight(130)
        exporting.addWidget(self.export_errors)
        self.format_game = QComboBox()
        self.format_game.currentIndexChanged.connect(self.show_format)
        exporting.addWidget(self.format_game)
        self.format_box, self.format_layout = page()
        exporting.addWidget(self.format_box)
        self.formats = {}
        self.export_destination = QLineEdit(str(self.settings.get("export_folder", "")))
        exporting.addWidget(self.export_destination)
        exporting.addWidget(button("Choose export folder", self.choose_export_folder))
        self.group_rating = QCheckBox("Group by Rating")
        exporting.addWidget(self.group_rating)
        self.export_button = button("Export project", self.run_export)
        exporting.addWidget(self.export_button)
        exporting.addStretch()
        configuration = self.pages["Config"][1]
        self.config_status = QPlainTextEdit()
        self.config_status.setReadOnly(True)
        configuration.addWidget(self.config_status)
        configuration.addWidget(button("Open game YAML folder", self.open_configs))
        configuration.addWidget(button("Reload configurations", self.reload_configs))

    def build_menus(self):
        menus = {
            name: self.menuBar().addMenu(name)
            for name in ["File", "Edit", "Clip", "View", "Window"]
        }
        actions = [
            ("File", "New project", self.new_project, None),
            ("File", "Add capture folder", self.add_folder, None),
            ("File", "Share selected clip", self.share, None),
            ("File", "Project Export", lambda: self.panel("Export"), None),
            ("File", "Exit", self.close, "Ctrl+Q"),
            ("Edit", "Undo", lambda: self.undo(False), "Ctrl+Z"),
            ("Edit", "Redo", lambda: self.undo(True), "Ctrl+Y"),
            ("Edit", "Game configuration files", self.open_configs, None),
            ("Clip", "Reset user metadata", self.reset_metadata, None),
            ("Clip", "Change game", self.change_game, None),
            ("View", "Play / pause", lambda: self.active_player().toggle(), None),
            ("View", "Mute / unmute", lambda: self.active_player().mute.toggle(), None),
            ("Window", "Reset window and panes", self.reset_layout, None),
        ]
        for menu, name, callback, shortcut in actions:
            action = QAction(name, self)
            action.triggered.connect(callback)
            if shortcut:
                action.setShortcut(shortcut)
            menus[menu].addAction(action)

    def error(self, message):
        logging.error("%s", message)
        self.statusBar().showMessage(str(message), 12000)
        self.command_error.setText(str(message))

    def confirm(self, message):
        return (
            QMessageBox.question(self, "Confirm catalogue operation", message)
            == QMessageBox.StandardButton.Yes
        )

    def selected_id(self, listing):
        item = listing.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def panel(self, name):
        if name == "Editing" and not self.catalogue.state("session"):
            self.error("Create a session before entering Editing")
            return
        self.save_description()
        self.player.fast(False)
        self.player.media.pause()
        self.export_player.media.pause()
        self.current_panel = name
        self.center.setCurrentWidget(self.pages[name][0])
        self.right.setVisible(name not in {"Export", "Config"})
        self.command_area.setVisible(name in {"Home", "Editing"})
        self.command.setEnabled(name == "Editing")
        self.search.setVisible(name not in {"Editing", "Export"})
        self.filters.setVisible(name not in {"Editing", "Export"})
        self.library.setSelectionMode(
            QListWidget.SelectionMode.SingleSelection
            if name == "Editing"
            else QListWidget.SelectionMode.ExtendedSelection
        )
        self.refresh_references()
        self.refresh_library()
        if name == "Editing":
            session = self.catalogue.state("session")
            self.load_clip(session["ids"][session["index"]])
            self.command.setFocus()
        elif name == "Export":
            self.export_selection()

    def refresh_references(self):
        self.refreshing = True
        projects = self.catalogue.projects()
        active = self.catalogue.state("active_project")
        project_selection = self.selected_id(self.projects)
        self.projects.clear()
        for project in projects:
            item = QListWidgetItem(
                ("● " if project["project_id"] == active else "") + project["name"]
            )
            item.setData(Qt.ItemDataRole.UserRole, project["project_id"])
            self.projects.addItem(item)
            if project["project_id"] == project_selection:
                self.projects.setCurrentItem(item)
        self.active_label.setText(
            "Active project: "
            + next(
                (project["name"] for project in projects if project["project_id"] == active), "None"
            )
        )
        for combo, default in [
            (self.project_filter, "All projects"),
            (self.export_project, "Choose project"),
        ]:
            selected = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(default, None)
            for project in projects:
                combo.addItem(project["name"], project["project_id"])
            combo.setCurrentIndex(max(0, combo.findData(selected)))
            combo.blockSignals(False)
        selected = self.game_filter.currentData()
        self.game_filter.clear()
        self.game_filter.addItem("All games", None)
        self.game_filter.addItem("Unassigned", "")
        for name in self.registry.games:
            self.game_filter.addItem(name, name)
        self.game_filter.setCurrentIndex(max(0, self.game_filter.findData(selected)))
        folder_selection = self.selected_id(self.folders)
        self.folders.clear()
        clips = {clip["clip_id"]: clip for clip in self.catalogue.clips()}
        for folder in self.catalogue.folders():
            ids = [
                row["clip_id"]
                for row in self.catalogue.rows(
                    "SELECT clip_id FROM sources WHERE folder_id=?", (folder["folder_id"],)
                )
            ]
            counts = Counter(clips[clip_id]["game"] or "Unknown" for clip_id in ids)
            durations = [
                self.media_info.get(clips[clip_id]["source_path"], {}).get("duration")
                for clip_id in ids
            ]
            durations = [duration for duration in durations if duration is not None]
            average = (
                f"{sum(durations) / len(durations):.1f}s"
                if durations
                else "unavailable until scanned"
            )
            text = f"{'Enabled' if folder['enabled'] else 'Disabled'} | {folder['path']}\n"
            text += f"{len(ids)} clips | {dict(counts)} | Avg {average}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, folder["folder_id"])
            self.folders.addItem(item)
            if folder["folder_id"] == folder_selection:
                self.folders.setCurrentItem(item)
        session = self.catalogue.state("session")
        self.nav["Editing"].setEnabled(bool(session))
        if session:
            counts = Counter(clips[clip_id]["triage"] or "undefined" for clip_id in session["ids"])
            total = len(session["ids"])
            self.session_status.setText(
                f"Position {session['index'] + 1} / {total}\n"
                + "\n".join(
                    f"{state}: {counts[state]} ({counts[state] / total:.0%})"
                    for state in ["keep", "discard", "undefined"]
                )
            )
        else:
            self.session_status.setText(
                "No active session. Filter and select clips in the library."
            )
        self.config_status.setPlainText(
            "\n".join(self.registry.errors)
            or "Configurations valid:\n" + "\n".join(self.registry.games)
        )
        self.refreshing = False

    def refresh_library(self):
        if self.refreshing:
            return
        try:
            clips = self.catalogue.clips()
            if self.current_panel == "Editing":
                session = self.catalogue.state("session")
                mapping = {clip["clip_id"]: clip for clip in clips}
                clips = [mapping[clip_id] for clip_id in session["ids"]] if session else []
            elif self.current_panel == "Export":
                ids = self.catalogue.member_ids(self.export_project.currentData())
                clips = [clip for clip in clips if clip["clip_id"] in ids]
            else:
                clips = query_clips(clips, self.search.text(), self.registry)
                triage = self.triage_filter.currentText()
                if triage == "Hide discarded" and not requests_discarded(self.search.text()):
                    clips = [clip for clip in clips if clip["triage"] != "discard"]
                elif triage not in {"All triage", "Hide discarded"}:
                    expected = None if triage == "Undefined" else triage.casefold()
                    clips = [clip for clip in clips if clip["triage"] == expected]
                game = self.game_filter.currentData()
                if game is not None:
                    clips = [clip for clip in clips if (clip["game"] or "") == game]
                project = self.project_filter.currentData()
                if project:
                    ids = self.catalogue.member_ids(project)
                    clips = [clip for clip in clips if clip["clip_id"] in ids]

                def captured(clip):
                    info = self.media_info.get(clip["source_path"], {})
                    if info.get("created"):
                        return info["created"]
                    try:
                        from datetime import datetime, timezone

                        return datetime.fromtimestamp(
                            Path(clip["source_path"]).stat().st_ctime, timezone.utc
                        ).isoformat()
                    except OSError:
                        return ""

                sort = self.sort.currentText()
                key = {
                    "Oldest first": captured,
                    "Newest first": captured,
                    "Filename": lambda clip: Path(clip["source_path"]).name.casefold(),
                    "Working title": lambda clip: title(clip, self.registry).casefold(),
                    "Modified": lambda clip: clip["catalogue_modified_at"],
                }[sort]
                clips.sort(
                    key=lambda clip: (key(clip), clip["source_path"]),
                    reverse=sort in {"Newest first", "Modified"},
                )
            selected = {
                item.data(Qt.ItemDataRole.UserRole) for item in self.library.selectedItems()
            }
            current = self.selected_id(self.library)
            if self.current_panel == "Editing" and self.catalogue.state("session"):
                session = self.catalogue.state("session")
                current = session["ids"][session["index"]]
            self.library.blockSignals(True)
            self.library.clear()
            for clip in clips:
                available = "" if Path(clip["source_path"]).is_file() else " [unavailable]"
                item = QListWidgetItem(
                    f"{title(clip, self.registry)}\n{clip['triage'] or 'undefined'}{available}"
                )
                item.setData(Qt.ItemDataRole.UserRole, clip["clip_id"])
                self.library.addItem(item)
                if clip["clip_id"] == current:
                    self.library.setCurrentItem(item)
                item.setSelected(clip["clip_id"] in selected or clip["clip_id"] == current)
            self.library.blockSignals(False)
            self.library_error.clear()
        except ValueError as error:
            self.library_error.setText(str(error))

    def select_clip(self, item, previous=None):
        if not item:
            return
        clip_id = item.data(Qt.ItemDataRole.UserRole)
        if self.current_panel == "Editing":
            self.save_description()
            session = self.catalogue.state("session")
            self.catalogue.navigate(session["ids"].index(clip_id))
            self.refresh_library()
            self.load_clip(clip_id)
        elif self.current_panel == "Export":
            self.export_player.load(self.catalogue.clip(clip_id))

    def load_clip(self, clip_id):
        self.current_id = clip_id
        self.pending_in = None
        self.command.clear()
        self.command_error.clear()
        self.player.load(self.catalogue.clip(clip_id))
        self.render_clip()
        self.command.setFocus()

    def render_clip(self):
        if not self.current_id:
            return
        clip = self.catalogue.clip(self.current_id)
        rendered = html.escape(title(clip, self.registry))
        if clip["mainline"]:
            rendered = rendered.replace(
                html.escape(clip["mainline"]), "<b>" + html.escape(clip["mainline"]) + "</b>"
            )
        self.working_title.setText(rendered)
        self.filename.setText(Path(clip["source_path"]).name)
        member_ids = self.catalogue.memberships(self.current_id)
        names = [
            project["name"]
            for project in self.catalogue.projects()
            if project["project_id"] in member_ids
        ]
        self.clip_status.setText(
            f"{clip['triage'] or 'Undefined'} | {clip['game'] or 'No game'} | Projects: {', '.join(names) or 'None'}"
        )
        for rating, star in enumerate(self.star_buttons, 1):
            star.setText("★" if rating <= (clip["rating"] or 0) else "☆")
        game = self.registry.game(clip["game"])
        self.structured.setText(
            " | ".join(
                f"{key}: {value}"
                for key, value in clip["metadata"].items()
                if game and key in game.fields
            )
            or "No structured metadata"
        )
        self.description.setPlainText(clip["description"] or "")
        self.technical.setText(clip["technical_condition"] or "")
        self.range_label.setText(
            f"In {clip['in_ms'] / 1000:.3f}s → Out {clip['out_ms'] / 1000:.3f}s"
            if clip["in_ms"] is not None
            else "No In/Out range"
        )
        self.player.seek.marker_range = (clip["in_ms"], clip["out_ms"])
        self.player.seek.update()
        self.command_history.setText("\n".join(self.history[self.current_id][-3:]))

    def edit(self, patch, **kwargs):
        if self.current_panel != "Editing" or not self.current_id:
            return
        try:
            self.save_description()
            self.catalogue.patch(self.current_id, patch, editing=True, **kwargs)
            self.render_clip()
        except (ValueError, OSError) as error:
            self.error(error)

    def save_description(self):
        if self.current_panel == "Editing" and self.current_id:
            text = self.description.toPlainText()
            if text != (self.catalogue.clip(self.current_id)["description"] or ""):
                self.catalogue.patch(self.current_id, {"description": text})

    def save_technical(self):
        if self.current_panel == "Editing" and self.current_id:
            self.catalogue.patch(self.current_id, {"technical_condition": self.technical.text()})

    def submit(self, advance=False):
        if self.current_panel != "Editing" or not self.current_id:
            return
        text = self.command.text()
        try:
            clip = self.catalogue.clip(self.current_id)
            patch = parse_command(text, clip["game"], self.registry)
            if advance and clip["triage"] != "discard":
                patch["triage"] = "keep"
            self.save_description()
            self.catalogue.patch(self.current_id, patch, editing=True)
            if text.strip():
                self.history[self.current_id].append(text)
                self.history[self.current_id] = self.history[self.current_id][-3:]
            self.command.clear()
            self.command_error.clear()
            self.render_clip()
            if advance:
                self.navigate(1)
        except ValueError as error:
            self.error(error)

    def navigate(self, offset):
        session = self.catalogue.state("session")
        if not session:
            return
        self.save_description()
        self.catalogue.navigate(session["index"] + offset)
        session = self.catalogue.state("session")
        self.refresh_references()
        self.refresh_library()
        self.load_clip(session["ids"][session["index"]])

    def active_player(self):
        return self.export_player if self.current_panel == "Export" else self.player

    def eventFilter(self, watched: QObject, event):
        if event.type() == QEvent.Type.ApplicationDeactivate:
            self.active_player().fast(False)
        if event.type() == QEvent.Type.FocusOut and watched is self.description:
            self.save_description()
        if event.type() == QEvent.Type.FocusOut:
            self.active_player().fast(False)
        if event.type() == QEvent.Type.KeyRelease and event.key() == Qt.Key.Key_Space:
            if not event.isAutoRepeat():
                self.active_player().fast(False)
        if event.type() != QEvent.Type.KeyPress or QApplication.activeModalWidget():
            return super().eventFilter(watched, event)
        if self.current_panel not in {"Editing", "Export"}:
            return super().eventFilter(watched, event)
        focus = QApplication.focusWidget()
        text_editing = isinstance(focus, (QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox))
        if focus is self.command:
            if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
                self.submit(bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier))
                return True
            if event.key() == Qt.Key.Key_Backspace and not self.command.text():
                self.edit({"triage": "discard"})
                return True
            if event.key() == Qt.Key.Key_Space and not self.command.text():
                text_editing = False
        if not text_editing and not event.modifiers():
            if event.key() == Qt.Key.Key_Space:
                if not event.isAutoRepeat():
                    self.active_player().fast(True)
                return True
            if self.current_panel == "Editing" and event.key() in {Qt.Key.Key_I, Qt.Key.Key_O}:
                (self.mark_in if event.key() == Qt.Key.Key_I else self.mark_out)()
                return True
        return super().eventFilter(watched, event)

    def mark_in(self):
        if self.current_panel == "Editing" and self.current_id:
            self.pending_in = self.player.media.position()
            self.range_label.setText(
                f"Pending In {self.pending_in / 1000:.3f}s — set Out to save; stored range unchanged"
            )

    def mark_out(self):
        if self.current_panel != "Editing" or not self.current_id:
            return
        clip = self.catalogue.clip(self.current_id)
        start = self.pending_in if self.pending_in is not None else clip["in_ms"]
        end = self.player.media.position()
        if start is None or end <= start:
            self.error("Set In before Out; stored range remains unchanged")
            return
        self.edit({"in_ms": start, "out_ms": end})
        self.pending_in = None

    def clear_range(self):
        self.pending_in = None
        self.edit({"in_ms": None, "out_ms": None})

    def new_project(self):
        name, accepted = QInputDialog.getText(self, "New project", "Project name")
        if accepted:
            try:
                self.catalogue.save_project(name)
                self.refresh_references()
            except ValueError as error:
                self.error(error)

    def rename_project(self):
        project_id = self.selected_id(self.projects)
        if project_id:
            name, accepted = QInputDialog.getText(self, "Rename project", "New name")
            if accepted:
                try:
                    self.catalogue.save_project(name, project_id)
                    self.refresh_references()
                except ValueError as error:
                    self.error(error)

    def activate_project(self):
        project_id = self.selected_id(self.projects)
        if project_id:
            self.catalogue.set_state("active_project", project_id)
            self.refresh_references()

    def deactivate(self):
        self.catalogue.set_state("active_project", None)
        self.refresh_references()

    def delete_project(self):
        project_id = self.selected_id(self.projects)
        if project_id and self.confirm(
            "Delete this project and its memberships? Clips and source files remain."
        ):
            self.catalogue.delete_project(project_id)
            self.refresh_references()
            self.refresh_library()

    def membership(self, include):
        project_id = self.selected_id(self.projects)
        if not project_id:
            self.error("Select a project first")
            return
        ids = [item.data(Qt.ItemDataRole.UserRole) for item in self.library.selectedItems()]
        for clip_id in ids:
            self.catalogue.patch(clip_id, {}, membership=(project_id, include))
        if self.current_panel == "Editing":
            self.render_clip()

    def create_session(self, mode):
        selected = {item.data(Qt.ItemDataRole.UserRole) for item in self.library.selectedItems()}
        ids = [
            self.library.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(self.library.count())
        ]
        if mode == "selected":
            ids = [clip_id for clip_id in ids if clip_id in selected]
        elif mode == "first":
            ids = ids[: self.session_count.value()]
        replace = bool(self.catalogue.state("session"))
        if replace and not self.confirm(
            "End the existing session and replace its queue? Clip metadata stays unchanged."
        ):
            return
        try:
            self.catalogue.create_session(ids, replace)
            self.panel("Editing")
        except ValueError as error:
            self.error(error)

    def end_session(self):
        if self.catalogue.state("session") and self.confirm(
            "End this session? Clip metadata stays unchanged."
        ):
            self.save_description()
            self.catalogue.set_state("session", None)
            self.current_id = None
            self.player.load(None)
            self.panel("Session")

    def selected_clip(self):
        clip_id = (
            self.current_id if self.current_panel == "Editing" else self.selected_id(self.library)
        )
        if not clip_id:
            raise ValueError("Select a clip first")
        return self.catalogue.clip(clip_id)

    def change_game(self):
        try:
            clip = self.selected_clip()
            options = ["Unassigned", *self.registry.games]
            name, accepted = QInputDialog.getItem(
                self, "Change game", "New game", options, editable=False
            )
            game = None if name == "Unassigned" else name
            if (
                accepted
                and game != clip["game"]
                and self.confirm("Changing game clears all game-specific metadata. Continue?")
            ):
                self.catalogue.patch(
                    clip["clip_id"], {"game": game, "metadata": {}}, replace_metadata=True
                )
                self.refresh_library()
                if self.current_panel == "Editing":
                    self.render_clip()
        except ValueError as error:
            self.error(error)

    def reset_metadata(self):
        try:
            clip = self.selected_clip()
            if self.confirm(
                "Reset notes, structured metadata, triage, rating and range? Source, game and project memberships stay unchanged."
            ):
                self.catalogue.patch(
                    clip["clip_id"],
                    {
                        "metadata": {},
                        "mainline": None,
                        "description": None,
                        "technical_condition": None,
                        "triage": None,
                        "rating": None,
                        "in_ms": None,
                        "out_ms": None,
                    },
                    replace_metadata=True,
                )
                self.refresh_library()
                if self.current_panel == "Editing":
                    self.render_clip()
        except ValueError as error:
            self.error(error)

    def undo(self, redo=False):
        self.catalogue.undo(redo)
        self.refresh_references()
        self.refresh_library()
        if self.current_panel == "Editing":
            self.render_clip()

    def background(self, function, done):
        if self.worker is not None:
            self.error("Wait for the current operation to finish")
            return
        self.worker = Worker(function)
        progress = QProgressDialog("Working…", "Cancel", 0, 0, self)
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.canceled.connect(self.worker.cancelled.set)
        self.worker.progress.connect(progress.setLabelText)

        def succeeded(result):
            progress.close()
            try:
                done(result)
            except Exception as error:
                self.error(error)

        def failed(message):
            progress.close()
            self.error(message)

        def finished():
            self.worker.deleteLater()
            self.worker = None

        self.worker.succeeded.connect(succeeded)
        self.worker.failed.connect(failed)
        self.worker.finished.connect(finished)
        self.worker.start()

    def add_folder(self):
        directory = QFileDialog.getExistingDirectory(self, "Capture folder")
        if not directory:
            return
        forced, accepted = QInputDialog.getItem(
            self,
            "Folder classification",
            "Game assignment",
            ["Automatic (nearest recognized ancestor)", *self.registry.games],
            editable=False,
        )
        if not accepted:
            return
        forced_game = None if forced.startswith("Automatic (") else forced

        def done(found):
            counts = Counter(item["game"] or "Unknown" for item in found)
            errors = sum(bool(item["error"]) for item in found)
            if self.confirm(
                f"Found {len(found)} MP4 files:\n{dict(counts)}\n{errors} media inspection warnings.\nAdd this folder?"
            ):
                folder_id = self.catalogue.add_folder(directory, forced_game)
                self.catalogue.ingest(folder_id, found)
                self.remember_media(found)
                self.refresh_references()
                self.refresh_library()

        self.background(
            lambda cancelled, progress: discover(
                Path(directory), self.registry, forced_game, cancelled, progress
            ),
            done,
        )

    def remember_media(self, found):
        from .catalogue import normalized

        for item in found:
            self.media_info[normalized(item["path"])] = item

    def rescan(self):
        folders = [folder for folder in self.catalogue.folders() if folder["enabled"]]

        def scan(cancelled, progress):
            results, errors = [], []
            for folder in folders:
                try:
                    found = discover(
                        Path(folder["path"]),
                        self.registry,
                        folder["forced_game"],
                        cancelled,
                        progress,
                    )
                    results.append((folder["folder_id"], found))
                except InterruptedError:
                    raise
                except (OSError, ValueError) as error:
                    errors.append(str(error))
            return results, errors

        def done(result):
            results, errors = result
            for folder_id, found in results:
                self.catalogue.ingest(folder_id, found)
                self.remember_media(found)
            self.refresh_references()
            self.refresh_library()
            self.statusBar().showMessage("\n".join(errors) or "Rescan complete", 12000)

        self.background(scan, done)

    def toggle_folder(self):
        folder_id = self.selected_id(self.folders)
        for folder in self.catalogue.folders():
            if folder["folder_id"] == folder_id:
                self.catalogue.enable_folder(folder_id, not folder["enabled"])
        self.refresh_references()

    def migrate(self):
        folder_id = self.selected_id(self.folders)
        if not folder_id:
            return
        destination = QFileDialog.getExistingDirectory(self, "New location of this capture folder")
        if destination and self.confirm(
            "Update catalogue source paths to this folder? No source files will be moved."
        ):
            try:
                self.catalogue.migrate(folder_id, destination)
                self.refresh_references()
                self.refresh_library()
            except (ValueError, OSError) as error:
                self.error(error)

    def remove_folder(self):
        folder_id = self.selected_id(self.folders)
        if folder_id and self.confirm(
            "Stop scanning this folder? Catalogue entries and files remain."
        ):
            self.catalogue.remove_folder(folder_id)
            self.refresh_references()

    def purge(self):
        folder_id = self.selected_id(self.folders)
        if folder_id and self.confirm(
            "Permanently purge this folder’s catalogue entries, memberships and session references? Source files remain. This cannot be undone."
        ):
            self.catalogue.remove_folder(folder_id, purge=True)
            if self.current_id and not any(
                clip["clip_id"] == self.current_id for clip in self.catalogue.clips()
            ):
                self.current_id = None
            self.refresh_references()
            self.refresh_library()

    def export_clips(self):
        ids = self.catalogue.member_ids(self.export_project.currentData())
        return [clip for clip in self.catalogue.clips() if clip["clip_id"] in ids]

    def export_selection(self):
        if self.refreshing:
            return
        clips = self.export_clips()
        errors = validate(clips, self.registry)
        self.export_errors.setPlainText(
            "\n".join(message for clip_id, message in errors)
            or f"Ready: {sum(clip['triage'] == 'keep' for clip in clips)} kept clips"
        )
        self.export_button.setEnabled(bool(self.export_project.currentData()) and not errors)
        self.format_game.blockSignals(True)
        self.format_game.clear()
        self.format_game.addItems(
            sorted({clip["game"] for clip in clips if clip["game"] in self.registry.games})
        )
        self.format_game.blockSignals(False)
        self.show_format()
        if self.current_panel == "Export":
            self.refresh_library()
            self.export_player.load(clips[0] if clips else None)

    def show_format(self):
        while self.format_layout.count():
            item = self.format_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        game = self.registry.game(self.format_game.currentText())
        if not game:
            return
        options = self.formats.setdefault(
            game.name, {"fields": list(game.display_order), "prefix": True}
        )
        prefix = QCheckBox("Game code prefix")
        prefix.setChecked(options["prefix"])
        prefix.toggled.connect(lambda checked: options.update(prefix=checked))
        self.format_layout.addWidget(prefix)
        for field in game.display_order:
            check = QCheckBox(field)
            check.setChecked(field in options["fields"])

            def toggle(checked, field=field, options=options):
                if checked and field not in options["fields"]:
                    options["fields"].append(field)
                elif not checked and field in options["fields"]:
                    options["fields"].remove(field)

            check.toggled.connect(toggle)
            self.format_layout.addWidget(check)

    def choose_export_folder(self):
        directory = QFileDialog.getExistingDirectory(
            self, "Export folder", self.export_destination.text()
        )
        if directory:
            self.export_destination.setText(directory)

    def save_settings(self):
        temporary = self.settings_path.with_suffix(".tmp")
        temporary.write_text(yaml.safe_dump(self.settings, allow_unicode=True), encoding="utf-8")
        temporary.replace(self.settings_path)

    def run_export(self):
        destination = self.export_destination.text().strip()
        if not destination:
            self.error("Choose an export folder")
            return
        clips = self.export_clips()
        self.export_selection()
        if validate(clips, self.registry):
            return
        self.settings["export_folder"] = destination
        self.save_settings()
        folders, formats = self.catalogue.folders(), self.formats.copy()
        group = self.group_rating.isChecked()

        def done(result):
            QMessageBox.information(
                self,
                "Project Export",
                f"{len(result.completed)} clips copied.\n"
                + (result.error or "Complete.")
                + "\n"
                + "\n".join(result.completed),
            )

        self.background(
            lambda cancelled, progress: export_project(
                clips, self.registry, destination, folders, formats, group, cancelled, progress
            ),
            done,
        )

    def share(self):
        try:
            clip = self.selected_clip()
        except ValueError as error:
            self.error(error)
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Share whole source clip")
        layout = QFormLayout(dialog)
        destination = QLineEdit(self.settings.get("share_folder", ""))
        layout.addRow("Output folder", destination)

        def browse():
            folder = QFileDialog.getExistingDirectory(dialog, "Share folder", destination.text())
            if folder:
                destination.setText(folder)

        layout.addRow(button("Browse", browse))
        custom = QLineEdit()
        custom.setPlaceholderText("Leave empty to generate; source extension is appended")
        layout.addRow("Custom filename stem", custom)
        prefix = QCheckBox("Game code prefix")
        prefix.setChecked(True)
        layout.addRow(prefix)
        game = self.registry.game(clip["game"])
        checks = []
        for field in game.display_order if game else ["mainline"]:
            check = QCheckBox(field)
            check.setChecked(True)
            checks.append(check)
            layout.addRow(check)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        folder = destination.text().strip()
        if not folder:
            self.error("Choose a share folder")
            return
        self.settings["share_folder"] = folder
        self.save_settings()
        fields = [check.text() for check in checks if check.isChecked()]
        custom_name = custom.text() or None
        folders = self.catalogue.folders()
        include_prefix = prefix.isChecked()
        self.background(
            lambda cancelled, progress: share_clip(
                clip, self.registry, folder, folders, custom_name, fields, include_prefix, cancelled
            ),
            lambda target: QMessageBox.information(
                self, "Shared", f"Copied whole source to:\n{target}"
            ),
        )

    def open_configs(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.root / "configs/games")))

    def reload_configs(self):
        self.registry = Registry(self.root / "configs/games")
        self.refresh_references()
        self.refresh_library()
        self.formats.clear()

    def reset_layout(self):
        self.showNormal()
        self.resize(1400, 900)
        self.splitter.setSizes([420, 630, 350])

    def closeEvent(self, event):
        if self.worker:
            self.worker.cancelled.set()
            self.error("Cancelling current operation; close again after it finishes")
            event.ignore()
            return
        self.save_description()
        self.player.media.stop()
        self.export_player.media.stop()
        QApplication.instance().removeEventFilter(self)
        event.accept()


def style_application(application):
    application.setStyle("Fusion")
    application.setStyleSheet("""
        QWidget { background: #20242a; color: #e2e7ed; font-size: 13px; }
        QLineEdit, QPlainTextEdit, QListWidget, QComboBox { background: #15191f; padding: 6px; }
        QPushButton { background: #323a45; border: 1px solid #495361; padding: 7px; border-radius: 3px; }
        QPushButton:hover { background: #435568; }
        QPushButton:disabled { color: #75808d; }
        QListWidget::item:selected { background: #35586c; }
        QSplitter::handle { background: #424b55; }
    """)


def main():
    from logging.handlers import RotatingFileHandler

    import PySide6

    (ROOT / "data").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        handlers=[
            RotatingFileHandler(
                ROOT / "data/dfsorter.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8"
            )
        ],
    )
    QCoreApplication.addLibraryPath(str(Path(PySide6.__file__).parent / "plugins"))
    application = QApplication(sys.argv)
    style_application(application)
    window = Window()
    window.show()
    return application.exec()


if __name__ == "__main__":
    sys.exit(main())
