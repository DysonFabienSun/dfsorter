import html
import logging
import os
import stat
import sys
import threading
import time
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from functools import wraps
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")

import yaml
from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QObject,
    QPoint,
    QSize,
    Qt,
    QThread,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QDesktopServices,
    QIcon,
    QPainter,
    QPixmap,
    QRegion,
    QTextDocument,
)
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
    QLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .activities import Activities
from .app_paths import ROOT, prepare_game_configs, prepare_tip_configs
from .browse import BrowsePage
from .catalogue import Catalogue
from .command_input import CommandInput
from .config import Registry, has_review_metadata, source_fallback, title
from .config_editor import ConfigEditor
from .deletion import delete_reviewed, preview
from .deletion_dialog import DeletionDialog
from .folder_preview_dialog import FolderPreviewDialog
from .history import EditHistory
from .output import prepare_export_manifest, run_export_manifest, safe_stem, share_clip, validate
from .overview import (
    PERIOD_DAYS,
    capture_datetime,
    compact_capture_time,
    library_overview,
    relative_capture_time,
)
from .parsing import (
    parse_command_details,
    preview_command_details,
    query_clips,
)
from .playback import Player, playback_start_settings, playback_volume
from .release_update import installed_release
from .scanning import ScanCoordinator
from .settings_dialog import SettingsDialog
from .theme import (
    COLORS,
    SIZES,
    apply_theme,
    font,
    resolved_scheme,
    role,
    symbol_text,
    title_styles,
)
from .thumbnails import ThumbnailCache
from .tips import TipLibrary, TipWidget
from .unavailable_dialog import UnavailableClipsDialog
from .update_ui import UpdateController
from .widgets import (
    CLIP_ROLE,
    FOLDER_ROLE,
    CaptureFolderDelegate,
    ClipDelegate,
    ClipScrollFade,
    EdgeChevron,
    Rating,
    SessionProgressBar,
    VerdictBar,
    heading,
    icon,
    refresh_icons,
    set_icon,
    success_check_icon,
    tag_prefix,
    tool,
)


def editing_action(function):
    """Record one user action, including nested edits and navigation after a verdict."""
    @wraps(function)
    def record(self, *args, **kwargs):
        enabled = self.current_panel == "Editing" and self.current_id is not None
        outer = enabled and self._editing_action_depth == 0
        if outer:
            clip_id, atomic = self.current_id, self.atomic_edit
            history = self.editing_history()
            before = self.editing_state(clip_id, atomic)
            command = self.command.text() if function.__name__ == "submit" else None
        self._editing_action_depth += 1
        try:
            return function(self, *args, **kwargs)
        finally:
            self._editing_action_depth -= 1
            if outer:
                after = self.editing_state(clip_id, atomic)
                previous = history.pending()
                if previous and previous.after != before:
                    history.undo_stack.clear()
                    history.redo_stack.clear()
                history.record(before, after, command=command)
                self.update_history_controls()
    return record


@dataclass
class AtomicEditState:
    clip_id: str
    origin: str
    baseline: tuple
    draft: tuple
    scroll_position: tuple[int, int]
    history: list[str | tuple[str, list[tuple[str, object]]]] = dataclass_field(
        default_factory=list
    )
    edits: EditHistory = dataclass_field(default_factory=EditHistory)


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


class FieldReminder(QLabel):
    def sizeHint(self):
        result = super().sizeHint()
        if self.text():
            document = QTextDocument()
            document.setDefaultFont(self.font())
            document.setHtml(self.text())
            document.setTextWidth(-1)
            result.setWidth(round(document.idealWidth() + 1))
        return result


def storage_gb(size):
    return f"{size / (1024**3):.2f} GB"


def folder_storage(paths, cancelled):
    sizes = {}
    for path in paths:
        total = 0
        failed = False

        def walk_error(error):
            nonlocal failed
            failed = True

        try:
            if not Path(path).is_dir():
                sizes[path] = None
                continue
            for directory, subdirectories, filenames in os.walk(
                path, followlinks=False, onerror=walk_error
            ):
                if cancelled():
                    return sizes
                subdirectories[:] = [
                    name for name in subdirectories
                    if not (Path(directory) / name).is_symlink()
                ]
                for filename in filenames:
                    if cancelled():
                        return sizes
                    try:
                        info = (Path(directory) / filename).stat(follow_symlinks=False)
                        if stat.S_ISREG(info.st_mode):
                            total += info.st_size
                    except OSError:
                        failed = True
                        continue
            sizes[path] = None if failed else total
        except OSError:
            sizes[path] = None
    return sizes


class CheckMenu(QMenu):
    def mouseReleaseEvent(self, event):
        action = self.activeAction()
        if action is not None and action.isCheckable() and action.isEnabled():
            action.trigger()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class FilterMenuButton(QPushButton):
    selectionChanged = Signal()

    def __init__(self, label, all_label, options=(), selected=None, empty_text=None):
        super().__init__(label)
        self.label = label
        self.all_label = all_label
        self.empty_text = empty_text
        self._all_selected = selected is None
        self._selected = set(selected or ())
        self._options = []
        self._menu = CheckMenu(self)
        self.setMenu(self._menu)
        self.setAccessibleName(f"{label} filter")
        self.set_options(options)

    def set_options(self, options):
        self._options = list(options)
        values = {value for _label, value in self._options}
        if not values:
            self._all_selected = True
            self._selected.clear()
        elif not self._all_selected:
            self._selected.intersection_update(values)
        self._rebuild_menu()

    def selected_values(self):
        if self._all_selected:
            return {value for _label, value in self._options}
        return set(self._selected)

    def set_selected_values(self, selected):
        values = {value for _label, value in self._options}
        selected = set(selected).intersection(values)
        self._all_selected = selected == values
        self._selected = set() if self._all_selected else selected
        self._rebuild_menu()
        self.selectionChanged.emit()

    def all_selected(self):
        return self._all_selected

    def _rebuild_menu(self):
        selected = self.selected_values()
        if self.label == "Clips":
            choices = (
                "all" if self._all_selected
                else ", ".join(label.lower() for label, value in self._options if value in selected)
                or "none"
            )
            self.setText(f"Clips: {choices}")
        else:
            self.setText(f"{self.label} ({len(selected)})")
        self.setMinimumWidth(self.sizeHint().width())
        self._menu.clear()
        all_action = self._menu.addAction(self.all_label)
        all_action.setCheckable(True)
        all_action.setChecked(self._all_selected)
        all_action.triggered.connect(self._toggle_all)
        if self._options:
            self._menu.addSeparator()
            for label, value in self._options:
                action = self._menu.addAction(label)
                action.setCheckable(True)
                action.setChecked(self._all_selected or value in self._selected)
                action.triggered.connect(
                    lambda checked=False, value=value: self._toggle_value(value, checked)
                )
        elif self.empty_text:
            self._menu.addSeparator()
            empty = self._menu.addAction(self.empty_text)
            empty.setEnabled(False)

    def _toggle_all(self, checked):
        self._all_selected = checked
        self._selected.clear()
        self._rebuild_menu()
        self.selectionChanged.emit()

    def _toggle_value(self, value, checked):
        selected = self.selected_values()
        if checked:
            selected.add(value)
        else:
            selected.discard(value)
        values = {option_value for _label, option_value in self._options}
        self._all_selected = selected == values
        self._selected = set() if self._all_selected else selected
        self._rebuild_menu()
        self.selectionChanged.emit()


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


class CurrentPageStack(QStackedWidget):
    def minimumSizeHint(self):
        page = self.currentWidget()
        return page.minimumSizeHint() if page else super().minimumSizeHint()


class BlockedCloseBell:
    def __init__(self, window):
        self.window = window
        if sys.platform != "win32":
            return
        import ctypes

        self.handle = int(window.winId())
        self.subclass_id = id(self)
        self.comctl32 = ctypes.windll.comctl32
        self.comctl32.SetWindowSubclass.argtypes = (
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t
        )
        self.comctl32.SetWindowSubclass.restype = ctypes.c_int
        self.comctl32.DefSubclassProc.argtypes = (
            ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t
        )
        self.comctl32.DefSubclassProc.restype = ctypes.c_ssize_t
        self.comctl32.RemoveWindowSubclass.argtypes = (
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t
        )
        self.user32 = ctypes.windll.user32
        self.user32.IsWindowEnabled.argtypes = (ctypes.c_void_p,)
        self.user32.IsWindowEnabled.restype = ctypes.c_int
        self.callback = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t,
            ctypes.c_ssize_t, ctypes.c_size_t, ctypes.c_size_t,
        )(self.window_proc)
        if not self.comctl32.SetWindowSubclass(self.handle, self.callback, self.subclass_id, 0):
            raise ctypes.WinError()

    def window_proc(self, handle, message, wparam, lparam, subclass_id, reference):
        close_requested = message == 0x0010 or (
            message == 0x0112 and wparam & 0xFFF0 == 0xF060
        )
        if close_requested and getattr(self.window, "settings_dialog", None) is None:
            modal = QApplication.activeModalWidget()
            if not self.user32.IsWindowEnabled(handle) or (
                modal is not None
                and (modal is self.window or self.window.isAncestorOf(modal))
            ):
                self.user32.MessageBeep(0xFFFFFFFF)
                if modal is not None:
                    modal.raise_()
                    modal.activateWindow()
                return 0
        return self.comctl32.DefSubclassProc(handle, message, wparam, lparam)

    def remove(self):
        if sys.platform == "win32":
            self.comctl32.RemoveWindowSubclass(self.handle, self.callback, self.subclass_id)


class Window(QMainWindow):
    def __init__(self, root=ROOT):
        super().__init__()
        self.close_requested = False
        self.root = Path(root)
        self.registry = Registry(self.root / "configs/games")
        self.tips = TipLibrary(self.root / "configs/tips")
        self.registry.errors.extend(self.tips.errors)
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
        if "playback_volume" in self.settings:
            stored_volume = self.settings["playback_volume"]
            normalized_volume = playback_volume(self.settings)
            if type(stored_volume) is not int or stored_volume != normalized_volume:
                self.settings["playback_volume"] = normalized_volume
                self.save_settings()
        if self.settings.get("theme") not in {"system", "light", "dark"}:
            self.settings["theme"] = "light"
        apply_theme(QApplication.instance(), self.settings["theme"])
        self.opening_clip_ids = {clip["clip_id"] for clip in self.catalogue.clips()}
        self.current_id = None
        self.current_panel = "Home"
        self.library_newest = False
        self.browse_newest = True
        self.browse_id = None
        self.browse_selected_id = None
        self.library_page_states = {}
        self.library_page_switch = False
        self.atomic_edit = None
        self.history = defaultdict(list)
        self.editing_histories = defaultdict(EditHistory)
        self._editing_action_depth = 0
        self.restored_command = None
        self.drafts = {}
        self.pane_overrides = {}
        self.space_down = False
        self.submit_resume = False
        self.consume_resume_space = False
        self.reject_enter_armed = False
        self.space_timer = QTimer(self)
        self.space_timer.setSingleShot(True)
        self.space_timer.setInterval(200)
        self.space_timer.timeout.connect(lambda: self.active_player().fast(True))
        self.media_info = self.catalogue.media_cache()
        self.source_stats = {}
        self.reference_stamp = None
        self._panel_initialized = False
        self._navigating = False
        self.pending_page = None
        self.pending_page_generation = 0
        self.library_items_cache = {}
        self.active_library_signature = None
        self.folder_sizes = {}
        self.folder_size_paths = ()
        self.folder_size_updated_at = 0.0
        self.folder_size_worker = None
        self.folder_size_pending = False
        self.clip_folder_names = self.catalogue.clip_folder_names()
        self.thumbnails = ThumbnailCache(self.root, self)
        self.thumbnails.ready.connect(self.thumbnail_ready)
        self.thumbnail_timer = QTimer(self)
        self.thumbnail_timer.setSingleShot(True)
        self.thumbnail_timer.timeout.connect(self.request_visible_thumbnails)
        self.pending_in = None
        self.pending_out = None
        self.range_block_message = ""
        self.worker = None
        self.share_flash_timers = {}
        self.share_context = None
        self.share_watched_job = None
        self.share_completed = False
        self.share_ignored_jobs = set()
        self.refreshing = False
        self.positioned_clip_pages = set()
        self.prepared_clips = {}
        self.setWindowTitle("DFSorter")
        self.setWindowIcon(QIcon(str(ROOT / "resources/mascot/dfsorter.ico")))
        self.resize(1400, 918)
        self.status_bar = self.statusBar()
        central, outer = page()
        self.central = central
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
            self.nav[name] = button(name, lambda checked=False, name=name: self.navigate_panel(name))
            self.nav[name].setObjectName("navigation")
            self.nav[name].setCheckable(True)
            self.nav[name].setFocusPolicy(Qt.FocusPolicy.NoFocus)
            navigation.addWidget(self.nav[name])
        navigation.addStretch()
        self.undo_button = tool("undo-2", "Undo · Ctrl+Z", lambda: self.undo(False))
        self.redo_button = tool("redo-2", "Redo · Ctrl+Shift+Z", lambda: self.undo(True))
        set_icon(self.undo_button, "undo-2", y_offset=-2)
        set_icon(self.redo_button, "redo-2", y_offset=-2)
        self.undo_button.setProperty("navUtilityStyle", "ghost")
        self.redo_button.setProperty("navUtilityStyle", "ghost")
        self.update_history_controls()
        navigation.addWidget(self.undo_button, 0, Qt.AlignmentFlag.AlignVCenter)
        navigation.addSpacing(4)
        navigation.addWidget(self.redo_button, 0, Qt.AlignmentFlag.AlignVCenter)
        navigation.addSpacing(16)
        self.activities_button = tool("list-todo", "Output Jobs", lambda: None)
        self.activities_button.setFixedSize(26, 26)
        self.activities_button.setObjectName("activitiesButton")
        self.activities_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.activities_button.setProperty("navUtilityStyle", "ghost")
        self.activities_button.setProperty("navUtility", True)
        self.activities = Activities(self, self.activities_button)
        self.activities.idle.connect(
            lambda: QTimer.singleShot(0, self.close) if self.close_requested else None
        )
        navigation.addWidget(self.activities_button, 0, Qt.AlignmentFlag.AlignVCenter)
        navigation.addSpacing(12)
        self.projects_toggle = button("Projects", self.toggle_projects)
        set_icon(self.projects_toggle, "folder-open", size=16, y_offset=1, right_padding=1)
        self.projects_toggle.setToolTip("Show Projects")
        self.projects_toggle.setAccessibleName("Show Projects")
        self.projects_toggle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.projects_toggle.setObjectName("projectsDrawerTab")
        self.projects_toggle.setFixedSize(96, 30)
        self.projects_toggle.setIconSize(QSize(17, 16))
        self.projects_toggle.setFont(font("md", "medium"))
        self.projects_tab_edge = QWidget(self.projects_toggle)
        self.projects_tab_edge.setObjectName("projectsDrawerTabEdge")
        self.projects_tab_edge.setGeometry(91, 4, 1, 22)
        self.projects_tab_edge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.projects_tab_chevron = EdgeChevron(self.projects_toggle)
        self.projects_tab_chevron.setGeometry(83, 11, 5, 7)
        self.theme_button = tool("moon", "Switch to dark mode", self.toggle_theme)
        self.theme_button.setProperty("navUtility", True)
        self.theme_button.setProperty("navUtilityStyle", "ghost")
        navigation.addWidget(self.theme_button, 0, Qt.AlignmentFlag.AlignVCenter)
        navigation.addSpacing(4)
        self.settings_button = tool("settings", "Settings and actions", lambda: None)
        set_icon(self.settings_button, "settings", y_offset=-2)
        self.settings_button.setProperty("navUtilityStyle", "ghost")
        for control in (
            self.undo_button,
            self.redo_button,
            self.theme_button,
            self.settings_button,
        ):
            control.setProperty("navUtility", True)
        navigation.addWidget(self.settings_button, 0, Qt.AlignmentFlag.AlignVCenter)
        navigation.addSpacing(8)
        outer.addWidget(self.navigation_strip)
        self.projects_toggle.setParent(self.central)
        self.projects_toggle.raise_()
        self.splitter = QSplitter()
        self.splitter.setObjectName("workspaceSplitter")
        self.splitter.setHandleWidth(5)
        workspace, workspace_layout = page()
        workspace_layout.setContentsMargins(
            13, SIZES["panel_padding"], SIZES["panel_padding"], SIZES["panel_padding"]
        )
        workspace_layout.setSpacing(0)
        workspace_layout.addWidget(self.splitter)
        outer.addWidget(workspace, 1)
        self.left, outer_left_layout = page()
        self.left.setObjectName("clipLibraryPane")
        outer_left_layout.setContentsMargins(0, 0, 0, 0)
        outer_left_layout.setSpacing(0)
        role(self.left, "sidebar")
        self.library_toolbar = QWidget()
        self.library_toolbar.setObjectName("libraryToolbar")
        toolbar_layout = QVBoxLayout(self.library_toolbar)
        toolbar_layout.setContentsMargins(8, 8, 8, 8)
        toolbar_layout.setSpacing(8)
        outer_left_layout.addWidget(self.library_toolbar)
        library_body = QWidget()
        role(library_body, "transparent")
        left_layout = QVBoxLayout(library_body)
        left_layout.setContentsMargins(0, 4, 8, 4)
        left_layout.setSpacing(8)
        self.left_layout = left_layout
        outer_left_layout.addWidget(library_body, 1)
        self.search = QLineEdit()
        self.search.setProperty("librarySearch", True)
        self.search.setPlaceholderText("Search or game:VAL agent:Jett kill:>=4")
        self.search.textChanged.connect(self.refresh_library_from_controls)
        toolbar_layout.addWidget(self.search)
        self.filters, filter_layout = page()
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(4)
        role(self.filters, "transparent")
        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.setSpacing(4)
        self.clip_filter = FilterMenuButton(
            "Clips",
            "All clips",
            [("Pending", None), ("Keep", "keep"), ("Discard", "discard")],
            selected={None, "keep"},
        )
        self.game_filter = FilterMenuButton(
            "Games", "All games", [("Uncategorized", "")]
        )
        self.project_filter = FilterMenuButton(
            "Projects", "All projects", empty_text="No projects"
        )
        for control in (self.clip_filter, self.game_filter, self.project_filter):
            control.selectionChanged.connect(self.refresh_library_from_controls)
            filter_row.addWidget(control)
        filter_row.addStretch()
        self.unavailable_toggle = tool(
            "eye-off", "Unavailable clips hidden · Show unavailable clips", self.toggle_unavailable
        )
        self.unavailable_toggle.setCheckable(True)
        self.unavailable_toggle.setChecked(
            bool(self.settings.get("show_unavailable_clips", False))
        )
        if self.unavailable_toggle.isChecked():
            set_icon(self.unavailable_toggle, "eye")
            self.unavailable_toggle.setToolTip(
                "Unavailable clips shown · Hide unavailable clips"
            )
            self.unavailable_toggle.setAccessibleName(
                "Unavailable clips shown · Hide unavailable clips"
            )
        filter_row.addWidget(self.unavailable_toggle)
        self.time_sort = tool(
            "arrow-down-up", "Oldest first · Switch to newest first", self.toggle_time_sort
        )
        filter_row.addWidget(self.time_sort)
        filter_layout.addLayout(filter_row)
        toolbar_layout.addWidget(self.filters)
        self.browse_filters, browse_filters_layout = page()
        browse_filters_layout.setContentsMargins(0, 0, 0, 0)
        browse_filters_layout.setSpacing(8)
        role(self.browse_filters, "transparent")
        self.browse_search = QLineEdit()
        self.browse_search.setProperty("librarySearch", True)
        self.browse_search.setPlaceholderText("Search clips")
        self.browse_search.textChanged.connect(self.refresh_library_from_controls)
        browse_filters_layout.addWidget(self.browse_search)
        toolbar_layout.insertWidget(1, self.browse_filters)
        self.library_error = QLabel()
        role(self.library_error, "error")
        self.library_error.setWordWrap(True)
        self.library_error.hide()
        left_layout.addWidget(self.library_error)
        self.session_header = QWidget()
        session_header_layout = QHBoxLayout(self.session_header)
        self.session_header.setObjectName("sessionHeader")
        session_header_layout.setContentsMargins(12, 9, 8, 9)
        self.session_heading = QLabel("Session clips")
        role(self.session_heading, "paneHeading")
        session_header_layout.addWidget(self.session_heading, 0, Qt.AlignmentFlag.AlignVCenter)
        self.session_position = QLabel()
        role(self.session_position, "secondary")
        self.session_position.setContentsMargins(0, 2, 0, 0)
        session_header_layout.addWidget(self.session_position, 0, Qt.AlignmentFlag.AlignVCenter)
        session_header_layout.addStretch()
        self.next_undefined_button = tool(
            "list-todo",
            "Next pending clip",
            self.navigate_next_undefined,
        )
        self.next_undefined_button.setProperty("sessionAction", True)
        session_header_layout.addWidget(
            self.next_undefined_button, 0, Qt.AlignmentFlag.AlignVCenter
        )
        self.session_header.hide()
        outer_left_layout.insertWidget(1, self.session_header)
        self.library = QListWidget()
        self.library.library_hover_row = -1
        self.library.setObjectName("clipLibrary")
        self.library.setMouseTracking(True)
        self.library.setUniformItemSizes(True)
        self.library.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.library.setItemDelegate(ClipDelegate(self.library))
        self.library.viewport().installEventFilter(self)
        self.library.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.library.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.library_top_fade = ClipScrollFade("top", self.library.viewport())
        self.library_top_fade.setObjectName("clipScrollTopFade")
        self.library_bottom_fade = ClipScrollFade("bottom", self.library.viewport())
        self.library_bottom_fade.setObjectName("clipScrollBottomFade")
        self.library_top_fade.hide()
        self.library_bottom_fade.hide()
        scrollbar = self.library.verticalScrollBar()
        scrollbar.rangeChanged.connect(self.update_library_scroll_fades)
        scrollbar.valueChanged.connect(self.update_library_scroll_fades)
        scrollbar.valueChanged.connect(self.schedule_thumbnails)
        scrollbar.rangeChanged.connect(self.schedule_thumbnails)
        self.library.currentItemChanged.connect(self.select_clip)
        self.library.itemSelectionChanged.connect(self.library.viewport().update)
        self.library.itemEntered.connect(self.update_library_hover_row)
        self.library.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.library.customContextMenuRequested.connect(self.show_clip_context_menu)
        self.clip_context_menu = QMenu(self.library)
        self.edit_clip_action = self.clip_context_menu.addAction("Edit clip…")
        self.edit_clip_action.triggered.connect(self.edit_context_clip)
        self.context_clip_id = None
        left_layout.addWidget(self.library, 1)
        self.session_counts = QLabel()
        self.session_counts.setWordWrap(True)
        self.session_counts.setAccessibleName("Session clip counts")
        self.session_counts.setContentsMargins(8, 0, 5, 0)
        role(self.session_counts, "secondary")
        self.session_counts.hide()
        left_layout.addWidget(self.session_counts)
        self.splitter.addWidget(self.left)
        self.center_column = QWidget()
        center_layout = QVBoxLayout(self.center_column)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)
        self.center = CurrentPageStack()
        center_layout.addWidget(self.center, 1)
        self.splitter.addWidget(self.center_column)
        self.pages = {}
        self.build_pages()
        self.share_spinner = QTimer(self)
        self.share_spinner.setInterval(80)
        self.share_spinner.timeout.connect(self.advance_share_spinner)
        self.share_spinner_angle = 0
        self.activities.changed.connect(self.update_share_controls)
        self.right, right_layout = page()
        self.right.setObjectName("projectsPane")
        right_layout.setContentsMargins(8, 4, 8, 4)
        role(self.right, "sidebar")
        projects_header = QHBoxLayout()
        projects_header.setContentsMargins(0, 0, 0, 0)
        projects_title_row, self.projects_heading = heading(
            "Projects", "folder-open", "paneHeading", self.search.sizeHint().height()
        )
        projects_header.addLayout(projects_title_row)
        projects_header.addStretch()
        self.projects_close = tool("x", "Close Projects", self.toggle_projects)
        self.projects_close.setObjectName("projectsPaneClose")
        projects_header.addWidget(self.projects_close)
        right_layout.addLayout(projects_header)
        active_row = QWidget()
        role(active_row, "transparent")
        active_layout = QHBoxLayout(active_row)
        active_layout.setContentsMargins(0, 0, 0, 0)
        active_layout.setSpacing(4)
        self.active_label = QLabel("Active:")
        role(self.active_label, "secondary")
        active_layout.addWidget(self.active_label)
        self.active_project_name = QLabel()
        self.active_project_name.setObjectName("projectsActiveName")
        self.active_project_name.setWordWrap(True)
        active_layout.addWidget(self.active_project_name, 1)
        right_layout.addWidget(active_row)
        self.active_row = active_row
        self.projects = QListWidget()
        self.projects.setObjectName("projectsList")
        right_layout.addWidget(self.projects)
        self.projects_empty = QWidget()
        role(self.projects_empty, "transparent")
        empty_layout = QVBoxLayout(self.projects_empty)
        empty_layout.setContentsMargins(8, 0, 8, 0)
        empty_layout.setSpacing(8)
        empty_layout.addStretch(3)
        empty_icon = QLabel()
        empty_icon.setProperty("headingIcon", "folder")
        empty_icon.setProperty("headingIconSize", 20)
        empty_icon.setProperty("headingIconColorRole", "text_muted")
        empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_icon.setFixedSize(32, 32)
        empty_icon.setPixmap(icon("folder", COLORS["text_muted"], size=20).pixmap(20, 20))
        empty_layout.addWidget(empty_icon, 0, Qt.AlignmentFlag.AlignHCenter)
        empty_title = QLabel("No projects yet")
        role(empty_title, "paneHeading")
        empty_layout.addWidget(empty_title, 0, Qt.AlignmentFlag.AlignHCenter)
        create_project = button("Create project…", self.new_project)
        set_icon(create_project, "plus")
        empty_layout.addWidget(create_project, 0, Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addStretch(4)
        right_layout.addWidget(self.projects_empty, 1)
        self.projects_toolbar = QWidget()
        self.projects_toolbar.setObjectName("projectsToolbar")
        role(self.projects_toolbar, "transparent")
        toolbar_layout = QVBoxLayout(self.projects_toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(4)
        toolbar_divider = QWidget()
        role(toolbar_divider, "divider")
        toolbar_divider.setFixedHeight(1)
        toolbar_layout.addWidget(toolbar_divider)
        project_tools = QHBoxLayout()
        project_tools.setContentsMargins(0, 0, 0, 0)
        project_tools.setSpacing(4)
        self.project_global_controls = []
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
                control = tool(names[text], text, callback)
                control.setProperty("projectsAction", True)
                project_tools.addWidget(control)
                if text in {"New project", "Rename", "Activate", "Deactivate"}:
                    self.project_global_controls.append(control)
        project_tools.addStretch()
        toolbar_layout.addLayout(project_tools)
        right_layout.addWidget(self.projects_toolbar)
        self.splitter.addWidget(self.right)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.splitterMoved.connect(self.panes_resized)
        self.command_area, command_layout = page()
        self.command_area.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        command_layout.setContentsMargins(12, 8 + self.fontMetrics().lineSpacing(), 12, 4)
        command_layout.setSpacing(4)
        self.command_history = QLabel()
        self.command_history.setTextFormat(Qt.TextFormat.RichText)
        role(self.command_history, "muted")
        self.command_history.setWordWrap(True)
        self.command_history.hide()
        command_layout.addWidget(self.command_history)
        self.shortcut_hint = QLabel()
        self.shortcut_hint.setTextFormat(Qt.TextFormat.RichText)
        role(self.shortcut_hint, "helper")
        self.shortcut_hint.setWordWrap(True)
        command_layout.addWidget(self.shortcut_hint)
        self.command = CommandInput()
        self.command.setObjectName("command")
        self.command.textChanged.connect(self.remember_draft)
        self.command.setPlaceholderText("Enter clip metadata…")
        self.command_separator_range = None
        self.command_separator_space_pending = False
        self.command_submitted_error = False
        self.command_submitted_navigation = False
        self.command_saved_timer = QTimer(self)
        self.command_saved_timer.setSingleShot(True)
        self.command_saved_timer.setInterval(1200)
        self.command_saved_timer.timeout.connect(self.update_command_state)
        command_layout.addWidget(self.command)
        self.command_feedback = QLabel()
        self.command_feedback.setTextFormat(Qt.TextFormat.RichText)
        self.command_feedback.setObjectName("muted")
        self.command_feedback.setWordWrap(True)
        self.command_feedback.setMinimumHeight(self.command_feedback.fontMetrics().height())
        command_layout.addWidget(self.command_feedback)
        self.field_reminder = FieldReminder()
        self.field_reminder.setTextFormat(Qt.TextFormat.RichText)
        self.field_reminder.setWordWrap(True)
        self.field_reminder.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred
        )
        # Keep the command baseline stable when checklist glyphs change font metrics.
        self.field_reminder.setMinimumHeight(self.field_reminder.fontMetrics().height())
        self.field_reminder.setAccessibleName("Metadata field checklist with command preview")
        self.field_reminder.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.field_reminder.setMouseTracking(True)
        self.field_reminder.linkHovered.connect(self.field_reminder_hovered)
        self.field_reminder_hover = None
        self.field_reminder_tooltips = {}
        self.field_reminder_default_tooltip = ""
        self.field_reminder.hide()
        fields_row = QHBoxLayout()
        fields_row.setSpacing(12)
        fields_row.addWidget(self.field_reminder)
        self.editing_tip = TipWidget(size=self.editing_bottom_size())
        fields_row.addWidget(self.editing_tip, 1)
        self.atomic_edit_notice = TipWidget(
            size=self.editing_bottom_size(),
            icon_name="triangle-alert",
            color_role="status_warning",
        )
        self.atomic_edit_notice.set_message(
            "Single-clip edit: Save or Shift+Enter keeps the selected verdict. "
            "Use Keep, Discard, or Pending to change it."
        )
        self.atomic_edit_notice.hide()
        fields_row.addWidget(self.atomic_edit_notice, 1)
        self.tip_timer = QTimer(self)
        self.tip_timer.setInterval(30_000)
        self.tip_timer.timeout.connect(self.rotate_tip)
        self.range_warning_icon = QLabel()
        self.range_warning_icon.setPixmap(
            icon("triangle-alert", COLORS["status_danger"], size=12).pixmap(12, 12)
        )
        self.range_warning = QLabel("I/O not set")
        role(self.range_warning, "error")
        for widget in (self.range_warning_icon, self.range_warning):
            policy = widget.sizePolicy()
            policy.setRetainSizeWhenHidden(True)
            widget.setSizePolicy(policy)
            widget.hide()
        self.range_warning_slot = QHBoxLayout()
        self.range_warning_slot.setSpacing(3)
        self.range_warning_slot.addWidget(self.range_warning_icon)
        self.range_warning_slot.addWidget(self.range_warning)
        self.player.controls.insertLayout(1, self.range_warning_slot)
        command_layout.addLayout(fields_row)
        self.command_error = QLabel()
        role(self.command_error, "error")
        self.command_error.setWordWrap(True)
        self.command_error.hide()
        command_layout.addWidget(self.command_error)
        center_layout.addWidget(self.command_area)
        self.transition_generation = 0
        self.prepared_reveal_generation = 0
        self.prepared_reveal_attempt = 0
        self.transition_pending = False
        self.transition_scope = "page"
        self.transition_cover = QWidget(central)
        self.transition_cover.setObjectName("pageLoading")
        cover_layout = QVBoxLayout(self.transition_cover)
        cover_layout.addStretch()
        self.transition_image = QLabel(self.transition_cover)
        self.transition_image.setScaledContents(True)
        self.transition_image.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.transition_image.hide()
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
        self.pending_navigation_timer = QTimer(self)
        self.pending_navigation_timer.setSingleShot(True)
        self.pending_navigation_timer.setInterval(1000)
        self.pending_navigation_timer.timeout.connect(self.show_pending_navigation_status)
        self.command_cover = QWidget(self.command_area)
        self.command_cover.setObjectName("commandCover")
        self.command_cover.hide()
        for player in (self.player, self.export_player, self.browse.player):
            player.loading_started.connect(lambda player=player: self.player_loading(player))
            player.preview_render_ready.connect(
                lambda player=player: self.player_render_ready(player)
            )
            player.loading_finished.connect(lambda player=player: self.player_ready(player))
        self.build_settings_menu()
        self.update_theme_button()
        QApplication.instance().styleHints().colorSchemeChanged.connect(self.system_theme_changed)
        self.scan_timer = QTimer(self)
        self.scan_timer.setInterval(30_000)
        self.scan_timer.timeout.connect(self.request_auto_scan)
        self.scan_retry_timer = QTimer(self)
        self.scan_retry_timer.setSingleShot(True)
        self.scan_retry_timer.setInterval(1000)
        self.scan_retry_timer.timeout.connect(self.auto_scan)
        self.scan_timer.start()
        self.browse_time_timer = QTimer(self)
        self.browse_time_timer.setInterval(60_000)
        self.browse_time_timer.timeout.connect(self.refresh_browse_times)
        self.library_time_timer = QTimer(self)
        self.library_time_timer.setInterval(60_000)
        self.library_time_timer.timeout.connect(self.refresh_library_times)
        QApplication.instance().installEventFilter(self)
        self.blocked_close_bell = BlockedCloseBell(self)
        QApplication.instance().focusChanged.connect(self.command_focus_changed)
        self.player.media.playbackStateChanged.connect(self.command_playback_changed)
        self.player.loading_finished.connect(self.update_command_state)
        self.preload_timer = QTimer(self)
        self.preload_timer.setSingleShot(True)
        self.preload_timer.setInterval(150)
        self.preload_timer.timeout.connect(self.prepare_inactive_clips)
        self.refresh_references()
        self.panel("Home")
        self.reset_layout()
        self.schedule_preload()
        self.restore_export_jobs()
        if self.registry.errors:
            self.statusBar().showMessage("Configuration errors — see Config panel")
        QTimer.singleShot(0, self.rescan)
        if installed_release():
            QTimer.singleShot(0, lambda: self.check_for_updates(quiet=True))

    def build_pages(self):
        for name in ["Home", "Browse", "Session", "Editing", "Export", "Config"]:
            widget, layout = page()
            self.pages[name] = (widget, layout)
            self.center.addWidget(widget)
        self.browse = BrowsePage(self)
        self.pages["Browse"][1].addWidget(self.browse)
        home = self.pages["Home"][1]
        home.setContentsMargins(SIZES["panel_padding"], 4, SIZES["panel_padding"], SIZES["panel_padding"])
        home_title_row, _home_title = heading("Capture folders", "folder-open")
        home.addLayout(home_title_row)
        explanation = QLabel(
            "Add folders containing recordings. Rescans discover new clips; source media is never modified."
        )
        explanation.setWordWrap(True)
        role(explanation, "secondary")
        home.addWidget(explanation)
        self.folder_summary = QLabel()
        role(self.folder_summary, "secondary")
        home.addWidget(self.folder_summary)
        folder_controls = QHBoxLayout()
        self.add_folder_button = button("Add folder…", lambda: self.add_folder())
        role(self.add_folder_button, "prominentNeutral")
        self.add_folder_button.setProperty("captureFolderAction", True)
        set_icon(self.add_folder_button, "folder-plus", "accent_default")
        folder_controls.addWidget(self.add_folder_button)
        self.game_configs_button = button("Game configs…", lambda: self.navigate_panel("Config"))
        self.game_configs_button.setProperty("captureFolderAction", True)
        folder_controls.addWidget(self.game_configs_button)
        self.rescan_button = button("Rescan", self.rescan)
        self.rescan_button.setProperty("captureFolderAction", True)
        set_icon(self.rescan_button, "refresh-cw")
        self.rescan_button.setToolTip(
            "Find new files in all enabled folders. Reuse cached media information for unchanged files."
        )
        folder_controls.addWidget(self.rescan_button)
        self.folder_more = QToolButton()
        self.folder_more.setObjectName("captureFolderMenuButton")
        self.folder_more.setProperty("captureFolderAction", True)
        self.folder_more.setText("More…")
        self.folder_more.setToolTip("More capture folder actions")
        self.folder_more.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.folder_more.setFixedHeight(SIZES["large"])
        self.folder_menu = QMenu(self.folder_more)
        self.folder_toggle_action = self.folder_menu.addAction("Pause scanning", self.toggle_folder)
        self.folder_toggle_action.setToolTip(
            "Pause scanning and exclude this folder from new sessions. Existing clips and sessions remain."
        )
        self.folder_unlinked_remove_action = self.folder_menu.addAction(
            "Remove saved entries…", self.remove_folder
        )
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
        self.folders.setProperty("contentSurface", "secondary")
        self.folders.setItemDelegate(CaptureFolderDelegate(self.folders))
        self.folders.setMinimumHeight(120)
        self.folders.setWordWrap(True)
        self.folder_context_menu = QMenu(self.folders)
        self.folder_context_menu.addAction(self.folder_toggle_action)
        self.folder_migrate_action = self.folder_context_menu.addAction("Relink folder…", self.migrate)
        self.folder_migrate_action.setToolTip("Find an already moved folder; no files are moved.")
        self.folder_remove_action = self.folder_context_menu.addAction("Remove folder…", self.remove_folder)
        self.folder_context_menu.setToolTipsVisible(True)
        self.folders.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.folders.customContextMenuRequested.connect(self.show_folder_context_menu)
        home.addWidget(self.folders, 1)
        note = QLabel(
            "Right-click a folder to pause or resume scanning, relink it, or remove it.\n"
            "Paused folders remain in the library but are excluded from new sessions. "
            "Unlinked clips are saved entries from folders no longer tracked."
        )
        note.setWordWrap(True)
        role(note, "muted")
        home.addWidget(note)
        session = self.pages["Session"][1]
        session.setContentsMargins(SIZES["panel_padding"], 4, SIZES["panel_padding"], 4)
        session_scroll = QScrollArea()
        session_scroll.setObjectName("sessionOverviewScroll")
        session_scroll.setWidgetResizable(True)
        session_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        overview_group = QWidget()
        overview_group.setObjectName("sessionOverview")
        role(overview_group, "transparent")
        overview_layout = QVBoxLayout(overview_group)
        overview_layout.setContentsMargins(0, 0, 0, 0)
        overview_layout.setSpacing(8)
        overview_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        overview_title_row, _overview_heading = heading(
            "Library overview", "chart-no-axes-column", row_height=self.search.sizeHint().height()
        )
        _overview_heading.setObjectName("overviewHeading")
        overview_layout.addLayout(overview_title_row)
        overview_description = QLabel(
            "Current verdicts for clips captured in the selected period."
        )
        role(overview_description, "secondary")
        overview_layout.addWidget(overview_description)
        periods = QHBoxLayout()
        periods.setSpacing(0)
        self.overview_period = "All time"
        self.overview_period_buttons = {}
        period_labels = list(PERIOD_DAYS)
        for index, label in enumerate(period_labels):
            control = QPushButton(label)
            control.setCheckable(True)
            control.setChecked(label == self.overview_period)
            control.setProperty("periodSegment", True)
            control.setProperty(
                "periodPosition",
                "first" if index == 0 else "last" if index == len(period_labels) - 1 else "middle",
            )
            control.clicked.connect(
                lambda checked=False, label=label: self.set_overview_period(label)
            )
            periods.addWidget(control)
            self.overview_period_buttons[label] = control
        periods.addStretch()
        overview_layout.addLayout(periods)
        self.overview_rows = QVBoxLayout()
        self.overview_rows.setSpacing(12)
        overview_layout.addLayout(self.overview_rows)
        self.overview_empty = QLabel("No available clips captured in this period.")
        role(self.overview_empty, "muted")
        self.overview_empty.hide()
        overview_layout.addWidget(self.overview_empty)
        self.overview_undated = QLabel()
        role(self.overview_undated, "muted")
        self.overview_undated.setWordWrap(True)
        self.overview_undated.hide()
        overview_layout.addWidget(self.overview_undated)
        overview_layout.addStretch()
        session_scroll.setWidget(overview_group)
        session.addWidget(session_scroll, 1)
        session_group = QWidget()
        session_group.setObjectName("sessionSetup")
        session_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        role(session_group, "transparent")
        session_setup = QVBoxLayout(session_group)
        session_setup.setContentsMargins(0, 0, 0, 0)
        session_setup.setSpacing(4)
        session_divider = QWidget()
        role(session_divider, "divider")
        session_divider.setFixedHeight(1)
        session_setup.addWidget(session_divider)
        session_setup.addSpacing(10)
        session_title_row, self.session_setup_heading = heading("", "circle-play")
        session_setup.addLayout(session_title_row)
        self.session_setup_states = QStackedWidget()
        active_session_page = QWidget()
        active_session = QVBoxLayout(active_session_page)
        active_session.setContentsMargins(0, 0, 0, 0)
        active_session.setSpacing(6)
        self.session_progress = SessionProgressBar()
        active_session.addWidget(self.session_progress)
        self.session_verdicts = QLabel()
        role(self.session_verdicts, "muted")
        self.session_verdicts.setTextFormat(Qt.TextFormat.RichText)
        active_session.addWidget(self.session_verdicts)
        existing_actions = QHBoxLayout()
        existing_actions.setSpacing(8)
        existing_actions.addWidget(button("End session", self.end_session))
        existing_actions.addStretch()
        active_session.addLayout(existing_actions)
        self.session_setup_states.addWidget(active_session_page)
        create_session_page = QWidget()
        create_session = QVBoxLayout(create_session_page)
        create_session.setContentsMargins(0, 0, 0, 0)
        create_session.setSpacing(8)
        inactive_status = QLabel("Choose pending clips from the library to create a session.")
        role(inactive_status, "secondary")
        create_session.addWidget(inactive_status)
        scope_label = QLabel("Scope")
        role(scope_label, "muted")
        create_session.addWidget(scope_label)
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
        create_session.addLayout(session_choices)
        create_session.addWidget(
            button("Create Session", lambda: self.create_session(self.session_mode)),
            0,
            Qt.AlignmentFlag.AlignLeft,
        )
        self.session_setup_states.addWidget(create_session_page)
        session_setup.addWidget(self.session_setup_states)
        session.addWidget(session_group)
        editing = self.pages["Editing"][1]
        self.player = Player(self.settings)
        self.player.volume_changed.connect(self.set_playback_volume)
        self.player.previous.connect(lambda: self.navigate(-1))
        self.player.next.connect(lambda: self.navigate(1))
        editing.addWidget(self.player, 1)
        title_row = QHBoxLayout()
        self.working_title = QLabel()
        self.working_title.setWordWrap(True)
        self.working_title.setTextFormat(Qt.TextFormat.RichText)
        self.working_title.setObjectName("workingTitle")
        title_row.addWidget(self.working_title, 1)
        self.atomic_save_button = button(
            "Save and return to clip", lambda: self.save_atomic_edit()
        )
        self.atomic_revert_button = button("Revert", self.revert_atomic_edit)
        role(self.atomic_revert_button, "danger")
        self.atomic_save_button.hide()
        self.atomic_revert_button.hide()
        title_row.addWidget(self.atomic_save_button, 0, Qt.AlignmentFlag.AlignTop)
        title_row.addWidget(self.atomic_revert_button, 0, Qt.AlignmentFlag.AlignTop)
        editing.addLayout(title_row)
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
        for text, state in [("Keep", "keep"), ("Discard", "discard"), ("Pending", None)]:
            control = button(text, lambda checked=False, state=state: self.edit({"triage": state}))
            control.setCheckable(True)
            role(control, state or "undefined")
            if state is None:
                control.setToolTip("Clear verdict and mark as pending")
            self.triage_buttons[state] = control
            triage.addWidget(control)
        triage.addWidget(button("Change game", self.change_game))
        triage.addStretch()
        editing.addLayout(triage)
        stars = QHBoxLayout()
        self.rating = Rating()
        self.rating.changed.connect(lambda value: self.edit({"rating": value}))
        stars.addWidget(self.rating)
        self.rating_clear = tool("x", "Clear rating", lambda: self.edit({"rating": None}))
        stars.addWidget(self.rating_clear)
        self.rating_hint = QLabel("r1 infamous · r2 diff edit · r3 filler · r4 great · r5 iconic")
        role(self.rating_hint, "muted")
        self.rating_hint.setToolTip("r1 infamous · r2 diff edit · r3 filler · r4 great · r5 iconic")
        stars.addWidget(self.rating_hint)
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
            control = tool(names[text], label, callback)
            if text == "Share":
                self.edit_share_button = control
            controls.addWidget(control)
        project_separator = QWidget()
        project_separator.setFixedSize(1, 20)
        role(project_separator, "divider")
        controls.addWidget(project_separator, 0, Qt.AlignmentFlag.AlignVCenter)
        self.add_project_next = tool(
            "folder-plus",
            "Add to project + Next · Ctrl+Enter (review mode)",
            self.add_to_project_next,
        )
        self.add_project_next.setEnabled(False)
        controls.addWidget(self.add_project_next)
        exporting = self.pages["Export"][1]
        export_heading = QLabel("Project export")
        role(export_heading, "heading")
        exporting.addWidget(export_heading)
        export_explanation = QLabel("Copy eligible project clips without changing original files.")
        role(export_explanation, "secondary")
        exporting.addWidget(export_explanation)
        self.export_project = QComboBox()
        self.export_project.currentIndexChanged.connect(self.export_selection)
        exporting.addWidget(self.export_project)
        self.export_player = Player(self.settings, pane="Export")
        self.export_player.volume_changed.connect(self.set_playback_volume)
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
        self.config_editor = ConfigEditor(self)
        self.pages["Config"][1].setContentsMargins(
            SIZES["panel_padding"], 4, SIZES["panel_padding"], SIZES["panel_padding"]
        )
        self.pages["Config"][1].addWidget(self.config_editor)
        self.left.layout().insertWidget(2, self.config_editor.sidebar_header)
        self.config_editor.sidebar_header.hide()
        self.left_layout.addWidget(self.config_editor.sidebar, 1)
        self.config_editor.sidebar.hide()

    def build_settings_menu(self):
        self.settings_menu = QMenu(self)
        self.browse_write_actions = []
        actions = [
            ("Settings…", self.open_settings, None),
            ("Check for updates…", self.check_for_updates, None),
            ("Capture folders…", lambda: self.panel("Home"), None),
            None,
            ("Reset clip metadata…", self.reset_metadata, None),
            ("Edit tag…", self.edit_tag, None),
            None,
            ("Delete rejected originals…", self.delete_rejected, None),
            ("Manage unavailable clips…", self.manage_unavailable_clips, None),
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
            if name in {
                "Reset clip metadata…",
                "Edit tag…",
                "Delete rejected originals…",
            }:
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
        if getattr(self, "settings_dialog", None) is not None:
            self.settings_dialog.raise_()
            self.settings_dialog.activateWindow()
            return
        dialog = SettingsDialog(self)
        self.settings_dialog = dialog
        dialog.finished.connect(lambda: self.close_settings_dialog(dialog))
        dialog.show()

    def close_settings_dialog(self, dialog):
        if self.settings_dialog is dialog:
            self.settings_dialog = None
        dialog.deleteLater()

    def check_for_updates(self, *, quiet=False):
        if not hasattr(self, "update_controller"):
            self.update_controller = UpdateController(self)
        self.update_controller.check(quiet=quiet)

    def update_theme_button(self):
        scheme = resolved_scheme(QApplication.instance(), self.settings.get("theme", "light"))
        target = "dark" if scheme == "light" else "light"
        icon_name = "moon" if target == "dark" else "sun"
        label = f"Switch to {target} mode"
        set_icon(self.theme_button, icon_name, y_offset=-2)
        self.theme_button.setToolTip(label)
        self.theme_button.setAccessibleName(label)

    def toggle_theme(self):
        scheme = resolved_scheme(QApplication.instance(), self.settings.get("theme", "light"))
        self.set_theme("dark" if scheme == "light" else "light")

    def set_theme(self, mode, *, persist=True):
        if mode not in {"system", "light", "dark"}:
            raise ValueError(f"Unknown theme: {mode}")
        self.settings["theme"] = mode
        if persist:
            self.save_settings()
        apply_theme(QApplication.instance(), mode)
        refresh_icons(self)
        if self.share_spinner.isActive():
            self.advance_share_spinner()
        self.update_share_controls()
        for glyph in self.findChildren(QLabel):
            name = glyph.property("headingIcon")
            if name:
                size = glyph.property("headingIconSize") or 20
                color_role = glyph.property("headingIconColorRole")
                glyph.setPixmap(
                    icon(
                        name,
                        COLORS[color_role] if color_role else None,
                        size=size,
                    ).pixmap(size, size)
                )
        self.range_warning_icon.setPixmap(
            icon("triangle-alert", COLORS["status_danger"], size=12).pixmap(12, 12)
        )
        self.editing_tip.refresh_theme()
        self.atomic_edit_notice.refresh_theme()
        self.update_theme_button()
        self.refresh_references()
        self.refresh_title_presentation()
        self.refresh_shortcut_hint()
        self.update_command_state()
        self.command.update()
        clip = self.effective_clip() if self.current_id else None
        if clip:
            self.render_field_reminder(clip, self.registry.game(clip["game"]))
            self.render_command_history()
        for player in (self.player, self.export_player, self.browse.player):
            player.seek.update()
            player.fast_indicator.update()
        self.rating.update()
        for bar in self.findChildren(VerdictBar):
            bar.update()
        self.update()

    def system_theme_changed(self, _scheme):
        if self.settings.get("theme") == "system":
            self.set_theme("system", persist=False)

    def delete_rejected(self):
        if self.current_panel == "Browse" or self.atomic_edit:
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

    def manage_unavailable_clips(self):
        if self.atomic_edit:
            return
        if self.worker is not None:
            self.error("Wait for the current operation to finish")
            return
        dialog = UnavailableClipsDialog(self)
        dialog.exec()
        dialog.deleteLater()

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
                self.player.load(self.effective_clip())
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

    def source_stat(self, path):
        if path not in self.source_stats:
            try:
                self.source_stats[path] = Path(path).stat()
            except OSError:
                self.source_stats[path] = None
        return self.source_stats[path]

    def source_available(self, path):
        stamp = self.source_stat(path)
        return stamp is not None and stat.S_ISREG(stamp.st_mode)

    def capture_datetime(self, clip):
        return capture_datetime(clip, self.media_info, self.source_stat)

    def catalogue_stamp(self):
        try:
            return self.catalogue.path.stat().st_mtime_ns
        except OSError:
            return None

    def player_loading(self, player):
        if (
            player.loaded_clip is not None
            and self.current_panel in {"Browse", "Editing", "Export"}
            and player is self.active_player()
        ):
            self.begin_page_transition("clip")

    def player_render_ready(self, player):
        if (
            self.transition_pending
            and self.current_panel in {"Browse", "Editing", "Export"}
            and player is self.active_player()
        ):
            player.video_container.layout_surface()
            # A native video child can paint above the Qt cover on its first show.
            player.video.setMask(QRegion(0, 0, 1, 1))
            player.video.show()
            self.command_cover.raise_()
            self.transition_cover.raise_()

    def player_ready(self, player):
        if self.current_panel in {"Browse", "Editing", "Export"} and player is self.active_player():
            self.queue_page_reveal()
        elif player.loaded_clip is not None:
            generation = player.media.generation
            pending = self.pending_page
            if pending is not None and pending["player"] is player:
                QTimer.singleShot(
                    0,
                    lambda: self.finish_pending_navigation(pending["generation"], generation),
                )
            else:
                QTimer.singleShot(0, lambda: self.capture_inactive_frame(player, generation))

    def capture_inactive_frame(self, player, generation):
        if (
            not player.isVisible()
            and player.media.generation == generation
            and not player.awaiting_frame
            and player.media.mediaStatus() == QMediaPlayer.MediaStatus.LoadedMedia
            and player.prepared_image is None
        ):
            image = player.media.frame_image()
            if not image.isNull():
                player.prepared_image = image
                player.prepared_position = player.media.position()

    def position_transition_covers(self):
        target = self.centralWidget() if self.transition_scope == "page" else self.center
        self.transition_cover.setGeometry(
            target.mapTo(self.centralWidget(), QPoint(0, 0)).x(),
            target.mapTo(self.centralWidget(), QPoint(0, 0)).y(),
            target.width(),
            target.height(),
        )
        self.command_cover.setGeometry(self.command_area.rect())
        self.transition_image.setGeometry(self.transition_cover.rect())

    def begin_page_transition(self, scope="page"):
        self.cancel_prepared_video_reveal()
        if scope == "page" and not self.transition_pending and self.isVisible():
            self.transition_image.setPixmap(self.centralWidget().grab())
            self.transition_image.show()
            self.transition_image.raise_()
            self.loading_label.raise_()
        elif scope == "clip":
            self.transition_image.hide()
            self.transition_image.clear()
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
            player.video.clearMask()
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
        if (
            self.current_panel in {"Browse", "Editing", "Export"}
            and self.active_player().awaiting_frame
        ):
            return
        self.loading_indicator_timer.stop()
        self.transition_pending = False
        self.centralWidget().layout().activate()
        for player in (self.player, self.export_player, self.browse.player):
            player.video_container.layout_surface()
            player.video.clearMask()
            player.video.show()
        self.transition_cover.hide()
        self.command_cover.hide()
        self.transition_image.hide()
        self.transition_image.clear()

    def cancel_page_transition(self):
        if not self.transition_pending:
            return
        self.transition_generation += 1
        self.transition_pending = False
        self.loading_indicator_timer.stop()
        self.transition_cover.hide()
        self.command_cover.hide()
        self.transition_image.hide()
        self.transition_image.clear()
        for player in (self.player, self.export_player, self.browse.player):
            player.video.clearMask()
            player.video.show()

    def page_needs_cover(self, name, clip=None):
        if name not in {"Browse", "Editing", "Export"}:
            return False
        if name == self.current_panel:
            return True
        if name == "Export":
            clip = clip if clip is not None else self.expected_export_clip()
            player = self.export_player
            return clip is not None and not self.player_has_clip(player, clip)
        if name == "Browse":
            clip = clip if clip is not None else self.expected_browse_clip()
            player = self.browse.player
        else:
            clip = clip if clip is not None else self.expected_editing_clip()
            player = self.player
        if clip is None:
            return False
        return not self.player_has_clip(player, clip)

    def player_has_clip(self, player, clip):
        return (
            clip is not None
            and player.loaded_clip is not None
            and getattr(player, "loaded_start_settings", None)
            == playback_start_settings(self.settings, player.pane)
            and self.clip_load_key(player.loaded_clip, player.pane)
            == self.clip_load_key(clip, player.pane)
            and not player.awaiting_frame
        )

    def cancel_prepared_video_reveal(self):
        self.prepared_reveal_generation += 1
        for player in (self.player, self.export_player, self.browse.player):
            if not player.video_container.prepared_frame.isHidden():
                player.video.hide()
                player.video_container.clear_prepared_frame()
                player.video.clearMask()

    def prepared_video_is_current(self, panel, player, media_generation, reveal_generation):
        return (
            self.current_panel == panel
            and not self.transition_pending
            and player.media.generation == media_generation
            and self.prepared_reveal_generation == reveal_generation
        )

    def show_ready_video(self, panel, player, media_generation, reveal_generation):
        if not self.prepared_video_is_current(
            panel, player, media_generation, reveal_generation
        ):
            return
        self.centralWidget().layout().activate()
        player.video_container.layout_surface()
        player.video.setMask(QRegion(0, 0, 1, 1))
        player.video.show()
        player.video_container.prepared_frame.raise_()
        geometry = (player.video.size(), player.video.devicePixelRatioF())
        screen = player.video.screen()
        refresh_rate = screen.refreshRate() if screen else 60
        frame_delay = max(1, round(2000 / refresh_rate)) if refresh_rate > 0 else 33
        delay = max(100, frame_delay) if player.warmed_video_geometry != geometry else frame_delay
        self.prepared_reveal_attempt += 1
        attempt = self.prepared_reveal_attempt
        QTimer.singleShot(
            delay,
            lambda: self.finish_ready_video(
                panel, player, media_generation, reveal_generation, attempt, geometry
            ),
        )

    def finish_ready_video(
        self, panel, player, media_generation, reveal_generation, attempt, geometry
    ):
        if (
            attempt != self.prepared_reveal_attempt
            or not self.prepared_video_is_current(
                panel, player, media_generation, reveal_generation
            )
        ):
            return
        if (player.video.size(), player.video.devicePixelRatioF()) != geometry:
            self.show_ready_video(panel, player, media_generation, reveal_generation)
            return
        player.video.clearMask()
        player.video_container.clear_prepared_frame()
        player.native_surface_warmed = True
        player.warmed_video_geometry = geometry

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "transition_cover"):
            self.position_transition_covers()
        if hasattr(self, "projects_toggle"):
            self.position_projects_toggle()

    def effective_snapshot(self):
        if self.atomic_edit and self.current_id == self.atomic_edit.clip_id:
            return self.atomic_edit.draft
        return self.catalogue.snapshot(self.current_id)

    def effective_clip(self):
        return self.effective_snapshot()[0]

    def effective_memberships(self):
        return self.effective_snapshot()[1]

    def editing_history(self):
        return self.atomic_edit.edits if self.atomic_edit else self.editing_histories[self.current_id]

    def editing_state(self, clip_id, atomic=None):
        snapshot = atomic.draft if atomic else self.catalogue.snapshot(clip_id)
        fields = (
            "clip_id", "game", "triage", "rating", "tag", "mainline", "description",
            "metadata", "in_ms", "out_ms",
        )
        return deepcopy({
            "snapshot": ({key: snapshot[0][key] for key in fields}, snapshot[1]),
            "pending": (self.pending_in, self.pending_out)
            if clip_id == self.current_id else (None, None),
            "history": atomic.history if atomic else self.history[clip_id],
        })

    def show_clip_context_menu(self, position):
        item = self.library.itemAt(position)
        if item is None or self.current_panel == "Editing":
            return
        self.context_clip_id = item.data(Qt.ItemDataRole.UserRole)
        if self.current_panel == "Home":
            self.highlight_home_clip(item)
        else:
            self.library.blockSignals(True)
            self.library.clearSelection()
            self.library.setCurrentItem(item)
            item.setSelected(True)
            self.library.blockSignals(False)
        self.clip_context_menu.popup(self.library.viewport().mapToGlobal(position))

    def highlight_home_clip(self, item):
        self.library.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.library.blockSignals(True)
        self.library.clearSelection()
        self.library.setCurrentItem(item)
        item.setSelected(True)
        self.library.blockSignals(False)
        self.library.viewport().update()

    def browse_library_clip(self, item):
        if self.current_panel not in {"Home", "Session"}:
            return
        clip_id = item.data(Qt.ItemDataRole.UserRole)
        self.browse_selected_id = clip_id
        if self.browse_search.text():
            self.browse_search.clear()
        self.panel("Browse")
        for index in range(self.library.count()):
            candidate = self.library.item(index)
            if candidate.data(Qt.ItemDataRole.UserRole) == clip_id:
                self.library.setCurrentItem(candidate)
                self.library.scrollToItem(candidate)
                break

    def edit_context_clip(self):
        if self.context_clip_id:
            self.start_atomic_edit(self.context_clip_id, self.current_panel)

    def start_atomic_edit(self, clip_id, origin=None):
        if self.atomic_edit:
            return
        baseline = self.catalogue.snapshot(clip_id)
        baseline[1].sort()
        self.atomic_edit = AtomicEditState(
            clip_id,
            origin or self.current_panel,
            baseline,
            deepcopy(baseline),
            (
                self.library.horizontalScrollBar().value(),
                self.library.verticalScrollBar().value(),
            ),
        )
        self.atomic_edit.history = deepcopy(self.history[clip_id])
        self.current_id = clip_id
        self.panel("Editing")

    def atomic_changed(self):
        return bool(
            self.atomic_edit
            and (self.atomic_edit.draft != self.atomic_edit.baseline or self.has_pending_range())
        )

    def can_save_atomic(self):
        return (
            self.atomic_changed()
            and not self.command.text()
            and not self.has_pending_range()
        )

    def save_atomic_edit(self):
        if not self.atomic_edit:
            return False
        if self.command.text():
            self.error("Submit the command with Enter before saving.")
            return False
        if not self.ensure_range_complete():
            return False
        if not self.atomic_changed():
            return False
        try:
            state = self.atomic_edit
            self.catalogue.commit_snapshot(state.baseline, state.draft)
            history = self.editing_histories[state.clip_id]
            if state.edits.undo_stack:
                previous = history.pending()
                if previous and previous.after != state.edits.undo_stack[0].before:
                    history.undo_stack.clear()
                history.undo_stack.extend(state.edits.undo_stack)
                history.redo_stack = state.edits.redo_stack
            self.history[state.clip_id] = deepcopy(state.history)
            self.atomic_edit = None
            self.current_id = None
            self.return_from_atomic_edit(state.origin, state.clip_id, state.scroll_position)
            return True
        except ValueError as error:
            self.error(error)
            return False

    def discard_atomic_edit(self):
        if not self.atomic_edit:
            return None
        origin = self.atomic_edit.origin
        self.command.clear()
        self.atomic_edit = None
        self.current_id = None
        self.reset_pending_range()
        return origin

    def confirm_revert_atomic(self):
        if not self.atomic_edit:
            return True
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Discard single-clip changes?")
        dialog.setText("Discard all staged changes and leave single-clip Editing?")
        discard = dialog.addButton("Discard changes", QMessageBox.ButtonRole.DestructiveRole)
        cancel = dialog.addButton(QMessageBox.StandardButton.Cancel)
        dialog.setDefaultButton(cancel)
        dialog.exec()
        return dialog.clickedButton() is discard

    def revert_atomic_edit(self):
        if not self.atomic_edit or not self.confirm_revert_atomic():
            return
        clip_id = self.atomic_edit.clip_id
        scroll_position = self.atomic_edit.scroll_position
        origin = self.discard_atomic_edit()
        self.return_from_atomic_edit(origin, clip_id, scroll_position)

    def return_from_atomic_edit(self, origin, clip_id, scroll_position):
        if origin == "Browse":
            self.browse_id = clip_id
            self.browse_selected_id = clip_id
        self.panel(origin)
        if self.current_panel != origin or origin not in {"Home", "Browse"}:
            return
        for index in range(self.library.count()):
            item = self.library.item(index)
            if item.data(Qt.ItemDataRole.UserRole) != clip_id:
                continue
            self.library.blockSignals(True)
            self.library.clearSelection()
            self.library.setCurrentItem(item)
            item.setSelected(True)
            self.library.blockSignals(False)
            break
        QTimer.singleShot(0, lambda: self.restore_library_scroll(scroll_position))

    def restore_library_scroll(self, position):
        horizontal, vertical = position
        self.library.horizontalScrollBar().setValue(horizontal)
        self.library.verticalScrollBar().setValue(vertical)

    def navigation_target(self, name):
        if name == "Browse":
            return self.expected_browse_clip(), self.browse.player
        if name == "Editing":
            return self.expected_editing_clip(), self.player
        if name == "Export":
            return self.expected_export_clip(), self.export_player
        return None, None

    def cancel_pending_navigation(self):
        if self.pending_page is None:
            return
        self.pending_page_generation += 1
        self.pending_page = None
        self.pending_navigation_timer.stop()
        if self.statusBar().currentMessage() == "Loading…":
            self.statusBar().clearMessage()
        for destination, control in self.nav.items():
            control.setChecked(destination == self.current_panel)

    def show_pending_navigation_status(self):
        if self.pending_page is not None:
            self.statusBar().showMessage("Loading…")

    def navigate_panel(self, name):
        if name == self.current_panel:
            self.cancel_pending_navigation()
            self.panel(name)
            return
        if name not in {"Browse", "Editing", "Export"} or (
            self.current_panel == "Config" or self.atomic_edit or self.has_pending_range()
        ):
            self.cancel_pending_navigation()
            self.panel(name)
            return
        clip, player = self.navigation_target(name)
        if clip is None or self.player_has_clip(player, clip):
            self.cancel_pending_navigation()
            self.panel(name)
            return
        key = self.clip_load_key(clip, name)
        if (
            self.pending_page is not None
            and self.pending_page["name"] == name
            and self.pending_page["key"] == key
        ):
            return
        self.cancel_pending_navigation()
        self.pending_page_generation += 1
        self.pending_page = {
            "name": name, "key": key, "player": player,
            "generation": self.pending_page_generation,
        }
        for destination, control in self.nav.items():
            control.setChecked(destination == self.current_panel)
        self.pending_navigation_timer.start()
        if player.loaded_clip is None or self.clip_load_key(player.loaded_clip, name) != key:
            if name in {"Browse", "Editing"}:
                self.prepared_clips[name] = key
            player.load(clip)

    def finish_pending_navigation(self, generation, media_generation):
        pending = self.pending_page
        if pending is None or pending["generation"] != generation:
            return
        player = pending["player"]
        if player.media.generation != media_generation or player.awaiting_frame:
            return
        name = pending["name"]
        clip, _ = self.navigation_target(name)
        if clip is None or self.clip_load_key(clip, name) != pending["key"]:
            self.cancel_pending_navigation()
            self.navigate_panel(name)
            return
        self.capture_inactive_frame(player, media_generation)
        self.cancel_pending_navigation()
        self.panel(name)

    def panel(self, name):
        self.cancel_pending_navigation()
        stamp = self.catalogue_stamp()
        if name == self.current_panel and self._panel_initialized:
            if stamp != self.reference_stamp:
                self.source_stats.clear()
                self.refresh_references()
                self.refresh_library()
            return
        if self.current_panel == "Config" and name != "Config":
            if not self.config_editor.confirm_discard():
                return
        if self.atomic_edit and self.current_panel == "Editing" and name != "Editing":
            if not self.confirm_revert_atomic():
                return
            self.discard_atomic_edit()
        if not self.ensure_range_complete():
            return
        self.submit_resume = False
        if name == "Editing" and not self.atomic_edit and not self.catalogue.state("session"):
            self.error("Create a session before entering Editing")
            return
        self._navigating = True
        if stamp != self.reference_stamp:
            self.source_stats.clear()
        for player in (self.player, self.export_player, self.browse.player):
            if player.loaded_clip is not None:
                self.source_stats.pop(player.loaded_clip["source_path"], None)
        self.cancel_prepared_video_reveal()
        target_clip = (
            self.expected_browse_clip() if name == "Browse"
            else self.expected_editing_clip() if name == "Editing"
            else self.expected_export_clip() if name == "Export"
            else None
        )
        needs_cover = self.page_needs_cover(name, target_clip)
        if needs_cover:
            self.begin_page_transition()
        else:
            self.cancel_page_transition()
        ready_player = None
        if not needs_cover and name != self.current_panel:
            if name == "Browse" and target_clip is not None:
                ready_player = self.browse.player
            elif name == "Editing" and target_clip is not None:
                ready_player = self.player
            elif name == "Export" and target_clip is not None:
                ready_player = self.export_player
            if (
                ready_player is not None
                and ready_player.media.mediaStatus() != QMediaPlayer.MediaStatus.LoadedMedia
            ):
                ready_player = None
        if ready_player is not None:
            policy = ready_player.video.sizePolicy()
            policy.setRetainSizeWhenHidden(True)
            ready_player.video.setSizePolicy(policy)
            ready_player.video.hide()
        self.cancel_space()
        self.player.media.pause()
        self.export_player.media.pause()
        self.browse.player.media.pause()
        leaving_browse = self.current_panel == "Browse" and name != "Browse"
        if leaving_browse:
            self.browse.set_fullscreen(False)
            self.thumbnails.retain(set())
        changing_panel = name != self.current_panel
        if changing_panel:
            if self.share_watched_job is not None:
                self.share_ignored_jobs.add(id(self.share_watched_job))
            self.share_context = None
            self.share_watched_job = None
            self.share_completed = False
            self.remember_library_page(self.current_panel)
        entering_browse = name == "Browse" and self.current_panel != "Browse"
        if entering_browse:
            self.browse_id = self.browse_selected_id
            self.browse_newest = True
        # Hiding focused filters can select an item from the outgoing page's list.
        # That automatic focus change must not become a manual Browse selection.
        library_signals_blocked = self.library.blockSignals(True)
        if changing_panel and self._panel_initialized:
            self._library_prior_selected = {
                item.data(Qt.ItemDataRole.UserRole) for item in self.library.selectedItems()
            }
            self._library_prior_current = self.selected_id(self.library)
            self._library_prior_scroll = (
                self.library.horizontalScrollBar().value(),
                self.library.verticalScrollBar().value(),
            )
            self.library_items_cache[self.current_panel] = (
                self.active_library_signature,
                [self.library.takeItem(0) for _ in range(self.library.count())],
            )
        self.current_panel = name
        if name != "Editing":
            self.tip_timer.stop()
        if name == "Browse":
            self.browse_time_timer.start()
        else:
            self.browse_time_timer.stop()
        if name in {"Home", "Session"}:
            self.library_time_timer.start()
        else:
            self.library_time_timer.stop()
        self.reject_enter_armed = False
        if name != "Editing":
            self.rating.command_preview = None
            self.rating.update()
        self.center.setCurrentWidget(self.pages[name][0])
        if leaving_browse:
            # Clearing the player changes Browse's layout; do it after the page is hidden.
            self.browse.leave()
        self.update_projects_visibility()
        for destination, control in self.nav.items():
            control.setChecked(destination == name)
        self.command_area.setVisible(name == "Editing")
        self.command.setEnabled(name == "Editing")
        self.shortcut_hint.setVisible(name == "Editing")
        self.refresh_shortcut_hint()
        self.field_reminder.hide()
        self.editing_tip.setVisible(
            name == "Editing"
            and bool(self.editing_tip.message)
            and self.settings.get("editing_tips_enabled", True)
            and not self.atomic_edit
        )
        self.atomic_edit_notice.setVisible(name == "Editing" and bool(self.atomic_edit))
        self.session_header.setVisible(name == "Editing")
        self.session_heading.setText("Single clip" if self.atomic_edit else "Session clips")
        self.next_undefined_button.setVisible(not self.atomic_edit)
        self.atomic_save_button.setVisible(bool(self.atomic_edit))
        self.atomic_revert_button.setVisible(bool(self.atomic_edit))
        self.player.previous_button.setEnabled(not self.atomic_edit)
        self.player.next_button.setEnabled(not self.atomic_edit)
        self.add_project_next.setVisible(not self.atomic_edit)
        self.search.setVisible(name not in {"Browse", "Editing", "Export", "Config"})
        self.filters.setVisible(name not in {"Editing", "Export", "Config"})
        self.browse_filters.setVisible(name == "Browse")
        self.library_toolbar.setVisible(name not in {"Editing", "Export", "Config"})
        self.left_layout.setContentsMargins(
            0, 0 if name in {"Home", "Browse", "Session", "Config"} else 4,
            0 if name == "Config" else 8, 4,
        )
        self.library.setVisible(name != "Config")
        self.library_error.setVisible(name != "Config" and bool(self.library_error.text()))
        self.config_editor.sidebar_header.setVisible(name == "Config")
        self.config_editor.sidebar.setVisible(name == "Config")
        self.update_time_sort_control()
        self.library.setSelectionMode(
            QListWidget.SelectionMode.SingleSelection
            if name in {"Home", "Browse", "Editing"}
            else QListWidget.SelectionMode.ExtendedSelection
        )
        self.library.blockSignals(library_signals_blocked)
        if stamp != self.reference_stamp:
            self.refresh_references()
        else:
            self.session_counts.setVisible(
                bool(self.catalogue.state("session")) and name == "Editing" and not self.atomic_edit
            )
            if name == "Session":
                self.refresh_session_status()
        self.library_page_switch = changing_panel
        self.refresh_library()
        QTimer.singleShot(0, lambda panel=name: self.position_clip_page_once(panel))
        if name == "Editing":
            if self.atomic_edit:
                self.load_clip(self.atomic_edit.clip_id, prepared=self.take_prepared_clip("Editing", self.atomic_edit.draft[0]))
            else:
                session = self.catalogue.state("session")
                clip_id = session["ids"][session["index"]]
                self.load_clip(clip_id, prepared=self.take_prepared_clip("Editing", self.catalogue.clip(clip_id)))
            self.review_mode()
            if changing_panel:
                self.rotate_tip()
        elif name == "Export":
            self.export_selection(refresh_library=False)
        if ready_player is not None and not self.transition_pending:
            ready_player.video_container.layout_surface()
            image = ready_player.prepared_image
            if image is None:
                image = ready_player.media.frame_image()
            ready_player.video_container.show_prepared_frame(
                image
            )
            # The splitter can resize the new page on the next event pass.
            QTimer.singleShot(
                0,
                lambda panel=name, player=ready_player,
                media_generation=ready_player.media.generation,
                reveal_generation=self.prepared_reveal_generation:
                    self.show_ready_video(panel, player, media_generation, reveal_generation),
            )
        self.queue_page_reveal()
        self.schedule_preload()
        self._navigating = False
        self._panel_initialized = True

    def refresh_references(self):
        if not self._navigating:
            self.source_stats.clear()
        self.library_items_cache.clear()
        self.update_history_controls()
        self.refreshing = True
        projects = self.catalogue.projects()
        active = self.catalogue.state("active_project")
        self.add_project_next.setEnabled(bool(active))
        project_selection = self.selected_id(self.projects)
        self.projects.clear()
        self.projects.setVisible(bool(projects))
        self.projects_empty.setVisible(not projects)
        self.projects_toolbar.setVisible(bool(projects))
        for project in projects:
            item = QListWidgetItem(project["name"])
            if project["project_id"] == active:
                item.setIcon(icon("check", COLORS["accent_default"]))
            item.setToolTip(
                project["name"] + (" · Active project" if project["project_id"] == active else "")
            )
            item.setData(Qt.ItemDataRole.UserRole, project["project_id"])
            self.projects.addItem(item)
            if project["project_id"] == project_selection:
                self.projects.setCurrentItem(item)
        active_name = next(
            (project["name"] for project in projects if project["project_id"] == active), None
        )
        self.active_project_name.setText(active_name or "")
        self.active_row.setVisible(bool(active_name))
        self.project_filter.set_options(
            [(project["name"], project["project_id"]) for project in projects]
        )
        selected = self.export_project.currentData()
        self.export_project.blockSignals(True)
        self.export_project.clear()
        self.export_project.addItem("Choose project", None)
        for project in projects:
            self.export_project.addItem(project["name"], project["project_id"])
        self.export_project.setCurrentIndex(max(0, self.export_project.findData(selected)))
        self.export_project.blockSignals(False)
        self.game_filter.set_options(
            [("Uncategorized", ""), *((name, name) for name in self.registry.games)]
        )
        folder_selection = self.selected_id(self.folders)
        self.folders.clear()
        clips = {clip["clip_id"]: clip for clip in self.catalogue.clips()}
        folders = self.catalogue.folders()
        self.request_folder_sizes(folders)
        linked_clip_count = 0
        for folder in folders:
            ids = [
                row["clip_id"]
                for row in self.catalogue.rows(
                    "SELECT clip_id FROM sources WHERE folder_id=?", (folder["folder_id"],)
                )
            ]
            counts = Counter(clips[clip_id]["game"] or "Unknown" for clip_id in ids)
            new_counts = Counter(
                clips[clip_id]["game"] or "Unknown"
                for clip_id in ids
                if clip_id not in self.opening_clip_ids
            )
            folder_bytes = self.folder_sizes.get(folder["path"])
            size_text = (
                storage_gb(folder_bytes)
                if folder_bytes is not None
                else "Size unavailable" if folder["path"] in self.folder_sizes else "Calculating size…"
            )
            new_bytes = 0
            for clip_id in ids:
                if clip_id in self.opening_clip_ids:
                    continue
                stamp = self.source_stat(clips[clip_id]["source_path"])
                if stamp is not None:
                    new_bytes += stamp.st_size
            new_size_text = f" (+{storage_gb(new_bytes)} new)" if new_bytes else ""
            linked_clip_count += len(ids)
            text = f"{folder['path']}\n"
            game_details = [
                {
                    "text": f"{name}: {count}",
                    "new": new_counts[name],
                }
                for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
            ]
            games = "   ".join(
                detail["text"]
                + (f" ({detail['new']} new)" if detail["new"] else "")
                for detail in game_details
            )
            text += f"{'Enabled' if folder['enabled'] else 'Paused'} · {len(ids)} clips · {size_text}{new_size_text}\n"
            text += games or "No detected games"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, folder["folder_id"])
            item.setData(
                FOLDER_ROLE,
                {
                    "path": folder["path"],
                    "status": "Enabled" if folder["enabled"] else "Paused",
                    "enabled": bool(folder["enabled"]),
                    "summary": f"{len(ids)} clips · {size_text}",
                    "summary_new": new_size_text,
                    "details": games or "No detected games",
                    "game_details": game_details,
                },
            )
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
            item.setData(
                FOLDER_ROLE,
                {
                    "path": "Unlinked catalogue clips",
                    "summary": f"{len(unlinked)} clips from removed folders",
                    "details": "Select More → Remove saved entries… to review",
                },
            )
            item.setToolTip(
                "\n".join(sorted({str(Path(clip["source_path"]).parent) for clip in unlinked}))
            )
            self.folders.addItem(item)
            if folder_selection == "__unlinked__":
                self.folders.setCurrentItem(item)
        if self.folders.count() == 1 and self.folders.currentRow() < 0:
            self.folders.setCurrentRow(0)
        folder_word = "folder" if len(folders) == 1 else "folders"
        clip_word = "clip" if linked_clip_count == 1 else "clips"
        self.folder_summary.setText(
            f"{len(folders)} {folder_word} · {linked_clip_count} {clip_word}"
        )
        self.refresh_library_overview(list(clips.values()))
        self.refresh_session_status(clips)
        self.refreshing = False
        self.reference_stamp = self.catalogue_stamp()
        self.schedule_preload()

    def request_folder_sizes(self, folders=None, *, force=False):
        folders = folders if folders is not None else self.catalogue.folders()
        paths = tuple(folder["path"] for folder in folders)
        if self.folder_size_worker is not None:
            self.folder_size_pending |= force or paths != self.folder_size_paths
            return
        if not paths or self.close_requested:
            return
        if not force and paths == self.folder_size_paths and time.monotonic() - self.folder_size_updated_at < 30:
            return
        self.folder_size_paths = paths
        self.folder_size_worker = Worker(
            lambda cancelled, progress: folder_storage(paths, cancelled)
        )
        results = []
        self.folder_size_worker.succeeded.connect(results.append)

        def finished():
            self.folder_size_worker.deleteLater()
            self.folder_size_worker = None
            if self.close_requested:
                QTimer.singleShot(0, self.close)
                return
            if results:
                self.folder_sizes = results[0]
                self.folder_size_updated_at = time.monotonic()
                self.refresh_references()
            if self.folder_size_pending:
                self.folder_size_pending = False
                self.request_folder_sizes(force=True)

        self.folder_size_worker.finished.connect(finished)
        self.folder_size_worker.start()

    def refresh_session_status(self, clips=None):
        if clips is None:
            clips = {clip["clip_id"]: clip for clip in self.catalogue.clips()}
        session = self.catalogue.state("session")
        self.nav["Editing"].setEnabled(bool(session))
        self.session_setup_heading.setText("Active session" if session else "No active session")
        self.session_setup_states.setCurrentIndex(0 if session else 1)
        self.session_counts.setVisible(
            bool(session) and self.current_panel == "Editing" and not self.atomic_edit
        )
        if self.atomic_edit:
            self.session_position.clear()
            return
        if session:
            states = []
            decided = []
            for clip_id in session["ids"]:
                clip = clips[clip_id]
                verdict = clip["triage"] or "pending"
                states.append(
                    verdict if self.source_available(clip["source_path"]) else "unavailable"
                )
                decided.append(clip["triage"] is not None)
            counts = Counter(states)
            total = len(session["ids"])
            self.session_position.setText(f"{session['index'] + 1} / {total}")
            processed = sum(decided)
            rejected = sum(clips[clip_id]["triage"] == "discard" for clip_id in session["ids"])
            self.session_counts.setText(
                f"{processed}/{total} ({rejected} rejected)"
            )
            last_processed = max((index + 1 for index, value in enumerate(decided) if value), default=0)
            self.session_progress.set_states(states, processed, last_processed)
            self.session_verdicts.setText(
                f"{counts['keep']} Keep · {counts['discard']} Discard · "
                f"{counts['pending']} Pending"
                + (
                    f' · <span style="color: {COLORS["status_warning"]}">'
                    f'{counts["unavailable"]} Unavailable</span>'
                    if counts["unavailable"] else ""
                )
            )
        else:
            self.session_position.clear()
            self.session_counts.clear()
            self.session_progress.set_states((), 0, 0)
            self.session_verdicts.clear()

    def set_overview_period(self, period):
        self.overview_period = period
        for label, control in self.overview_period_buttons.items():
            control.setChecked(label == period)
        self.refresh_library_overview()

    def refresh_library_overview(self, clips=None):
        clips = clips if clips is not None else self.catalogue.clips()
        total, rows, undated, unavailable, sizes = library_overview(
            clips, self.media_info, self.overview_period, stat_for=self.source_stat
        )
        while self.overview_rows.count():
            item = self.overview_rows.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()
        self.add_overview_row("All games", total, sum(sizes.values()), emphasized=True)
        aggregate_total = sum(total.values())
        for game, counts in rows:
            self.add_overview_row(game, counts, sizes[game], reference_total=aggregate_total)
        self.overview_empty.setVisible(not sum(total.values()))
        finite = PERIOD_DAYS[self.overview_period] is not None
        exclusions = []
        if unavailable:
            noun = "file is" if unavailable == 1 else "files are"
            exclusions.append(f"{unavailable} clip {noun} missing or unreachable (excluded)")
        if undated:
            noun = "file lacks" if undated == 1 else "files lack"
            treatment = "excluded from this period" if finite else "included in All time"
            exclusions.append(
                f"{undated} available clip {noun} a usable capture date ({treatment})"
            )
        self.overview_undated.setVisible(bool(exclusions))
        self.overview_undated.setText("; ".join(exclusions) + ".")

    def add_overview_row(self, name, counts, size, *, emphasized=False, reference_total=None):
        keep = counts["keep"]
        discard = counts["discard"]
        pending = counts["pending"]
        total = keep + discard + pending
        processed = keep + discard
        percentage = processed / total if total else 0
        row = QWidget()
        row.setObjectName("overviewSummary" if emphasized else "overviewGame")
        layout = QVBoxLayout(row)
        layout.setContentsMargins(0, 4 if emphasized else 0, 0, 4 if emphasized else 0)
        layout.setSpacing(4)
        heading = QHBoxLayout()
        label = QLabel(name)
        label.setFont(
            font("base" if emphasized else "md", "semibold" if emphasized else "medium")
        )
        heading.addWidget(label)
        heading.addStretch()
        progress = QLabel(f"{total} clips · {processed} processed ({percentage:.0%})")
        role(progress, "secondary")
        heading.addWidget(progress)
        layout.addLayout(heading)
        bar = VerdictBar()
        if not emphasized:
            bar.setFixedHeight(12)
            bar.set_reference_total(reference_total)
        bar.set_counts(keep, discard, pending)
        layout.addWidget(bar)
        details = QHBoxLayout()
        verdicts = QLabel(f"{keep} Keep · {discard} Discard · {pending} Pending")
        role(verdicts, "muted")
        details.addWidget(verdicts)
        details.addStretch()
        storage = QLabel(storage_gb(size))
        role(storage, "muted")
        details.addWidget(storage)
        layout.addLayout(details)
        self.overview_rows.addWidget(row)

    def render_card(self, item, clip):
        previous = item.data(CLIP_ROLE) or {}
        compact_card = self.current_panel in {"Home", "Session", "Editing"}
        available = "" if self.source_available(clip["source_path"]) else " [unavailable]"
        card_title = tag_prefix(clip) + title(
            {**clip, "mainline": (clip.get("mainline") or "").strip()},
            self.registry,
            lowercase=self.settings.get("lowercase_generated_titles", True),
            mainline_separator=" | ",
        )
        browse_details = None
        compact_time = None
        captured = None
        if self.current_panel == "Browse":
            captured = self.capture_datetime(clip)
            capture_label = relative_capture_time(captured)
            folder_name = self.clip_folder_names.get(clip["clip_id"], "Unlinked")
            browse_details = f"{capture_label} · {folder_name}"
        elif self.current_panel in {"Home", "Session"}:
            captured = self.capture_datetime(clip)
            compact_time = compact_capture_time(captured)
        rating = f" · R{clip['rating']}" if clip["rating"] is not None else ""
        folder_name = self.clip_folder_names.get(clip["clip_id"], "Unlinked")
        details = browse_details or (
            f"{clip['game'] or 'Unassigned'}{rating} · {folder_name}"
        )
        item.setText(f"{card_title}\n{details}{available}")
        tooltip = item.text()
        if self.current_panel in {"Browse", "Home", "Session"} and captured is not None:
            tooltip += "\nCaptured: " + captured.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        item.setToolTip(tooltip + "\n" + clip["source_path"])
        item.setData(Qt.ItemDataRole.UserRole, clip["clip_id"])
        item.setData(
            CLIP_ROLE,
            {
                "title": card_title,
                "rich_title": tag_prefix(
                    clip,
                    rich=True,
                    size_role="md" if self.current_panel == "Browse" or compact_card else "base",
                )
                + title(
                    {**clip, "mainline": (clip.get("mainline") or "").strip()},
                    self.registry,
                    rich=True,
                    lowercase=self.settings.get("lowercase_generated_titles", True),
                    rich_styles=title_styles(
                        card=True,
                        library=self.current_panel == "Export",
                        compact_card=compact_card,
                    ),
                    mainline_separator=" | ",
                    underline_first_mainline_word=(clip.get("tag") or "").strip().casefold()
                    == "3rd",
                ),
                "browse_details": browse_details,
                "compact_time": compact_time,
                "compact_card": compact_card,
                "game": clip["game"],
                "rating": clip["rating"],
                "folder": folder_name,
                "triage": clip["triage"],
                "unavailable": bool(available),
                "thumbnail": previous.get("thumbnail") if self.current_panel == "Browse" else None,
                "thumbnail_key": previous.get("thumbnail_key") if self.current_panel == "Browse" else None,
            },
        )

    def schedule_thumbnails(self, *_args):
        if self.current_panel == "Browse" and hasattr(self, "thumbnail_timer"):
            self.thumbnail_timer.start(30)

    def request_visible_thumbnails(self):
        if self.current_panel != "Browse" or not self.library.count():
            self.thumbnails.retain(set())
            return
        viewport = self.library.viewport()
        top = self.library.indexAt(QPoint(4, 0)).row()
        bottom = self.library.indexAt(QPoint(4, max(0, viewport.height() - 1))).row()
        top = max(0, top)
        bottom = self.library.count() - 1 if bottom < 0 else bottom
        screen = max(1, bottom - top + 1)
        clips = {clip["clip_id"]: clip for clip in self.catalogue.clips()}
        needed = set()
        for row in range(max(0, top - screen), min(self.library.count(), bottom + screen + 1)):
            item = self.library.item(row)
            clip = clips.get(item.data(Qt.ItemDataRole.UserRole))
            if clip is None:
                continue
            media = self.media_info.get(clip["source_path"])
            duration = media["duration"] if media is not None and "duration" in media.keys() else None
            request_clip = {**clip, "duration": duration}
            key, image = self.thumbnails.request(request_clip)
            if key is not None:
                needed.add(key)
            data = item.data(CLIP_ROLE) or {}
            if data.get("thumbnail_key") != key or data.get("thumbnail") is not image:
                data["thumbnail_key"] = key
                data["thumbnail"] = image
                item.setData(CLIP_ROLE, data)
        self.thumbnails.retain(needed)

    def thumbnail_ready(self, clip_id, key, image):
        if self.current_panel != "Browse" or image is None:
            return
        clip = self.catalogue.clip(clip_id)
        if clip is None or self.thumbnails.signature(clip) != key:
            return
        for row in range(self.library.count()):
            item = self.library.item(row)
            if item.data(Qt.ItemDataRole.UserRole) != clip_id:
                continue
            data = item.data(CLIP_ROLE) or {}
            if data.get("thumbnail_key") == key:
                data["thumbnail"] = image
                item.setData(CLIP_ROLE, data)
            break

    def refresh_browse_times(self):
        if self.current_panel != "Browse":
            return
        clips = {clip["clip_id"]: clip for clip in self.catalogue.clips()}
        for index in range(self.library.count()):
            item = self.library.item(index)
            clip = clips.get(item.data(Qt.ItemDataRole.UserRole))
            if clip is not None:
                self.render_card(item, clip)

    def refresh_library_times(self):
        if self.current_panel not in {"Home", "Session"}:
            return
        clips = {clip["clip_id"]: clip for clip in self.catalogue.clips()}
        for index in range(self.library.count()):
            item = self.library.item(index)
            clip = clips.get(item.data(Qt.ItemDataRole.UserRole))
            if clip is not None:
                self.render_card(item, clip)

    def browse_sort_key(self, clip):
        captured = self.capture_datetime(clip)
        return captured.isoformat() if captured else "", clip["source_path"]

    def filtered_clips(self, clips, panel):
        if panel == "Browse":
            hidden = self.catalogue.hidden_deleted_ids()
            clips = [clip for clip in clips if clip["clip_id"] not in hidden]
            clips = query_clips(clips, self.browse_search.text(), self.registry)
        else:
            clips = query_clips(clips, self.search.text(), self.registry)
            if panel == "Session":
                excluded = self.catalogue.session_excluded_ids()
                clips = [clip for clip in clips if clip["clip_id"] not in excluded]
        if not self.settings.get("show_unavailable_clips", False):
            clips = [clip for clip in clips if self.source_available(clip["source_path"])]
        triage = self.clip_filter.selected_values()
        clips = [clip for clip in clips if clip["triage"] in triage]
        games = self.game_filter.selected_values()
        clips = [clip for clip in clips if (clip["game"] or "") in games]
        if not self.project_filter.all_selected():
            project_ids = set()
            for project_id in self.project_filter.selected_values():
                project_ids.update(self.catalogue.member_ids(project_id))
            clips = [clip for clip in clips if clip["clip_id"] in project_ids]
        clips.sort(
            key=self.browse_sort_key,
            reverse=self.browse_newest if panel == "Browse" else self.library_newest,
        )
        return clips

    def expected_browse_clip(self):
        clips = self.filtered_clips(self.catalogue.clips(), "Browse")
        if not clips:
            return None
        candidate = self.browse_id if self.current_panel == "Browse" else self.browse_selected_id
        return next((clip for clip in clips if clip["clip_id"] == candidate), clips[0])

    def expected_editing_clip(self):
        if self.atomic_edit:
            return self.atomic_edit.draft[0]
        session = self.catalogue.state("session")
        if not session:
            return None
        return self.catalogue.clip(session["ids"][session["index"]])

    def expected_export_clip(self):
        ids = self.catalogue.member_ids(self.export_project.currentData())
        if not ids:
            return None
        selected = (
            self.selected_id(self.library) if self.current_panel == "Export"
            else self.library_page_states.get("Export", {}).get("current")
        )
        clip_id = selected if selected in ids else next(
            clip["clip_id"] for clip in self.catalogue.clips() if clip["clip_id"] in ids
        )
        return self.catalogue.clip(clip_id)

    def clip_load_key(self, clip, pane="Editing"):
        if clip is None:
            return None
        source = Path(clip["source_path"])
        try:
            stamp = self.source_stat(str(source))
            if stamp is None:
                raise OSError
            identity = (stamp.st_size, stamp.st_mtime_ns)
        except OSError:
            identity = None
        return (
            clip["clip_id"], clip["source_path"], identity,
            clip["in_ms"], clip["out_ms"],
            playback_start_settings(self.settings, pane),
        )

    def schedule_preload(self):
        if not self.close_requested and hasattr(self, "preload_timer"):
            self.preload_timer.start()

    def prepare_inactive_clips(self):
        if self.close_requested:
            return
        for player in (self.player, self.browse.player, self.export_player):
            if player.loaded_clip is not None:
                self.source_stats.pop(player.loaded_clip["source_path"], None)
        for panel, player, clip in (
            ("Browse", self.browse.player, self.expected_browse_clip()),
            ("Editing", self.player, self.expected_editing_clip()),
            ("Export", self.export_player, self.expected_export_clip()),
        ):
            if self.current_panel == panel:
                continue
            key = self.clip_load_key(clip, panel)
            if panel in self.prepared_clips and self.prepared_clips[panel] == key:
                continue
            self.prepared_clips[panel] = key
            if clip is not None and self.player_has_clip(player, clip):
                continue
            if clip is not None or player.loaded_clip is not None:
                player.load(clip)

    def take_prepared_clip(self, panel, clip):
        key = self.prepared_clips.pop(panel, None)
        return key is not None and key == self.clip_load_key(clip, panel)

    def update_time_sort_control(self):
        newest = self.browse_newest if self.current_panel == "Browse" else self.library_newest
        current, other = ("Newest", "oldest") if newest else ("Oldest", "newest")
        label = f"{current} first · Switch to {other} first"
        self.time_sort.setToolTip(label)
        self.time_sort.setAccessibleName(label)

    def toggle_time_sort(self):
        if self.current_panel == "Browse":
            self.browse_newest = not self.browse_newest
        else:
            self.library_newest = not self.library_newest
        self.update_time_sort_control()
        self.refresh_library(reset_selection=True)

    def toggle_browse_sort(self):
        self.toggle_time_sort()

    def toggle_unavailable(self, checked):
        self.settings["show_unavailable_clips"] = checked
        set_icon(self.unavailable_toggle, "eye" if checked else "eye-off")
        label = (
            "Unavailable clips shown · Hide unavailable clips"
            if checked
            else "Unavailable clips hidden · Show unavailable clips"
        )
        self.unavailable_toggle.setToolTip(label)
        self.unavailable_toggle.setAccessibleName(label)
        self.save_settings()
        self.refresh_library(reset_selection=True)

    def update_browse_navigation(self):
        row = self.library.currentRow()
        self.browse.player.previous_button.setEnabled(row > 0)
        self.browse.player.next_button.setEnabled(0 <= row < self.library.count() - 1)

    def remember_library_page(self, panel=None):
        panel = panel or self.current_panel
        self.library_page_states[panel] = {
            "current": self.selected_id(self.library),
            "selected": {
                item.data(Qt.ItemDataRole.UserRole) for item in self.library.selectedItems()
            },
            "scroll": (
                self.library.horizontalScrollBar().value(),
                self.library.verticalScrollBar().value(),
            ),
        }

    def position_selected_clip(self):
        row = self.library.currentRow()
        if row < 0:
            return
        self.library.doItemsLayout()
        scrollbar = self.library.verticalScrollBar()
        offset = scrollbar.value()
        anchor = self.library.item(max(0, row - 1))
        anchor_rect = self.library.visualItemRect(anchor)
        target = anchor_rect.top() + offset
        if row > 0:
            target += round(anchor_rect.height() * 2 / 3)
        last = self.library.visualItemRect(self.library.item(self.library.count() - 1))
        content_bottom = last.bottom() + offset + 1
        natural_maximum = max(0, content_bottom - self.library.viewport().height())
        scrollbar.setMaximum(max(natural_maximum, target))
        scrollbar.setValue(target)

    def position_clip_page_once(self, panel):
        if panel != self.current_panel or panel in self.positioned_clip_pages:
            return
        self.positioned_clip_pages.add(panel)
        if self.library.currentRow() >= 0:
            self.position_selected_clip()

    def update_library_scroll_fades(self, *_args):
        viewport = self.library.viewport()
        fade_height = 16
        self.library_top_fade.setGeometry(0, 0, viewport.width(), fade_height)
        self.library_bottom_fade.setGeometry(
            0, max(0, viewport.height() - fade_height), viewport.width(), fade_height
        )
        first = self.library.item(0)
        last = self.library.item(self.library.count() - 1)
        self.library_top_fade.setVisible(
            first is not None and self.library.visualItemRect(first).top() < 0
        )
        self.library_bottom_fade.setVisible(
            last is not None
            and self.library.visualItemRect(last).bottom() > viewport.rect().bottom()
        )
        self.library_top_fade.raise_()
        self.library_bottom_fade.raise_()

    def refresh_library_from_controls(self, *_args):
        self.refresh_library(reset_selection=True)

    def refresh_library(self, *, reset_selection=False):
        if not self._navigating:
            self.source_stats.clear()
            self.library_items_cache.clear()
        self.update_history_controls()
        if getattr(self, "settings_dialog", None) is not None:
            self.settings_dialog.refresh()
        if self.refreshing:
            return
        if self.current_panel == "Config":
            self.library_page_switch = False
            return
        try:
            self.clip_folder_names = self.catalogue.clip_folder_names()
            clips = self.catalogue.clips()
            if self.current_panel == "Editing":
                if self.atomic_edit:
                    clips = [self.atomic_edit.draft[0]]
                else:
                    session = self.catalogue.state("session")
                    mapping = {clip["clip_id"]: clip for clip in clips}
                    clips = [mapping[clip_id] for clip_id in session["ids"]] if session else []
            elif self.current_panel == "Export":
                ids = self.catalogue.member_ids(self.export_project.currentData())
                clips = [clip for clip in clips if clip["clip_id"] in ids]
            else:
                clips = self.filtered_clips(clips, self.current_panel)
            signature = tuple(
                (
                    clip["clip_id"], clip["catalogue_modified_at"],
                    clip["source_path"],
                    (stamp.st_size, stamp.st_mtime_ns) if (
                        stamp := self.source_stat(clip["source_path"])
                    ) else None,
                    self.media_info.get(clip["source_path"], {}).get("created"),
                )
                for clip in clips
            )
            cached = self.library_items_cache.pop(self.current_panel, None)
            reusable_items = cached[1] if cached and cached[0] == signature else None
            page_state = (
                self.library_page_states.get(self.current_panel)
                if self.library_page_switch
                else None
            )
            selected = (
                set(page_state["selected"])
                if page_state
                else getattr(self, "_library_prior_selected", set()) if self.library_page_switch
                else {
                    item.data(Qt.ItemDataRole.UserRole)
                    for item in self.library.selectedItems()
                }
            )
            current = (
                page_state["current"] if page_state
                else getattr(self, "_library_prior_current", None) if self.library_page_switch
                else self.selected_id(self.library)
            )
            if reset_selection and self.current_panel in {"Home", "Browse", "Session"}:
                current = clips[0]["clip_id"] if clips else None
                selected = {current} if current else set()
                if self.current_panel == "Browse":
                    self.browse_selected_id = current
            elif self.current_panel == "Browse":
                current = self.browse_id
                if current not in {clip["clip_id"] for clip in clips}:
                    current = clips[0]["clip_id"] if clips else None
                selected = {current}
            if self.current_panel == "Editing" and self.atomic_edit:
                current = self.atomic_edit.clip_id
            elif self.current_panel == "Editing" and self.catalogue.state("session"):
                session = self.catalogue.state("session")
                current = session["ids"][session["index"]]
            horizontal_scroll = (
                page_state["scroll"][0]
                if page_state
                else self._library_prior_scroll[0] if self.library_page_switch
                else self.library.horizontalScrollBar().value()
            )
            scroll = (
                page_state["scroll"][1]
                if page_state
                else self._library_prior_scroll[1] if self.library_page_switch
                else self.library.verticalScrollBar().value()
            )
            if reset_selection:
                horizontal_scroll = scroll = 0
            anchor = self.library.itemAt(1, 1)
            anchor_id = anchor.data(Qt.ItemDataRole.UserRole) if anchor else None
            anchor_offset = self.library.visualItemRect(anchor).top() if anchor else 0
            self.library.blockSignals(True)
            self.library.clear()
            for index, clip in enumerate(clips):
                item = reusable_items[index] if reusable_items is not None else QListWidgetItem()
                if reusable_items is None:
                    self.render_card(item, clip)
                self.library.addItem(item)
                if clip["clip_id"] == current:
                    self.library.setCurrentItem(item)
                item.setSelected(clip["clip_id"] in selected or clip["clip_id"] == current)
            self.library.doItemsLayout()
            if not page_state and not reset_selection:
                for index in range(self.library.count()):
                    item = self.library.item(index)
                    if item.data(Qt.ItemDataRole.UserRole) == anchor_id:
                        scroll = (
                            self.library.verticalScrollBar().value()
                            + self.library.visualItemRect(item).top()
                            - anchor_offset
                        )
                        break
            self.library.horizontalScrollBar().setValue(horizontal_scroll)
            self.library.verticalScrollBar().setValue(scroll)
            self.schedule_thumbnails()
            self.library.blockSignals(False)
            self.library_page_switch = False
            self.active_library_signature = signature
            if self.current_panel == "Browse":
                self.browse_id = current
                clip = self.catalogue.clip(current) if current else None
                self.browse.load(clip, prepared=self.take_prepared_clip("Browse", clip))
                self.update_browse_navigation()
                self.schedule_thumbnails()
            self.library_error.clear()
            self.library_error.hide()
        except ValueError as error:
            self.library_error.setText(str(error))
            self.library_error.show()
        self.schedule_preload()

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

    def switch_editing_clip(self, clip_id):
        if self.atomic_edit:
            return
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
        self.refresh_session_status()
        self.begin_page_transition("clip")
        self.load_clip(clip_id)

    def load_clip(self, clip_id, *, prepared=False):
        if not self.ensure_range_complete():
            return
        self.command_submitted_error = False
        self.command_submitted_navigation = False
        self.command_saved_timer.stop()
        self.submit_resume = False
        self.cancel_space()
        self.current_id = clip_id
        self.update_share_controls()
        self.reject_enter_armed = False
        self.pending_in = None
        self.pending_out = None
        self.command.setText("" if self.atomic_edit else self.drafts.get(clip_id, ""))
        self.command_error.clear()
        self.command_error.hide()
        self.render_clip()
        if not prepared:
            self.player.load(self.effective_clip())
        self.review_mode()

    def refresh_title_presentation(self):
        self.browse.render_title()
        for index in range(self.library.count()):
            item = self.library.item(index)
            clip = (
                self.atomic_edit.draft[0]
                if self.atomic_edit and item.data(Qt.ItemDataRole.UserRole) == self.atomic_edit.clip_id
                else self.catalogue.clip(item.data(Qt.ItemDataRole.UserRole))
            )
            if clip:
                self.render_card(item, clip)
        if self.current_id:
            self.render_working_title(self.effective_clip())

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
                underline_first_mainline_word=(clip.get("tag") or "").strip().casefold() == "3rd",
            )
        else:
            fallback = html.escape(source_fallback(clip, game, include_suffix=True))
            if game:
                fallback = (
                    f'<span style="{title_styles()["prefix"]}">'
                    f"{html.escape(game.code + '_')}</span>{fallback}"
                )
            rendered = fallback
            rendered += (
                f' <span style="color:{COLORS["text_secondary"]}; font-size:12px; font-weight:400">'
                "— Working title not set</span>"
            )
        rendered = f'<span style="color:{COLORS["text_secondary"]}">{rendered}</span>'
        self.working_title.setText(tag_prefix(clip, rich=True) + rendered)

    def render_clip(self):
        self.update_history_controls()
        if not self.current_id:
            return
        clip = self.effective_clip()
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
        member_ids = self.effective_memberships()
        names = [
            project["name"]
            for project in self.catalogue.projects()
            if project["project_id"] in member_ids
        ]
        self.clip_status.setText(
            f"{clip['triage'] or 'Pending'} | {clip['game'] or 'No game'} | Projects: {', '.join(names) or 'None'}"
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
        self.render_command_history()
        self.refresh_session_status()
        self.atomic_save_button.setEnabled(self.can_save_atomic())
        self.update_command_state()

    def render_command_history(self):
        command_history = self.atomic_edit.history if self.atomic_edit else self.history[self.current_id]
        history_lines = []
        for entry in command_history[-3:]:
            if isinstance(entry, tuple):
                command_text, inferred = entry
                details = ", ".join(
                    f"{key.replace('_', ' ').title()} = "
                    + (", ".join(map(str, value)) if isinstance(value, list) else str(value))
                    for key, value in inferred
                )
                history_lines.append(
                    f"{html.escape(command_text)} "
                    f'<span style="font-size:11px; color:{COLORS["text_muted"]}">'
                    f"(Inferred: {html.escape(details)})</span>"
                )
            else:
                history_lines.append(html.escape(entry))
        self.command_history.setText("<br>".join(history_lines))
        self.command_history.setVisible(bool(self.command_history.text()))

    def field_reminder_hovered(self, link):
        self.field_reminder_hover = link.removeprefix("field:") if link.startswith("field:") else None
        self.field_reminder.setToolTip(
            self.field_reminder_tooltips.get(
                self.field_reminder_hover, self.field_reminder_default_tooltip
            )
        )

    @staticmethod
    def field_options_tooltip(game, key, state):
        label = html.escape(key.replace("_", " ").title())
        definition = game.fields.get(key, {})
        if definition.get("type") == "enum":
            values = definition["values"]
            aliases = defaultdict(list)
            for alias, canonical in definition.get("aliases", {}).items():
                aliases[canonical].append(alias)
            options = [
                html.escape(str(value))
                + (
                    " (" + ", ".join(
                        f"<i>{html.escape(alias)}</i>" for alias in aliases[value]
                    ) + ")"
                    if aliases[value]
                    else ""
                )
                for value in values
            ]
            columns = 4 if len(options) > 36 else 3 if len(options) > 20 else 2 if len(options) > 10 else 1
            if max(map(len, options)) > 28:
                columns = min(columns, 2)
            rows = (len(options) + columns - 1) // columns
            cells = [
                "<tr>" + "".join(
                    f'<td style="padding-right:12px; white-space:nowrap">{options[row + col * rows]}</td>'
                    if row + col * rows < len(options) else "<td></td>"
                    for col in range(columns)
                ) + "</tr>"
                for row in range(rows)
            ]
            details = f"Valid options ({len(values)}):<br><table>{''.join(cells)}</table>"
            if definition.get("multiple"):
                details += "<br>Multiple values can be entered in order."
        elif definition.get("type") == "freeform":
            prefixes = [key, *definition.get("prefixes", [])]
            details = "Free text. Use " + " or ".join(
                f"{html.escape(prefix)}:text" for prefix in prefixes
            ) + "."
            if definition.get("multiple"):
                details += " Repeat the prefix for multiple values."
        elif key == "kill":
            details = "Enter 0K, 1K, 2K, and so on."
        elif key == "clutch":
            details = "Enter 1v1, 1v2, 1v3, and so on."
        elif key == "rating":
            details = "Valid options: R1, R2, R3, R4, R5."
        elif key == "tag":
            details = 'Enter [TAG], tag:TAG, or tag:"text with spaces".'
        elif key == "mainline":
            details = "Enter text after the first -- separator."
        else:
            details = "Enter a value in the metadata command."
        return f"{html.escape(state)}<br><br><b>{label}</b><br>{details}"

    def render_field_reminder(self, clip, game):
        self.update_range_warning()
        self.field_reminder.setVisible(self.current_panel == "Editing" and game is not None)
        if game is None:
            self.field_reminder.clear()
            self.field_reminder_hover = None
            self.field_reminder_tooltips = {}
            self.field_reminder_default_tooltip = ""
            self.field_reminder.setToolTip("")
            return
        state = "Saved metadata."
        inferred_fields = set()
        if self.command.text().strip():
            result, validation, _ = preview_command_details(
                self.command.text(),
                clip["game"],
                self.registry,
                existing_metadata=clip["metadata"],
            )
            patch = result.patch
            inferred_fields = {key for key, _value in result.inferred}
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
        self.field_reminder_default_tooltip = (
            state
            + " ✓ populated · ◇ inferred · ! suggested · o optional · x invalid for current configuration."
        )
        fields = list(
            dict.fromkeys([*game.display_order, *game.fields, "mainline", "rating", "tag"])
        )
        entries = []
        self.field_reminder_tooltips = {
            key: self.field_options_tooltip(game, key, state) for key in fields
        }
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
                mark, color = "x", "status_danger"
            elif key in inferred_fields:
                mark, color = (
                    symbol_text("◇", self.editing_bottom_size()),
                    "accent_default",
                )
            elif not missing:
                mark, color = symbol_text("✓"), "status_success"
            elif key in game.suggested_fields:
                mark, color = "!", "status_warning"
            else:
                mark, color = "o", "text_muted"
            entries.append(
                f'<a href="field:{key}" style="color:{COLORS[color]}; text-decoration:none">'
                f"{mark}&nbsp;{html.escape(key)}</a>"
            )
        self.field_reminder.setText(
            f'<span style="font-size:{self.editing_bottom_size()}px">'
            + " &nbsp; ".join(entries) + "</span>"
        )
        self.field_reminder.setToolTip(
            self.field_reminder_tooltips.get(
                self.field_reminder_hover, self.field_reminder_default_tooltip
            )
        )

    @editing_action
    def edit(self, patch, **kwargs):
        if self.current_panel == "Browse":
            return
        if self.current_panel != "Editing" or not self.current_id:
            return
        try:
            if self.atomic_edit:
                self.atomic_edit.draft = self.catalogue.draft_snapshot(
                    self.atomic_edit.draft, patch, editing=True,
                    active_project=self.catalogue.state("active_project"), **kwargs
                )
            else:
                self.catalogue.patch(self.current_id, patch, editing=True, **kwargs)
            self.render_clip()
        except (ValueError, OSError) as error:
            self.error(error)

    @editing_action
    def submit(self):
        if self.current_panel == "Browse":
            return
        if self.current_panel != "Editing" or not self.current_id:
            return
        text = self.command.text()
        try:
            clip = self.effective_clip()
            result = parse_command_details(
                text, clip["game"], self.registry, existing_metadata=clip["metadata"]
            )
            patch = result.patch
            if self.atomic_edit:
                self.atomic_edit.draft = self.catalogue.draft_snapshot(
                    self.atomic_edit.draft, patch, editing=True,
                    active_project=self.catalogue.state("active_project")
                )
            else:
                self.catalogue.patch(self.current_id, patch, editing=True)
            if text.strip():
                history = self.atomic_edit.history if self.atomic_edit else self.history[self.current_id]
                history.append((text, result.inferred) if result.inferred else text)
                del history[:-3]
            self.command.clear()
            self.command_submitted_navigation = bool(text.strip())
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
            self.command_submitted_navigation = False
            self.command_submitted_error = True
            self.update_command_state()
            self.error(error)

    @editing_action
    def add_to_project_next(self):
        if self.atomic_edit:
            return
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

    @editing_action
    def advance_review(self):
        if self.atomic_edit:
            self.save_atomic_edit()
            return
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
            if not has_review_metadata(clip, game):
                self.error("Cannot Keep + Next: add at least one metadata field or mainline")
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
                self.switch_editing_clip(next_id)
            else:
                self.render_clip()
                self.refresh_session_status(clips)
                item = self.library.currentItem()
                if item is not None:
                    self.render_card(item, clips[self.current_id])
                unfinished = any(clips[clip_id]["triage"] is None for clip_id in session["ids"])
                message = (
                    "No pending clips ahead — earlier Session clips remain pending."
                    if unfinished
                    else "Session complete — no pending clips remain."
                )
                self.statusBar().showMessage(message, 12000)
            self.review_mode()
        except (ValueError, OSError) as error:
            self.error(error)

    def navigate_next_undefined(self):
        if self.atomic_edit:
            return
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
            self.switch_editing_clip(next_id)
        else:
            self.statusBar().showMessage("No pending clips ahead in this session.", 12000)

    def navigate(self, offset):
        if self.atomic_edit:
            return
        if self.current_panel == "Browse":
            index = self.library.currentRow() + offset
            if 0 <= index < self.library.count():
                self.library.setCurrentRow(index)
            return
        session = self.catalogue.state("session")
        if not session:
            return
        index = max(0, min(len(session["ids"]) - 1, session["index"] + offset))
        self.switch_editing_clip(session["ids"][index])

    def active_player(self):
        if self.current_panel == "Browse":
            return self.browse.player
        return self.export_player if self.current_panel == "Export" else self.player

    def remember_draft(self, text):
        self.restored_command = None
        self.command_submitted_error = False
        self.command_submitted_navigation = False
        self.command_saved_timer.stop()
        self.command_error.clear()
        self.command_error.hide()
        if text:
            self.submit_resume = False
        if self.current_id:
            if not self.atomic_edit:
                self.drafts[self.current_id] = text
            clip = self.effective_clip()
            self.render_field_reminder(clip, self.registry.game(clip["game"]))
        self.update_command_state()
        if self.atomic_edit:
            self.atomic_save_button.setEnabled(self.can_save_atomic())

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
        if hasattr(self, "config_editor"):
            self.config_editor.break_history_group()
        if old is self.command and new is not self.command:
            self.submit_resume = False
            self.command_submitted_navigation = False
        self.update_command_state()

    def command_playback_changed(self, state):
        self.submit_resume = False
        self.update_command_state()

    def update_command_state(self):
        clip = self.effective_clip() if self.current_id else None
        self.command.set_ghost_context(
            self.settings.get("ghost_autocomplete_enabled", True),
            self.registry.game(clip["game"]) if clip else None,
        )
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
        validation, message, patch = "empty", "", {}
        if self.current_id:
            clip = self.effective_clip()
            result, validation, message = preview_command_details(
                self.command.text(),
                clip["game"],
                self.registry,
                submitted=self.command_submitted_error,
                existing_metadata=clip["metadata"],
            )
            patch = result.patch
        rating = (
            patch.get("rating")
            if validation == "valid" and self.current_panel == "Editing"
            else None
        )
        if self.rating.command_preview != rating:
            self.rating.command_preview = rating
            self.rating.update()
        self.rating_clear.setEnabled(rating is None)
        self.rating_clear.setIcon(icon("x" if rating is None else "clock"))
        self.rating_clear.setToolTip(
            "Clear rating" if rating is None else "Rating pending · press Enter"
        )
        self.rating_clear.setAccessibleName("Clear rating" if rating is None else "Rating pending")
        feedback = html.escape(message)
        if validation == "valid" and patch.get("tag"):
            candidate = patch["tag"]
            known = self.catalogue.tag_exists(candidate)
            label = "Known tag" if known else "New tag"
            label_color = COLORS["text_secondary" if known else "accent_default"]
            feedback = (
                f'<span style="color:{COLORS["text_primary"]}; font-weight:600">'
                f'[{html.escape(candidate)}]</span> '
                f'<span style="color:{label_color}">{label}</span>'
            )
        if validation == "empty":
            if self.command_saved_timer.isActive():
                validation, message = "saved", "Saved"
            if state == "resume":
                message = "Saved · Space to resume"
            elif state == "paused" and not message:
                message = "Type to enter commands"
            feedback = html.escape(message)
        if self.range_block_message:
            validation = "invalid"
            feedback = html.escape(self.range_block_message)
        self.command_feedback.setText(feedback)
        if self.command.property("validationState") != validation:
            self.command.setProperty("validationState", validation)
            self.command.style().unpolish(self.command)
            self.command.style().polish(self.command)
            self.command.update()

    def review_mode(self):
        self.submit_resume = False
        self.player.setFocus()
        self.update_command_state()

    def refresh_shortcut_hint(self):
        pairs = (
            [("Space", "Play/pause"), ("I/O", "Range"), ("Enter", "Metadata")]
            + (
                [("Shift+Enter", "Save and return")]
                if self.atomic_edit
                else [("Shift+Enter", "Verdict + next")]
            )
            + [("?", "All shortcuts")]
        )
        key_style = f'color:{COLORS["text_primary"]}; font-weight:600'
        action_style = f'color:{COLORS["text_muted"]}'
        self.shortcut_hint.setText(
            " · ".join(
                f'<span style="{key_style}">{html.escape(key)}</span> '
                f'<span style="{action_style}">{html.escape(action)}</span>'
                for key, action in pairs
            )
        )
        self.shortcut_hint.setAccessibleName(
            ", ".join(f"{key}: {action}" for key, action in pairs)
        )

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
        if self.current_panel == "Session":
            return
        self.pane_overrides[self.isMaximized()] = not self.right.isVisible()
        self.update_projects_visibility()

    def panes_resized(self, position, index):
        if self.right.isVisible() and self.splitter.sizes()[2] == 0:
            if self.current_panel == "Session":
                self.update_projects_visibility()
                return
            self.pane_overrides[self.isMaximized()] = False
            self.update_projects_visibility()

    def update_projects_visibility(self):
        allowed = self.current_panel not in {"Browse", "Export", "Config"}
        session_forces_open = self.current_panel == "Session"
        visible = session_forces_open or (
            allowed and self.pane_overrides.get(self.isMaximized(), self.isMaximized())
        )
        self.splitter.setCollapsible(2, not session_forces_open)
        was_visible = self.right.isVisible()
        left_width = self.splitter.sizes()[0]
        self.right.setVisible(visible)
        self.projects_toggle.setVisible(allowed and not visible)
        self.projects_close.setVisible(not session_forces_open)
        self.position_projects_toggle()
        for action in self.projects.actions():
            action.setEnabled(
                not self.atomic_edit
                or action.text() in {"Add to project", "Remove selected clips"}
            )
        for control in self.project_global_controls:
            control.setEnabled(not self.atomic_edit)
        if visible and self.splitter.sizes()[2] == 0:
            self.splitter.setSizes([420, max(400, self.width() - 770), 350])
        if session_forces_open and not was_visible:
            sizes = self.splitter.sizes()
            self.splitter.setSizes(
                [left_width, max(0, sum(sizes) - left_width - sizes[2]), sizes[2]]
            )

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "right"):
            self.update_projects_visibility()

    def position_projects_toggle(self):
        self.projects_toggle.move(
            self.central.width() - self.projects_toggle.width(),
            self.navigation_strip.height(),
        )
        self.projects_toggle.raise_()

    @editing_action
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
            if self.atomic_edit:
                self.edit({"tag": value or None})
                return
            self.catalogue.patch(clip["clip_id"], {"tag": value or None})
            if self.current_panel == "Editing":
                self.render_clip()
            else:
                self.refresh_library()

    def show_shortcuts(self):
        if self.atomic_edit:
            QMessageBox.information(
                self,
                "Single-clip Editing shortcuts",
                "SINGLE-CLIP EDITING\n"
                "Shift+Enter: Save and return to the originating clip (command bar must be empty)\n"
                "Save and return to clip: Save the staged changes\n"
                "Both actions retain the selected Keep, Discard, or Pending verdict. "
                "Use the verdict buttons to change it.\n\n"
                "Enter in the command bar submits metadata. Escape returns to review mode.",
            )
            return
        QMessageBox.information(
            self,
            "Review shortcuts",
            'REVIEW MODE\nSpace: Play / Pause · Hold Space: 3×\n← / →: Seek ±5 s · Shift+←/→: ±1 s\n↑ / ↓: Previous / next session clip\nI / O: Set range · Backspace: Reject\n/ or Enter: Metadata · ?: Help\nShift+Enter: Verdict + Next Pending (command bar must be empty)\nCtrl+Enter: Add to active project + Next (requires an active project; preserves triage)\n\nINPUT MODE\nEnter: Submit command and stay in input\n=: Insert “ -- ” separator\nShift+Enter: Verdict + Next Pending (command bar must be empty)\nCtrl+Enter: Unavailable\nEscape: Return to review, preserving the draft\n\nType while paused to enter input (Settings → General).\nBlue: valid command. Amber underline: incomplete. Red underline: invalid.\nBrief green underline: saved. The hint shows when Space resumes playback.\nExisting review shortcuts take priority over paused typing.\nUse [LOW_FPS], tag:LOW_FPS or tag:"audio issue"; tag:"" clears.\nSubmit metadata with Enter, then Shift+Enter for verdict.\nKeep requires a configured game and at least one metadata field or mainline.\nExplicit Discard advances without metadata.\nRatings never change verdicts. Drafts last for this run only.',
        )

    def update_library_hover_row(self, hovered=None):
        row = self.library.row(hovered) if hovered is not None else -1
        if row == self.library.library_hover_row:
            return
        previous = self.library.library_hover_row
        self.library.library_hover_row = row
        for changed in {previous, previous + 1, row, row + 1}:
            item = self.library.item(changed) if changed >= 0 else None
            if item is not None:
                self.library.viewport().update(self.library.visualItemRect(item))

    def eventFilter(self, watched: QObject, event):
        if (
            getattr(self, "settings_dialog", None) is not None
            and self.settings_dialog.isVisible()
            and isinstance(watched, QWidget)
            and (watched is self or self.isAncestorOf(watched))
            and watched is not self.settings_dialog
            and not self.settings_dialog.isAncestorOf(watched)
            and event.type() in {
                QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
                QEvent.Type.MouseButtonDblClick, QEvent.Type.Wheel,
                QEvent.Type.KeyPress, QEvent.Type.KeyRelease, QEvent.Type.Shortcut,
            }
        ):
            return True
        if watched == self.library.viewport() and event.type() in {
            QEvent.Type.Leave, QEvent.Type.HoverLeave,
        }:
            self.update_library_hover_row()
        if (
            watched is self.library.viewport()
            and self.current_panel in {"Home", "Session"}
            and event.type() == QEvent.Type.MouseButtonDblClick
            and event.button() == Qt.MouseButton.LeftButton
        ):
            item = self.library.itemAt(event.position().toPoint())
            if item is not None:
                self.browse_library_clip(item)
                return True
        if (
            watched is self.library.viewport()
            and self.current_panel == "Home"
        ):
            if (
                event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
            ):
                item = self.library.itemAt(event.position().toPoint())
                if item is not None:
                    self.highlight_home_clip(item)
                return True
            if (
                event.type() == QEvent.Type.MouseButtonRelease
                and event.button() == Qt.MouseButton.LeftButton
            ):
                return True
        if event.type() == QEvent.Type.ApplicationActivate:
            self.request_auto_scan()
        if (
            event.type() == QEvent.Type.Resize
            and hasattr(self, "library")
            and watched is self.library.viewport()
        ):
            self.update_library_scroll_fades()
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
        if event.type() in {QEvent.Type.MouseButtonPress, QEvent.Type.Wheel}:
            self.command_separator_range = None
            self.reject_enter_armed = False
            self.submit_resume = False
            self.update_command_state()
            self.cancel_space()
        if (
            event.type() == QEvent.Type.MouseButtonPress
            and self.current_panel == "Editing"
            and QApplication.focusWidget() is self.command
            and isinstance(watched, QWidget)
            and watched.window() is self
            and watched is not self.command
            and not self.command.isAncestorOf(watched)
            and not QApplication.activeModalWidget()
            and not QApplication.activePopupWidget()
        ):
            self.review_mode()
        if event.type() in {QEvent.Type.ApplicationDeactivate, QEvent.Type.FocusOut}:
            self.command_separator_range = None
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
            watched
            if isinstance(watched, (QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox))
            else QApplication.focusWidget()
        )
        text_editing = isinstance(focus, (QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox))
        key = event.key()
        modifiers = event.modifiers()
        if self.reject_enter_armed and key not in {
            Qt.Key.Key_Shift,
            Qt.Key.Key_Control,
            Qt.Key.Key_Alt,
            Qt.Key.Key_Meta,
        }:
            self.reject_enter_armed = False
            if (
                self.current_panel == "Editing"
                and not text_editing
                and key in {Qt.Key.Key_Return, Qt.Key.Key_Enter}
                and modifiers == Qt.KeyboardModifier.NoModifier
                and not event.isAutoRepeat()
            ):
                self.advance_review()
                return True
        if self.current_panel == "Browse":
            if key == Qt.Key.Key_Escape and self.browse.fullscreen_state is not None:
                self.browse.set_fullscreen(False)
                return True
            if self.browse.fullscreen_state is not None and not text_editing and not modifiers:
                if key in {Qt.Key.Key_Comma, Qt.Key.Key_Period}:
                    self.browse.player.media.stepFrame(key == Qt.Key.Key_Period)
                    return True
                if key in {Qt.Key.Key_BracketLeft, Qt.Key.Key_BracketRight}:
                    self.navigate(-1 if key == Qt.Key.Key_BracketLeft else 1)
                    return True
                if key in {Qt.Key.Key_Up, Qt.Key.Key_Down}:
                    volume = self.browse.player.volume
                    current = volume.value()
                    if key == Qt.Key.Key_Up:
                        volume.setValue(min(100, (current // 5 + 1) * 5))
                    else:
                        volume.setValue(max(0, (current - 1) // 5 * 5))
                    self.browse.player.show_fullscreen_feedback(
                        "volume-2" if key == Qt.Key.Key_Up else "volume-1",
                        volume.value(),
                    )
                    return True
            if (
                key in {Qt.Key.Key_F, Qt.Key.Key_F11}
                and modifiers == Qt.KeyboardModifier.NoModifier
                and not text_editing
            ):
                if not event.isAutoRepeat():
                    self.browse.toggle_fullscreen()
                return True
        if key == Qt.Key.Key_Space and self.consume_resume_space:
            return True
        if key == Qt.Key.Key_Escape and self.current_panel == "Editing":
            self.review_mode()
            return True
        if focus is self.command:
            if (
                self.current_panel == "Editing"
                and self.command_submitted_navigation
                and not self.command.text()
                and key in {Qt.Key.Key_Up, Qt.Key.Key_Down}
                and modifiers == Qt.KeyboardModifier.NoModifier
            ):
                self.navigate(-1 if key == Qt.Key.Key_Up else 1)
                return True
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
            if (
                key == Qt.Key.Key_Equal
                and modifiers == Qt.KeyboardModifier.NoModifier
                and not event.isAutoRepeat()
            ):
                start = (
                    self.command.selectionStart()
                    if self.command.hasSelectedText()
                    else self.command.cursorPosition()
                )
                restore_space = False
                text = self.command.text()
                if (
                    "--" not in text
                    and start == len(text)
                    and not self.command.hasSelectedText()
                ):
                    trimmed_end = len(text.rstrip(" "))
                    restore_space = trimmed_end < start
                    if restore_space:
                        self.command.setSelection(trimmed_end, start - trimmed_end)
                        start = trimmed_end
                self.command.insert(" -- ")
                self.command_separator_range = (start, start + 4, restore_space)
                self.command_separator_space_pending = True
                return True
            separator_range = self.command_separator_range
            suppress_space = self.command_separator_space_pending
            self.command_separator_range = None
            self.command_separator_space_pending = False
            if separator_range is not None:
                start, end, restore_space = separator_range
                if (
                    self.command.cursorPosition() == end
                    and self.command.text()[start:end] == " -- "
                    and not self.command.hasSelectedText()
                ):
                    if (
                        key == Qt.Key.Key_Space
                        and modifiers == Qt.KeyboardModifier.NoModifier
                        and suppress_space
                    ):
                        self.command_separator_range = separator_range
                        return True
                    if key == Qt.Key.Key_Backspace:
                        self.command.setSelection(start, end - start)
                        if restore_space:
                            self.command.insert(" ")
                        else:
                            self.command.del_()
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
            if player is self.browse.player and self.browse.fullscreen_state is not None:
                player.show_fullscreen_feedback(
                    "fast-forward" if key == Qt.Key.Key_Right else "rewind"
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
                    if not event.isAutoRepeat():
                        self.reject_enter_armed = True
                    return True
            if self.current_panel in {"Browse", "Editing"} and event.key() in {
                Qt.Key.Key_I,
                Qt.Key.Key_O,
            }:
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
        clip = self.effective_clip()
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
        self.range_block_message = f"{reason}, or use Clear range."
        self.update_range_warning()
        self.update_command_state()
        self.range_warning.setToolTip(f"{reason}, or use Clear range, before leaving this clip.")
        return False

    def update_range_warning(self):
        start, end = self.range_endpoints() if self.current_id else (None, None)
        has_endpoint = start is not None or end is not None
        missing = start is None or end is None
        visible = self.current_panel == "Editing" and bool(self.current_id)
        visible = visible and has_endpoint and (missing or not 0 <= start < end)
        self.range_warning.setText("I/O not set" if missing else "I/O invalid")
        self.range_warning.setToolTip(
            "Set both In and Out to complete the range."
            if missing
            else "In must be earlier than Out."
        )
        self.range_warning.setVisible(visible)
        self.range_warning_icon.setVisible(visible)
        if not visible and getattr(self, "range_block_message", ""):
            self.range_block_message = ""
            self.update_command_state()

    def reset_pending_range(self):
        self.pending_in = self.pending_out = None
        self.player.seek.pending_in = self.player.seek.pending_out = None
        self.player.seek.update()

    def mark_in(self):
        self.mark_range_point("in")

    def mark_out(self):
        self.mark_range_point("out")

    @editing_action
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
            if self.atomic_edit:
                self.atomic_save_button.setEnabled(False)
            return
        self.save_range(start, end)

    @editing_action
    def save_range(self, start, end):
        if self.current_panel == "Browse":
            return
        try:
            if self.atomic_edit:
                self.atomic_edit.draft = self.catalogue.draft_snapshot(
                    self.atomic_edit.draft, {"in_ms": start, "out_ms": end}, editing=True
                )
            else:
                self.catalogue.patch(
                    self.current_id, {"in_ms": start, "out_ms": end}, editing=True
                )
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
        if self.current_panel == "Browse" or self.atomic_edit:
            return
        name, accepted = QInputDialog.getText(self, "New project", "Project name")
        if accepted:
            try:
                self.catalogue.save_project(name)
                self.refresh_references()
            except ValueError as error:
                self.error(error)

    def rename_project(self):
        if self.current_panel == "Browse" or self.atomic_edit:
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
        if self.current_panel == "Browse" or self.atomic_edit:
            return
        project_id = self.selected_id(self.projects)
        if project_id:
            self.catalogue.set_state("active_project", project_id)
            self.refresh_references()

    def deactivate(self):
        if self.current_panel == "Browse" or self.atomic_edit:
            return
        self.catalogue.set_state("active_project", None)
        self.refresh_references()

    def delete_project(self):
        if self.current_panel == "Browse" or self.atomic_edit:
            return
        project_id = self.selected_id(self.projects)
        if project_id and self.confirm(
            "Delete this project and its memberships? Clips and source files remain."
        ):
            self.catalogue.delete_project(project_id)
            self.refresh_references()
            self.refresh_library()

    @editing_action
    def membership(self, include):
        if self.current_panel == "Browse":
            return
        project_id = self.selected_id(self.projects)
        if not project_id:
            self.error("Select a project first")
            return
        ids = [item.data(Qt.ItemDataRole.UserRole) for item in self.library.selectedItems()]
        for clip_id in ids:
            if self.atomic_edit and clip_id == self.atomic_edit.clip_id:
                self.atomic_edit.draft = self.catalogue.draft_snapshot(
                    self.atomic_edit.draft, {}, membership=(project_id, include)
                )
            else:
                self.catalogue.patch(clip_id, {}, membership=(project_id, include))
        self.update_history_controls()
        if self.current_panel == "Editing":
            self.render_clip()

    def create_session(self, mode):
        if self.current_panel == "Browse" or self.atomic_edit:
            return
        if not self.ensure_range_complete():
            return
        selected = {item.data(Qt.ItemDataRole.UserRole) for item in self.library.selectedItems()}
        visible_ids = [
            self.library.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(self.library.count())
        ]
        clips = {clip["clip_id"]: clip for clip in self.catalogue.clips()}
        ids = [clip_id for clip_id in visible_ids if clips[clip_id]["triage"] is None]
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
            self.positioned_clip_pages.discard("Editing")
            self.library_page_states.pop("Editing", None)
            self.panel("Editing")
        except ValueError as error:
            self.error(error)

    def end_session(self):
        if self.current_panel == "Browse" or self.atomic_edit:
            return
        if not self.ensure_range_complete():
            return
        session = self.catalogue.state("session")
        if not session:
            return
        clips = {clip["clip_id"]: clip for clip in self.catalogue.clips()}
        complete = all(clips[clip_id]["triage"] is not None for clip_id in session["ids"])
        if complete or self.confirm("End this session? Clip metadata stays unchanged."):
            self.catalogue.set_state("session", None)
            self.current_id = None
            self.player.load(None)
            self.clip_filter.set_selected_values({None})
            self.panel("Session")

    def selected_clip(self):
        clip_id = (
            self.current_id if self.current_panel == "Editing" else self.selected_id(self.library)
        )
        if not clip_id:
            raise ValueError("Select a clip first")
        return self.effective_clip() if self.atomic_edit else self.catalogue.clip(clip_id)

    @editing_action
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
                if self.atomic_edit:
                    self.atomic_edit.draft = self.catalogue.draft_snapshot(
                        self.atomic_edit.draft,
                        {"game": game, "metadata": {}},
                        replace_metadata=True,
                    )
                else:
                    self.catalogue.patch(
                        clip["clip_id"], {"game": game, "metadata": {}}, replace_metadata=True
                    )
                self.refresh_library()
                if self.current_panel == "Editing":
                    self.render_clip()
        except ValueError as error:
            self.error(error)

    @editing_action
    def reset_metadata(self):
        if self.current_panel == "Browse":
            return
        try:
            clip = self.selected_clip()
            if self.confirm(
                "Reset notes, structured metadata, triage, rating and range? Source, game and project memberships stay unchanged."
            ):
                reset_patch = {
                        "metadata": {},
                        "mainline": None,
                        "description": None,
                        "tag": None,
                        "triage": None,
                        "rating": None,
                        "in_ms": None,
                        "out_ms": None,
                    }
                if self.atomic_edit:
                    self.atomic_edit.draft = self.catalogue.draft_snapshot(
                        self.atomic_edit.draft, reset_patch, replace_metadata=True
                    )
                else:
                    self.catalogue.patch(
                        clip["clip_id"], reset_patch, replace_metadata=True
                    )
                self.reset_pending_range()
                self.refresh_library()
                if self.current_panel == "Editing":
                    self.render_clip()
        except ValueError as error:
            self.error(error)

    def update_history_controls(self):
        history = None
        if self.current_panel == "Config" and hasattr(self, "config_editor"):
            history = self.config_editor.edit_history()
        elif self.current_panel == "Editing" and self.current_id:
            history = self.editing_history()
        self.undo_button.setEnabled(bool(history and history.undo_stack))
        self.redo_button.setEnabled(bool(history and history.redo_stack))
        for action in getattr(self, "browse_write_actions", []):
            action.setEnabled(
                self.current_panel != "Browse"
                and (
                    not self.atomic_edit
                    or action.text() in {"Reset clip metadata…", "Edit tag…"}
                )
            )

    def undo(self, redo=False):
        if self.current_panel == "Config":
            self.config_editor.undo(redo)
            return
        if self.current_panel != "Editing" or not self.current_id:
            return
        history = self.editing_history()
        operation = history.pending(redo)
        if operation is None:
            return
        expected = operation.before if redo else operation.after
        target = operation.after if redo else operation.before
        if self.editing_state(self.current_id, self.atomic_edit) != expected:
            history.undo_stack.clear()
            history.redo_stack.clear()
            self.update_history_controls()
            self.error("Clip state changed outside this history; previous edits can no longer be undone.")
            return
        try:
            snapshot = self.effective_snapshot()
            restored = (dict(snapshot[0], **target["snapshot"][0]), target["snapshot"][1])
            if self.atomic_edit:
                self.atomic_edit.draft = deepcopy(restored)
                self.atomic_edit.history = deepcopy(target["history"])
            else:
                self.catalogue.commit_snapshot(snapshot, restored)
                self.history[self.current_id] = deepcopy(target["history"])
            self.pending_in, self.pending_out = target["pending"]
            self.player.seek.pending_in, self.player.seek.pending_out = target["pending"]
            history.finish(redo)
            if operation.command:
                if not redo and not self.command.text():
                    self.command.setText(operation.command)
                    self.restored_command = (self.current_id, operation.command)
                elif redo and self.restored_command == (self.current_id, operation.command):
                    self.command.clear()
            self.range_block_message = ""
            self.command_error.clear()
            self.command_error.hide()
            self.submit_resume = False
            self.command_saved_timer.stop()
            self.refresh_references()
            self.refresh_library()
            self.render_clip()
        except (ValueError, OSError) as error:
            self.error(error)

    def background(self, function, done, label="Working…", *, quiet=False):
        if self.close_requested:
            return
        if self.worker is not None or self.activities.busy():
            self.error("Wait for the current operation to finish")
            return
        self.worker = Worker(function)
        results = []
        if quiet:
            self.worker.succeeded.connect(results.append)

            def failed_quietly(message):
                if not self.close_requested:
                    self.statusBar().showMessage(f"Automatic scan: {message}", 12000)

            self.worker.failed.connect(failed_quietly)

            def finished_quietly():
                self.worker.deleteLater()
                self.worker = None
                self.activities._schedule()
                if self.close_requested:
                    QTimer.singleShot(0, self.close)
                    return
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
            if not self.close_requested:
                self.error(message)

        def finished():
            progress.canceled.disconnect(cancel)
            progress.close()
            progress.deleteLater()
            self.worker.deleteLater()
            self.worker = None
            self.activities._schedule()
            if self.close_requested:
                QTimer.singleShot(0, self.close)
                return
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

    def add_folder(self, directory=None):
        if self.current_panel == "Browse":
            return
        if self.worker is not None:
            self.error("Wait for the current operation to finish")
            return
        directory = directory or QFileDialog.getExistingDirectory(self, "Capture folder")
        if not directory:
            return

        def done(found):
            dialog = FolderPreviewDialog(
                directory, found, self.registry.games, self,
                game_folder=bool(self.registry.resolve(Path(directory).name)),
            )
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
            forced_game = dialog.forced_game
            edit_directory = dialog.edit_directory
            dialog.deleteLater()
            if edit_directory:
                return lambda: self.add_folder(edit_directory)
            if accepted:
                if forced_game:
                    found = [
                        {**item, "game": item["game"] or forced_game} for item in found
                    ]

                def ingest(cancelled, progress):
                    if cancelled():
                        raise InterruptedError("Import cancelled")
                    folder_id = self.catalogue.add_folder(directory)
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
            found = coordinator.folder({"path": directory})
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
        if self.close_requested:
            return
        if not self.scan_retry_timer.isActive():
            self.scan_retry_timer.start()

    def auto_scan(self):
        if self.close_requested:
            return
        if (self.worker is not None or self.activities.busy()
                or QApplication.activeModalWidget() is not None):
            self.scan_retry_timer.start()
            return
        self.rescan(quiet=True)

    def rescan(self, force=False, *, quiet=False):
        if self.close_requested:
            return
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
            self.request_folder_sizes(force=True)
            self.refresh_library()
            metrics["ui_refresh"] = time.perf_counter() - started
            logging.info("Scan including UI refresh: %s", metrics)
            if not quiet or errors:
                self.statusBar().showMessage(
                    ("Automatic scan: " + " · ".join(errors))
                    if quiet
                    else f"Scan: {metrics['hits']} cached, {metrics['probes']} inspected, "
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
        self.folder_unlinked_remove_action.setVisible(folder_id == "__unlinked__")
        self.folder_unlinked_remove_action.setEnabled(
            folder_id == "__unlinked__" and self.worker is None
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

    def export_selection(self, *, refresh_library=True):
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
            if refresh_library:
                self.refresh_library()
            current = self.selected_id(self.library)
            clip = next((clip for clip in clips if clip["clip_id"] == current), None)
            if clip is None and clips:
                clip = clips[0]
                self.library.blockSignals(True)
                self.library.setCurrentRow(0)
                self.library.blockSignals(False)
            if clip is None:
                if self.export_player.loaded_clip is not None:
                    self.export_player.load(None)
            elif not self.player_has_clip(self.export_player, clip):
                self.export_player.load(clip)
        else:
            self.schedule_preload()

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
        self.schedule_preload()

    def rotate_tip(self):
        if (
            self.current_panel != "Editing"
            or self.atomic_edit
            or not self.settings.get("editing_tips_enabled", True)
        ):
            self.tip_timer.stop()
            self.editing_tip.hide()
            return
        clip = self.effective_clip() if self.current_id else None
        message = self.tips.next(clip["game"] if clip else None)
        self.editing_tip.set_message(message)
        self.editing_tip.setVisible(bool(message))
        if message:
            self.tip_timer.start()
        else:
            self.tip_timer.stop()

    def update_tips_enabled(self):
        if self.atomic_edit:
            self.tip_timer.stop()
            self.editing_tip.hide()
        elif self.settings.get("editing_tips_enabled", True):
            self.rotate_tip()
        else:
            self.tip_timer.stop()
            self.editing_tip.hide()

    def editing_bottom_size(self):
        size = self.settings.get("editing_bottom_size", 12)
        return size if type(size) is int and size in (11, 12, 13) else 12

    def update_editing_bottom_size(self):
        self.editing_tip.set_tip_size(self.editing_bottom_size())
        self.atomic_edit_notice.set_tip_size(self.editing_bottom_size())
        if self.current_panel == "Editing" and self.current_id:
            clip = self.effective_clip()
            self.render_field_reminder(clip, self.registry.game(clip["game"]))

    def set_playback_volume(self, value):
        self.settings["playback_volume"] = value
        for player in (
            getattr(self, "browse", None) and self.browse.player,
            getattr(self, "player", None),
            getattr(self, "export_player", None),
        ):
            if player is None or player.volume.value() == value:
                continue
            player.volume.blockSignals(True)
            player.volume.setValue(value)
            player.volume.blockSignals(False)
            player.audio.setVolume(value / 100)
        self.save_settings()

    def run_export(self):
        if self.worker is not None or self.close_requested:
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
        formats = deepcopy(self.formats)
        group = self.group_rating.isChecked()
        lowercase = self.settings.get("lowercase_generated_titles", True)
        try:
            ids = self.catalogue.member_ids(project_id)
            clips = [clip for clip in self.catalogue.clips() if clip["clip_id"] in ids]
            manifest = prepare_export_manifest(
                clips, self.registry, destination, self.catalogue.folders(),
                formats, group, lowercase=lowercase,
            )
            manifest["project_name"] = self.export_project.currentText()
            manifest["choices"] = {
                "project_id": project_id, "formats": formats,
                "group_rating": group, "lowercase": lowercase,
            }
            job_id = str(uuid4())
            self.catalogue.save_export_job(job_id, manifest, "Queued")
        except (OSError, ValueError) as error:
            self.error(error)
            return
        self.settings["export_folder"] = destination
        self.save_settings()
        self.add_export_job(job_id, f"Export · {self.export_project.currentText()}")

    def add_export_job(self, job_id, label, *, paused=False):
        record = next(record for record in self.catalogue.export_jobs()
                      if record["job_id"] == job_id)
        count = len(record["manifest"]["items"])
        return self.activities.submit(
            "Export", label,
            lambda cancelled, progress: run_export_manifest(
                self.catalogue, job_id, cancelled, progress,
            ),
            record_id=job_id, forget=self.catalogue.delete_export_job, paused=paused,
            subtitle=f"{count} {'clip' if count == 1 else 'clips'}",
        )

    def restore_export_jobs(self):
        for record in self.catalogue.export_jobs():
            if record["status"] == "Completed":
                self.catalogue.delete_export_job(record["job_id"])
                continue
            self.add_export_job(
                record["job_id"],
                f"Export · {record['manifest'].get('project_name', Path(record['manifest']['destination']).name)}",
                paused=True,
            )

    def flash_share(self, control):
        control.setProperty("shareAccepted", True)
        control.style().unpolish(control)
        control.style().polish(control)
        timer = self.share_flash_timers.get(control)
        if timer is None:
            timer = QTimer(control)
            timer.setSingleShot(True)
            def reset():
                control.setProperty("shareAccepted", False)
                control.style().unpolish(control)
                control.style().polish(control)
            timer.timeout.connect(reset)
            self.share_flash_timers[control] = timer
        timer.start(1200)

    def update_share_controls(self):
        context = (
            ("Browse", self.browse.clip["clip_id"]) if self.current_panel == "Browse" and self.browse.clip
            else ("Editing", self.current_id) if self.current_panel == "Editing" and self.current_id
            else None
        )
        if context != self.share_context:
            if (
                self.share_watched_job is not None
                and self.share_context is not None
                and (context is None or context[1] != self.share_context[1])
            ):
                self.share_ignored_jobs.add(id(self.share_watched_job))
            self.share_context = context
            self.share_watched_job = None
            self.share_completed = False
        active_job = self.activities.active_share(context[1]) if context else None
        if active_job and id(active_job) not in self.share_ignored_jobs:
            self.share_watched_job = active_job
            self.share_completed = False
        elif self.share_watched_job:
            self.share_completed = self.share_watched_job.state == "Completed"
            self.share_watched_job = None
        self.share_ignored_jobs.intersection_update(
            id(job) for job in self.activities.jobs
            if job.kind == "Share" and job.state in {"Queued", "Running", "Cancelling"}
        )
        sharing_browse = bool(self.browse.clip and self.activities.active_share(
            self.browse.clip["clip_id"]
        ))
        sharing_edit = bool(self.activities.active_share(self.current_id))
        if not sharing_browse:
            self.browse.share_button.setIcon(QIcon())
            set_icon(self.browse.fullscreen_share_button, "share-2")
        self.browse.update_share()
        completed_edit = self.share_completed and context == ("Editing", self.current_id)
        self.edit_share_button.setEnabled(bool(self.current_id) and not sharing_edit and not completed_edit)
        hint = ("Share in progress · Open Output Jobs for progress" if sharing_edit
                else "Shared" if completed_edit else "Share")
        self.edit_share_button.setToolTip(hint)
        self.edit_share_button.setAccessibleName(hint)
        if self.edit_share_button.property("shareCompleted") != completed_edit:
            self.edit_share_button.setProperty("shareCompleted", completed_edit)
            self.edit_share_button.style().unpolish(self.edit_share_button)
            self.edit_share_button.style().polish(self.edit_share_button)
        if not sharing_edit:
            if completed_edit:
                self.edit_share_button.setIcon(success_check_icon(20))
            else:
                set_icon(self.edit_share_button, "share-2")
        if sharing_edit or sharing_browse:
            if not self.share_spinner.isActive():
                self.share_spinner.start()
            self.advance_share_spinner()
        else:
            self.share_spinner.stop()

    def advance_share_spinner(self):
        self.share_spinner_angle = (self.share_spinner_angle + 30) % 360
        for control, clip_id, size in (
            (self.browse.share_button,
             self.browse.clip["clip_id"] if self.browse.clip else None, 16),
            (self.browse.fullscreen_share_button,
             self.browse.clip["clip_id"] if self.browse.clip else None, 20),
            (self.edit_share_button, self.current_id, 20),
        ):
            if not self.activities.active_share(clip_id):
                continue
            source = icon("loader-circle", COLORS["text_disabled"], size=size).pixmap(size, size)
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.translate(size / 2, size / 2)
            painter.rotate(self.share_spinner_angle)
            painter.drawPixmap(-size // 2, -size // 2, source)
            painter.end()
            control.setIcon(QIcon(pixmap))
            control.setIconSize(QSize(size, size))

    def share(self):
        if self.current_panel == "Browse":
            self.browse.share()
            return
        try:
            clip = deepcopy(self.selected_clip())
        except ValueError as error:
            self.error(error)
            return
        if self.activities.active_share(clip["clip_id"]):
            return
        if self.share_completed and self.share_context == ("Editing", clip["clip_id"]):
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
        if self.atomic_edit and self.command.text():
            self.error("Submit the command with Enter before sharing.")
            return
        if self.atomic_edit and not self.ensure_range_complete():
            return
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
        custom.setObjectName("shareCustomFilename")
        custom.setPlaceholderText("Leave empty to generate; .mp4 is appended")
        layout.addRow("Custom filename stem", custom)
        all_fields = QCheckBox("All fields")
        all_fields.setObjectName("shareAllFields")
        layout.addRow(all_fields)
        prefix = QCheckBox("Game code prefix")
        prefix.setObjectName("shareGamePrefix")
        layout.addRow(prefix)
        game = self.registry.game(clip["game"])
        checks = []
        for field in game.display_order if game else ["mainline"]:
            check = QCheckBox(field)
            check.setObjectName(f"shareField_{field}")
            checks.append(check)
            layout.addRow(check)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        confirm = buttons.button(QDialogButtonBox.StandardButton.Ok)

        def update_choices():
            all_fields.blockSignals(True)
            all_fields.setChecked(bool(checks) and all(check.isChecked() for check in checks))
            all_fields.blockSignals(False)
            usable_prefix = bool(game and game.code.strip() and prefix.isChecked())
            confirm.setEnabled(
                bool(custom.text().strip())
                or any(check.isChecked() for check in checks)
                or usable_prefix
            )

        def toggle_all(checked):
            for check in checks:
                check.setChecked(checked)
            update_choices()

        all_fields.toggled.connect(toggle_all)
        for check in checks:
            check.toggled.connect(update_choices)
        prefix.toggled.connect(update_choices)
        custom.textChanged.connect(update_choices)
        update_choices()
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        folder = destination.text().strip()
        if not folder:
            self.error("Choose a share folder")
            return
        self.settings["share_folder"] = folder
        self.save_settings()
        fields = [check.text() for check in checks if check.isChecked()]
        custom_name = custom.text().strip() or None
        folders = self.catalogue.folders()
        include_prefix = prefix.isChecked()
        selected_range = mode.currentData()
        lowercase = self.settings.get("lowercase_generated_titles", True)
        stem = custom_name or title(clip, self.registry, fields, include_prefix, lowercase=lowercase)
        self.activities.submit(
            "Share", f"Share · {clip['game'] or 'Unassigned'}",
            lambda cancelled, progress: share_clip(
                clip,
                self.registry,
                folder,
                folders,
                stem,
                None,
                False,
                cancelled,
                selected_range=selected_range,
                detailed_progress=progress,
            ),
            clip_id=clip["clip_id"], subtitle=f"{safe_stem(stem)}.mp4",
        )
        self.flash_share(self.edit_share_button)

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
        if (
            not self.close_requested
            and self.current_panel == "Config"
            and not self.config_editor.confirm_discard()
        ):
            event.ignore()
            return
        if self.activities.busy():
            if not self.close_requested:
                answer = QMessageBox.question(
                    self, "Exit while output jobs are active?",
                    "Output jobs are queued or running. Exit and cancel them?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    event.ignore()
                    return
            self.close_requested = True
            self.scan_timer.stop()
            self.scan_retry_timer.stop()
            self.activities.cancel_all()
            if self.activities.busy():
                self.statusBar().showMessage("Closing after output jobs stop…")
                event.ignore()
                return
        if self.worker:
            self.close_requested = True
            self.scan_timer.stop()
            self.scan_retry_timer.stop()
            self.worker.cancelled.set()
            self.statusBar().showMessage("Closing after the current operation stops…")
            event.ignore()
            return
        if self.folder_size_worker:
            self.close_requested = True
            self.scan_timer.stop()
            self.scan_retry_timer.stop()
            self.folder_size_worker.cancelled.set()
            event.ignore()
            return
        self.cancel_pending_navigation()
        self.atomic_edit = None
        if getattr(self, "settings_dialog", None) is not None:
            self.save_settings()
            self.settings_dialog.reject()
        self.thumbnails.close()
        self.preload_timer.stop()
        self.browse_time_timer.stop()
        self.library_time_timer.stop()
        self.player.media.shutdown()
        self.export_player.media.shutdown()
        self.browse.player.media.shutdown()
        self.scan_timer.stop()
        self.scan_retry_timer.stop()
        QApplication.instance().removeEventFilter(self)
        self.blocked_close_bell.remove()
        try:
            QApplication.instance().styleHints().colorSchemeChanged.disconnect(
                self.system_theme_changed
            )
        except RuntimeError:
            pass
        event.accept()


def style_application(application):
    apply_theme(application)


def main():
    from logging.handlers import RotatingFileHandler

    import PySide6

    (ROOT / "data").mkdir(exist_ok=True)
    config_notices = prepare_game_configs()
    prepare_tip_configs()
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
    if config_notices:
        QTimer.singleShot(
            0,
            lambda: QMessageBox.warning(
                window,
                "Game configuration conflicts",
                "Some incoming game settings could not be merged. Local settings were kept.\n\n"
                + "\n".join(config_notices)
                + "\n\nDetails: configs/default-updates/merge-conflicts.txt",
            ),
        )
    return application.exec()


if __name__ == "__main__":
    sys.exit(main())
