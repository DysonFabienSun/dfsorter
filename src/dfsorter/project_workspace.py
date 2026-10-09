"""Project assembly, independent filters, readiness and temporary candidate history."""

import sqlite3
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, QSize, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .date_input import DateInput, parse_capture_date
from .history import EditHistory
from .parsing import query_clips
from .playback import Player, playback_start_settings
from .project_summary import SIZE_EXPLANATION, project_readiness, ready_source_bytes
from .theme import role
from .widgets import CLIP_ROLE, MiddleElideComboBox, TrailingIconButton, set_icon, storage_gb, tool


@dataclass
class WorkspaceView:
    query: str = ""
    game: str | None = None
    verdict: str = "keep"
    from_date: str = ""
    through_date: str = ""
    unavailable: bool = False
    newest: bool = False
    readiness: str | None = None
    selected: set = field(default_factory=set)
    current: str | None = None
    visible: list = field(default_factory=list)
    scroll: int = 0


def filter_candidates(
    clips, state, registry, members, capture, available, *, member_view=False, readiness=None
):
    """Filter a catalogue snapshot without Session eligibility or membership side effects."""
    today = date.today()
    lower = parse_capture_date(state.from_date, today=today)
    upper = parse_capture_date(state.through_date, today=today)
    if lower and upper and lower > upper:
        raise ValueError("From must be on or before Through")
    clips = query_clips(clips, state.query, registry)
    clips = [
        clip
        for clip in clips
        if (clip["clip_id"] in members) == member_view
        and (state.game is None or (clip["game"] or "") == state.game)
        and (state.verdict == "all" or (clip["triage"] or "pending") == state.verdict)
        and (state.unavailable or available(clip["source_path"]))
        and (not state.readiness or clip["clip_id"] in readiness[state.readiness])
    ]
    captured = {clip["clip_id"]: capture(clip) for clip in clips}
    unknown = sum(value is None for value in captured.values()) if lower or upper else 0
    if lower or upper:
        clips = [
            clip
            for clip in clips
            if (value := captured[clip["clip_id"]]) is not None
            and (not lower or value.astimezone().date() >= lower)
            and (not upper or value.astimezone().date() <= upper)
        ]
    clips.sort(
        key=lambda clip: (
            captured[clip["clip_id"]].timestamp() if captured[clip["clip_id"]] else float("-inf"),
            clip["source_path"].casefold(),
            clip["clip_id"],
        ),
        reverse=state.newest,
    )
    return clips, unknown


class MembershipHistory:
    def __init__(self, catalogue, project_id, skipped=None):
        self.catalogue = catalogue
        self.project_id = project_id
        self.history = EditHistory()
        self.skipped = skipped if skipped is not None else set()
        self.last_kind = None
        self.revision = catalogue.membership_revisions[project_id]

    def sync(self):
        revision = self.catalogue.membership_revisions[self.project_id]
        removed = self.catalogue.removed_clip_ids
        self.skipped.difference_update(removed)
        references_removed = any(
            removed.intersection(operation.before[1])
            for stack in (self.history.undo_stack, self.history.redo_stack)
            for operation in stack
        )
        if self.revision != revision or references_removed:
            self.history = EditHistory()
            self.revision = revision
        return self.history

    def apply(self, ids, include):
        self.sync()
        changed = self.catalogue.batch_membership(self.project_id, ids, include)
        self.revision = self.catalogue.membership_revisions[self.project_id]
        if changed:
            self.history.record(("membership", changed, not include), ("membership", changed, include))
        return changed

    def skip(self, ids):
        self.sync()
        if self.project_id not in {project["project_id"] for project in self.catalogue.projects()}:
            raise ValueError("Project no longer exists")
        members = self.catalogue.member_ids(self.project_id)
        existing = {clip["clip_id"] for clip in self.catalogue.clips()}
        changed = tuple(dict.fromkeys(clip_id for clip_id in ids
                                      if clip_id in existing - members - self.skipped))
        if changed:
            self.skipped.update(changed)
            self.history.record(("skip", changed, False), ("skip", changed, True))
        return changed

    def undo(self, redo=False):
        history = self.sync()
        operation = history.pending(redo)
        if not operation:
            return ()
        expected = operation.before if redo else operation.after
        target = operation.after if redo else operation.before
        try:
            self.last_kind = target[0]
            if target[0] == "skip":
                existing = {clip["clip_id"] for clip in self.catalogue.clips()}
                projects = {project["project_id"] for project in self.catalogue.projects()}
                if (self.project_id not in projects or not set(target[1]) <= existing
                        or any((clip_id in self.skipped) != expected[2] for clip_id in target[1])):
                    raise ValueError("Temporary skip history is stale")
                changed = target[1]
                if target[2]:
                    self.skipped.update(changed)
                else:
                    self.skipped.difference_update(changed)
            else:
                changed = self.catalogue.batch_membership(
                    self.project_id, target[1], target[2], expected=expected[2]
                )
        except (ValueError, sqlite3.Error):
            self.history = EditHistory()
            raise
        self.revision = self.catalogue.membership_revisions[self.project_id]
        history.finish(redo)
        return changed


class ProjectWorkspace:
    def __init__(self, window, layout):
        self.window = window
        self.project_id = window.catalogue.state("workspace_project")
        self.view = "Assigned" if self.project_id else "Available"
        self.states = {}
        self.project_views = {}
        self.histories = {}
        self.skipped_ids = {}
        self.valid = True
        self.loading = False
        self.members = set()
        self.categories = {}
        self.errors = {}
        self.clips = []
        self.pending_view = None
        self.controls = QWidget()
        self.controls.setObjectName("projectWorkspaceToolbar")
        body = QVBoxLayout(self.controls)
        body.setContentsMargins(8, 8, 8, 8)
        body.setSpacing(8)
        self.views = MiddleElideComboBox()
        self.views.addItem("Assigned", "Assigned")
        self.views.addItem("Available", "Available")
        self.views.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.views.setMinimumContentsLength(12)
        self.views.setAccessibleName("Project workspace view")
        row = QHBoxLayout()
        row.addWidget(self.views, 1)
        self.unavailable = tool(
            "eye-off", "Unavailable clips hidden · Show unavailable clips", self.filters_changed
        )
        self.unavailable.setCheckable(True)
        self.unavailable.setProperty("unavailableSources", True)
        self.unavailable.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        row.addWidget(self.unavailable, 0, Qt.AlignmentFlag.AlignVCenter)
        body.addLayout(row)
        self.search = QLineEdit()
        self.search.setProperty("librarySearch", True)
        self.search.setPlaceholderText("Search · game:VAL rating:>=4")
        self.search.setAccessibleName("Project workspace search")
        search_row = QHBoxLayout()
        search_row.addWidget(self.search, 1)
        self.scope = QLabel()
        role(self.scope, "secondary")
        search_row.addWidget(self.scope)
        self.category = QPushButton("All members")
        self.category.clicked.connect(lambda: self.open_category(None))
        search_row.addWidget(self.category)
        body.addLayout(search_row)
        row = QHBoxLayout()
        self.game = QComboBox()
        self.game.setAccessibleName("Workspace game filter")
        self.verdict = QComboBox()
        self.verdict.setAccessibleName("Workspace verdict filter")
        for label, value in [
            ("All verdicts", "all"),
            ("Keep", "keep"),
            ("Pending", "pending"),
            ("Discard", "discard"),
        ]:
            self.verdict.addItem(label, value)
        self.sort = QComboBox()
        self.sort.addItems(["Oldest first", "Newest first"])
        self.sort.setAccessibleName("Workspace capture date order")
        for control in (self.game, self.verdict, self.sort):
            control.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            control.setMinimumContentsLength(1)
            row.addWidget(control, 1)
        body.addLayout(row)
        utilities = QHBoxLayout()
        self.dates_toggle = TrailingIconButton("Dates")
        role(self.dates_toggle, "compactDisclosure")
        self.dates_toggle.setIconSize(QSize(14, 14))
        self.dates_toggle.setCheckable(True)
        self.dates_toggle.setAccessibleName("Show capture date filters")
        utilities.addWidget(self.dates_toggle)
        body.addLayout(utilities)
        self.date_filters = QWidget()
        role(self.date_filters, "transparent")
        filters = QGridLayout(self.date_filters)
        filters.setContentsMargins(0, 0, 0, 0)
        self.date_filters.hide()
        self.dates_toggle.toggled.connect(self.date_filters.setVisible)
        filters.setHorizontalSpacing(body.spacing())
        filters.setVerticalSpacing(body.spacing())
        filters.setColumnStretch(1, 1)
        filters.setColumnStretch(3, 1)
        self.from_date = DateInput()
        self.through_date = DateInput()
        self.from_label = QLabel("From")
        self.through_label = QLabel("Through")
        for column, label, control in (
            (0, self.from_label, self.from_date),
            (2, self.through_label, self.through_date),
        ):
            filters.addWidget(label, 0, column)
            control.setPlaceholderText("YYYY-MM-DD")
            control.setToolTip("YYYY-M-D or M-D · Omitted year defaults to the current local year")
            control.setAccessibleName(f"Capture date {label.text().lower()} (inclusive, local time)")
            control.setClearButtonEnabled(True)
            filters.addWidget(control, 0, column + 1)
        self.dates_toggle.toggled.connect(self.update_date_disclosure)
        utilities.addStrut(self.from_date.sizeHint().height())
        utilities.addWidget(self.date_filters, 1)
        utilities.addStretch()
        self.list_footer = QWidget()
        footer = QVBoxLayout(self.list_footer)
        footer.setContentsMargins(8, 8, 8, 8)
        footer.setSpacing(4)
        self.selection_actions = QWidget()
        row = QHBoxLayout(self.selection_actions)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.selected_action = QPushButton()
        self.skip_action = QPushButton()
        self.selected_action.clicked.connect(lambda: self.change_membership(False))
        self.skip_action.clicked.connect(self.skip_selected)
        row.addWidget(self.selected_action)
        row.addWidget(self.skip_action)
        row.addStretch()
        footer.addWidget(self.selection_actions)
        row = QHBoxLayout()
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        role(self.summary, "secondary")
        row.addWidget(self.summary, 1)
        self.bulk_actions = QPushButton("Bulk actions")
        bulk_menu = QMenu(self.bulk_actions)
        self.matching_action = bulk_menu.addAction("")
        self.matching_action.triggered.connect(lambda: self.change_membership(True))
        self.bulk_actions.setMenu(bulk_menu)
        row.addWidget(self.bulk_actions)
        footer.addLayout(row)
        window.left.layout().addWidget(self.list_footer)
        self.list_footer.hide()
        window.left.layout().insertWidget(1, self.controls)
        self.controls.hide()
        row = QHBoxLayout()
        self.selector = MiddleElideComboBox()
        role(self.selector, "projectIdentity")
        self.selector.setAccessibleName("Workspace project")
        self.selector.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.selector.setMinimumContentsLength(12)
        row.addWidget(self.selector, 1)
        self.more = QPushButton("More")
        menu = QMenu(self.more)
        self.new_action = menu.addAction("New project…", window.new_project)
        menu.addSeparator()
        self.rename_action = menu.addAction("Rename…", window.rename_project)
        self.delete_action = menu.addAction("Delete…", window.delete_project)
        self.more.setMenu(menu)
        row.addWidget(self.more)
        self.help_button = tool("circle-help", "Project assembly and export guide", self.show_guide)
        row.addWidget(self.help_button, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(row)
        self.empty = QLabel("Choose a project or create a new project to assemble clips.")
        self.empty.setWordWrap(True)
        role(self.empty, "secondary")
        layout.addWidget(self.empty)
        row = QHBoxLayout()
        self.readiness_buttons = {}
        for name in ("Ready", "Pending", "Blocked", "Skipped"):
            control = QPushButton(name)
            role(control, "statusCounter")
            control.setCheckable(True)
            control.clicked.connect(lambda checked=False, name=name: self.open_category(name))
            row.addWidget(control)
            self.readiness_buttons[name] = control
        row.addStretch()
        layout.addLayout(row)
        self.player = Player(window.settings, pane="Export")
        player_layout = self.player.layout()
        margins = player_layout.contentsMargins()
        player_layout.setContentsMargins(margins.left(), 0, margins.right(), margins.bottom())
        self.player.loading_finished.connect(self.finish_view_switch)
        self.player.volume_changed.connect(window.set_playback_volume)
        self.player.previous.connect(lambda: self.navigate(-1))
        self.player.next.connect(lambda: self.navigate(1))
        window.library.preview_guard = self.allow_preview
        self.range_warning_icon = QLabel()
        self.range_warning = QLabel("I/O not set")
        role(self.range_warning, "error")
        warning = QHBoxLayout()
        warning.setSpacing(3)
        for widget in (self.range_warning_icon, self.range_warning):
            policy = widget.sizePolicy()
            policy.setRetainSizeWhenHidden(True)
            widget.setSizePolicy(policy)
            widget.hide()
            warning.addWidget(widget)
        self.player.controls.insertLayout(1, warning)
        self.range_controls = []
        for name, label, callback in (
            ("list-start", "Set In · I", window.mark_in),
            ("list-end", "Set Out · O", window.mark_out),
            ("brackets", "Clear range", window.clear_range),
            ("share-2", "Share", window.share),
        ):
            control = tool(name, label, callback)
            self.player.controls.addWidget(control)
            self.range_controls.append(control)
        self.share_button = self.range_controls[-1]
        divider = QWidget()
        divider.setFixedSize(1, 20)
        role(divider, "divider")
        self.player.controls.addWidget(divider, 0, Qt.AlignmentFlag.AlignVCenter)
        self.edit_button = tool("pencil", "Edit clip…", self.edit_preview)
        self.player.controls.addWidget(self.edit_button)
        layout.addWidget(self.player, 1)
        self.working_title = QLabel()
        self.working_title.setObjectName("workingTitle")
        self.working_title.setTextFormat(Qt.TextFormat.RichText)
        self.working_title.setWordWrap(True)
        layout.addWidget(self.working_title)
        self.filename = QLabel()
        self.filename.setTextFormat(Qt.TextFormat.PlainText)
        self.filename.setWordWrap(True)
        role(self.filename, "secondary")
        layout.addWidget(self.filename)
        self.export_button = QPushButton("Export…")
        role(self.export_button, "primary")
        self.export_button.clicked.connect(window.run_export)
        export_row = QHBoxLayout()
        export_row.addStretch()
        self.export_size = QLabel()
        role(self.export_size, "secondary")
        export_row.addWidget(self.export_size, 0, Qt.AlignmentFlag.AlignVCenter)
        export_row.addWidget(self.export_button, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(export_row)
        self.views.currentIndexChanged.connect(
            lambda _: self.switch_view(self.views.currentData())
        )
        self.selector.currentIndexChanged.connect(self.switch_project)
        for control in (self.search, self.from_date, self.through_date):
            control.textChanged.connect(self.filters_changed)
        for control in (self.game, self.verdict, self.sort):
            control.currentIndexChanged.connect(self.filters_changed)
        window.library.itemSelectionChanged.connect(self.update_actions)

    def show_guide(self):
        QMessageBox.information(
            self.window,
            "Project assembly and export",
            "1. Choose a project and collect clips\n"
            "Select an existing project or use More → New project… to create one. "
            "Collect through Editing’s Projects auto-add or bulk actions in Available. "
            "More also contains Rename and Delete.\n\n"
            "2. Refine candidates in Available\n"
            "Search, game and verdict filters narrow the results; Dates reveals capture-date filters. "
            "Available hides saved members. Add selected collects nonmembers; "
            "Assigned offers Remove selected below the list. Bulk actions → All matching acts on every filtered "
            "result, including offscreen rows. Plain-click starts a new selection; "
            "Ctrl-click adds separate rows; Shift-click selects a range; Ctrl+A selects "
            "all visible rows. The eye toggle shows or hides unavailable sources. "
            "Without a project, the view selector is disabled and the catalogue is shown.\n\n"
            "3. Remove exceptions in Assigned\n"
            "To include a broad set except a few recordings, add all matching first. "
            "Switch to Assigned, click the first exception, Ctrl-click the others, "
            "then use Remove selected, or filter and use Bulk actions → Remove all matching. Removal changes "
            "membership only; removing more than 20 matching members asks for confirmation. "
            "Return to Available and use Skip selected on nonmember "
            "exceptions to hide those candidates for this project until restart. Saved "
            "members remain visible. Add, remove and skip batches share Undo/Redo; "
            "successful add/remove actions and Undo/Redo clear selection. "
            "Skip selects the surviving preview: the next clip if skipped, "
            "or the previous clip at the end of the list.\n\n"
            "4. Optionally edit or share a clip\n"
            "Set In and Set Out save a completed valid range immediately. Complete a pending "
            "range or use Clear range before leaving the clip. Share uses the saved range "
            "or whole clip. Edit clip… opens single-clip Editing; Save or Revert returns "
            "to the originating project and view. Range saves are outside Export Undo/Redo.\n\n"
            "5. Inspect Assigned and readiness\n"
            "Ready clips can export; Pending clips need a verdict; Blocked clips have an "
            "unavailable source or invalid export metadata; Skipped counts Discard members. "
            "These counts cover the whole project. Click a category to inspect it; "
            "All members returns to the complete project. Resolve or remove Pending and "
            "Blocked clips before export. Temporary candidate skips do not affect readiness.\n\n"
            "6. Export the project\n"
            "Export… opens destination, filename format, folder organization and a size summary. Resolve Pending and Blocked members before submission. Submission exports the "
            "project’s eligible saved members, regardless of row selection, list filters "
            "or temporary candidate skips. "
            "Settings are remembered separately for each project after submission.\n\n"
            "Project assembly preserves verdicts, metadata and original files and does "
            "not create a Session. Export copies whole files; In/Out points do not trim them.",
        )

    @property
    def state(self):
        return self.view_state(self.view)

    def view_state(self, view):
        key = (self.project_id, view)
        if key not in self.states:
            self.states[key] = WorkspaceView(
                verdict="all" if view == "Assigned" else "keep",
                unavailable=view == "Assigned",
            )
        return self.states[key]

    def history(self):
        if not self.project_id:
            return None
        return self.histories.setdefault(
            self.project_id, MembershipHistory(
                self.window.catalogue, self.project_id,
                self.skipped_ids.setdefault(self.project_id, set()),
            )
        )

    def refresh_references(self):
        self.loading = True
        projects = self.window.catalogue.projects()
        existing = {project["project_id"] for project in projects}
        for mapping in (self.histories, self.skipped_ids, self.project_views):
            for project_id in set(mapping) - existing:
                mapping.pop(project_id)
        self.states = {key: state for key, state in self.states.items()
                       if key[0] is None or key[0] in existing}
        if self.project_id not in {project["project_id"] for project in projects}:
            self.project_id = None
        self.selector.clear()
        self.selector.addItem("Choose project", None)
        for project in projects:
            self.selector.addItem(project["name"], project["project_id"])
            self.selector.setItemData(self.selector.count() - 1, project["name"], Qt.ItemDataRole.ToolTipRole)
        self.selector.setCurrentIndex(max(0, self.selector.findData(self.project_id)))
        self.game.clear()
        self.game.addItem("All games", None)
        self.game.addItem("Uncategorized", "")
        for name in self.window.registry.games:
            self.game.addItem(name, name)
        self.loading = False
        self.load_controls()
        self.refresh_readiness()

    def remember(self):
        if self.window.current_panel != "Export":
            return
        listing = self.window.library
        self.state.selected = {
            item.data(Qt.ItemDataRole.UserRole) for item in listing.selectedItems()
        }
        self.state.current = self.window.selected_id(listing)
        self.state.scroll = listing.verticalScrollBar().value()

    def switch_project(self, *_):
        if self.loading:
            return
        if not self.window.ensure_range_complete():
            self.loading = True
            self.selector.setCurrentIndex(max(0, self.selector.findData(self.project_id)))
            self.loading = False
            return
        self.remember()
        self.project_views[self.project_id] = self.view
        self.project_id = self.selector.currentData()
        self.view = self.project_views.get(
            self.project_id, "Assigned" if self.project_id else "Available"
        )
        self.window.catalogue.set_state("workspace_project", self.project_id)
        self.load_controls()
        self.refresh(restore=True)

    def select_project(self, project_id, *, new=False):
        if new:
            self.project_views[project_id] = "Available"
        self.selector.setCurrentIndex(max(0, self.selector.findData(project_id)))

    def switch_view(self, view, *, deselect=False):
        if self.loading:
            return
        if not self.project_id:
            self.load_controls()
            return
        if not self.window.ensure_range_complete():
            self.load_controls()
            return
        self.remember()
        self.pending_view = None
        if view == self.view:
            self.refresh(restore=True, deselect=deselect)
            return
        clip = self.expected_clip(view)
        if clip is not None and not self.window.player_has_clip(self.player, clip):
            self.pending_view = (
                view, self.project_id, self.window.clip_load_key(clip, "Export"), deselect
            )
            self.player.load(clip)
            return
        self.commit_view_switch(view, deselect=deselect)

    def commit_view_switch(self, view, *, deselect=False):
        self.pending_view = None
        self.view = view
        self.load_controls()
        self.refresh(restore=True, deselect=deselect)

    def finish_view_switch(self):
        pending = self.pending_view
        if pending is None or self.player.awaiting_frame:
            return
        view, project_id, key, deselect = pending
        if self.window.current_panel != "Export" or project_id != self.project_id:
            self.pending_view = None
            return
        clip = self.expected_clip(view)
        if key != self.window.clip_load_key(clip, "Export"):
            self.switch_view(view, deselect=deselect)
            return
        if key != self.window.clip_load_key(self.player.loaded_clip, "Export"):
            return
        self.commit_view_switch(view, deselect=deselect)

    def load_controls(self):
        self.loading = True
        state = self.state
        self.update_view_counts()
        self.views.setCurrentIndex(self.views.findData(self.view))
        self.views.setEnabled(bool(self.project_id))
        self.search.setText(state.query)
        self.game.setCurrentIndex(max(0, self.game.findData(state.game)))
        self.verdict.setCurrentIndex(self.verdict.findData(state.verdict))
        self.sort.setCurrentIndex(int(state.newest))
        self.from_date.setText(state.from_date)
        self.through_date.setText(state.through_date)
        self.unavailable.setChecked(state.unavailable)
        self.update_unavailable_toggle()
        self.category.setVisible(self.view == "Assigned")
        self.category.setToolTip(
            f"{state.readiness} · Return to all members" if state.readiness else "All members"
        )
        self.category.setAccessibleName(self.category.toolTip())
        self.scope.setText(f"{state.readiness} only" if self.view == "Assigned" and state.readiness else "")
        self.scope.setVisible(bool(self.scope.text()))
        # Reloading or clearing filters must not retract an opened drawer.
        if state.from_date or state.through_date:
            self.dates_toggle.setChecked(True)
        self.update_date_disclosure()
        self.update_readiness_selection()
        self.loading = False

    def filters_changed(self, *_):
        if self.loading:
            return
        if not self.window.ensure_range_complete():
            self.load_controls()
            return
        state = self.state
        state.query = self.search.text()
        state.game = self.game.currentData()
        state.verdict = self.verdict.currentData()
        self.set_date_bounds(self.from_date.text().strip(), self.through_date.text().strip())
        self.update_date_disclosure()
        state.unavailable = self.unavailable.isChecked()
        self.update_unavailable_toggle()
        state.newest = bool(self.sort.currentIndex())
        self.refresh(reset=True)

    def update_date_disclosure(self):
        active = bool(self.from_date.text() or self.through_date.text())
        self.dates_toggle.setText("Dates · Active" if active else "Dates")
        expanded = self.dates_toggle.isChecked()
        set_icon(self.dates_toggle, "chevron-left" if expanded else "chevron-right", "text_secondary", size=14)
        self.dates_toggle.setAccessibleName(
            "Collapse capture date filters" if expanded else "Expand capture date filters"
        )
        self.dates_toggle.setToolTip(
            f"From: {self.from_date.text() or 'Any'} · Through: {self.through_date.text() or 'Any'}"
        )

    def update_readiness_selection(self):
        for name, control in self.readiness_buttons.items():
            control.setChecked(self.view == "Assigned" and self.state.readiness == name)

    def set_date_bounds(self, lower, upper):
        for view in ("Assigned", "Available"):
            state = self.view_state(view)
            state.from_date = lower
            state.through_date = upper

    def entry_view(self):
        if self.view == "Assigned" and not self.window.catalogue.member_ids(self.project_id):
            return "Available"
        return self.view

    def update_view_counts(self, clips=None):
        catalogue = self.window.catalogue
        clips = catalogue.clips() if clips is None else clips
        members = catalogue.member_ids(self.project_id)
        skipped = self.skipped_ids.get(self.project_id, set())
        counts = {
            "Assigned": len(members),
            "Available": sum(
                clip["clip_id"] not in members
                and clip["clip_id"] not in skipped
                and clip["triage"] == "keep"
                and self.window.source_available(clip["source_path"])
                for clip in clips
            ),
        }
        for view, count in counts.items():
            name = f"Assigned - {self.selector.currentText()}" if view == "Assigned" and self.project_id else view
            label = f"{name} ({count})"
            index = self.views.findData(view)
            self.views.setItemText(index, label)
            self.views.setItemData(
                index, label + " · Count uses default filters, excludes temporary skips",
                Qt.ItemDataRole.ToolTipRole,
            )

    def update_unavailable_toggle(self):
        shown = self.unavailable.isChecked()
        set_icon(self.unavailable, "eye" if shown else "eye-off")
        label = (
            "Unavailable clips shown · Hide unavailable clips" if shown
            else "Unavailable clips hidden · Show unavailable clips"
        )
        self.unavailable.setToolTip(label)
        self.unavailable.setAccessibleName(label)

    def open_category(self, category):
        if not self.window.ensure_range_complete():
            self.update_readiness_selection()
            return
        self.remember()
        self.set_date_bounds("", "")
        self.view = "Assigned"
        previous = self.state
        self.states[(self.project_id, self.view)] = WorkspaceView(
            verdict="all",
            unavailable=True,
            readiness=category,
            newest=previous.newest,
        )
        self.window.library.setFocus(Qt.FocusReason.OtherFocusReason)
        self.load_controls()
        self.refresh(reset=True, restore=True)

    def refresh_readiness(self, clips=None):
        catalogue = self.window.catalogue
        self.members = catalogue.member_ids(self.project_id)
        clips = catalogue.clips() if clips is None else clips
        self.categories, self.errors = project_readiness(
            [clip for clip in clips if clip["clip_id"] in self.members], self.window.registry
        )
        for name, control in self.readiness_buttons.items():
            control.setText(f"{name} {len(self.categories[name])}")
            count = len(self.categories[name])
            control.setToolTip(
                f"{name} clips prevent export. Click to inspect."
                if count and name in {"Pending", "Blocked"}
                else f"Show {name.lower()} project members"
            )
            emphasis = (
                "muted" if not count else "ready" if name == "Ready"
                else "warning" if name == "Pending" else "error" if name == "Blocked"
                else "secondary"
            )
            if control.property("statusEmphasis") != emphasis:
                control.setProperty("statusEmphasis", emphasis)
                control.style().unpolish(control)
                control.style().polish(control)
            control.setEnabled(bool(self.project_id))
        self.update_readiness_selection()
        self.export_button.setEnabled(bool(self.project_id))
        self.update_export_size(clips)
        self.rename_action.setEnabled(bool(self.project_id))
        self.delete_action.setEnabled(bool(self.project_id))
        self.empty.setVisible(not self.project_id)
        self.update_view_counts(clips)

    def update_export_size(self, clips):
        total = ready_source_bytes(clips, self.categories["Ready"]) if self.project_id else None
        count = len(self.categories["Ready"])
        self.export_size.setText(
            f"{count} ready · Estimated export: {storage_gb(total) if total is not None else '— GB'}"
        )
        self.export_size.setToolTip(
            SIZE_EXPLANATION
            + (" Choose a project to estimate export size." if not self.project_id
               else " Ready source sizes could not be read." if total is None else "")
        )

    def refresh(self, *, reset=False, restore=False, deselect=False, select_current=False):
        window = self.window
        if window.current_panel != "Export":
            self.refresh_readiness()
            return
        if not restore:
            self.remember()
        window.source_stats.clear()
        window.clip_folder_names = window.catalogue.clip_folder_names()
        clips = window.catalogue.clips()
        self.refresh_readiness(clips)
        try:
            clips, unknown = filter_candidates(
                clips,
                self.state,
                window.registry,
                self.members,
                window.capture_datetime,
                window.source_available,
                member_view=self.view == "Assigned",
                readiness=self.categories,
            )
        except ValueError as error:
            self.valid = False
            if self.state.from_date or self.state.through_date:
                self.dates_toggle.setChecked(True)
            window.library_error.setText(str(error))
            window.library_error.show()
            if not restore:
                self.update_actions()
                return
            mapping = {clip["clip_id"]: clip for clip in clips}
            clips = [mapping[clip_id] for clip_id in self.state.visible if clip_id in mapping]
            unknown = 0
            reset = False
        else:
            self.valid = True
            window.library_error.clear()
            window.library_error.hide()
        clips = self.mask_candidates(clips)
        state = self.state
        ids = [clip["clip_id"] for clip in clips]
        if reset:
            state.current = ids[0] if ids else None
            state.selected = {state.current} if state.current else set()
            state.scroll = 0
        elif state.current not in ids:
            index = state.visible.index(state.current) if state.current in state.visible else -1
            following = [clip_id for clip_id in state.visible[index + 1 :] if clip_id in ids]
            preceding = [clip_id for clip_id in state.visible[: max(0, index)] if clip_id in ids]
            state.current = next(
                iter(following), preceding[-1] if preceding else ids[0] if ids else None
            )
            if state.current:
                state.selected.add(state.current)
        state.selected.intersection_update(ids)
        if deselect:
            state.selected.clear()
        if select_current:
            state.selected = {state.current} if state.current else set()
        state.visible = ids
        self.clips = clips
        listing = window.library
        listing.blockSignals(True)
        listing.clear()
        for clip in clips:
            item = QListWidgetItem()
            window.render_card(item, clip)
            data = item.data(CLIP_ROLE)
            is_member = clip["clip_id"] in self.members
            membership = "In project" if is_member else "Outside project"
            reason = self.errors.get(clip["clip_id"], "").partition(": ")[2]
            data.update(project_member=is_member, project_reason=reason, project_workspace=True,
                        danger_selection=self.view == "Available" and is_member)
            item.setData(CLIP_ROLE, data)
            detail = " · ".join(part for part in (membership, reason) if part)
            item.setToolTip(item.toolTip() + ("\n" + detail if detail else ""))
            item.setData(Qt.ItemDataRole.AccessibleTextRole, item.text() + " " + detail)
            listing.addItem(item)
            if clip["clip_id"] == state.current:
                listing.setCurrentItem(item, QItemSelectionModel.SelectionFlag.NoUpdate)
            item.setSelected(clip["clip_id"] in state.selected)
        listing.doItemsLayout()
        listing.verticalScrollBar().setValue(state.scroll)
        listing.blockSignals(False)
        if deselect:
            listing.selectionModel().member_type = None
        self.summary.setText(
            f"{len(clips)} clips"
            + (f" · {unknown} unknown capture dates excluded" if unknown else "")
        )
        self.preview()
        self.update_actions()
        window.update_history_controls()
        window.update_library_scroll_fades()

    def preview(self):
        if self.pending_view is not None:
            self.loading = True
            self.views.setCurrentIndex(self.views.findData(self.view))
            self.loading = False
        self.pending_view = None
        clip_id = self.window.selected_id(self.window.library)
        clip = next((clip for clip in self.clips if clip["clip_id"] == clip_id), None)
        previous = self.player.loaded_clip
        if previous and (not clip or previous["clip_id"] != clip_id):
            if not self.window.ensure_range_complete():
                self.restore_selection()
                return
            self.window.reset_pending_range()
        prepared = self.window.take_prepared_clip("Export", clip)
        same_source = (
            clip is not None
            and self.player.loaded_clip is not None
            and self.window.clip_load_key(self.player.loaded_clip, "Export")
            == self.window.clip_load_key(clip, "Export")
            and getattr(self.player, "loaded_start_settings", None)
            == playback_start_settings(self.window.settings, "Export")
        )
        if not prepared and not same_source and (clip or self.player.loaded_clip):
            self.player.load(clip)
        if clip:
            self.window.render_working_title(clip, self.working_title)
        else:
            self.working_title.clear()
        self.filename.setText(Path(clip["source_path"]).name if clip else "")
        index = self.window.library.currentRow()
        self.player.previous_button.setEnabled(index > 0)
        self.player.next_button.setEnabled(0 <= index < self.window.library.count() - 1)
        for control in (*self.range_controls, self.edit_button):
            control.setEnabled(clip is not None)
        self.window.update_range_warning()
        self.window.update_share_controls()

    def preview_clip(self):
        clip_id = self.window.selected_id(self.window.library)
        return next((clip for clip in self.clips if clip["clip_id"] == clip_id), None)

    def allow_preview(self, clip_id):
        loaded = self.player.loaded_clip
        return (bool(loaded and loaded["clip_id"] == clip_id)
                or self.window.ensure_range_complete())

    def restore_selection(self):
        listing = self.window.library
        listing.blockSignals(True)
        listing.clearSelection()
        for row in range(listing.count()):
            item = listing.item(row)
            clip_id = item.data(Qt.ItemDataRole.UserRole)
            if clip_id == self.state.current:
                listing.setCurrentItem(item, QItemSelectionModel.SelectionFlag.NoUpdate)
            item.setSelected(clip_id in self.state.selected)
        listing.blockSignals(False)
        self.update_actions()

    def mask_candidates(self, clips, view=None, members=None):
        skipped = self.skipped_ids.get(self.project_id, set())
        skipped.difference_update(self.window.catalogue.removed_clip_ids)
        if (view or self.view) == "Assigned":
            return clips
        members = self.members if members is None else members
        return [clip for clip in clips if clip["clip_id"] not in skipped
                or clip["clip_id"] in members]

    def edit_preview(self):
        clip = self.preview_clip()
        if clip:
            self.window.start_atomic_edit(clip["clip_id"], "Export")

    def expected_clip(self, view=None):
        window = self.window
        view = view or self.view
        state = self.view_state(view)
        clips = window.catalogue.clips()
        members = window.catalogue.member_ids(self.project_id)
        categories, _ = project_readiness(
            [clip for clip in clips if clip["clip_id"] in members], window.registry
        )
        try:
            clips, _ = filter_candidates(
                clips,
                state,
                window.registry,
                members,
                window.capture_datetime,
                window.source_available,
                member_view=view == "Assigned",
                readiness=categories,
            )
        except ValueError:
            clips = [clip for clip in clips if clip["clip_id"] in state.visible]
        clips = self.mask_candidates(clips, view, members)
        return next(
            (clip for clip in clips if clip["clip_id"] == state.current),
            clips[0] if clips else None,
        )

    def navigate(self, offset):
        if not self.window.ensure_range_complete():
            return
        listing = self.window.library
        index = listing.currentRow() + offset
        if 0 <= index < listing.count():
            listing.setCurrentRow(index, QItemSelectionModel.SelectionFlag.NoUpdate)
            listing.scrollToItem(listing.item(index))
            self.remember()

    def update_actions(self):
        if self.window.current_panel != "Export":
            return
        selected = {
            item.data(Qt.ItemDataRole.UserRole) for item in self.window.library.selectedItems()
        }
        self.state.selected = selected
        include = self.view == "Available" and not bool(selected & self.members)
        count = len(selected - self.members if include else selected & self.members)
        matching = len(set(self.state.visible) - self.members if include
                       else set(self.state.visible) & self.members)
        suffix = f" ({count})" if count != 1 else ""
        bracketed = self.window.settings.get("nier_automata_hotkey_labels", False)
        verb = ("[A]dd" if include else "[R]emove") if bracketed else ("Add" if include else "Remove")
        self.selected_action.setText(f"{verb} selected{suffix}")
        self.skip_action.setText(f"{'[S]kip' if bracketed else 'Skip'} selected{suffix}")
        self.selected_action.setToolTip(
            f"{'Add selected clips to' if include else 'Remove selected clips from'} this project · "
            f"{'A' if include else 'R'}"
        )
        self.skip_action.setToolTip("Temporarily hide selected candidates in this project · S")
        self.selection_actions.setVisible(bool(count))
        self.selected_action.setVisible(bool(count))
        self.skip_action.setVisible(include and bool(count))
        self.matching_action.setText(f"{'Add' if include else 'Remove'} all matching ({matching})")
        self.matching_action.setVisible(True)
        enabled = bool(self.project_id and self.valid)
        self.selected_action.setEnabled(enabled and bool(count))
        self.matching_action.setEnabled(enabled and bool(matching))
        self.bulk_actions.setEnabled(enabled and bool(matching))
        self.skip_action.setEnabled(enabled and include and bool(count))

    def invalidate_clip_histories(self, ids):
        for clip_id in ids:
            self.window.editing_histories.pop(clip_id, None)

    def change_membership(self, all_matching):
        if not self.project_id or not self.valid:
            return
        selected = {item.data(Qt.ItemDataRole.UserRole)
                    for item in self.window.library.selectedItems()}
        include = self.view == "Available" and not bool(selected & self.members)
        ids = (
            tuple(self.state.visible)
            if all_matching
            else tuple(
                item.data(Qt.ItemDataRole.UserRole) for item in self.window.library.selectedItems()
            )
        )
        ids = tuple(clip_id for clip_id in ids if (clip_id in self.members) != include)
        clip = self.preview_clip()
        if clip and self.window.has_pending_range() and clip["clip_id"] in ids:
            if not self.window.ensure_range_complete():
                return
        if all_matching and not include and len(ids) > 20:
            if not self.window.confirm(
                f"Remove all {len(ids)} matching clips from this project? "
                "Clip metadata and original files remain unchanged."
            ):
                return
        changed = ()
        try:
            changed = self.history().apply(ids, include)
            self.invalidate_clip_histories(changed)
            if changed:
                self.clear_selection()
            self.window.statusBar().showMessage(
                f"{'Added' if include else 'Removed'} {len(changed)} clips; "
                f"{len(ids) - len(changed)} {'already included' if include else 'already absent'}.",
                12000,
            )
        except (ValueError, sqlite3.Error) as error:
            self.window.error(error)
        self.refresh(
            restore=True,
            deselect=bool(changed) and all_matching,
            select_current=bool(changed) and not all_matching,
        )
        if all_matching and changed:
            self.switch_view("Assigned" if include else "Available", deselect=True)

    def clear_selection(self):
        self.remember()
        # Return focus before disabling the action, so Qt cannot focus another button.
        self.window.library.setFocus(Qt.FocusReason.OtherFocusReason)
        self.state.selected.clear()
        self.window.library.clearSelection()
        self.window.library.selectionModel().member_type = None

    def skip_selected(self):
        if not self.project_id or not self.valid or self.view != "Available":
            return
        ids = {item.data(Qt.ItemDataRole.UserRole)
               for item in self.window.library.selectedItems()} - self.members
        clip = self.preview_clip()
        if clip and clip["clip_id"] in ids and not self.window.ensure_range_complete():
            return
        try:
            changed = self.history().skip(ids)
        except (ValueError, sqlite3.Error) as error:
            self.window.error(error)
            return
        if changed:
            self.clear_selection()
            count = len(changed)
            total = len(self.skipped_ids[self.project_id])
            self.window.statusBar().showMessage(
                f"Skipped {count} {'clip' if count == 1 else 'clips'} · "
                f"{total} {'clip' if total == 1 else 'clips'} temporarily skipped "
                "in this project until restart.",
                12000,
            )
            self.refresh(restore=True, select_current=True)

    def undo(self, redo=False):
        if not self.project_id:
            return
        if not self.window.ensure_range_complete():
            return
        changed = ()
        try:
            history = self.history()
            changed = history.undo(redo)
            if history.last_kind == "membership":
                self.invalidate_clip_histories(changed)
            if changed:
                self.clear_selection()
        except (ValueError, sqlite3.Error) as error:
            self.window.error(error)
        self.refresh(restore=True, deselect=bool(changed))
