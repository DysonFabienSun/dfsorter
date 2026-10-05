"""Project assembly, independent filters, readiness and membership-only history."""

import sqlite3
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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

from .history import EditHistory
from .output import validate
from .parsing import query_clips
from .playback import Player, playback_start_settings
from .theme import role
from .widgets import CLIP_ROLE, tool


@dataclass
class WorkspaceView:
    query: str = ""
    game: str | None = None
    verdict: str = "keep"
    from_date: str = ""
    through_date: str = ""
    unavailable: bool = False
    outside: bool = False
    newest: bool = False
    readiness: str | None = None
    selected: set = field(default_factory=set)
    current: str | None = None
    visible: list = field(default_factory=list)
    scroll: int = 0


def project_readiness(clips, registry):
    errors = dict(validate(clips, registry))
    categories = {name: set() for name in ("Ready", "Pending", "Blocked", "Skipped")}
    for clip in clips:
        category = (
            "Pending"
            if clip["triage"] is None
            else "Skipped"
            if clip["triage"] == "discard"
            else "Blocked"
            if clip["clip_id"] in errors
            else "Ready"
        )
        categories[category].add(clip["clip_id"])
    return categories, errors


def filter_candidates(
    clips, state, registry, members, capture, available, *, member_view=False, readiness=None
):
    """Filter a catalogue snapshot without Session eligibility or membership side effects."""
    try:
        lower = date.fromisoformat(state.from_date) if state.from_date else None
        upper = date.fromisoformat(state.through_date) if state.through_date else None
    except ValueError:
        raise ValueError("Capture dates must use YYYY-MM-DD") from None
    if lower and upper and lower > upper:
        raise ValueError("From must be on or before Through")
    clips = query_clips(clips, state.query, registry)
    clips = [
        clip
        for clip in clips
        if (not member_view or clip["clip_id"] in members)
        and (member_view or not state.outside or clip["clip_id"] not in members)
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
    def __init__(self, catalogue, project_id):
        self.catalogue = catalogue
        self.project_id = project_id
        self.history = EditHistory()
        self.revision = catalogue.membership_revisions[project_id]

    def sync(self):
        revision = self.catalogue.membership_revisions[self.project_id]
        removed = self.catalogue.removed_clip_ids
        references_removed = any(
            removed.intersection(operation.before[0])
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
            self.history.record((changed, not include), (changed, include))
        return changed

    def undo(self, redo=False):
        history = self.sync()
        operation = history.pending(redo)
        if not operation:
            return ()
        expected = operation.before if redo else operation.after
        target = operation.after if redo else operation.before
        try:
            changed = self.catalogue.batch_membership(
                self.project_id, target[0], target[1], expected=expected[1]
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
        self.view = "Project clips" if self.project_id else "Library"
        self.states = {}
        self.project_views = {}
        self.histories = {}
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
        self.views = QComboBox()
        self.views.addItems(["Library", "Project clips"])
        self.views.setAccessibleName("Project workspace view")
        body.addWidget(self.views)
        self.search = QLineEdit()
        self.search.setProperty("librarySearch", True)
        self.search.setPlaceholderText("Search · game:VAL rating:>=4")
        self.search.setAccessibleName("Project workspace search")
        body.addWidget(self.search)
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
            control.setMinimumContentsLength(6)
            row.addWidget(control, 1)
        body.addLayout(row)
        dates = QHBoxLayout()
        self.from_date = QLineEdit()
        self.through_date = QLineEdit()
        for label, control in [("From", self.from_date), ("Through", self.through_date)]:
            dates.addWidget(QLabel(label))
            control.setPlaceholderText("YYYY-MM-DD")
            control.setAccessibleName(f"Capture date {label.lower()} (inclusive, local time)")
            control.setClearButtonEnabled(True)
            dates.addWidget(control, 1)
        body.addLayout(dates)
        row = QHBoxLayout()
        self.outside = QCheckBox("Outside project")
        self.unavailable = QCheckBox("Unavailable sources")
        row.addWidget(self.outside)
        row.addWidget(self.unavailable)
        body.addLayout(row)
        self.category = QPushButton("All members")
        self.category.clicked.connect(lambda: self.open_category(None))
        body.addWidget(self.category)
        row = QHBoxLayout()
        self.selected_action = QPushButton()
        self.matching_action = QPushButton()
        self.selected_action.clicked.connect(lambda: self.change_membership(False))
        self.matching_action.clicked.connect(lambda: self.change_membership(True))
        row.addWidget(self.selected_action, 1)
        row.addWidget(self.matching_action, 1)
        body.addLayout(row)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        role(self.summary, "secondary")
        body.addWidget(self.summary)
        window.left.layout().insertWidget(1, self.controls)
        self.controls.hide()
        row = QHBoxLayout()
        self.selector = QComboBox()
        self.selector.setAccessibleName("Workspace project")
        self.selector.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.selector.setMinimumContentsLength(12)
        row.addWidget(self.selector, 1)
        self.new_button = QPushButton("New project…")
        self.new_button.clicked.connect(window.new_project)
        row.addWidget(self.new_button)
        self.more = QPushButton("More")
        menu = QMenu(self.more)
        menu.addAction("Rename…", window.rename_project)
        menu.addAction("Delete…", window.delete_project)
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
            control.clicked.connect(lambda checked=False, name=name: self.open_category(name))
            row.addWidget(control)
            self.readiness_buttons[name] = control
        layout.addLayout(row)
        self.player = Player(window.settings, pane="Export")
        self.player.loading_finished.connect(self.finish_view_switch)
        self.player.volume_changed.connect(window.set_playback_volume)
        self.player.previous.connect(lambda: self.navigate(-1))
        self.player.next.connect(lambda: self.navigate(1))
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
        layout.addWidget(self.export_button, 0, Qt.AlignmentFlag.AlignRight)
        self.views.currentTextChanged.connect(self.switch_view)
        self.selector.currentIndexChanged.connect(self.switch_project)
        for control in (self.search, self.from_date, self.through_date):
            control.textChanged.connect(self.filters_changed)
        for control in (self.game, self.verdict, self.sort):
            control.currentIndexChanged.connect(self.filters_changed)
        for control in (self.outside, self.unavailable):
            control.toggled.connect(self.filters_changed)
        window.library.itemSelectionChanged.connect(self.update_actions)

    def show_guide(self):
        QMessageBox.information(
            self.window,
            "Project assembly and export",
            "1. Choose a project\n"
            "Select an existing project or use New project… to create one. "
            "More contains Rename and Delete.\n\n"
            "2. Find clips in Library\n"
            "Library shows catalogue clips for collection. It initially shows Keep clips "
            "with available sources. Search, game, verdict and capture-date filters narrow "
            "the results. Outside project hides clips already included.\n\n"
            "3. Add clips\n"
            "Add all matching includes every filtered result, including offscreen rows. "
            "Existing members are skipped. Add selected includes only selected rows.\n\n"
            "4. Remove exceptions in Project clips\n"
            "To include a broad set except a few recordings, add all matching first. "
            "Switch to Project clips, click the first exception, Ctrl-click the others, "
            "then use Remove selected. Each batch has one Undo/Redo step.\n\n"
            "5. Preview and check readiness\n"
            "Click a row to preview it. Ctrl-click selects separate rows; Shift-click "
            "selects a range; Ctrl+A selects all filtered results while the list has focus. "
            "Ready, Pending, Blocked and Skipped count the whole project. Click a category "
            "to inspect it; All members returns to the complete project. "
            "Edit clip… opens single-clip Editing. Pending and Blocked clips must be "
            "resolved or removed before export; Discard clips are skipped.\n\n"
            "6. Export the project\n"
            "Export… opens destination and filename settings. Submission exports the "
            "project’s eligible members, regardless of row selection or list filters. "
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
                verdict="all" if view == "Project clips" else "keep",
                unavailable=view == "Project clips",
            )
        return self.states[key]

    def history(self):
        if not self.project_id:
            return None
        return self.histories.setdefault(
            self.project_id, MembershipHistory(self.window.catalogue, self.project_id)
        )

    def refresh_references(self):
        self.loading = True
        projects = self.window.catalogue.projects()
        if self.project_id not in {project["project_id"] for project in projects}:
            self.project_id = None
        self.selector.clear()
        self.selector.addItem("Choose project", None)
        for project in projects:
            self.selector.addItem(project["name"], project["project_id"])
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
        self.remember()
        self.project_views[self.project_id] = self.view
        self.project_id = self.selector.currentData()
        self.view = self.project_views.get(
            self.project_id, "Project clips" if self.project_id else "Library"
        )
        self.window.catalogue.set_state("workspace_project", self.project_id)
        self.load_controls()
        self.refresh(restore=True)

    def select_project(self, project_id, *, new=False):
        if new:
            self.project_views[project_id] = "Library"
        self.selector.setCurrentIndex(max(0, self.selector.findData(project_id)))

    def switch_view(self, view):
        if self.loading:
            return
        self.remember()
        self.pending_view = None
        if view == self.view:
            self.refresh(restore=True)
            return
        clip = self.expected_clip(view)
        if clip is not None and not self.window.player_has_clip(self.player, clip):
            self.pending_view = (view, self.project_id, self.window.clip_load_key(clip, "Export"))
            self.player.load(clip)
            return
        self.commit_view_switch(view)

    def commit_view_switch(self, view):
        self.pending_view = None
        self.view = view
        self.load_controls()
        self.refresh(restore=True)

    def finish_view_switch(self):
        pending = self.pending_view
        if pending is None or self.player.awaiting_frame:
            return
        view, project_id, key = pending
        if self.window.current_panel != "Export" or project_id != self.project_id:
            self.pending_view = None
            return
        clip = self.expected_clip(view)
        if key != self.window.clip_load_key(clip, "Export"):
            self.switch_view(view)
            return
        if key != self.window.clip_load_key(self.player.loaded_clip, "Export"):
            return
        self.commit_view_switch(view)

    def load_controls(self):
        self.loading = True
        state = self.state
        self.views.setCurrentText(self.view)
        self.search.setText(state.query)
        self.game.setCurrentIndex(max(0, self.game.findData(state.game)))
        self.verdict.setCurrentIndex(self.verdict.findData(state.verdict))
        self.sort.setCurrentIndex(int(state.newest))
        self.from_date.setText(state.from_date)
        self.through_date.setText(state.through_date)
        self.outside.setChecked(state.outside)
        self.unavailable.setChecked(state.unavailable)
        self.outside.setVisible(self.view == "Library")
        self.category.setVisible(self.view == "Project clips")
        self.category.setText(
            f"{state.readiness} · Return to all members" if state.readiness else "All members"
        )
        self.loading = False

    def filters_changed(self, *_):
        if self.loading:
            return
        state = self.state
        state.query = self.search.text()
        state.game = self.game.currentData()
        state.verdict = self.verdict.currentData()
        state.from_date = self.from_date.text().strip()
        state.through_date = self.through_date.text().strip()
        state.outside = self.outside.isChecked()
        state.unavailable = self.unavailable.isChecked()
        state.newest = bool(self.sort.currentIndex())
        self.refresh(reset=True)

    def open_category(self, category):
        self.remember()
        self.view = "Project clips"
        previous = self.state
        self.states[(self.project_id, self.view)] = WorkspaceView(
            verdict="all",
            unavailable=True,
            readiness=category,
            newest=previous.newest,
        )
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
            control.setEnabled(bool(self.project_id))
        self.export_button.setEnabled(bool(self.project_id))
        self.more.setEnabled(bool(self.project_id))
        self.empty.setVisible(not self.project_id)

    def refresh(self, *, reset=False, restore=False):
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
                member_view=self.view == "Project clips",
                readiness=self.categories,
            )
        except ValueError as error:
            self.valid = False
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
            data.update(project_member=is_member, project_reason=reason, project_workspace=True)
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
            self.views.setCurrentText(self.view)
            self.loading = False
        self.pending_view = None
        clip_id = self.window.selected_id(self.window.library)
        clip = next((clip for clip in self.clips if clip["clip_id"] == clip_id), None)
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
                member_view=view == "Project clips",
                readiness=categories,
            )
        except ValueError:
            clips = [clip for clip in clips if clip["clip_id"] in state.visible]
        return next(
            (clip for clip in clips if clip["clip_id"] == state.current),
            clips[0] if clips else None,
        )

    def navigate(self, offset):
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
        include = self.view == "Library"
        count = len(selected - self.members if include else selected & self.members)
        matching = len(set(self.state.visible) - self.members)
        self.selected_action.setText(f"{'Add' if include else 'Remove'} selected ({count})")
        self.matching_action.setText(f"Add all matching ({matching})")
        self.matching_action.setVisible(include)
        enabled = bool(self.project_id and self.valid)
        self.selected_action.setEnabled(enabled and bool(count))
        self.matching_action.setEnabled(enabled and bool(matching))

    def invalidate_clip_histories(self, ids):
        for clip_id in ids:
            self.window.editing_histories.pop(clip_id, None)

    def change_membership(self, all_matching):
        if not self.project_id or not self.valid:
            return
        include = self.view == "Library"
        ids = (
            tuple(self.state.visible)
            if all_matching
            else tuple(
                item.data(Qt.ItemDataRole.UserRole) for item in self.window.library.selectedItems()
            )
        )
        try:
            changed = self.history().apply(ids, include)
            self.invalidate_clip_histories(changed)
            self.window.statusBar().showMessage(
                f"{'Added' if include else 'Removed'} {len(changed)} clips; "
                f"{len(ids) - len(changed)} {'already included' if include else 'already absent'}.",
                12000,
            )
        except (ValueError, sqlite3.Error) as error:
            self.window.error(error)
        self.refresh()

    def undo(self, redo=False):
        if not self.project_id:
            return
        try:
            self.invalidate_clip_histories(self.history().undo(redo))
        except (ValueError, sqlite3.Error) as error:
            self.window.error(error)
        self.refresh()
