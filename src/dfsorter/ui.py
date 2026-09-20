import html
import logging
import os
import sys
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path

os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")

import yaml
from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QObject,
    QPoint,
    Qt,
    QThread,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import QAction, QDesktopServices, QIcon
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .browse import BrowsePage
from .catalogue import Catalogue
from .config import Registry, title
from .deletion import delete_reviewed, preview
from .deletion_dialog import DeletionDialog
from .output import export_project, share_clip, validate
from .parsing import parse_command, preview_command, query_clips, requests_discarded
from .playback import Player
from .scanning import ScanCoordinator
from .settings_dialog import SettingsDialog
from .theme import COLORS, SIZES, apply_theme, role, title_styles
from .widgets import CLIP_ROLE, ClipDelegate, Rating, icon, tag_prefix, tool

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
    result.setMaximumWidth(260)
    if text in {"Create Session", "Export project"}:
        role(result, "primary")
    elif text in {"Purge folder catalogue entries", "Delete project"}:
        role(result, "danger")
    return result


def page():
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(*([SIZES["panel_padding"]] * 4))
    layout.setSpacing(8)
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
        self.browse_newest = True
        self.browse_id = None
        self.browse_selected_id = None
        self.history = defaultdict(list)
        self.drafts = {}
        self.pane_overrides = {}
        self.space_down = False
        self.submit_resume = False
        self.consume_resume_space = False
        self.space_timer = QTimer(self)
        self.space_timer.setSingleShot(True)
        self.space_timer.setInterval(200)
        self.space_timer.timeout.connect(lambda: self.active_player().fast(True))
        self.media_info = self.catalogue.media_cache()
        self.pending_in = None
        self.pending_out = None
        self.worker = None
        self.refreshing = False
        self.setWindowTitle("DFSorter")
        self.setWindowIcon(QIcon(str(ROOT / "resources/mascot/dfsorter.ico")))
        self.resize(1400, 918)
        central, outer = page()
        self.setCentralWidget(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.navigation_strip = QWidget()
        self.navigation_strip.setObjectName("navigationStrip")
        navigation = QHBoxLayout(self.navigation_strip)
        navigation.setContentsMargins(SIZES["panel_padding"], 0, 4, 0)
        navigation.setSpacing(0)
        self.nav = {}
        for name in ["Home", "Browse", "Session", "Editing", "Export", "Config"]:
            self.nav[name] = button(name, lambda checked=False, name=name: self.panel(name))
            self.nav[name].setObjectName("navigation")
            self.nav[name].setCheckable(True)
            self.nav[name].setFocusPolicy(Qt.FocusPolicy.NoFocus)
            navigation.addWidget(self.nav[name])
        navigation.addStretch()
        self.undo_button = tool("undo-2", "Undo · Ctrl+Z", lambda: self.undo(False))
        self.redo_button = tool("redo-2", "Redo · Ctrl+Shift+Z", lambda: self.undo(True))
        self.undo_button.setIcon(icon("undo-2", COLORS["history_available"]))
        self.redo_button.setIcon(icon("redo-2", COLORS["history_available"]))
        self.update_history_controls()
        navigation.addWidget(self.undo_button, 0, Qt.AlignmentFlag.AlignVCenter)
        navigation.addSpacing(4)
        navigation.addWidget(self.redo_button, 0, Qt.AlignmentFlag.AlignVCenter)
        navigation.addSpacing(16)
        self.projects_toggle = button("Projects", self.toggle_projects)
        self.projects_toggle.setIcon(icon("folder-open"))
        self.projects_toggle.setToolTip("Show / hide Projects")
        self.projects_toggle.setAccessibleName("Show / hide Projects")
        self.projects_toggle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.projects_toggle.setCheckable(True)
        self.projects_toggle.setFixedHeight(SIZES["toolbar"])
        navigation.addWidget(self.projects_toggle, 0, Qt.AlignmentFlag.AlignVCenter)
        navigation.addSpacing(8)
        self.settings_button = tool("settings", "Settings and actions", lambda: None)
        for control in (self.undo_button, self.redo_button, self.settings_button):
            control.setProperty("navUtility", True)
        navigation.addWidget(self.settings_button, 0, Qt.AlignmentFlag.AlignVCenter)
        navigation.addSpacing(8)
        outer.addWidget(self.navigation_strip)
        self.splitter = QSplitter()
        self.splitter.setHandleWidth(1)
        workspace, workspace_layout = page()
        workspace_layout.setSpacing(0)
        workspace_layout.addWidget(self.splitter)
        outer.addWidget(workspace, 1)
        self.left, left_layout = page()
        left_layout.setContentsMargins(8, 4, 8, 4)
        role(self.left, "panel")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search or game:VAL agent:Jett kill:>=4")
        self.search.returnPressed.connect(self.refresh_library)
        left_layout.addWidget(self.search)
        self.filters, filter_layout = page()
        self.triage_filter = QComboBox()
        self.triage_filter.addItems(
            ["Hide discarded", "All triage", "Undefined", "Keep", "Discard"]
        )
        self.triage_filter.setCurrentText("Undefined")
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
        self.browse_filters, browse_filters_layout = page()
        browse_filters_layout.setContentsMargins(0, 0, 0, 0)
        self.browse_search = QLineEdit()
        self.browse_search.setPlaceholderText("Search clips")
        self.browse_search.returnPressed.connect(self.refresh_library)
        browse_filters_layout.addWidget(self.browse_search)
        self.browse_game = QComboBox()
        self.browse_game.addItem("All games", None)
        self.browse_game.currentIndexChanged.connect(self.refresh_library)
        browse_filters_layout.addWidget(self.browse_game)
        browse_header = QHBoxLayout()
        browse_header.setContentsMargins(13, 0, 5, 0)
        browse_title = QLabel("Library clips")
        role(browse_title, "paneHeading")
        browse_header.addWidget(browse_title, 1)
        self.browse_sort = tool("arrow-down-up", "Newest first · Switch to oldest first", self.toggle_browse_sort)
        browse_header.addWidget(self.browse_sort)
        browse_filters_layout.addLayout(browse_header)
        left_layout.addWidget(self.browse_filters)
        self.library_error = QLabel()
        role(self.library_error, "error")
        self.library_error.setWordWrap(True)
        self.library_error.hide()
        left_layout.addWidget(self.library_error)
        self.session_header = QWidget()
        session_header_layout = QHBoxLayout(self.session_header)
        self.session_header.setObjectName("sessionHeader")
        session_header_layout.setContentsMargins(13, 0, 5, 0)
        session_heading = QLabel("Session clips")
        role(session_heading, "paneHeading")
        session_header_layout.addWidget(session_heading)
        session_header_layout.addStretch()
        self.next_undefined_button = tool(
            "arrow-down-to-dot",
            "Next undefined clip · Jump ahead without changing verdicts (no wrap)",
            self.navigate_next_undefined,
        )
        session_header_layout.addWidget(self.next_undefined_button)
        self.session_header.hide()
        left_layout.addWidget(self.session_header)
        self.library = QListWidget()
        self.library.setMouseTracking(True)
        self.library.setUniformItemSizes(True)
        self.library.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.library.setItemDelegate(ClipDelegate(self.library))
        self.library.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.library.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.library.currentItemChanged.connect(self.select_clip)
        left_layout.addWidget(self.library, 1)
        self.session_counts = QLabel()
        self.session_counts.setWordWrap(True)
        self.session_counts.setAccessibleName("Session clip counts")
        role(self.session_counts, "secondary")
        self.session_counts.hide()
        left_layout.addWidget(self.session_counts)
        self.splitter.addWidget(self.left)
        self.center_column = QWidget()
        center_layout = QVBoxLayout(self.center_column)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)
        self.center = QStackedWidget()
        center_layout.addWidget(self.center, 1)
        self.splitter.addWidget(self.center_column)
        self.pages = {}
        self.build_pages()
        self.right, right_layout = page()
        role(self.right, "panel")
        self.active_label = QLabel()
        role(self.active_label, "secondary")
        self.active_label.setWordWrap(True)
        right_layout.addWidget(self.active_label)
        self.projects = QListWidget()
        right_layout.addWidget(self.projects)
        project_tools = QHBoxLayout()
        self.projects.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        for text, callback in [
            ("New project", self.new_project),
            ("Rename", self.rename_project),
            ("Activate", self.activate_project),
            ("Deactivate", self.deactivate),
            ("Add to project", lambda: self.membership(True)),
            ("Remove selected clips", lambda: self.membership(False)),
            ("Delete project", self.delete_project),
        ]:
            action = QAction(text, self.projects)
            action.triggered.connect(callback)
            self.projects.addAction(action)
            names = {
                "New project": "plus",
                "Rename": "pencil",
                "Activate": "check",
                "Deactivate": "power",
                "Add to project": "folder-plus",
                "Remove selected clips": "folder-x",
            }
            if text in names:
                project_tools.addWidget(tool(names[text], text, callback))
        project_tools.addStretch()
        right_layout.addLayout(project_tools)
        self.splitter.addWidget(self.right)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.splitterMoved.connect(self.panes_resized)
        self.command_area, command_layout = page()
        self.command_area.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        command_layout.setContentsMargins(12, 4 + self.fontMetrics().lineSpacing(), 12, 4)
        command_layout.setSpacing(4)
        self.command_history = QLabel()
        role(self.command_history, "muted")
        self.command_history.setWordWrap(True)
        self.command_history.hide()
        command_layout.addWidget(self.command_history)
        self.shortcut_hint = QLabel(
            "Space Play · ←/→ Seek · ↑/↓ Clips · I/O Range · R1–5 Rate · Backspace Reject · / or Enter Metadata · Shift+Enter Verdict + Next Undefined · Ctrl+Enter Add to project + Next · ? Shortcuts"
        )
        self.shortcut_hint.setObjectName("muted")
        self.shortcut_hint.setWordWrap(True)
        command_layout.addWidget(self.shortcut_hint)
        self.command = QLineEdit()
        self.command.setObjectName("command")
        self.command.textChanged.connect(self.remember_draft)
        self.command.setPlaceholderText("Enter clip metadata…")
        self.command_submitted_error = False
        self.command_saved_timer = QTimer(self)
        self.command_saved_timer.setSingleShot(True)
        self.command_saved_timer.setInterval(1200)
        self.command_saved_timer.timeout.connect(self.update_command_state)
        command_layout.addWidget(self.command)
        self.command_feedback = QLabel()
        self.command_feedback.setTextFormat(Qt.TextFormat.PlainText)
        self.command_feedback.setObjectName("muted")
        self.command_feedback.setWordWrap(True)
        self.command_feedback.setMinimumHeight(self.command_feedback.fontMetrics().height())
        command_layout.addWidget(self.command_feedback)
        self.field_reminder = QLabel()
        self.field_reminder.setTextFormat(Qt.TextFormat.RichText)
        self.field_reminder.setWordWrap(True)
        # Keep the command baseline stable when checklist glyphs change font metrics.
        self.field_reminder.setMinimumHeight(self.field_reminder.fontMetrics().height())
        self.field_reminder.setAccessibleName("Metadata field checklist with command preview")
        self.field_reminder.hide()
        fields_row = QHBoxLayout()
        fields_row.addWidget(self.field_reminder, 1)
        self.range_warning_icon = QLabel()
        self.range_warning_icon.setPixmap(icon("triangle-alert", COLORS["danger"], size=12).pixmap(12, 12))
        self.range_warning = QLabel("I/O not set")
        self.range_warning.setStyleSheet(f"color: {COLORS['danger']}; font-size: 11px;")
        for widget in (self.range_warning_icon, self.range_warning):
            policy = widget.sizePolicy()
            policy.setRetainSizeWhenHidden(True)
            widget.setSizePolicy(policy)
            widget.hide()
            fields_row.addWidget(widget)
        command_layout.addLayout(fields_row)
        self.command_error = QLabel()
        role(self.command_error, "error")
        self.command_error.setWordWrap(True)
        self.command_error.hide()
        command_layout.addWidget(self.command_error)
        center_layout.addWidget(self.command_area)
        self.transition_generation = 0
        self.transition_pending = False
        self.transition_scope = "page"
        self.transition_cover = QWidget(central)
        self.transition_cover.setObjectName("pageLoading")
        self.transition_cover.setStyleSheet(
            f"QWidget#pageLoading {{ background: {COLORS['bg_app']}; }}"
        )
        cover_layout = QVBoxLayout(self.transition_cover)
        cover_layout.addStretch()
        self.loading_label = QLabel("Loading…")
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        role(self.loading_label, "secondary")
        cover_layout.addWidget(self.loading_label)
        cover_layout.addStretch()
        self.transition_cover.hide()
        self.loading_indicator_timer = QTimer(self)
        self.loading_indicator_timer.setSingleShot(True)
        self.loading_indicator_timer.setInterval(1000)
        self.loading_indicator_timer.timeout.connect(self.loading_label.show)
        self.command_cover = QWidget(self.command_area)
        self.command_cover.setStyleSheet(f"background: {COLORS['bg_app']};")
        self.command_cover.hide()
        for player in (self.player, self.export_player, self.browse.player):
            player.loading_started.connect(lambda player=player: self.player_loading(player))
            player.loading_finished.connect(lambda player=player: self.player_ready(player))
        self.build_settings_menu()
        self.scan_timer = QTimer(self)
        self.scan_timer.setInterval(30_000)
        self.scan_timer.timeout.connect(self.request_auto_scan)
        self.scan_retry_timer = QTimer(self)
        self.scan_retry_timer.setSingleShot(True)
        self.scan_retry_timer.setInterval(1000)
        self.scan_retry_timer.timeout.connect(self.auto_scan)
        self.scan_timer.start()
        QApplication.instance().installEventFilter(self)
        QApplication.instance().focusChanged.connect(self.command_focus_changed)
        self.player.media.playbackStateChanged.connect(self.command_playback_changed)
        self.player.loading_finished.connect(self.update_command_state)
        self.refresh_references()
        self.panel("Home")
        self.reset_layout()
        if self.registry.errors:
            self.statusBar().showMessage("Configuration errors — see Config panel")
        QTimer.singleShot(0, self.rescan)

    def build_pages(self):
        for name in ["Home", "Browse", "Session", "Editing", "Export", "Config"]:
            widget, layout = page()
            self.pages[name] = (widget, layout)
            self.center.addWidget(widget)
        self.browse = BrowsePage(self)
        self.pages["Browse"][1].addWidget(self.browse)
        home = self.pages["Home"][1]
        home_title = QLabel("Capture folders")
        role(home_title, "heading")
        home.addWidget(home_title)
        explanation = QLabel(
            "Add folders containing recordings. Rescan finds new clips; original files stay untouched."
        )
        explanation.setWordWrap(True)
        role(explanation, "secondary")
        home.addWidget(explanation)
        folder_controls = QHBoxLayout()
        self.add_folder_button = button("Add folder…", self.add_folder)
        self.add_folder_button.setIcon(icon("folder-plus"))
        folder_controls.addWidget(self.add_folder_button)
        self.rescan_button = button("Rescan", self.rescan)
        self.rescan_button.setIcon(icon("refresh-cw"))
        self.rescan_button.setToolTip(
            "Find new files in all enabled folders. Reuse cached media information for unchanged files."
        )
        folder_controls.addWidget(self.rescan_button)
        self.folder_more = QToolButton()
        self.folder_more.setObjectName("captureFolderMenuButton")
        self.folder_more.setText("More…")
        self.folder_menu = QMenu(self.folder_more)
        self.folder_toggle_action = self.folder_menu.addAction("Pause scanning", self.toggle_folder)
        self.folder_toggle_action.setToolTip(
            "Pause scanning and exclude this folder from new sessions. Existing clips and sessions remain."
        )
        self.folder_migrate_action = self.folder_menu.addAction("Relink folder…", self.migrate)
        self.folder_migrate_action.setToolTip("Find an already moved folder; no files are moved.")
        self.folder_remove_action = self.folder_menu.addAction("Remove folder…", self.remove_folder)
        self.folder_menu.addSeparator()
        rebuild = self.folder_menu.addAction("Rebuild media information…", self.reinspect)
        rebuild.setToolTip(
            "Rescan all enabled folders and reread every file’s media information, ignoring the cache."
        )
        self.folder_menu.setToolTipsVisible(True)
        self.folder_menu.aboutToShow.connect(self.update_folder_actions)
        self.folder_more.setMenu(self.folder_menu)
        self.folder_more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        folder_controls.addWidget(self.folder_more)
        folder_controls.addStretch()
        home.addLayout(folder_controls)
        self.folders = QListWidget()
        self.folders.setMinimumHeight(120)
        self.folders.setWordWrap(True)
        self.folder_context_menu = QMenu(self.folders)
        self.folder_context_menu.addAction(self.folder_toggle_action)
        self.folder_context_menu.setToolTipsVisible(True)
        self.folders.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.folders.customContextMenuRequested.connect(self.show_folder_context_menu)
        home.addWidget(self.folders, 1)
        note = QLabel(
            "Right-click a folder to pause or resume scanning; select More for other actions. "
            "Paused folders stay in the library but are excluded "
            "from new sessions. Unlinked clips are saved entries from folders no longer tracked."
        )
        note.setWordWrap(True)
        role(note, "secondary")
        home.addWidget(note)
        session = self.pages["Session"][1]
        self.session_status = QLabel()
        self.session_status.setWordWrap(True)
        session.addWidget(self.session_status)
        self.session_count = QSpinBox()
        self.session_count.setRange(1, 1000000)
        self.session_count.setValue(50)
        session_choices = QHBoxLayout()
        self.session_mode = "first"
        self.session_choices = {}
        for text, mode in [
            ("Session from selected", "selected"),
            ("Session from first N", "first"),
            ("Session from all results", "all"),
        ]:
            control = button(
                {"selected": "Selected", "first": "First N", "all": "All"}[mode],
                lambda checked=False, mode=mode: self.choose_session_mode(mode),
            )
            control.setCheckable(True)
            control.setChecked(mode == "first")
            self.session_choices[mode] = control
            session_choices.addWidget(control)
        session_choices.addWidget(self.session_count)
        session_choices.addStretch()
        session.addLayout(session_choices)
        session.addWidget(button("Create Session", lambda: self.create_session(self.session_mode)))
        session.addWidget(button("Resume session", lambda: self.panel("Editing")))
        session.addWidget(button("End session", self.end_session))
        session.addStretch()
        editing = self.pages["Editing"][1]
        self.player = Player(self.settings)
        self.player.previous.connect(lambda: self.navigate(-1))
        self.player.next.connect(lambda: self.navigate(1))
        editing.addWidget(self.player, 1)
        self.working_title = QLabel()
        self.working_title.setWordWrap(True)
        self.working_title.setTextFormat(Qt.TextFormat.RichText)
        self.working_title.setObjectName("workingTitle")
        editing.addWidget(self.working_title)
        self.filename = QLabel()
        role(self.filename, "secondary")
        self.filename.setWordWrap(True)
        editing.addWidget(self.filename)
        self.clip_status = QLabel()
        role(self.clip_status, "secondary")
        self.clip_status.setWordWrap(True)
        editing.addWidget(self.clip_status)
        triage = QHBoxLayout()
        self.triage_buttons = {}
        for text, state in [("Keep", "keep"), ("Discard", "discard"), ("Undefined", None)]:
            control = button(text, lambda checked=False, state=state: self.edit({"triage": state}))
            control.setCheckable(True)
            role(control, state or "undefined")
            self.triage_buttons[state] = control
            triage.addWidget(control)
        triage.addWidget(button("Change game", self.change_game))
        triage.addStretch()
        editing.addLayout(triage)
        stars = QHBoxLayout()
        self.rating = Rating()
        self.rating.changed.connect(lambda value: self.edit({"rating": value}))
        stars.addWidget(self.rating)
        stars.addWidget(tool("x", "Clear rating", lambda: self.edit({"rating": None})))
        stars.addStretch()
        stars.addWidget(tool("circle-help", "Review shortcuts · ?", self.show_shortcuts))
        editing.addLayout(stars)
        self.structured = QLabel()
        self.structured.setObjectName("muted")
        self.structured.setWordWrap(True)
        editing.addWidget(self.structured)
        self.description = QLabel()
        self.description.setTextFormat(Qt.TextFormat.PlainText)
        self.description.setWordWrap(True)
        self.description.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.description.setAccessibleName("Description")
        self.description.hide()
        editing.addWidget(self.description)
        controls = self.player.controls
        for text, callback in [
            ("Set In", self.mark_in),
            ("Set Out", self.mark_out),
            ("Clear range", self.clear_range),
            ("Share", self.share),
        ]:
            names = {
                "Set In": "list-start",
                "Set Out": "list-end",
                "Clear range": "brackets",
                "Share": "share-2",
            }
            label = {"Set In": "Set In · I", "Set Out": "Set Out · O"}.get(text, text)
            controls.addWidget(tool(names[text], label, callback))
        project_separator = QWidget()
        project_separator.setFixedSize(1, 20)
        project_separator.setStyleSheet(f"background: {COLORS['separator']};")
        controls.addWidget(project_separator, 0, Qt.AlignmentFlag.AlignVCenter)
        self.add_project_next = tool(
            "folder-plus",
            "Add to project + Next · Ctrl+Enter (review mode)",
            self.add_to_project_next,
        )
        self.add_project_next.setEnabled(False)
        controls.addWidget(self.add_project_next)
        exporting = self.pages["Export"][1]
        self.export_project = QComboBox()
        self.export_project.currentIndexChanged.connect(self.export_selection)
        exporting.addWidget(self.export_project)
        self.export_player = Player(self.settings)
        self.export_player.previous_button.hide()
        self.export_player.next_button.hide()
        exporting.addWidget(self.export_player, 1)
        self.export_errors = QPlainTextEdit()
        self.export_errors.setReadOnly(True)
        self.export_errors.setMaximumHeight(130)
        exporting.addWidget(self.export_errors)
        self.format_game = QComboBox()
        self.format_game.currentIndexChanged.connect(self.show_format)
        exporting.addWidget(self.format_game)
        self.format_box = QWidget()
        self.format_layout = QGridLayout(self.format_box)
        exporting.addWidget(self.format_box)
        self.formats = {}
        self.export_destination = QLineEdit(str(self.settings.get("export_folder", "")))
        exporting.addWidget(self.export_destination)
        exporting.addWidget(button("Choose export folder", self.choose_export_folder))
        self.group_rating = QCheckBox("Group by Rating")
        exporting.addWidget(self.group_rating)
        self.export_button = button("Export project", self.run_export)
        exporting.addWidget(self.export_button)
        configuration = self.pages["Config"][1]
        self.config_status = QPlainTextEdit()
        self.config_status.setReadOnly(True)
        configuration.addWidget(self.config_status)
        configuration.addWidget(button("Open game YAML folder", self.open_configs))
        configuration.addWidget(button("Reload configurations", self.reload_configs))

    def build_settings_menu(self):
        self.settings_menu = QMenu(self)
        self.browse_write_actions = []
        actions = [
            ("Settings…", self.open_settings, None),
            ("Capture folders…", lambda: self.panel("Home"), None),
            None,
            ("Reset clip metadata…", self.reset_metadata, None),
            ("Edit tag…", self.edit_tag, None),
            None,
            ("Delete rejected originals…", self.delete_rejected, None),
            ("Reset window and panes", self.reset_layout, None),
            None,
            ("Exit", self.close, "Ctrl+Q"),
        ]
        for entry in actions:
            if entry is None:
                self.settings_menu.addSeparator()
                continue
            name, callback, shortcut = entry
            action = QAction(name, self)
            action.triggered.connect(callback)
            if name in {"Settings…", "Reset clip metadata…", "Edit tag…", "Delete rejected originals…"}:
                self.browse_write_actions.append(action)
            if shortcut:
                action.setShortcut(shortcut)
            self.addAction(action)
            self.settings_menu.addAction(action)
        for name, callback, shortcut in [
            ("Undo", lambda: self.undo(False), "Ctrl+Z"),
            ("Redo", lambda: self.undo(True), "Ctrl+Shift+Z"),
        ]:
            action = QAction(name, self)
            action.triggered.connect(callback)
            action.setShortcut(shortcut)
            self.addAction(action)
        self.settings_button.setMenu(self.settings_menu)
        self.settings_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.settings_button.setObjectName("settingsMenuButton")
        self.settings_button.ensurePolished()
        self.settings_button.setFixedSize(SIZES["toolbar"], SIZES["toolbar"])

    def error(self, message):
        logging.error("%s", message)
        self.statusBar().showMessage(str(message), 12000)
        self.command_error.setText(str(message))
        self.command_error.setVisible(bool(str(message)))

    def open_settings(self):
        if self.current_panel == "Browse":
            return
        dialog = SettingsDialog(self)
        self.settings_dialog = dialog
        dialog.exec()
        self.settings_dialog = None
        dialog.deleteLater()

    def delete_rejected(self):
        if self.current_panel == "Browse":
            return
        if self.worker is not None:
            self.error("Wait for the current operation to finish")
            return
        self.background(
            lambda cancelled, progress: preview(
                self.catalogue, self.media_info, cancelled, progress
            ),
            lambda candidates: QTimer.singleShot(0, lambda: self.review_deletion(candidates)),
        )

    def review_deletion(self, candidates):
        if self.current_panel == "Browse":
            return
        if self.worker is not None:
            QTimer.singleShot(25, lambda: self.review_deletion(candidates))
            return
        dialog = DeletionDialog(candidates, self)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        reviewed = dialog.candidates
        dialog.deleteLater()
        if not accepted:
            return
        self.player.load(None)
        self.export_player.load(None)

        def done(results):
            self.refresh_references()
            self.refresh_library()
            if self.current_id:
                self.player.load(self.catalogue.clip(self.current_id))
                self.render_clip()
            self.export_selection()
            report = QDialog(self)
            report.setWindowTitle("Deletion results")
            report.resize(850, 500)
            layout = QVBoxLayout(report)
            count = sum(status == "Deleted" for path, status in results)
            layout.addWidget(
                QLabel(
                    f"Deleted {count} of {len(results)} reviewed originals. "
                    "Catalogue records remain."
                )
            )
            details = QPlainTextEdit()
            details.setReadOnly(True)
            details.setPlainText("\n".join(f"{status}: {path}" for path, status in results))
            layout.addWidget(details)
            close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            close.rejected.connect(report.reject)
            layout.addWidget(close)
            report.exec()
            report.deleteLater()

        self.background(
            lambda cancelled, progress: delete_reviewed(
                self.catalogue, reviewed, cancelled=cancelled, progress=progress
            ),
            done,
        )

    def confirm(self, message):
        return (
            QMessageBox.question(self, "Confirm catalogue operation", message)
            == QMessageBox.StandardButton.Yes
        )

    def selected_id(self, listing):
        item = listing.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def player_loading(self, player):
        if self.current_panel in {"Browse", "Editing", "Export"} and player is self.active_player():
            self.begin_page_transition("clip")

    def player_ready(self, player):
        if self.current_panel in {"Browse", "Editing", "Export"} and player is self.active_player():
            self.queue_page_reveal()

    def position_transition_covers(self):
        target = self.centralWidget() if self.transition_scope == "page" else self.center
        self.transition_cover.setGeometry(
            target.mapTo(self.centralWidget(), QPoint(0, 0)).x(),
            target.mapTo(self.centralWidget(), QPoint(0, 0)).y(),
            target.width(),
            target.height(),
        )
        self.command_cover.setGeometry(self.command_area.rect())

    def begin_page_transition(self, scope="page"):
        if not self.transition_pending or scope == "page":
            self.transition_scope = scope
        self.transition_generation += 1
        if not self.transition_pending:
            self.transition_pending = True
            self.loading_label.hide()
            self.loading_indicator_timer.start()
        for player in (self.player, self.export_player, self.browse.player):
            policy = player.video.sizePolicy()
            policy.setRetainSizeWhenHidden(True)
            player.video.setSizePolicy(policy)
            player.video.hide()
        self.position_transition_covers()
        self.command_cover.setVisible(
            self.transition_scope == "clip" and self.current_panel == "Editing"
        )
        self.command_cover.raise_()
        self.transition_cover.show()
        self.transition_cover.raise_()

    def queue_page_reveal(self):
        generation = self.transition_generation
        QTimer.singleShot(0, lambda: self.reveal_page(generation))

    def reveal_page(self, generation):
        if generation != self.transition_generation or not self.transition_pending:
            return
        if self.current_panel in {"Browse", "Editing", "Export"} and self.active_player().awaiting_frame:
            return
        self.loading_indicator_timer.stop()
        self.transition_pending = False
        self.transition_cover.hide()
        self.command_cover.hide()
        self.centralWidget().layout().activate()
        for player in (self.player, self.export_player, self.browse.player):
            player.video.show()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "transition_cover"):
            self.position_transition_covers()

    def panel(self, name):
        if not self.ensure_range_complete():
            return
        self.submit_resume = False
        if name == "Editing" and not self.catalogue.state("session"):
            self.error("Create a session before entering Editing")
            return
        self.begin_page_transition()
        self.cancel_space()
        self.player.media.pause()
        self.export_player.media.pause()
        self.browse.player.media.pause()
        if self.current_panel == "Browse" and name != "Browse":
            self.browse.leave()
        entering_browse = name == "Browse" and self.current_panel != "Browse"
        if entering_browse:
            self.browse_id = self.browse_selected_id
            self.browse_newest = True
            self.browse_sort.setToolTip("Newest first · Switch to oldest first")
            self.browse_sort.setAccessibleName("Newest first · Switch to oldest first")
        # Hiding focused filters can select an item from the outgoing page's list.
        # That automatic focus change must not become a manual Browse selection.
        library_signals_blocked = self.library.blockSignals(True)
        self.current_panel = name
        self.center.setCurrentWidget(self.pages[name][0])
        self.update_projects_visibility()
        for destination, control in self.nav.items():
            control.setChecked(destination == name)
        self.command_area.setVisible(name == "Editing")
        self.command.setEnabled(name == "Editing")
        self.shortcut_hint.setVisible(name == "Editing")
        self.field_reminder.hide()
        self.session_header.setVisible(name == "Editing")
        self.search.setVisible(name not in {"Browse", "Editing", "Export"})
        self.filters.setVisible(name not in {"Browse", "Editing", "Export"})
        self.browse_filters.setVisible(name == "Browse")
        self.library.setSelectionMode(
            QListWidget.SelectionMode.SingleSelection
            if name in {"Browse", "Editing"}
            else QListWidget.SelectionMode.ExtendedSelection
        )
        self.library.blockSignals(library_signals_blocked)
        self.refresh_references()
        self.refresh_library()
        if entering_browse:
            self.library.scrollToTop()
            if self.library.currentItem() is not None:
                self.library.scrollToItem(self.library.currentItem())
        if name == "Editing":
            session = self.catalogue.state("session")
            self.load_clip(session["ids"][session["index"]])
            self.review_mode()
        elif name == "Export":
            self.export_selection()
        self.queue_page_reveal()

    def refresh_references(self):
        self.update_history_controls()
        self.refreshing = True
        projects = self.catalogue.projects()
        active = self.catalogue.state("active_project")
        self.add_project_next.setEnabled(bool(active))
        project_selection = self.selected_id(self.projects)
        self.projects.clear()
        for project in projects:
            item = QListWidgetItem(project["name"])
            if project["project_id"] == active:
                item.setIcon(icon("check", COLORS["accent"]))
            item.setToolTip(
                project["name"] + (" · Active project" if project["project_id"] == active else "")
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
        selected = self.browse_game.currentData()
        self.browse_game.blockSignals(True)
        self.browse_game.clear()
        self.browse_game.addItem("All games", None)
        self.browse_game.addItem("Unassigned", "")
        for name in self.registry.games:
            self.browse_game.addItem(name, name)
        self.browse_game.setCurrentIndex(max(0, self.browse_game.findData(selected)))
        self.browse_game.blockSignals(False)
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
            text = f"{folder['path']}\n"
            games = ", ".join(f"{name}: {count}" for name, count in sorted(counts.items()))
            text += (
                f"{'Scanning on' if folder['enabled'] else 'Scanning paused'} · {len(ids)} clips"
            )
            text += f" · {games} · Average {average}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, folder["folder_id"])
            self.folders.addItem(item)
            if folder["folder_id"] == folder_selection:
                self.folders.setCurrentItem(item)
        unlinked = self.catalogue.unlinked_clips()
        if unlinked:
            item = QListWidgetItem(
                f"Unlinked catalogue clips\n{len(unlinked)} clips from removed folders · "
                "Select More → Remove saved entries… to review"
            )
            item.setData(Qt.ItemDataRole.UserRole, "__unlinked__")
            item.setToolTip(
                "\n".join(sorted({str(Path(clip["source_path"]).parent) for clip in unlinked}))
            )
            self.folders.addItem(item)
            if folder_selection == "__unlinked__":
                self.folders.setCurrentItem(item)
        if self.folders.count() == 1 and self.folders.currentRow() < 0:
            self.folders.setCurrentRow(0)
        self.refresh_session_status(clips)
        self.config_status.setPlainText(
            "\n".join(self.registry.errors)
            or "Configurations valid:\n" + "\n".join(self.registry.games)
        )
        self.refreshing = False

    def refresh_session_status(self, clips=None):
        if clips is None:
            clips = {clip["clip_id"]: clip for clip in self.catalogue.clips()}
        session = self.catalogue.state("session")
        self.nav["Editing"].setEnabled(bool(session))
        self.session_counts.setVisible(bool(session) and self.current_panel == "Editing")
        if session:
            counts = Counter(clips[clip_id]["triage"] or "undefined" for clip_id in session["ids"])
            total = len(session["ids"])
            self.session_counts.setText(
                f"Kept {counts['keep']} · Rejected {counts['discard']}\n"
                f"Undefined {counts['undefined']} · Total {total}"
            )
            self.session_status.setText(
                f"Position {session['index'] + 1} / {total}\n"
                + "\n".join(
                    f"{state}: {counts[state]} ({counts[state] / total:.0%})"
                    for state in ["keep", "discard", "undefined"]
                )
            )
        else:
            self.session_counts.clear()
            self.session_status.setText(
                "No active session. Filter and select clips in the library."
            )

    def render_card(self, item, clip):
        available = "" if Path(clip["source_path"]).is_file() else " [unavailable]"
        card_title = tag_prefix(clip) + title(
            {**clip, "mainline": (clip.get("mainline") or "").strip()},
            self.registry,
            lowercase=self.settings.get("lowercase_generated_titles", True),
            mainline_separator=" | ",
        )
        browse_details = None
        if self.current_panel == "Browse":
            from datetime import datetime

            captured = self.browse_sort_key(clip)[0]
            try:
                captured = datetime.fromisoformat(captured.replace("Z", "+00:00")).astimezone().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            except ValueError:
                captured = captured or "Date unavailable"
            source = Path(clip["source_path"])
            folder_name = next(
                (Path(folder["path"]).name for folder in self.catalogue.folders()
                 if source.is_relative_to(Path(folder["path"]))),
                "Unlinked",
            )
            browse_details = f"{captured} · {folder_name}"
        details = browse_details or f"{clip['game'] or 'Unassigned'} · {clip['triage'] or 'undefined'}"
        item.setText(f"{card_title}\n{details}{available}")
        item.setToolTip(item.text() + "\n" + clip["source_path"])
        item.setData(Qt.ItemDataRole.UserRole, clip["clip_id"])
        item.setData(
            CLIP_ROLE,
            {
                "title": card_title,
                "rich_title": tag_prefix(clip, rich=True)
                + title(
                    {**clip, "mainline": (clip.get("mainline") or "").strip()},
                    self.registry,
                    rich=True,
                    lowercase=self.settings.get("lowercase_generated_titles", True),
                    rich_styles=title_styles(card=True),
                    mainline_separator=" | ",
                ),
                "browse_details": browse_details,
                "game": clip["game"],
                "triage": clip["triage"],
                "unavailable": bool(available),
            },
        )

    def browse_sort_key(self, clip):
        from datetime import datetime, timezone

        captured = self.media_info.get(clip["source_path"], {}).get("created")
        if not captured:
            try:
                captured = datetime.fromtimestamp(
                    Path(clip["source_path"]).stat().st_ctime, timezone.utc
                ).isoformat()
            except OSError:
                captured = ""
        return captured, clip["source_path"]

    def toggle_browse_sort(self):
        self.browse_newest = not self.browse_newest
        current, other = ("Newest", "oldest") if self.browse_newest else ("Oldest", "newest")
        label = f"{current} first · Switch to {other} first"
        self.browse_sort.setToolTip(label)
        self.browse_sort.setAccessibleName(label)
        self.refresh_library()

    def update_browse_navigation(self):
        row = self.library.currentRow()
        self.browse.player.previous_button.setEnabled(row > 0)
        self.browse.player.next_button.setEnabled(0 <= row < self.library.count() - 1)

    def refresh_library(self):
        self.update_history_controls()
        if getattr(self, "settings_dialog", None) is not None:
            self.settings_dialog.refresh()
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
            elif self.current_panel == "Browse":
                hidden = self.catalogue.hidden_deleted_ids()
                clips = [
                    clip for clip in clips
                    if clip["clip_id"] not in hidden
                ]
                clips = query_clips(clips, self.browse_search.text(), self.registry)
                game = self.browse_game.currentData()
                if game is not None:
                    clips = [clip for clip in clips if (clip["game"] or "") == game]
                clips.sort(key=self.browse_sort_key, reverse=self.browse_newest)
            else:
                clips = query_clips(clips, self.search.text(), self.registry)
                if self.current_panel == "Session":
                    excluded = self.catalogue.session_excluded_ids()
                    clips = [clip for clip in clips if clip["clip_id"] not in excluded]
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
            if self.current_panel == "Browse":
                current = self.browse_id
                if current not in {clip["clip_id"] for clip in clips}:
                    current = clips[0]["clip_id"] if clips else None
                selected = {current}
            if self.current_panel == "Editing" and self.catalogue.state("session"):
                session = self.catalogue.state("session")
                current = session["ids"][session["index"]]
            scroll = self.library.verticalScrollBar().value()
            anchor = self.library.itemAt(1, 1)
            anchor_id = anchor.data(Qt.ItemDataRole.UserRole) if anchor else None
            anchor_offset = self.library.visualItemRect(anchor).top() if anchor else 0
            self.library.blockSignals(True)
            self.library.clear()
            for clip in clips:
                item = QListWidgetItem()
                self.render_card(item, clip)
                self.library.addItem(item)
                if clip["clip_id"] == current:
                    self.library.setCurrentItem(item)
                item.setSelected(clip["clip_id"] in selected or clip["clip_id"] == current)
            self.library.doItemsLayout()
            for index in range(self.library.count()):
                item = self.library.item(index)
                if item.data(Qt.ItemDataRole.UserRole) == anchor_id:
                    scroll = (
                        self.library.verticalScrollBar().value()
                        + self.library.visualItemRect(item).top()
                        - anchor_offset
                    )
                    break
            self.library.verticalScrollBar().setValue(scroll)
            self.library.blockSignals(False)
            if self.current_panel == "Browse":
                self.browse_id = current
                self.browse.load(self.catalogue.clip(current) if current else None)
                self.update_browse_navigation()
            self.library_error.clear()
            self.library_error.hide()
        except ValueError as error:
            self.library_error.setText(str(error))
            self.library_error.show()

    def select_clip(self, item, previous=None):
        if not item:
            return
        clip_id = item.data(Qt.ItemDataRole.UserRole)
        if self.current_panel == "Browse":
            self.cancel_space()
            self.browse_id = clip_id
            self.browse_selected_id = clip_id
            self.browse.load(self.catalogue.clip(clip_id))
            self.update_browse_navigation()
        elif self.current_panel == "Editing":
            self.switch_editing_clip(clip_id)
        elif self.current_panel == "Export":
            self.export_player.load(self.catalogue.clip(clip_id))

    def switch_editing_clip(self, clip_id, ensure_visible=False):
        if clip_id == self.current_id:
            return
        if not self.ensure_range_complete():
            self.library.blockSignals(True)
            for index in range(self.library.count()):
                item = self.library.item(index)
                if item.data(Qt.ItemDataRole.UserRole) == self.current_id:
                    self.library.setCurrentItem(item)
                    break
            self.library.blockSignals(False)
            return
        session = self.catalogue.state("session")
        self.catalogue.navigate(session["ids"].index(clip_id))
        for index in range(self.library.count()):
            item = self.library.item(index)
            item_id = item.data(Qt.ItemDataRole.UserRole)
            if item_id in {self.current_id, clip_id}:
                self.render_card(item, self.catalogue.clip(item_id))
            if item_id == clip_id:
                self.library.blockSignals(True)
                self.library.setCurrentItem(item)
                self.library.blockSignals(False)
                if ensure_visible:
                    self.library.scrollToItem(item)
        self.refresh_session_status()
        self.begin_page_transition("clip")
        self.load_clip(clip_id)

    def load_clip(self, clip_id):
        if not self.ensure_range_complete():
            return
        self.command_submitted_error = False
        self.command_saved_timer.stop()
        self.submit_resume = False
        self.cancel_space()
        self.current_id = clip_id
        self.pending_in = None
        self.pending_out = None
        self.command.setText(self.drafts.get(clip_id, ""))
        self.command_error.clear()
        self.command_error.hide()
        self.render_clip()
        self.player.load(self.catalogue.clip(clip_id))
        self.review_mode()

    def refresh_title_presentation(self):
        self.browse.render_title()
        for index in range(self.library.count()):
            item = self.library.item(index)
            clip = self.catalogue.clip(item.data(Qt.ItemDataRole.UserRole))
            if clip:
                self.render_card(item, clip)
        if self.current_id:
            self.render_working_title(self.catalogue.clip(self.current_id))

    def render_working_title(self, clip):
        game = self.registry.game(clip["game"])
        title_fields = game.display_order if game else ["mainline"]
        has_title = any(
            (clip.get("mainline") if key == "mainline" else clip["metadata"].get(key))
            not in (None, "", [])
            for key in title_fields
        )
        if has_title:
            rendered = title(
                clip,
                self.registry,
                rich=True,
                mainline_separator=" | ",
                lowercase=self.settings.get("lowercase_generated_titles", True),
                rich_styles=title_styles(),
            )
        else:
            rendered = html.escape(Path(clip["source_path"]).name)
            rendered += (
                f' <span style="color:{COLORS["text_secondary"]}; font-size:12px; font-weight:400">'
                "— Working title not set</span>"
            )
        rendered = f'<span style="color:{COLORS["text_working_title"]}">{rendered}</span>'
        self.working_title.setText(tag_prefix(clip, rich=True) + rendered)

    def render_clip(self):
        self.update_history_controls()
        if not self.current_id:
            return
        clip = self.catalogue.clip(self.current_id)
        game = self.registry.game(clip["game"])
        for index in range(self.library.count()):
            item = self.library.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == self.current_id:
                self.render_card(item, clip)
                break
        self.command.setPlaceholderText(
            game.command_example if game and game.command_example else "Enter clip metadata…"
        )
        self.render_working_title(clip)
        self.render_field_reminder(clip, game)
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
        self.rating.value = clip["rating"]
        self.rating.preview = None
        self.rating.update()
        for state, control in self.triage_buttons.items():
            control.setChecked(clip["triage"] == state)
        self.structured.setText(
            " | ".join(
                f"{key}: {', '.join(map(str, value)) if isinstance(value, list) else value}"
                for key, value in clip["metadata"].items()
                if game and key in game.fields
            )
            or "No structured metadata"
        )
        self.description.setText(clip["description"] or "")
        self.description.setVisible(bool((clip["description"] or "").strip()))
        self.player.seek.marker_range = (clip["in_ms"], clip["out_ms"])
        self.player.seek.update()
        self.command_history.setText("\n".join(self.history[self.current_id][-3:]))
        self.command_history.setVisible(bool(self.command_history.text()))
        self.refresh_session_status()
        self.update_command_state()

    def render_field_reminder(self, clip, game):
        self.update_range_warning()
        self.field_reminder.setVisible(self.current_panel == "Editing" and game is not None)
        if game is None:
            self.field_reminder.clear()
            return
        state = "Saved metadata."
        if self.command.text().strip():
            patch, validation, _ = preview_command(self.command.text(), clip["game"], self.registry)
            clip = {
                **clip,
                **patch,
                "metadata": {**clip["metadata"], **patch.get("metadata", {})},
            }
            state = (
                "Command preview; press Enter to save."
                if validation == "valid"
                else "Partial command preview; finish or correct the command before saving."
            )
        self.field_reminder.setToolTip(
            state
            + " ✓ populated · ! required for export · o optional · x invalid for current configuration."
        )
        fields = list(
            dict.fromkeys([*game.display_order, *game.fields, "mainline", "rating", "tag"])
        )
        entries = []
        for key in fields:
            if key == "description":
                continue
            value = clip["metadata"].get(key) if key in game.fields else clip.get(key)
            missing = value in (None, "", [])
            valid = True
            if not missing:
                if key in {"kill", "clutch", "rating"}:
                    valid = type(value) is int and value >= (0 if key == "kill" else 1)
                    if key == "rating":
                        valid = valid and value <= 5
                elif key in game.fields:
                    definition = game.fields[key]
                    multiple = definition.get("multiple", False)
                    values = value if isinstance(value, list) else [value]
                    valid = isinstance(value, list) if multiple else isinstance(value, str)
                    valid = valid and all(
                        isinstance(entry, str) and bool(entry.strip()) for entry in values
                    )
                    if definition.get("type") == "enum":
                        valid = valid and all(
                            entry in definition.get("values", []) for entry in values
                        )
                else:
                    valid = isinstance(value, str)
            if not valid:
                mark, color = "x", "danger"
            elif not missing:
                mark, color = "✓", "success"
            elif key in game.required_for_export:
                mark, color = "!", "warning"
            else:
                mark, color = "o", "text_muted"
            entries.append(
                f'<span style="color:{COLORS[color]}">{mark}&nbsp;{html.escape(key)}</span>'
            )
        self.field_reminder.setText(
            '<span style="font-size:11px">' + " &nbsp; ".join(entries) + "</span>"
        )

    def edit(self, patch, **kwargs):
        if self.current_panel == "Browse":
            return
        if self.current_panel != "Editing" or not self.current_id:
            return
        try:
            self.catalogue.patch(self.current_id, patch, editing=True, **kwargs)
            self.render_clip()
        except (ValueError, OSError) as error:
            self.error(error)

    def submit(self):
        if self.current_panel == "Browse":
            return
        if self.current_panel != "Editing" or not self.current_id:
            return
        text = self.command.text()
        try:
            clip = self.catalogue.clip(self.current_id)
            patch = parse_command(text, clip["game"], self.registry)
            self.catalogue.patch(self.current_id, patch, editing=True)
            if text.strip():
                self.history[self.current_id].append(text)
                self.history[self.current_id] = self.history[self.current_id][-3:]
            self.command.clear()
            self.command_error.clear()
            self.command_error.hide()
            self.render_clip()
            self.command.setFocus()
            self.submit_resume = self.editing_paused()
            if text.strip():
                self.command_saved_timer.start()
            self.update_command_state()
        except ValueError as error:
            self.submit_resume = False
            self.command_submitted_error = True
            self.update_command_state()
            self.error(error)

    def add_to_project_next(self):
        if self.current_panel == "Browse":
            return
        if not self.ensure_range_complete():
            return
        project_id = self.catalogue.state("active_project")
        session = self.catalogue.state("session")
        if self.current_panel != "Editing" or not self.current_id or not project_id or not session:
            return
        try:
            self.catalogue.patch(self.current_id, {}, membership=(project_id, True))
            if session["index"] + 1 < len(session["ids"]):
                self.navigate(1)
            else:
                self.render_clip()
                self.statusBar().showMessage("Added to active project — end of session.", 12000)
            self.review_mode()
        except (ValueError, OSError) as error:
            self.error(error)

    def advance_review(self):
        if self.current_panel == "Browse":
            return
        if self.current_panel != "Editing" or not self.current_id:
            return
        if not self.ensure_range_complete():
            return
        if self.command.text():
            self.error(
                "Enter input mode if needed, then press Enter to submit existing commands first."
            )
            return
        session = self.catalogue.state("session")
        if not session or not session["ids"]:
            return
        clip = self.catalogue.clip(self.current_id)
        if clip["triage"] != "discard":
            game = self.registry.game(clip["game"])
            if not game:
                self.error("Assign a configured game before Keep + Next, or explicitly Discard.")
                return
            missing = [
                key
                for key in game.required_for_export
                if clip["metadata"].get(key) in (None, "", [])
            ]
            if missing:
                self.error("Cannot Keep + Next: missing required fields: " + ", ".join(missing))
                return
        try:
            if clip["triage"] != "discard":
                self.catalogue.patch(self.current_id, {"triage": "keep"}, editing=True)
            self.command_error.clear()
            self.command_error.hide()
            clips = {clip["clip_id"]: clip for clip in self.catalogue.clips()}
            next_id = next(
                (
                    clip_id
                    for clip_id in session["ids"][session["index"] + 1 :]
                    if clips[clip_id]["triage"] is None
                ),
                None,
            )
            if next_id is not None:
                self.switch_editing_clip(next_id, ensure_visible=True)
            else:
                self.render_clip()
                self.refresh_session_status(clips)
                item = self.library.currentItem()
                if item is not None:
                    self.render_card(item, clips[self.current_id])
                unfinished = any(clips[clip_id]["triage"] is None for clip_id in session["ids"])
                message = (
                    "No undefined clips ahead — earlier Session clips remain undefined."
                    if unfinished
                    else "Session complete — no undefined clips remain."
                )
                self.statusBar().showMessage(message, 12000)
            self.review_mode()
        except (ValueError, OSError) as error:
            self.error(error)

    def navigate_next_undefined(self):
        session = self.catalogue.state("session")
        if self.current_panel != "Editing" or not session:
            return
        clips = {clip["clip_id"]: clip for clip in self.catalogue.clips()}
        next_id = next(
            (
                clip_id
                for clip_id in session["ids"][session["index"] + 1 :]
                if clips[clip_id]["triage"] is None
            ),
            None,
        )
        if next_id is not None:
            self.switch_editing_clip(next_id, ensure_visible=True)
        else:
            self.statusBar().showMessage("No undefined clips ahead in this session.", 12000)

    def navigate(self, offset):
        if self.current_panel == "Browse":
            index = self.library.currentRow() + offset
            if 0 <= index < self.library.count():
                self.library.setCurrentRow(index)
            return
        session = self.catalogue.state("session")
        if not session:
            return
        index = max(0, min(len(session["ids"]) - 1, session["index"] + offset))
        self.switch_editing_clip(session["ids"][index], ensure_visible=True)

    def active_player(self):
        if self.current_panel == "Browse":
            return self.browse.player
        return self.export_player if self.current_panel == "Export" else self.player

    def remember_draft(self, text):
        self.command_submitted_error = False
        self.command_saved_timer.stop()
        self.command_error.clear()
        self.command_error.hide()
        if text:
            self.submit_resume = False
        if self.current_id:
            self.drafts[self.current_id] = text
            clip = self.catalogue.clip(self.current_id)
            self.render_field_reminder(clip, self.registry.game(clip["game"]))
        self.update_command_state()

    def editing_paused(self):
        return (
            self.current_panel == "Editing"
            and self.current_id is not None
            and not self.player.awaiting_frame
            and self.player.media.duration() > 0
            and self.player.media.mediaStatus() != QMediaPlayer.MediaStatus.InvalidMedia
            and self.player.media.playbackState() == QMediaPlayer.PlaybackState.PausedState
        )

    def command_focus_changed(self, old, new):
        if old is self.command and new is not self.command:
            self.submit_resume = False
        self.update_command_state()

    def command_playback_changed(self, state):
        self.submit_resume = False
        self.update_command_state()

    def update_command_state(self):
        focus = QApplication.focusWidget()
        state = "review"
        if self.current_panel == "Editing":
            if focus is self.command:
                state = "resume" if self.submit_resume and self.editing_paused() else "input"
            elif (
                self.editing_paused()
                and self.settings.get("paused_typing_enabled", True)
                and not isinstance(focus, (QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox))
                and not QApplication.activeModalWidget()
                and not QApplication.activePopupWidget()
            ):
                state = "paused"
        if self.command.property("commandState") != state:
            self.command.setProperty("commandState", state)
        validation, message = "empty", ""
        if self.current_id:
            clip = self.catalogue.clip(self.current_id)
            _, validation, message = preview_command(
                self.command.text(),
                clip["game"],
                self.registry,
                submitted=self.command_submitted_error,
            )
        if validation == "empty":
            if self.command_saved_timer.isActive():
                validation, message = "saved", "Saved"
            if state == "resume":
                message = "Saved · Space to resume"
            elif state == "paused" and not message:
                message = "Type to enter commands"
        self.command_feedback.setText(message)
        if self.command.property("validationState") != validation:
            self.command.setProperty("validationState", validation)
            self.command.style().unpolish(self.command)
            self.command.style().polish(self.command)
            self.command.update()

    def review_mode(self):
        self.submit_resume = False
        self.player.setFocus()
        self.update_command_state()

    def cancel_space(self):
        self.space_timer.stop()
        self.space_down = False
        if hasattr(self, "player"):
            self.active_player().fast(False)

    def choose_session_mode(self, mode):
        self.session_mode = mode
        self.session_count.setEnabled(mode == "first")
        for name, control in self.session_choices.items():
            control.setChecked(name == mode)

    def toggle_projects(self):
        self.pane_overrides[self.isMaximized()] = not self.right.isVisible()
        self.update_projects_visibility()

    def panes_resized(self, position, index):
        if self.right.isVisible() and self.splitter.sizes()[2] == 0:
            self.pane_overrides[self.isMaximized()] = False
            self.update_projects_visibility()

    def update_projects_visibility(self):
        allowed = self.current_panel not in {"Browse", "Export", "Config"}
        visible = allowed and self.pane_overrides.get(self.isMaximized(), self.isMaximized())
        self.right.setVisible(visible)
        self.projects_toggle.setEnabled(allowed)
        self.projects_toggle.setChecked(visible)
        if visible and self.splitter.sizes()[2] == 0:
            self.splitter.setSizes([420, max(400, self.width() - 770), 350])

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "right"):
            self.update_projects_visibility()

    def edit_tag(self):
        if self.current_panel == "Browse":
            return
        try:
            clip = self.selected_clip()
        except ValueError as error:
            self.error(error)
            return
        value, accepted = QInputDialog.getText(
            self,
            "Tag",
            "Optional tag",
            text=clip["tag"] or "",
        )
        if accepted:
            self.catalogue.patch(clip["clip_id"], {"tag": value or None})
            if self.current_panel == "Editing":
                self.render_clip()
            else:
                self.refresh_library()

    def show_shortcuts(self):
        QMessageBox.information(
            self,
            "Review shortcuts",
            'REVIEW MODE\nSpace: Play / Pause · Hold Space: 3×\n← / →: Seek ±5 s · Shift+←/→: ±1 s\n↑ / ↓: Previous / next session clip\nI / O: Set range · Backspace: Reject\n/ or Enter: Metadata · ?: Help\nShift+Enter: Verdict + Next Undefined (command bar must be empty)\nCtrl+Enter: Add to active project + Next (requires an active project; preserves triage)\n\nINPUT MODE\nEnter: Submit command and stay in input\nShift+Enter: Verdict + Next Undefined (command bar must be empty)\nCtrl+Enter: Unavailable\nEscape: Return to review, preserving your draft\n\nType while paused to enter input (Settings → General).\nBlue: valid command. Amber underline: incomplete. Red underline: invalid.\nBrief green underline: saved. The hint shows when Space resumes playback.\nExisting review shortcuts take priority over paused typing.\nUse tag:LOW_FPS or tag:"audio issue"; tag:"" clears.\nSubmit metadata with Enter, then Shift+Enter for verdict.\nKeep requires a configured game and its required fields.\nExplicit Discard advances without those requirements.\nRatings never change verdicts. Drafts last for this run only.',
        )

    def eventFilter(self, watched: QObject, event):
        if event.type() == QEvent.Type.ApplicationActivate:
            self.request_auto_scan()
        if (
            event.type() in {QEvent.Type.Resize, QEvent.Type.Move}
            and watched in (self.center, self.command_area)
            and self.transition_pending
        ):
            self.position_transition_covers()
        if event.type() == QEvent.Type.ShortcutOverride:
            focus = QApplication.focusWidget()
            if (
                isinstance(focus, (QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox))
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier
                and event.key() in {Qt.Key.Key_Z, Qt.Key.Key_Y}
            ):
                event.accept()
                return True
        if event.type() == QEvent.Type.MouseButtonPress:
            self.submit_resume = False
            self.update_command_state()
            self.cancel_space()
        if event.type() in {QEvent.Type.ApplicationDeactivate, QEvent.Type.FocusOut}:
            if event.type() == QEvent.Type.ApplicationDeactivate:
                self.submit_resume = False
                self.consume_resume_space = False
                self.update_command_state()
            self.cancel_space()
        if event.type() == QEvent.Type.KeyRelease and event.key() == Qt.Key.Key_Space:
            if self.consume_resume_space:
                if not event.isAutoRepeat():
                    self.consume_resume_space = False
                return True
            if not event.isAutoRepeat() and self.space_down:
                held = not self.space_timer.isActive()
                self.cancel_space()
                if not held:
                    self.active_player().toggle()
                return True
        if (
            event.type() != QEvent.Type.KeyPress
            or QApplication.activeModalWidget()
            or QApplication.activePopupWidget()
        ):
            return super().eventFilter(watched, event)
        if self.current_panel not in {"Browse", "Editing", "Export"}:
            return super().eventFilter(watched, event)
        focus = (
            watched if isinstance(watched, (QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox))
            else QApplication.focusWidget()
        )
        text_editing = isinstance(focus, (QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox))
        key = event.key()
        modifiers = event.modifiers()
        if key == Qt.Key.Key_Space and self.consume_resume_space:
            return True
        if key == Qt.Key.Key_Escape and self.current_panel == "Editing":
            self.review_mode()
            return True
        if focus is self.command:
            if self.submit_resume and key not in {
                Qt.Key.Key_Shift,
                Qt.Key.Key_Control,
                Qt.Key.Key_Alt,
                Qt.Key.Key_Meta,
            }:
                resume = (
                    key == Qt.Key.Key_Space
                    and modifiers == Qt.KeyboardModifier.NoModifier
                    and self.editing_paused()
                )
                self.submit_resume = False
                self.update_command_state()
                if resume:
                    self.consume_resume_space = True
                    self.review_mode()
                    self.player.media.setPlaybackRate(1)
                    self.player.media.play()
                    return True
            if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
                if modifiers == Qt.KeyboardModifier.NoModifier:
                    self.submit()
                elif modifiers == Qt.KeyboardModifier.ShiftModifier:
                    if not event.isAutoRepeat():
                        self.advance_review()
                return True
        if text_editing:
            if key == Qt.Key.Key_Z and modifiers == (
                Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
            ):
                editor = focus.lineEdit() if isinstance(focus, QSpinBox) else focus
                editor.redo()
                return True
            return super().eventFilter(watched, event)
        if self.current_panel == "Editing" and key in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            if modifiers == Qt.KeyboardModifier.ShiftModifier and not event.isAutoRepeat():
                self.advance_review()
            elif modifiers == Qt.KeyboardModifier.ControlModifier and not event.isAutoRepeat():
                self.add_to_project_next()
            elif modifiers == Qt.KeyboardModifier.NoModifier:
                self.command.setFocus()
            return True
        if (
            self.current_panel in {"Browse", "Editing"}
            and key in {Qt.Key.Key_Up, Qt.Key.Key_Down}
            and modifiers == Qt.KeyboardModifier.NoModifier
        ):
            self.navigate(-1 if key == Qt.Key.Key_Up else 1)
            return True
        if key in {Qt.Key.Key_Left, Qt.Key.Key_Right} and modifiers in {
            Qt.KeyboardModifier.NoModifier,
            Qt.KeyboardModifier.ShiftModifier,
        }:
            delta = 1000 if modifiers else 5000
            player = self.active_player()
            player.seek_to(
                max(
                    0,
                    min(
                        player.media.duration(),
                        player.media.position() + (delta if key == Qt.Key.Key_Right else -delta),
                    ),
                )
            )
            return True
        if self.current_panel == "Editing" and key == Qt.Key.Key_Question:
            self.show_shortcuts()
            return True
        if not modifiers:
            if event.key() == Qt.Key.Key_Space:
                if not event.isAutoRepeat() and not self.space_down:
                    self.space_down = True
                    self.space_timer.start()
                return True
            if self.current_panel == "Editing":
                if key == Qt.Key.Key_Slash:
                    self.command.setFocus()
                    return True
                if key == Qt.Key.Key_Backspace:
                    self.edit({"triage": "discard"})
                    return True
            if self.current_panel in {"Browse", "Editing"} and event.key() in {Qt.Key.Key_I, Qt.Key.Key_O}:
                (self.mark_in if event.key() == Qt.Key.Key_I else self.mark_out)()
                return True
        if (
            self.editing_paused()
            and self.settings.get("paused_typing_enabled", True)
            and modifiers in {Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ShiftModifier}
            and event.text()
            and event.text().isprintable()
        ):
            self.command.setFocus()
            self.command.insert(event.text())
            return True
        return super().eventFilter(watched, event)

    def has_pending_range(self):
        return self.pending_in is not None or self.pending_out is not None

    def range_endpoints(self):
        clip = self.catalogue.clip(self.current_id)
        return (
            self.pending_in if self.pending_in is not None else clip["in_ms"],
            self.pending_out if self.pending_out is not None else clip["out_ms"],
        )

    def ensure_range_complete(self):
        if not self.has_pending_range():
            return True
        start, end = self.range_endpoints()
        if start is None:
            reason = "Set In to complete the range"
        elif end is None:
            reason = "Set Out to complete the range"
        else:
            reason = "Set In earlier than Out to complete a valid range"
        self.update_range_warning()
        self.range_warning.setToolTip(f"{reason}, or use Clear range, before leaving this clip.")
        return False

    def update_range_warning(self):
        start, end = self.range_endpoints() if self.current_id else (None, None)
        missing = start is None or end is None
        visible = self.current_panel == "Editing" and bool(self.current_id)
        visible = visible and (missing or not 0 <= start < end)
        self.range_warning.setText("I/O not set" if missing else "I/O invalid")
        self.range_warning.setToolTip(
            "Set both In and Out to complete the range."
            if missing else "In must be earlier than Out."
        )
        self.range_warning.setVisible(visible)
        self.range_warning_icon.setVisible(visible)

    def reset_pending_range(self):
        self.pending_in = self.pending_out = None
        self.player.seek.pending_in = self.player.seek.pending_out = None
        self.player.seek.update()

    def mark_in(self):
        self.mark_range_point("in")

    def mark_out(self):
        self.mark_range_point("out")

    def mark_range_point(self, endpoint):
        if self.current_panel == "Browse":
            self.browse.mark(endpoint)
            return
        if self.current_panel != "Editing" or not self.current_id:
            return
        position = self.player.media.position()
        if endpoint == "in":
            self.pending_in = self.player.seek.pending_in = position
        else:
            self.pending_out = self.player.seek.pending_out = position
        self.player.seek.update()
        start, end = self.range_endpoints()
        if start is None or end is None or not 0 <= start < end:
            self.ensure_range_complete()
            return
        self.save_range(start, end)

    def save_range(self, start, end):
        if self.current_panel == "Browse":
            return
        try:
            self.catalogue.patch(self.current_id, {"in_ms": start, "out_ms": end}, editing=True)
            self.reset_pending_range()
            self.command_error.clear()
            self.command_error.hide()
            self.statusBar().clearMessage()
            self.render_clip()
        except (ValueError, OSError) as error:
            self.error(error)

    def clear_range(self):
        if self.current_panel == "Browse":
            self.browse.clear_range()
            return
        if self.current_panel == "Editing" and self.current_id:
            self.save_range(None, None)

    def new_project(self):
        if self.current_panel == "Browse":
            return
        name, accepted = QInputDialog.getText(self, "New project", "Project name")
        if accepted:
            try:
                self.catalogue.save_project(name)
                self.refresh_references()
            except ValueError as error:
                self.error(error)

    def rename_project(self):
        if self.current_panel == "Browse":
            return
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
        if self.current_panel == "Browse":
            return
        project_id = self.selected_id(self.projects)
        if project_id:
            self.catalogue.set_state("active_project", project_id)
            self.refresh_references()

    def deactivate(self):
        if self.current_panel == "Browse":
            return
        self.catalogue.set_state("active_project", None)
        self.refresh_references()

    def delete_project(self):
        if self.current_panel == "Browse":
            return
        project_id = self.selected_id(self.projects)
        if project_id and self.confirm(
            "Delete this project and its memberships? Clips and source files remain."
        ):
            self.catalogue.delete_project(project_id)
            self.refresh_references()
            self.refresh_library()

    def membership(self, include):
        if self.current_panel == "Browse":
            return
        project_id = self.selected_id(self.projects)
        if not project_id:
            self.error("Select a project first")
            return
        ids = [item.data(Qt.ItemDataRole.UserRole) for item in self.library.selectedItems()]
        for clip_id in ids:
            self.catalogue.patch(clip_id, {}, membership=(project_id, include))
        self.update_history_controls()
        if self.current_panel == "Editing":
            self.render_clip()

    def create_session(self, mode):
        if self.current_panel == "Browse":
            return
        if not self.ensure_range_complete():
            return
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
        if self.current_panel == "Browse":
            return
        if not self.ensure_range_complete():
            return
        if self.catalogue.state("session") and self.confirm(
            "End this session? Clip metadata stays unchanged."
        ):
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
        if self.current_panel == "Browse":
            return
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
        if self.current_panel == "Browse":
            return
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
                        "tag": None,
                        "triage": None,
                        "rating": None,
                        "in_ms": None,
                        "out_ms": None,
                    },
                    replace_metadata=True,
                )
                self.reset_pending_range()
                self.refresh_library()
                if self.current_panel == "Editing":
                    self.render_clip()
        except ValueError as error:
            self.error(error)

    def update_history_controls(self):
        allowed = self.current_panel != "Browse"
        self.undo_button.setEnabled(allowed and bool(self.catalogue.undo_stack))
        self.redo_button.setEnabled(allowed and bool(self.catalogue.redo_stack))
        for action in getattr(self, "browse_write_actions", []):
            action.setEnabled(allowed)

    def undo(self, redo=False):
        if self.current_panel == "Browse":
            return
        self.catalogue.undo(redo)
        self.refresh_references()
        self.refresh_library()
        if self.current_panel == "Editing":
            self.render_clip()

    def background(self, function, done, label="Working…", *, quiet=False):
        if self.worker is not None:
            self.error("Wait for the current operation to finish")
            return
        self.worker = Worker(function)
        results = []
        if quiet:
            self.worker.succeeded.connect(results.append)
            self.worker.failed.connect(
                lambda message: self.statusBar().showMessage(f"Automatic scan: {message}", 12000)
            )

            def finished_quietly():
                self.worker.deleteLater()
                self.worker = None
                if results:
                    try:
                        done(results[0])
                    except Exception as error:
                        logging.exception("Automatic scan refresh failed")
                        self.statusBar().showMessage(f"Automatic scan: {error}", 12000)

            self.worker.finished.connect(finished_quietly)
            self.worker.start()
            return
        progress = QProgressDialog(label, "Cancel", 0, 0, self)
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)

        def cancel():
            self.worker.cancelled.set()
            progress.setLabelText("Cancelling… Please wait.")
            progress.setCancelButton(None)
            progress.show()

        progress.canceled.connect(cancel)
        self.worker.progress.connect(
            lambda text: progress.setLabelText(text) if not self.worker.cancelled.is_set() else None
        )

        def succeeded(result):
            results.append(result)

        def failed(message):
            self.error(message)

        def finished():
            progress.canceled.disconnect(cancel)
            progress.close()
            progress.deleteLater()
            self.worker.deleteLater()
            self.worker = None
            if results:
                try:
                    continuation = done(results[0])
                    if callable(continuation):
                        continuation()
                except Exception as error:
                    self.error(error)

        self.worker.succeeded.connect(succeeded)
        self.worker.failed.connect(failed)
        self.worker.finished.connect(finished)
        progress.show()
        progress.repaint()
        QTimer.singleShot(0, self.worker.start)

    def add_folder(self):
        if self.current_panel == "Browse":
            return
        if self.worker is not None:
            self.error("Wait for the current operation to finish")
            return
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

                def ingest(cancelled, progress):
                    if cancelled():
                        raise InterruptedError("Import cancelled")
                    folder_id = self.catalogue.add_folder(directory, forced_game)
                    try:
                        self.catalogue.ingest(folder_id, found, cancelled)
                    except Exception:
                        self.catalogue.remove_folder(folder_id, purge=False)
                        raise
                    return found

                def applied(found):
                    self.remember_media(found)
                    self.refresh_references()
                    self.refresh_library()

                return lambda: self.background(ingest, applied, "Updating catalogue…")

        def inspect_folder(cancelled, progress):
            coordinator = ScanCoordinator(self.catalogue, self.registry, cancelled, progress)
            found = coordinator.folder({"path": directory, "forced_game": forced_game})
            if not coordinator.executable:
                for item in found:
                    if item.get("duration") is None:
                        item["error"] = "ffprobe unavailable"
            logging.info("Folder preview metrics: %s", coordinator.metrics)
            return found

        self.background(
            inspect_folder,
            done,
            label="Inspecting capture folder…",
        )

    def remember_media(self, found):
        from .catalogue import normalized

        for item in found:
            self.media_info[normalized(item["path"])] = item

    def reinspect(self):
        self.rescan(force=True)

    def request_auto_scan(self):
        if not self.scan_retry_timer.isActive():
            self.scan_retry_timer.start()

    def auto_scan(self):
        if self.worker is not None or QApplication.activeModalWidget() is not None:
            self.scan_retry_timer.start()
            return
        self.rescan(quiet=True)

    def rescan(self, force=False, *, quiet=False):
        self.scan_retry_timer.stop()
        if not any(folder["enabled"] for folder in self.catalogue.folders()):
            return

        def scan(cancelled, progress):
            folders = [folder for folder in self.catalogue.folders() if folder["enabled"]]
            return ScanCoordinator(self.catalogue, self.registry, cancelled, progress, force).run(
                folders
            )

        def done(result):
            found, errors, metrics = result
            started = time.perf_counter()
            self.catalogue.hidden_deleted_ids()
            self.remember_media(found)
            self.refresh_references()
            self.refresh_library()
            metrics["ui_refresh"] = time.perf_counter() - started
            logging.info("Scan including UI refresh: %s", metrics)
            self.statusBar().showMessage(
                f"Scan: {metrics['hits']} cached, {metrics['probes']} inspected, "
                f"{metrics['warnings']} warnings. " + " · ".join(errors),
                12000,
            )

        self.background(scan, done, label="Discovering files…", quiet=quiet)

    def show_folder_context_menu(self, position):
        item = self.folders.itemAt(position)
        if item is None or item.data(Qt.ItemDataRole.UserRole) == "__unlinked__":
            return
        self.folders.setCurrentItem(item)
        self.update_folder_actions()
        self.folder_context_menu.popup(self.folders.viewport().mapToGlobal(position))

    def update_folder_actions(self):
        folder_id = self.selected_id(self.folders)
        folder = next(
            (folder for folder in self.catalogue.folders() if folder["folder_id"] == folder_id),
            None,
        )
        for action in (
            self.folder_toggle_action,
            self.folder_migrate_action,
            self.folder_remove_action,
        ):
            action.setEnabled(folder is not None and self.worker is None)
        self.folder_toggle_action.setText(
            "Pause scanning" if not folder or folder["enabled"] else "Resume scanning"
        )
        if folder_id == "__unlinked__":
            self.folder_remove_action.setEnabled(self.worker is None)
        self.folder_remove_action.setText(
            "Remove saved entries…" if folder_id == "__unlinked__" else "Remove folder…"
        )

    def toggle_folder(self):
        if self.current_panel == "Browse":
            return
        if self.worker is not None:
            self.error("Wait for the current operation to finish")
            return
        folder_id = self.selected_id(self.folders)
        for folder in self.catalogue.folders():
            if folder["folder_id"] == folder_id:
                self.catalogue.enable_folder(folder_id, not folder["enabled"])
        self.refresh_references()
        self.refresh_library()

    def migrate(self):
        if self.current_panel == "Browse":
            return
        if self.worker is not None:
            self.error("Wait for the current operation to finish")
            return
        folder_id = self.selected_id(self.folders)
        if not folder_id:
            return
        destination = QFileDialog.getExistingDirectory(self, "New location of this capture folder")
        if destination:
            try:
                new, rows, updates = self.catalogue.migration_plan(folder_id, destination)
                found = sum(Path(path).is_file() for path, clip_id in updates)
                if not self.confirm(
                    f"Relink {len(rows)} catalogue clips to:\n{new}\n\n"
                    f"{found} files found; {len(rows) - found} will be unavailable.\n"
                    "Keep clip metadata, projects and session references. No files will be moved."
                ):
                    return
                self.catalogue.migrate(folder_id, destination)
                self.media_info = self.catalogue.media_cache()
                self.refresh_references()
                self.refresh_library()
            except (ValueError, OSError) as error:
                self.error(error)

    def confirm_folder_removal(self, folder, clips):
        ids = {clip["clip_id"] for clip in clips}
        session = self.catalogue.state("session")
        in_session = len(ids.intersection(session["ids"])) if session else 0
        in_projects = len(
            ids.intersection(
                row["clip_id"]
                for row in self.catalogue.rows("SELECT DISTINCT clip_id FROM members")
            )
        )
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Remove capture folder" if folder else "Remove unlinked entries")
        dialog.setText(folder["path"] if folder else "Unlinked catalogue clips")
        dialog.setInformativeText(
            f"{len(clips)} saved clips · {in_session} in the current session · {in_projects} in projects.\n\n"
            "Remove entries from the catalogue, including their metadata and project/session references? "
            "A database backup will be saved first. Original files will stay untouched."
        )
        dialog.setDetailedText("\n".join(clip["source_path"] for clip in clips))
        remove = dialog.addButton("Remove from catalogue", QMessageBox.ButtonRole.DestructiveRole)
        role(remove, "danger")
        cancel = dialog.addButton(QMessageBox.StandardButton.Cancel)
        dialog.setDefaultButton(cancel)
        dialog.exec()
        clicked = dialog.clickedButton()
        dialog.deleteLater()
        return clicked is remove

    def remove_folder(self):
        if self.current_panel == "Browse":
            return
        if self.worker is not None:
            self.error("Wait for the current operation to finish")
            return
        folder_id = self.selected_id(self.folders)
        folder = next(
            (row for row in self.catalogue.folders() if row["folder_id"] == folder_id), None
        )
        if folder_id == "__unlinked__":
            clips = self.catalogue.unlinked_clips()
        elif folder:
            ids = {
                row["clip_id"]
                for row in self.catalogue.rows(
                    "SELECT clip_id FROM sources WHERE folder_id=?", (folder_id,)
                )
            }
            clips = [clip for clip in self.catalogue.clips() if clip["clip_id"] in ids]
        else:
            return
        if not self.confirm_folder_removal(folder, clips):
            return
        try:
            backup = self.catalogue.backup()
            if folder:
                self.catalogue.remove_folder(folder_id)
            else:
                self.catalogue.remove_unlinked([clip["clip_id"] for clip in clips])
            self.media_info = self.catalogue.media_cache()
            for clip in clips:
                self.drafts.pop(clip["clip_id"], None)
                self.history.pop(clip["clip_id"], None)
            if self.current_id in {clip["clip_id"] for clip in clips}:
                self.current_id = None
                self.player.load(None)
            self.refresh_references()
            self.refresh_library()
            if backup:
                self.statusBar().showMessage(f"Catalogue entries removed. Backup: {backup}", 20000)
        except (ValueError, OSError) as error:
            self.error(error)

    def export_clips(self):
        ids = self.catalogue.member_ids(self.export_project.currentData())
        return [clip for clip in self.catalogue.clips() if clip["clip_id"] in ids]

    def export_selection(self):
        if self.refreshing:
            return
        clips = self.export_clips()
        errors = validate(clips, self.registry)
        role(self.export_errors, "error" if errors else "success")
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
            current = self.selected_id(self.library)
            clip = next((clip for clip in clips if clip["clip_id"] == current), None)
            if clip is None and clips:
                clip = clips[0]
                self.library.blockSignals(True)
                self.library.setCurrentRow(0)
                self.library.blockSignals(False)
            self.export_player.load(clip)

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
        self.format_layout.addWidget(prefix, 0, 0)
        for index, field in enumerate(game.display_order, start=1):
            check = QCheckBox(field)
            check.setChecked(field in options["fields"])

            def toggle(checked, field=field, options=options):
                if checked and field not in options["fields"]:
                    options["fields"].append(field)
                elif not checked and field in options["fields"]:
                    options["fields"].remove(field)

            check.toggled.connect(toggle)
            self.format_layout.addWidget(check, index // 3, index % 3)

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
        if self.worker is not None:
            self.error("Wait for the current operation to finish")
            return
        destination = self.export_destination.text().strip()
        if not destination:
            self.error("Choose an export folder")
            return
        project_id = self.export_project.currentData()
        if not project_id:
            self.error("Choose a project")
            return
        formats = self.formats.copy()
        group = self.group_rating.isChecked()
        lowercase = self.settings.get("lowercase_generated_titles", True)

        def export(cancelled, progress):
            if cancelled():
                raise InterruptedError("Export cancelled")
            ids = self.catalogue.member_ids(project_id)
            clips = [clip for clip in self.catalogue.clips() if clip["clip_id"] in ids]
            return export_project(
                clips,
                self.registry,
                destination,
                self.catalogue.folders(),
                formats,
                group,
                cancelled,
                progress,
                lowercase=lowercase,
            )

        def done(result):
            self.settings["export_folder"] = destination
            self.save_settings()
            QMessageBox.information(
                self,
                "Project Export",
                f"{len(result.completed)} clips copied.\n"
                + (result.error or "Complete.")
                + "\n"
                + "\n".join(result.completed),
            )

        self.background(export, done, label="Preparing project export…")

    def share(self):
        if self.current_panel == "Browse":
            self.browse.share()
            return
        try:
            clip = self.selected_clip()
        except ValueError as error:
            self.error(error)
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Share clip")
        layout = QFormLayout(dialog)
        mode = QComboBox()
        valid_range = clip["in_ms"] is not None and clip["out_ms"] is not None
        if valid_range:
            mode.addItem(
                f"Selected range · {clip['in_ms'] / 1000:.3f}–{clip['out_ms'] / 1000:.3f}s · {(clip['out_ms'] - clip['in_ms']) / 1000:.3f}s",
                True,
            )
        mode.addItem("Whole clip", False)
        layout.addRow("Share", mode)
        layout.addRow(QLabel("H.264 MP4 · All audio tracks mixed to stereo AAC"))
        if self.current_panel == "Editing" and self.has_pending_range():
            layout.addRow(
                QLabel("Range changes are pending; selected range uses the saved markers.")
            )
        destination = QLineEdit(self.settings.get("share_folder", ""))
        layout.addRow("Output folder", destination)

        def browse():
            folder = QFileDialog.getExistingDirectory(dialog, "Share folder", destination.text())
            if folder:
                destination.setText(folder)

        layout.addRow(button("Browse", browse))
        custom = QLineEdit()
        custom.setPlaceholderText("Leave empty to generate; .mp4 is appended")
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
        selected_range = mode.currentData()
        lowercase = self.settings.get("lowercase_generated_titles", True)
        self.background(
            lambda cancelled, progress: share_clip(
                clip,
                self.registry,
                folder,
                folders,
                custom_name,
                fields,
                include_prefix,
                cancelled,
                selected_range=selected_range,
                lowercase=lowercase,
                progress=progress,
            ),
            lambda target: QMessageBox.information(
                self, "Shared", f"Shared H.264 MP4 to:\n{target}"
            ),
        )

    def open_configs(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.root / "configs/games")))

    def reload_configs(self):
        self.registry = Registry(self.root / "configs/games")
        self.refresh_references()
        self.refresh_library()
        self.formats.clear()
        if self.current_panel == "Editing" and self.current_id:
            self.render_clip()

    def reset_layout(self):
        self.pane_overrides.clear()
        self.showNormal()
        self.resize(1400, 918)
        self.splitter.setSizes([420, 630, 350])
        self.update_projects_visibility()

    def closeEvent(self, event):
        if self.worker:
            self.worker.cancelled.set()
            self.error("Cancelling current operation; close again after it finishes")
            event.ignore()
            return
        self.player.media.shutdown()
        self.export_player.media.shutdown()
        self.browse.player.media.shutdown()
        self.scan_timer.stop()
        self.scan_retry_timer.stop()
        QApplication.instance().removeEventFilter(self)
        event.accept()


def style_application(application):
    apply_theme(application)


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
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("DFSorter.Desktop")
    application = QApplication(sys.argv)
    application.setWindowIcon(QIcon(str(ROOT / "resources/mascot/dfsorter.ico")))
    style_application(application)
    window = Window()
    window.show()
    return application.exec()


if __name__ == "__main__":
    sys.exit(main())
