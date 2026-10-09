import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_ui
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QInputDialog,
    QLabel,
    QScrollArea,
    QStyle,
    QStyleOptionViewItem,
    QTabWidget,
)

from dfsorter.catalogue import Catalogue
from dfsorter.output import prepare_export_manifest, run_export_manifest
from dfsorter.playback import playback_start_settings
from dfsorter.project_export_dialog import ProjectExportDialog, normalized_preferences
from dfsorter.project_workspace import MembershipHistory, WorkspaceView, filter_candidates
from dfsorter.settings_dialog import SettingsDialog
from dfsorter.theme import COLORS
from dfsorter.ui import ROOT, Window
from dfsorter.widgets import CLIP_ROLE

application = test_ui.application
window = test_ui.window


def test_project_placeholder_and_disabled_counters_render(window, application):
    window.set_theme("dark")
    window.panel("Export")
    application.processEvents()
    workspace = window.workspace
    selector = workspace.selector
    assert selector.currentIndex() == -1
    placeholder = selector.grab().toImage()
    selector.setPlaceholderText("")
    empty = selector.grab().toImage()
    selector.setPlaceholderText("Choose project…")
    assert placeholder != empty
    for button in workspace.readiness_buttons.values():
        assert not button.isEnabled()
        for emphasis in ("muted", "ready", "warning", "error"):
            button.setProperty("statusEmphasis", emphasis)
            button.setChecked(True)
            button.style().unpolish(button)
            button.style().polish(button)
            image = button.grab().toImage()
            background = image.pixelColor(0, 0)
            assert image.pixelColor(image.width() // 2, 0) == background
            assert image.pixelColor(0, image.height() // 2) == background
            assert button.palette().color(button.foregroundRole()) == QColor(COLORS["text_disabled"])


def test_project_chooser_startup_and_creation_cancellation(window, tmp_path, monkeypatch):
    window.set_theme("dark")
    workspace = window.workspace
    assert workspace.selector.currentIndex() == -1
    assert workspace.selector.placeholderText() == "Choose project…"
    assert workspace.selector.count() == 1
    _, project = seed_workspace(window, tmp_path, 1)
    window.catalogue.set_state("workspace_project", project)
    from dfsorter.project_workspace import ProjectWorkspace

    original_init = ProjectWorkspace.__init__
    observed = []

    def observe_startup(self, *args):
        original_init(self, *args)
        observed.append(self.project_id)

    monkeypatch.setattr(ProjectWorkspace, "__init__", observe_startup)
    restarted = Window(tmp_path)
    try:
        assert observed == [None]
        assert restarted.workspace.selector.currentIndex() == -1
    finally:
        restarted.close()
        restarted.deleteLater()
    selector = workspace.selector
    monkeypatch.setattr(QInputDialog, "getText", lambda *_args, **_kwargs: ("", False))
    index = selector.count() - 1
    selector.setCurrentIndex(index)
    selector.activated.emit(index)
    assert workspace.project_id == project
    assert selector.currentData() == project
    workspace.select_project(None)
    selector.setCurrentIndex(index)
    selector.activated.emit(index)
    assert workspace.project_id is None
    assert selector.currentIndex() == -1


@pytest.mark.parametrize("category", ["Ready", "Pending", "Blocked", "Skipped"])
def test_readiness_second_click_clears_category(window, tmp_path, category):
    window.set_theme("dark")
    ids, project = seed_workspace(window, tmp_path, 1)
    window.catalogue.batch_membership(project, ids, True)
    workspace = window.workspace
    workspace.refresh()
    button = workspace.readiness_buttons[category]
    button.click()
    assert workspace.state.readiness == category
    assert button.isChecked()
    button.click()
    assert workspace.state.readiness is None
    assert not any(control.isChecked() for control in workspace.readiness_buttons.values())
    assert [clip["clip_id"] for clip in workspace.clips] == ids


def test_v8_migration_preserves_catalogue_and_jobs(catalogue, clips):
    project = catalogue.save_project("Existing")
    catalogue.batch_membership(project, [clips[0]["clip_id"]], True)
    catalogue.create_session([clip["clip_id"] for clip in clips])
    catalogue.save_export_job("job", {"items": [{"frozen": True}]}, "Cancelled")
    catalogue.set_state("active_project", project)
    before = catalogue.clips()
    session = catalogue.state("session")
    jobs = catalogue.export_jobs()
    with catalogue.connection() as database:
        database.execute("ALTER TABLE projects DROP COLUMN output_preferences")
        database.execute("PRAGMA user_version = 8")
    migrated = Catalogue(catalogue.path)
    assert migrated.clips() == before
    assert migrated.state("session") == session
    assert migrated.export_jobs() == jobs
    assert migrated.member_ids(project) == {clips[0]["clip_id"]}
    assert migrated.projects()[0]["output_preferences"] == {}
    assert migrated.state("review_destination") == project
    assert migrated.state("active_project") is None
    assert migrated.rows("PRAGMA user_version")[0]["user_version"] == 10


def test_batch_idempotency_rollback_and_membership_history(catalogue, clips):
    ids = [clip["clip_id"] for clip in clips]
    project = catalogue.save_project("Project")
    other = catalogue.save_project("Other")
    history = MembershipHistory(catalogue, project)
    assert history.apply(ids, False) == ()
    assert not history.sync().undo_stack
    assert history.apply(ids, True) == tuple(ids)
    assert history.apply(ids, True) == ()
    assert len(history.sync().undo_stack) == 1
    catalogue.patch(ids[0], {"mainline": "changed"}, membership=(other, True))
    history.undo()
    assert not catalogue.member_ids(project)
    assert catalogue.member_ids(other) == {ids[0]}
    assert catalogue.clip(ids[0])["mainline"] == "changed"
    history.undo(True)
    assert catalogue.member_ids(project) == set(ids)
    with pytest.raises(ValueError, match="selection changed"):
        catalogue.batch_membership(project, [ids[0], "missing"], False)
    assert catalogue.member_ids(project) == set(ids)
    with catalogue.connection() as database:
        database.execute(
            "CREATE TRIGGER refuse_removal BEFORE DELETE ON members "
            f"WHEN OLD.clip_id='{ids[1]}' BEGIN SELECT RAISE(ABORT,'failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        catalogue.batch_membership(project, ids, False)
    assert catalogue.member_ids(project) == set(ids)


def test_history_rejects_external_stale_pairs_and_editing_invalidates(catalogue, clips):
    project = catalogue.save_project("Project")
    ids = [clip["clip_id"] for clip in clips]
    history = MembershipHistory(catalogue, project)
    history.apply(ids, True)
    # A second connection cannot publish the in-process revision; replay still verifies pairs.
    with catalogue.connection() as database:
        database.execute("DELETE FROM members WHERE clip_id=?", (ids[1],))
    with pytest.raises(ValueError, match="stale"):
        history.undo()
    assert catalogue.member_ids(project) == {ids[0], ids[2]}
    assert not history.sync().undo_stack
    history.apply([ids[1]], True)
    catalogue.patch(ids[0], {}, membership=(project, False))
    assert not history.sync().undo_stack


def test_auto_add_requires_explicit_destination_and_new_keep(catalogue, clips):
    project = catalogue.save_project("Destination")
    catalogue.set_state("review_destination", project)
    first, second, third = [clip["clip_id"] for clip in clips]
    catalogue.patch(first, {"triage": "keep"}, editing=True)
    catalogue.patch(first, {"rating": 4}, editing=True, auto_add_destination=project)
    catalogue.patch(second, {"triage": "keep"}, auto_add_destination=project)
    assert not catalogue.member_ids(project)
    catalogue.patch(third, {"triage": "keep"}, editing=True, auto_add_destination=project)
    assert catalogue.member_ids(project) == {third}


def test_cleanup_invalidates_only_affected_history_after_commit(catalogue, clips):
    first, second = [clip["clip_id"] for clip in clips[:2]]
    project = catalogue.save_project("Affected")
    other = catalogue.save_project("Unaffected")
    affected = MembershipHistory(catalogue, project)
    unaffected = MembershipHistory(catalogue, other)
    affected.apply([first], True)
    unaffected.apply([second], True)
    Path(clips[0]["source_path"]).unlink()
    with catalogue.connection() as database:
        database.execute(
            "CREATE TRIGGER refuse_cleanup BEFORE DELETE ON clips "
            "BEGIN SELECT RAISE(ABORT,'failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        catalogue.remove_unavailable([first])
    assert affected.sync().undo_stack
    assert unaffected.sync().undo_stack
    assert catalogue.member_ids(project) == {first}
    with catalogue.connection() as database:
        database.execute("DROP TRIGGER refuse_cleanup")
    catalogue.remove_unavailable([first])
    assert not affected.sync().undo_stack
    assert unaffected.sync().undo_stack
    unaffected.undo()
    assert not catalogue.member_ids(other)


def test_workspace_project_management_and_destination_isolation(window, tmp_path, monkeypatch):
    ids, original = seed_workspace(window, tmp_path, 2)
    window.catalogue.set_state("review_destination", original)
    window.auto_collect_enabled = True
    window.update_collection_controls()
    monkeypatch.setattr(QInputDialog, "getText", lambda *_args, **_kwargs: ("New", True))
    selector = window.workspace.selector
    new_index = selector.count() - 1
    assert selector.itemText(new_index) == "New project…"
    selector.setFocus()
    selector.showPopup()
    QTest.keyClick(selector.view(), Qt.Key.Key_End)
    QTest.keyClick(selector.view(), Qt.Key.Key_Return)
    created = window.workspace.project_id
    assert created != original
    assert window.workspace.view == "Available"
    assert window.catalogue.state("review_destination") == original
    window.workspace.matching_action.trigger()
    window.catalogue.save_export_job("frozen", {"items": [{"frozen": True}]}, "Cancelled")
    monkeypatch.setattr(QInputDialog, "getText", lambda *_args, **_kwargs: ("Renamed", True))
    window.rename_project()
    assert window.workspace.project_id == created
    assert window.workspace.selector.currentText() == "Renamed"
    assert window.workspace.views.itemText(0) == "Assigned - Renamed (2)"
    assert window.workspace.views.itemText(1) == "Available (0)"
    assert window.catalogue.member_ids(created) == set(ids)
    window.catalogue.set_state("review_destination", created)
    window.update_collection_controls()
    assert window.auto_collect_enabled
    monkeypatch.setattr(window, "confirm", lambda *_: True)
    window.delete_project()
    assert window.workspace.project_id is None
    assert window.workspace.views.itemText(0) == "Assigned (0)"
    assert window.catalogue.state("review_destination") is None
    assert not window.auto_collect_enabled
    assert not window.workspace.export_button.isEnabled()
    assert len(window.catalogue.export_jobs()) == 1
    assert len(window.catalogue.clips()) == len(ids)
    assert all(Path(clip["source_path"]).is_file() for clip in window.catalogue.clips())


@pytest.mark.parametrize("bounds", [
    ("2026-10-05", "2026-10-05"), ("10-5", "10-5"), ("2026-10-5", "10-05"),
])
def test_filters_local_dates_unknown_and_query(catalogue, clips, registry, monkeypatch, bounds):
    clips[0].update(triage="keep", rating=4, metadata={"agent": "Jett"})
    clips[1].update(triage="keep", rating=3)
    clips[2].update(triage="discard", rating=5)
    local = datetime(2026, 10, 5, tzinfo=datetime.now().astimezone().tzinfo)
    monkeypatch.setattr("dfsorter.project_workspace.date", SimpleNamespace(today=lambda: local.date()))
    dates = {
        clips[0]["clip_id"]: local.astimezone(timezone.utc),
        clips[1]["clip_id"]: (local + timedelta(hours=23, minutes=59)).astimezone(timezone.utc),
        clips[2]["clip_id"]: None,
    }

    def filtered(state, **kwargs):
        return filter_candidates(
            clips,
            state,
            registry,
            {clips[0]["clip_id"]},
            lambda clip: dates[clip["clip_id"]],
            lambda path: True,
            **kwargs,
        )

    result, unknown = filtered(
        WorkspaceView(verdict="all", from_date=bounds[0], through_date=bounds[1])
    )
    assert result == clips[1:2] and unknown == 1
    assert len(filtered(WorkspaceView(verdict="all"))[0]) == 2
    assert filtered(WorkspaceView(query="agent:Jett rating:>=4"), member_view=True)[0] == clips[:1]
    assert filtered(WorkspaceView())[0] == clips[1:2]
    assert filtered(WorkspaceView(verdict="all"), member_view=True)[0] == clips[:1]
    with pytest.raises(ValueError, match="From"):
        filtered(WorkspaceView(from_date="2026-10-06", through_date="2026-10-05"))
    with pytest.raises(ValueError, match="From"):
        filtered(WorkspaceView(from_date="10-6", through_date="10-5"))
    with pytest.raises(ValueError):
        filtered(WorkspaceView(query="rating:>=no"))


def test_enqueue_preferences_transaction_and_delete(catalogue, clips, registry, tmp_path):
    clip_id = clips[0]["clip_id"]
    project = catalogue.save_project("Project")
    catalogue.patch(clip_id, {"triage": "keep", "mainline": "Title"}, membership=(project, True))
    inputs = [catalogue.clip(clip_id)]
    manifest = prepare_export_manifest(inputs, registry, tmp_path / "out", catalogue.folders())
    prefs = {"destination": str(tmp_path / "out")}
    catalogue.enqueue_project_export(project, "job", manifest, prefs, expected_clips=inputs)
    with pytest.raises(sqlite3.IntegrityError):
        catalogue.enqueue_project_export(
            project, "job", manifest, {"changed": True}, expected_clips=inputs
        )
    assert catalogue.projects()[0]["output_preferences"] == prefs
    catalogue.patch(clip_id, {"rating": 5})
    with pytest.raises(ValueError, match="changed"):
        catalogue.enqueue_project_export(project, "other", manifest, {}, expected_clips=inputs)
    assert len(catalogue.export_jobs()) == 1
    catalogue.set_state("workspace_project", project)
    catalogue.set_state("review_destination", project)
    catalogue.delete_project(project)
    assert catalogue.state("workspace_project") is None
    assert catalogue.state("review_destination") is None
    assert len(catalogue.export_jobs()) == 1
    assert Path(inputs[0]["source_path"]).is_file()


def seed_workspace(window, tmp_path, count=30):
    window.set_theme("dark", persist=False)
    root = tmp_path / "captures"
    root.mkdir()
    folder = window.catalogue.add_folder(root)
    paths = [root / f"clip-{index:03}.mp4" for index in range(count)]
    for path in paths:
        path.write_bytes(b"original")
    window.catalogue.ingest(folder, [{"path": path, "game": "VALORANT"} for path in paths])
    ids = [clip["clip_id"] for clip in window.catalogue.clips()]
    for clip_id in ids:
        window.catalogue.patch(clip_id, {"triage": "keep", "mainline": "Highlight"})
    window.catalogue.enable_folder(folder, False)
    project = window.catalogue.save_project("Highlights")
    window.refresh_references()
    window.panel("Export")
    window.workspace.select_project(project, new=True)
    return ids, project


def selected_ids(window):
    return {item.data(Qt.ItemDataRole.UserRole) for item in window.library.selectedItems()}


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_export_size_counts_ready_originals_independently_of_workspace_view(
    window, application, tmp_path, monkeypatch, theme
):
    ids, project = seed_workspace(window, tmp_path, 6)
    window.set_theme(theme, persist=False)
    window.catalogue.batch_membership(project, ids, True)
    window.catalogue.patch(ids[0], {"in_ms": 100, "out_ms": 900})
    window.catalogue.patch(ids[2], {"triage": None})
    window.catalogue.patch(ids[3], {"mainline": None})
    window.catalogue.patch(ids[4], {"triage": "discard"})
    Path(window.catalogue.clip(ids[5])["source_path"]).unlink()
    sizes = {clip["source_path"]: int(size * 2**30)
             for clip, size in zip(window.catalogue.clips(), [1.5, 0.25, 3, 4, 5, 6])}
    original_stat = Path.stat

    def sized_stat(path, *args, **kwargs):
        result = original_stat(path, *args, **kwargs)
        if str(path) in sizes:
            fields = list(result)
            fields[6] = sizes[str(path)]
            return os.stat_result(fields)
        return result

    monkeypatch.setattr(Path, "stat", sized_stat)
    workspace = window.workspace
    workspace.refresh()
    assert workspace.categories["Ready"] == set(ids[:2])
    assert workspace.export_size.text() == "2 ready · Estimated export: 1.75 GB"
    assert "1,073,741,824 bytes" in workspace.export_size.toolTip()
    dialog = ProjectExportDialog(window, project)
    assert dialog.summary.text() == "2 clips ready · Estimated size: 1.75 GB"
    assert "1 Discard clip excluded" == dialog.exclusions.text()
    assert not dialog.submit_button.isEnabled()
    dialog.reject()
    window.library.clearSelection()
    workspace.skipped_ids[project].update(ids[:2])
    workspace.search.setText("no matching recordings")
    assert not workspace.state.visible
    assert workspace.export_size.text() == "2 ready · Estimated export: 1.75 GB"
    application.processEvents()
    label_rect = workspace.export_size.geometry()
    button_rect = workspace.export_button.geometry()
    assert label_rect.right() < button_rect.left()
    assert abs(label_rect.center().y() - button_rect.center().y()) <= 1
    # A fresh readiness update must see current sizes rather than stale stat cache entries.
    sizes[window.catalogue.clip(ids[0])["source_path"]] = 2 * 2**30
    workspace.refresh_readiness()
    assert workspace.export_size.text() == "2 ready · Estimated export: 2.25 GB"
    window.catalogue.batch_membership(project, ids[:1], False)
    workspace.refresh_readiness()
    assert workspace.export_size.text() == "1 ready · Estimated export: 0.25 GB"
    other = window.catalogue.save_project("Empty project")
    window.refresh_references()
    workspace.select_project(other, new=True)
    assert workspace.export_size.text() == "0 ready · Estimated export: 0.00 GB"
    workspace.select_project(None)
    assert workspace.export_size.text() == "0 ready · Estimated export: — GB"


@pytest.mark.parametrize("view", ["Assigned", "Available"])
def test_export_selection_membership_mouse_and_keyboard(window, application, tmp_path, view):
    ids, project = seed_workspace(window, tmp_path, 5)
    window.catalogue.batch_membership(project, ids[::2], True)
    window.workspace.refresh()
    select_view(window, view)
    visible = ids[::2] if view == "Assigned" else ids[1::2]
    assert window.workspace.state.visible == visible
    listing = window.library
    listing.setFocus()

    def click(row, modifier=Qt.KeyboardModifier.NoModifier):
        QTest.mouseClick(listing.viewport(), Qt.MouseButton.LeftButton, modifier,
                         listing.visualItemRect(listing.item(row)).center())

    click(0)
    assert selected_ids(window) == {visible[0]}
    click(1, Qt.KeyboardModifier.ControlModifier)
    assert selected_ids(window) == set(visible[:2])
    click(0)
    click(len(visible) - 1, Qt.KeyboardModifier.ShiftModifier)
    assert selected_ids(window) == set(visible)
    listing.clearSelection()
    QTest.keyClick(listing, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    assert selected_ids(window) == set(visible)
    click(0)
    assert selected_ids(window) == {visible[0]}


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_project_member_actions_and_accent_selection(window, tmp_path, theme):
    ids, project = seed_workspace(window, tmp_path, 2)
    window.set_theme(theme, persist=False)
    window.catalogue.batch_membership(project, ids[:1], True)
    window.workspace.refresh()
    select_view(window, "Assigned")
    listing = window.library
    listing.clearSelection()
    listing.item(0).setSelected(True)
    workspace = window.workspace
    assert workspace.selected_action.text() == "Remove selected"
    assert workspace.matching_action.text() == "Remove all matching (1)"
    assert workspace.skip_action.isHidden()
    assert not listing.item(0).data(CLIP_ROLE)["danger_selection"]
    image = QImage(500, 100, QImage.Format.Format_ARGB32)
    image.fill(QColor(COLORS["surface_workspace"]))
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 500, 100)
    option.font = listing.font()
    option.state = QStyle.StateFlag.State_Selected
    painter = QPainter(image)
    listing.itemDelegate().paint(painter, option, listing.model().index(0, 0))
    painter.end()
    assert image.pixelColor(1, 15) == QColor(COLORS["accent_default"])
    assert image.pixelColor(5, 2) == QColor(COLORS["accent_selection"])
    listing.clearSelection()
    assert workspace.selected_action.text() == "Remove selected (0)"
    assert not workspace.selected_action.isEnabled()
    assert not workspace.skip_action.isEnabled()
    assert workspace.matching_action.text() == "Remove all matching (1)"


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_membership_views_and_unavailable_icon(window, application, tmp_path, theme):
    ids, project = seed_workspace(window, tmp_path, 3)
    window.set_theme(theme, persist=False)
    workspace = window.workspace
    window.catalogue.batch_membership(project, ids[2:], True)
    for clip_id in ids[1:]:
        Path(window.catalogue.clip(clip_id)["source_path"]).unlink()
    workspace.refresh()
    assert [workspace.views.itemText(i) for i in range(workspace.views.count())] == [
        "Assigned - Highlights (1)", "Available (1)"
    ]
    assert workspace.state.visible == ids[:1]
    assert not workspace.unavailable.isChecked()
    assert "hidden" in workspace.unavailable.toolTip()
    workspace.unavailable.click()
    assert set(workspace.state.visible) == set(ids[:2])
    assert "shown" in workspace.unavailable.accessibleName()
    select_view(window, "Assigned")
    assert workspace.state.visible == ids[2:]
    assert workspace.unavailable.isChecked()
    workspace.unavailable.click()
    assert not workspace.state.visible
    select_view(window, "Available")
    assert workspace.unavailable.isChecked()
    assert set(workspace.state.visible) == set(ids[:2])
    workspace.select_project(None)
    assert not workspace.views.isEnabled()
    assert workspace.view == "Available"
    workspace.unavailable.click()
    assert set(workspace.state.visible) == set(ids)
    assert not workspace.selected_action.isEnabled()
    assert not workspace.skip_action.isEnabled()
    application.processEvents()
    assert abs(workspace.views.geometry().center().y()
               - workspace.unavailable.geometry().center().y()) <= 1


def test_date_bounds_shared_between_views_and_isolated_by_project(window, tmp_path):
    ids, project = seed_workspace(window, tmp_path, 3)
    workspace = window.workspace
    window.catalogue.batch_membership(project, ids[:1], True)
    workspace.refresh()
    workspace.from_date.setText("3-1")
    workspace.through_date.setText("12-31")
    select_view(window, "Assigned")
    assert workspace.from_date.text() == "3-1"
    assert workspace.through_date.text() == "12-31"
    workspace.from_date.setText("3-")
    select_view(window, "Available")
    assert workspace.from_date.text() == "3-"
    assert not workspace.valid
    workspace.from_date.setText("3-13")
    other = window.catalogue.save_project("Other")
    window.refresh_references()
    workspace.select_project(other)
    assert workspace.from_date.text() == workspace.through_date.text() == ""
    workspace.select_project(project)
    assert workspace.from_date.text() == "3-13"
    assert workspace.through_date.text() == "12-31"
    workspace.open_category(None)
    assert workspace.from_date.text() == workspace.through_date.text() == ""
    select_view(window, "Available")
    assert workspace.from_date.text() == workspace.through_date.text() == ""


def test_view_counts_use_defaults_and_exclude_skips(window, tmp_path):
    ids, project = seed_workspace(window, tmp_path, 6)
    workspace = window.workspace
    window.catalogue.batch_membership(project, ids[:2], True)
    window.catalogue.patch(ids[0], {"triage": "discard"})
    window.catalogue.patch(ids[1], {"triage": None})
    window.catalogue.patch(ids[5], {"triage": None})
    Path(window.catalogue.clip(ids[4])["source_path"]).unlink()
    workspace.refresh()

    def counts(assigned, available):
        assert workspace.views.itemText(0) == f"Assigned - Highlights ({assigned})"
        assert workspace.views.itemText(1) == f"Available ({available})"

    counts(2, 2)
    workspace.search.setText("no matching title")
    workspace.from_date.setText("bad")
    workspace.unavailable.click()
    counts(2, 2)
    workspace.history().skip([ids[2]])
    workspace.refresh()
    counts(2, 1)
    workspace.undo()
    counts(2, 2)
    window.catalogue.batch_membership(project, [ids[3]], True)
    workspace.refresh()
    counts(3, 1)
    window.catalogue.batch_membership(project, [ids[3]], False)
    workspace.refresh()
    counts(2, 2)


@pytest.mark.parametrize("origin", ["Home", "Export"])
def test_export_click_falls_back_only_when_default_assigned_is_empty(
    window, application, tmp_path, origin
):
    ids, project = seed_workspace(window, tmp_path, 2)
    workspace = window.workspace
    select_view(window, "Assigned")
    assert workspace.view == "Assigned"  # Manual selection of an empty view stays possible.
    window.panel(origin)
    window.nav["Export"].click()
    assert test_ui.wait_for(application, lambda: window.pending_page is None
                            and workspace.pending_view is None)
    assert window.current_panel == "Export"
    assert workspace.view == "Available"
    window.catalogue.batch_membership(project, ids[:1], True)
    workspace.refresh()
    select_view(window, "Assigned")
    workspace.search.setText("no matching title")
    assert not workspace.state.visible
    window.panel(origin)
    window.nav["Export"].click()
    assert test_ui.wait_for(application, lambda: window.pending_page is None)
    assert workspace.view == "Assigned"
    assert not workspace.state.visible


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("action", ["add", "remove", "skip", "add_all", "remove_all", "all_members"])
def test_workspace_actions_return_focus_to_clips(window, application, tmp_path, action, theme):
    ids, project = seed_workspace(window, tmp_path, 3)
    workspace = window.workspace
    window.set_theme(theme, persist=False)
    if action in {"remove", "remove_all", "all_members"}:
        window.catalogue.batch_membership(project, ids, True)
        select_view(window, "Assigned")
    button = (
        workspace.skip_action if action == "skip"
        else workspace.bulk_actions if action.endswith("_all")
        else workspace.category if action == "all_members"
        else workspace.selected_action
    )
    window.library.setCurrentRow(0)
    window.activateWindow()
    assert test_ui.wait_for(application, window.isActiveWindow)
    button.setFocus()
    assert test_ui.wait_for(application, button.hasFocus)
    if action.endswith("_all"):
        menu = workspace.bulk_actions.menu()
        menu.popup(button.mapToGlobal(QPoint(0, button.height())))
        application.processEvents()
        QTest.mouseClick(menu, Qt.MouseButton.LeftButton,
                         pos=menu.actionGeometry(workspace.matching_action).center())
    else:
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert test_ui.wait_for(application, lambda: workspace.pending_view is None)
    assert window.library.hasFocus()
    assert all(not control.hasFocus() for control in (
        workspace.selected_action, workspace.skip_action, workspace.bulk_actions, workspace.category
    ))
    if action in {"add", "remove", "skip"}:
        assert window.selected_id(window.library) == ids[1]
        assert selected_ids(window) == {ids[1]}
        assert workspace.state.selected == {ids[1]}
    elif action.endswith("_all"):
        assert not selected_ids(window)
    else:
        assert selected_ids(window) == {ids[0]}


def test_offscreen_removal_and_successful_actions_clear_selection(window, tmp_path, monkeypatch):
    ids, project = seed_workspace(window, tmp_path, 100)
    workspace = window.workspace
    confirmations = []
    monkeypatch.setattr(window, "confirm", lambda message: confirmations.append(message) or True)
    workspace.matching_action.trigger()
    assert not confirmations
    assert test_ui.wait_for(QApplication.instance(), lambda: workspace.pending_view is None)
    assert workspace.view == "Assigned"
    assert not selected_ids(window)
    assert window.library.selectionModel().member_type is None
    assert window.library.count() == 100
    select_view(window, "Assigned")
    window.library.item(0).setSelected(True)
    assert workspace.matching_action.text() == "Remove all matching (100)"
    workspace.matching_action.trigger()
    assert len(confirmations) == 1
    assert test_ui.wait_for(QApplication.instance(), lambda: workspace.pending_view is None)
    assert workspace.view == "Available"
    assert not window.catalogue.member_ids(project)
    assert not selected_ids(window)
    window.undo()
    assert window.catalogue.member_ids(project) == set(ids)
    assert not selected_ids(window)
    select_view(window, "Assigned")
    assert workspace.matching_action.text() == "Remove all matching (100)"
    workspace.matching_action.trigger()
    assert len(confirmations) == 2
    assert test_ui.wait_for(QApplication.instance(), lambda: workspace.pending_view is None)
    assert workspace.view == "Available"
    assert not window.catalogue.member_ids(project)
    window.undo()
    assert not selected_ids(window)
    window.undo(True)
    assert not selected_ids(window)


@pytest.mark.parametrize("count", [20, 21])
@pytest.mark.parametrize("accepted", [False, True])
def test_remove_all_matching_confirmation_threshold_and_cancellation(
    window, tmp_path, monkeypatch, count, accepted
):
    ids, project = seed_workspace(window, tmp_path, count + 5)
    workspace = window.workspace
    workspace.history().apply(ids[:count], True)
    workspace.refresh()
    select_view(window, "Assigned")
    window.library.clearSelection()
    window.library.item(0).setSelected(True)
    window.library.verticalScrollBar().setValue(100)
    selection = selected_ids(window)
    current = window.selected_id(window.library)
    scroll = window.library.verticalScrollBar().value()
    history = workspace.history().sync()
    before = window.catalogue.clips()
    confirmations = []
    monkeypatch.setattr(window, "confirm",
                        lambda message: confirmations.append(message) or accepted)
    workspace.matching_action.trigger()
    assert test_ui.wait_for(QApplication.instance(), lambda: workspace.pending_view is None)
    assert len(confirmations) == (1 if count > 20 else 0)
    if confirmations:
        assert f"{count} matching clips" in confirmations[0]
    if count > 20 and not accepted:
        assert workspace.view == "Assigned"
        assert window.catalogue.member_ids(project) == set(ids[:count])
        assert selected_ids(window) == selection
        assert window.selected_id(window.library) == current
        assert window.library.verticalScrollBar().value() == scroll
        assert len(history.undo_stack) == 1 and not history.redo_stack
    else:
        assert workspace.view == "Available"
        assert not window.catalogue.member_ids(project)
        assert not selected_ids(window)
        assert len(history.undo_stack) == 2
        window.undo()
        assert window.catalogue.member_ids(project) == set(ids[:count])
    assert window.catalogue.clips() == before


@pytest.mark.parametrize("include", [True, False])
def test_all_matching_switches_views_preserving_filters_and_dates(
    window, application, tmp_path, monkeypatch, include
):
    ids, project = seed_workspace(window, tmp_path, 4)
    workspace = window.workspace
    window.catalogue.batch_membership(project, ids[:2], True)
    window.catalogue.patch(ids[0], {"mainline": "Exception"})
    local = datetime.now().astimezone().replace(month=6, day=12)
    monkeypatch.setattr(window, "capture_datetime", lambda clip: local)
    workspace.view_state("Assigned").query = "Highlight"
    workspace.view_state("Assigned").newest = True
    workspace.view_state("Available").query = "game:VAL"
    workspace.set_date_bounds("1-1", "12-31")
    workspace.load_controls()
    workspace.refresh()
    select_view(window, "Available" if include else "Assigned")
    workspace.matching_action.trigger()
    assert test_ui.wait_for(application, lambda: workspace.pending_view is None)
    assert workspace.view == ("Assigned" if include else "Available")
    assert workspace.search.text() == ("Highlight" if include else "game:VAL")
    assert workspace.from_date.text() == "1-1"
    assert workspace.through_date.text() == "12-31"
    assert not selected_ids(window)
    assert window.catalogue.member_ids(project) == (set(ids) if include else {ids[0]})
    workspace.undo()
    assert window.catalogue.member_ids(project) == set(ids[:2])
    assert workspace.view == ("Assigned" if include else "Available")


@pytest.mark.parametrize("fails", [False, True])
def test_all_matching_no_change_or_failure_keeps_view(window, tmp_path, monkeypatch, fails):
    seed_workspace(window, tmp_path, 2)
    workspace = window.workspace
    select_view(window, "Assigned")
    if fails:
        def fail(*args):
            raise ValueError("Membership change failed")

        monkeypatch.setattr(workspace.history(), "apply", fail)
        monkeypatch.setattr(window, "error", lambda error: None)
    workspace.change_membership(True)
    assert workspace.view == "Assigned"
    assert workspace.pending_view is None


def test_remove_selected_above_threshold_does_not_confirm(window, tmp_path, monkeypatch):
    ids, project = seed_workspace(window, tmp_path, 21)
    workspace = window.workspace
    workspace.matching_action.trigger()
    select_view(window, "Assigned")
    window.library.selectAll()
    confirmations = []
    monkeypatch.setattr(window, "confirm", lambda message: confirmations.append(message) or False)
    workspace.selected_action.click()
    assert not confirmations
    assert not window.catalogue.member_ids(project)


def test_skip_status_reports_action_and_current_project_total(window, tmp_path):
    seed_workspace(window, tmp_path, 7)
    workspace = window.workspace
    for total in range(1, 4):
        workspace.skip_selected()
        noun = "clip" if total == 1 else "clips"
        assert window.statusBar().currentMessage() == (
            f"Skipped 1 clip · {total} {noun} temporarily skipped in this project until restart."
        )
    workspace.undo()
    workspace.undo(redo=True)
    workspace.undo()
    window.library.selectAll()
    workspace.skip_selected()
    assert window.statusBar().currentMessage() == (
        "Skipped 5 clips · 7 clips temporarily skipped in this project until restart."
    )
    other = window.catalogue.save_project("Other")
    window.refresh_references()
    workspace.select_project(other, new=True)
    workspace.skip_selected()
    assert window.statusBar().currentMessage() == (
        "Skipped 1 clip · 1 clip temporarily skipped in this project until restart."
    )


def test_skip_masks_member_visibility_isolation_and_restart(
    window, application, tmp_path, close_window
):
    ids, project = seed_workspace(window, tmp_path, 3)
    workspace = window.workspace
    before = window.catalogue.clips()
    workspace.skip_selected()
    assert workspace.state.visible == ids[1:]
    assert selected_ids(window) == {ids[1]}
    assert window.catalogue.clips() == before
    assert not window.catalogue.member_ids(project)
    assert workspace.matching_action.text() == "Add all matching (2)"
    other = window.catalogue.save_project("Other")
    window.refresh_references()
    workspace.select_project(other, new=True)
    assert workspace.state.visible == ids
    workspace.select_project(project)
    assert workspace.state.visible == ids[1:]
    window.catalogue.batch_membership(project, ids[:1], True)
    workspace.refresh()
    assert workspace.state.visible == ids[1:]
    select_view(window, "Assigned")
    assert workspace.state.visible == ids[:1]
    select_view(window, "Available")
    window.catalogue.batch_membership(project, ids[:1], False)
    workspace.refresh()
    assert workspace.state.visible == ids[1:]
    window.close()
    application.processEvents()
    restarted = Window(window.root)
    try:
        assert not restarted.workspace.skipped_ids
        restarted.panel("Export")
        select_view(restarted, "Available")
        assert restarted.workspace.state.visible == ids
    finally:
        close_window(restarted, application)


@pytest.mark.parametrize(
    "current, skipped, expected",
    [(0, (0, 1), 2), (2, (2, 3), 1), (0, (1, 3), 0), (0, (0, 1, 2, 3), None)],
)
@pytest.mark.parametrize("action", ["skip", "add", "remove"])
def test_selected_actions_select_surviving_preview(
    window, tmp_path, current, skipped, expected, action
):
    ids, project = seed_workspace(window, tmp_path, 4)
    workspace = window.workspace
    if action == "remove":
        window.catalogue.batch_membership(project, ids, True)
        select_view(window, "Assigned")
    window.library.setCurrentRow(current)
    window.library.clearSelection()
    for row in skipped:
        window.library.item(row).setSelected(True)
    button = workspace.skip_action if action == "skip" else workspace.selected_action
    button.click()
    expected_id = ids[expected] if expected is not None else None
    assert selected_ids(window) == ({expected_id} if expected_id else set())
    assert window.selected_id(window.library) == expected_id
    assert workspace.state.selected == selected_ids(window)
    assert workspace.state.visible == [clip_id for row, clip_id in enumerate(ids) if row not in skipped]
    changed_ids = {ids[row] for row in skipped}
    expected_members = (
        changed_ids if action == "add"
        else set(ids) - changed_ids if action == "remove"
        else set()
    )
    assert window.catalogue.member_ids(project) == expected_members
    assert button.isEnabled() == (expected is not None)
    if expected_id:
        assert workspace.player.loaded_clip["clip_id"] == expected_id
    else:
        assert workspace.player.loaded_clip is None
    workspace.undo()
    assert workspace.state.visible == ids
    assert not selected_ids(window)


def test_typed_skip_history_chronology_and_stale_replay(catalogue, clips):
    ids = [clip["clip_id"] for clip in clips]
    project = catalogue.save_project("Project")
    skipped = set()
    history = MembershipHistory(catalogue, project, skipped)
    history.apply(ids[:1], True)
    assert history.skip(ids) == tuple(ids[1:])
    assert history.skip(ids) == ()
    assert len(history.sync().undo_stack) == 2
    history.undo()
    assert not skipped and catalogue.member_ids(project) == {ids[0]}
    history.undo()
    assert not catalogue.member_ids(project)
    history.undo(True)
    history.undo(True)
    assert skipped == set(ids[1:])
    skipped.clear()
    with pytest.raises(ValueError, match="stale"):
        history.undo()
    assert not history.sync().undo_stack


def test_transactional_range_only_update(catalogue, clips):
    clip_id = clips[0]["clip_id"]
    project = catalogue.save_project("Project")
    catalogue.set_state("review_destination", project)
    before = catalogue.clip(clip_id)
    assert catalogue.update_range(clip_id, 100, 900, expected=(None, None))
    assert catalogue.clip(clip_id) == {**before, "in_ms": 100, "out_ms": 900}
    assert not catalogue.member_ids(project)
    assert clip_id in catalogue.invalidated_clip_histories
    with pytest.raises(ValueError, match="stale"):
        catalogue.update_range(clip_id, 200, 800, expected=(None, None))
    with pytest.raises(ValueError, match="earlier"):
        catalogue.update_range(clip_id, 900, 100, expected=(100, 900))
    assert catalogue.update_range(clip_id, None, None, expected=(100, 900))
    assert catalogue.clip(clip_id) == before


def test_export_pending_range_guards_and_immediate_save(window, tmp_path, monkeypatch):
    ids, project = seed_workspace(window, tmp_path, 3)
    workspace = window.workspace
    other = window.catalogue.save_project("Other")
    window.refresh_references()
    monkeypatch.setattr(workspace.player.media, "position", lambda: 100)
    window.mark_in()
    assert window.has_pending_range()
    assert not workspace.range_warning.isHidden()
    QTest.mouseClick(window.library.viewport(), Qt.MouseButton.LeftButton,
                     pos=window.library.visualItemRect(window.library.item(1)).center())
    assert selected_ids(window) == {ids[0]}
    workspace.navigate(1)
    assert window.selected_id(window.library) == ids[0]
    workspace.search.setText("absent")
    assert workspace.search.text() == ""
    workspace.views.setCurrentIndex(workspace.views.findData("Assigned"))
    assert workspace.view == "Available"
    workspace.select_project(other)
    assert workspace.project_id == project
    workspace.skip_selected()
    assert not workspace.skipped_ids[project]
    workspace.selected_action.click()
    assert not window.catalogue.member_ids(project)
    window.start_atomic_edit(ids[0], "Export")
    assert window.atomic_edit is None
    window.panel("Home")
    assert window.current_panel == "Export"
    window.run_export()
    assert not window.catalogue.export_jobs()
    monkeypatch.setattr(workspace.player.media, "position", lambda: 50)
    window.mark_out()
    assert window.has_pending_range()
    assert workspace.range_warning.text() == "I/O invalid"
    monkeypatch.setattr(workspace.player.media, "position", lambda: 900)
    window.mark_out()
    assert not window.has_pending_range()
    saved = window.catalogue.clip(ids[0])
    assert (saved["in_ms"], saved["out_ms"]) == (100, 900)
    assert not workspace.history().sync().undo_stack
    assert not window.catalogue.member_ids(project)
    workspace.navigate(1)
    assert window.selected_id(window.library) == ids[1]


@pytest.mark.parametrize("result", ["Completed", "Failed", "Cancelled"])
def test_export_share_feedback_and_atomic_return(window, tmp_path, monkeypatch, result):
    ids, project = seed_workspace(window, tmp_path, 2)
    workspace = window.workspace
    job = SimpleNamespace(kind="Share", state="Running")
    monkeypatch.setattr(window.activities, "jobs", [job])
    monkeypatch.setattr(window.activities, "active_share",
                        lambda clip_id: job if clip_id == ids[0] and job.state == "Running" else None)
    window.update_share_controls()
    assert not workspace.share_button.isEnabled()
    assert "progress" in workspace.share_button.toolTip()
    job.state = result
    window.update_share_controls()
    assert workspace.share_button.property("shareCompleted") == (result == "Completed")
    assert workspace.share_button.toolTip() == ("Shared" if result == "Completed" else "Share")
    assert workspace.share_button.isEnabled() == (result != "Completed")
    workspace.navigate(1)
    assert not workspace.share_button.property("shareCompleted")
    workspace.skip_selected()
    workspace.edit_preview()
    assert window.atomic_edit.clip_id == ids[1]
    window.edit({"rating": 4})
    assert window.save_atomic_edit()
    assert window.current_panel == "Export"
    assert workspace.project_id == project and workspace.view == "Available"
    assert workspace.state.visible == ids[1:]
    assert window.selected_id(window.library) == ids[1]
    workspace.edit_preview()
    window.edit({"rating": 5})
    monkeypatch.setattr(window, "confirm_revert_atomic", lambda: True)
    window.revert_atomic_edit()
    assert window.current_panel == "Export"
    assert workspace.state.visible == ids[1:]
    assert window.catalogue.clip(ids[1])["rating"] == 4


def test_export_share_pending_range_uses_saved_markers(window, tmp_path, monkeypatch):
    ids, project = seed_workspace(window, tmp_path, 1)
    window.save_range(100, 900)
    monkeypatch.setattr(window.export_player.media, "position", lambda: 1000)
    window.mark_in()
    assert window.has_pending_range()

    def cancel(dialog):
        labels = [label.text() for label in dialog.findChildren(QLabel)]
        assert "Range changes are pending; selected range uses the saved markers." in labels
        choices = dialog.findChildren(QComboBox)
        assert choices[0].currentData() is True
        assert "0.100–0.900s" in choices[0].currentText()
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", cancel)
    window.share()
    assert window.has_pending_range()
    assert not window.activities.jobs
    assert not window.catalogue.member_ids(project)


def select_view(window, view):
    window.workspace.views.setCurrentIndex(window.workspace.views.findData(view))
    assert test_ui.wait_for(QApplication.instance(), lambda: window.workspace.pending_view is None)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_view_switch_loading_covers_only_export_video(
    window, application, tmp_path, monkeypatch, theme
):
    ids, project = seed_workspace(window, tmp_path, 2)
    window.set_theme(theme, persist=False)
    window.catalogue.batch_membership(project, [ids[1]], True)
    player = window.export_player
    player.load(None)
    application.processEvents()
    window.cancel_page_transition()
    loads = []

    def slow_load(clip):
        loads.append(clip["clip_id"])
        player.loaded_clip = clip
        player.loaded_start_settings = playback_start_settings(window.settings, "Export")
        player.awaiting_frame = True
        player.loading_started.emit()

    monkeypatch.setattr(player, "load", slow_load)
    for view, clip_id in (("Assigned", ids[1]), ("Available", ids[0])):
        previous_view = window.workspace.view
        previous_row = window.library.item(0)
        window.workspace.views.setCurrentIndex(window.workspace.views.findData(view))
        application.processEvents()
        assert loads[-1] == clip_id
        assert window.transition_pending
        assert window.workspace.view == previous_view
        assert window.library.item(0) is previous_row
        assert window.transition_scope == "clip"
        container = player.video_container
        assert window.transition_cover.geometry() == QRect(
            container.mapTo(window.centralWidget(), QPoint()), container.size()
        )
        for control in (
            window.workspace.selector,
            *window.workspace.readiness_buttons.values(),
            window.workspace.working_title,
            window.workspace.filename,
            window.workspace.export_button,
            window.workspace.views,
        ):
            assert control.isVisible()
            assert not window.transition_cover.geometry().contains(
                control.mapTo(window.centralWidget(), control.rect().center())
            )
        window.resize(window.width() - 20, window.height() - 20)
        application.processEvents()
        assert window.transition_cover.geometry() == QRect(
            container.mapTo(window.centralWidget(), QPoint()), container.size()
        )
        player.awaiting_frame = False
        player.loading_finished.emit()
        application.processEvents()
        assert not window.transition_pending
        assert window.transition_cover.isHidden()
        assert window.workspace.view == view
        assert window.selected_id(window.library) == clip_id
    assert loads == [ids[1], ids[0]]


def test_pending_view_switch_can_be_cancelled(window, application, tmp_path, monkeypatch):
    ids, project = seed_workspace(window, tmp_path, 2)
    window.catalogue.batch_membership(project, [ids[1]], True)
    player = window.export_player
    player.load(None)
    application.processEvents()
    window.cancel_page_transition()

    def slow_load(clip):
        player.loaded_clip = clip
        player.loaded_start_settings = playback_start_settings(window.settings, "Export")
        player.awaiting_frame = True
        player.loading_started.emit()

    monkeypatch.setattr(player, "load", slow_load)
    window.workspace.views.setCurrentIndex(window.workspace.views.findData("Assigned"))
    assert window.workspace.pending_view is not None
    window.workspace.views.setCurrentIndex(window.workspace.views.findData("Available"))
    assert window.workspace.pending_view is None
    player.awaiting_frame = False
    player.loading_finished.emit()
    application.processEvents()
    assert window.workspace.view == "Available"
    assert window.library.count() == 1
    assert window.selected_id(window.library) == ids[0]
    assert not window.transition_pending


def test_real_video_view_switch_prepares_once_before_list_change(
    window, application, tmp_path, monkeypatch
):
    first = test_ui.add_clips(window, tmp_path, valid=True)[0]
    source = Path(window.catalogue.clip(first)["source_path"])
    second_source = source.with_name("second.mp4")
    second_source.write_bytes(source.read_bytes())
    folder = window.catalogue.folders()[0]["folder_id"]
    window.catalogue.ingest(folder, [{"path": str(second_source), "game": "VALORANT"}])
    ids = [clip["clip_id"] for clip in window.catalogue.clips()]
    second = next(clip_id for clip_id in ids if clip_id != first)
    for clip_id in ids:
        window.catalogue.patch(clip_id, {"triage": "keep"})
    project = window.catalogue.save_project("Video previews")
    window.catalogue.batch_membership(project, [second], True)
    window.refresh_references()
    window.workspace.select_project(project, new=True)
    window.panel("Export")
    window.library.setCurrentRow(ids.index(first))
    player = window.export_player
    assert test_ui.wait_for(
        application, lambda: not player.awaiting_frame and not window.transition_pending
    )
    previous = window.library.currentItem()
    loads = []
    original_load = player.load

    def record_load(clip):
        loads.append(clip["clip_id"])
        original_load(clip)

    monkeypatch.setattr(player, "load", record_load)
    window.workspace.views.setCurrentIndex(window.workspace.views.findData("Assigned"))
    assert window.workspace.view == "Available"
    assert window.library.currentItem() is previous
    assert window.workspace.pending_view is not None
    assert test_ui.wait_for(application, lambda: window.workspace.pending_view is None)
    assert window.workspace.view == "Assigned"
    assert window.library.count() == 1
    assert window.selected_id(window.library) == second
    assert loads == [second]
    assert not player.awaiting_frame


def test_assemble_300_paused_clips_and_undo(window, application, tmp_path, monkeypatch):
    ids, project = seed_workspace(window, tmp_path, 300)
    workspace = window.workspace
    workspace.search.setText("game:VAL Highlight")
    assert window.library.count() == 300
    assert window.catalogue.state("session") is None
    workspace.matching_action.trigger()
    assert window.catalogue.member_ids(project) == set(ids)
    assert window.undo_button.isEnabled()
    select_view(window, "Assigned")
    window.library.clearSelection()
    for index in (1, 8, 22):
        window.library.item(index).setSelected(True)
    selected = {window.library.item(index).data(Qt.ItemDataRole.UserRole) for index in (1, 8, 22)}
    workspace.selected_action.click()
    assert len(window.catalogue.member_ids(project)) == 297
    window.undo()
    assert window.catalogue.member_ids(project) == set(ids)
    window.undo()
    assert not window.catalogue.member_ids(project)
    window.undo(True)
    assert window.catalogue.member_ids(project) == set(ids)
    assert all(clip["triage"] == "keep" for clip in window.catalogue.clips())
    assert selected <= window.catalogue.member_ids(project)
    assert window.catalogue.state("session") is None
    # Membership assembly and filtering feed the same frozen output engine as resumed jobs.
    setup = ProjectExportDialog(window, project)
    setup.destination.setText(str(tmp_path / "exported"))
    monkeypatch.setattr(window, "add_export_job", lambda *_: None)
    setup.submit()
    assert setup.job_id
    copied = run_export_manifest(window.catalogue, setup.job_id)
    assert copied.error is None and len(copied.completed) == 300
    assert len(set(copied.completed)) == 300
    assert all(Path(path).read_bytes() == b"original" for path in copied.completed)
    assert all(
        Path(clip["source_path"]).read_bytes() == b"original" for clip in window.catalogue.clips()
    )
    assert window.catalogue.state("session") is None


@pytest.mark.parametrize("panel", ["Home", "Browse", "Session", "Export"])
@pytest.mark.parametrize("selection", ["empty", "single", "multiple"])
def test_clip_right_click_preserves_selection_and_preview(
    window, application, tmp_path, monkeypatch, panel, selection
):
    ids, _project = seed_workspace(window, tmp_path, count=3)
    window.catalogue.enable_folder(window.catalogue.folders()[0]["folder_id"], True)
    for clip_id in ids:
        window.catalogue.patch(clip_id, {"triage": None})
    window.catalogue.create_session(ids)
    if panel == "Export":
        for clip_id in ids:
            window.catalogue.patch(clip_id, {"triage": "keep"})
    window.panel(panel)
    window.refresh_library()
    application.processEvents()
    window.library.setCurrentRow(0)
    window.library.clearSelection()
    if selection != "empty":
        window.library.item(0).setSelected(True)
    if selection == "multiple":
        window.library.item(1).setSelected(True)
    selected = selected_ids(window)
    current = window.library.currentItem()
    preview = window.current_id
    session = window.catalogue.state("session")
    target = window.library.item(2)
    assert target is not None
    window.library.scrollToItem(target)
    application.processEvents()
    position = window.library.visualItemRect(target).center()
    popups = []
    monkeypatch.setattr(window.clip_context_menu, "popup", popups.append)
    monkeypatch.setattr(
        window.library, "preview_guard",
        lambda *_: pytest.fail("Right-click attempted to change the preview"),
    )
    QTest.mouseClick(window.library.viewport(), Qt.MouseButton.RightButton, pos=position)
    window.show_clip_context_menu(position)
    assert popups
    assert window.context_clip_id == target.data(Qt.ItemDataRole.UserRole)
    assert window.library.currentItem() is current
    assert selected_ids(window) == selected
    assert window.current_id == preview
    assert window.catalogue.state("session") == session


def test_selection_preview_filters_and_atomic_return(window, application, tmp_path, monkeypatch):
    ids, project = seed_workspace(window, tmp_path)
    workspace = window.workspace
    window.library.setFocus()
    QTest.keyClick(window.library, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    assert len(window.library.selectedItems()) == len(ids)
    workspace.navigate(1)
    assert len(window.library.selectedItems()) == len(ids)
    selected = {item.data(Qt.ItemDataRole.UserRole) for item in window.library.selectedItems()}
    current = window.selected_id(window.library)
    monkeypatch.setattr(window.clip_context_menu, "popup", lambda *_: None)
    window.show_clip_context_menu(window.library.visualItemRect(window.library.item(0)).center())
    assert {
        item.data(Qt.ItemDataRole.UserRole) for item in window.library.selectedItems()
    } == selected
    assert window.context_clip_id == ids[0]
    window.library.verticalScrollBar().setValue(200)
    scroll = window.library.verticalScrollBar().value()
    window.start_atomic_edit(current, "Export")
    assert not window.membership_menu.collection_changes_enabled
    window.edit({"rating": 4})
    assert window.save_atomic_edit()
    assert window.current_panel == "Export"
    assert workspace.view == "Available"
    assert window.selected_id(window.library) == current
    assert {
        item.data(Qt.ItemDataRole.UserRole) for item in window.library.selectedItems()
    } == selected
    assert window.library.verticalScrollBar().value() == scroll
    workspace.from_date.setText("bad")
    assert window.library.count() == len(ids)
    assert not workspace.matching_action.isEnabled()
    workspace.from_date.clear()
    assert workspace.matching_action.isEnabled()
    assert window.library.currentRow() == 0
    select_view(window, "Assigned")
    assert window.library.count() == 0
    select_view(window, "Available")
    assert window.library.count() == len(ids)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_export_dialog_live_filename_examples_and_compact_fields(
    window, application, tmp_path, theme
):
    ids, project = seed_workspace(window, tmp_path, 5)
    window.set_theme(theme, persist=False)
    window.settings["lowercase_generated_titles"] = theme == "light"
    window.catalogue.batch_membership(project, ids, True)
    window.catalogue.patch(ids[0], {
        "metadata": {"agent": "Jett", "kill": 3}, "mainline": "Clutch Win",
    })
    window.catalogue.patch(ids[1], {"game": "Apex Legends", "mainline": None})
    window.catalogue.patch(ids[2], {"game": "Battlefield 6", "triage": "discard"})
    window.catalogue.patch(ids[3], {"game": "Overwatch", "triage": None})
    dialog = ProjectExportDialog(window, project)
    dialog.show()
    application.processEvents()
    assert {dialog.game.itemData(i) for i in range(dialog.game.count())} == {
        "Apex Legends", "VALORANT",
    }
    previous_prefix = dialog.field_layout.itemAt(0).widget()
    dialog.game.setCurrentIndex(dialog.game.findData("VALORANT"))
    assert previous_prefix.isHidden()
    application.processEvents()
    prefix_row = dialog.field_layout.itemAt(0).widget()
    prefix = dialog.prefix
    fields = dialog.field_layout.itemAt(1).widget()
    controls = {control.text(): control for control in fields.findChildren(QCheckBox)}
    assert prefix.text() == "Game code [VAL]"
    assert fields.y() > prefix_row.geometry().bottom()
    assert prefix.parentWidget() is dialog.include_rating.parentWidget() is prefix_row
    assert prefix.geometry().center().y() == dialog.include_rating.geometry().center().y()
    assert prefix.geometry().right() < dialog.include_rating.x()
    assert dialog.fields.geometry().bottom() < dialog.preview.y()
    assert dialog.preview.geometry().bottom() < dialog.group_rating.y()
    assert dialog.game.currentText() == "VALORANT · VAL"
    assert len({control.y() for control in controls.values()}) == 1
    assert not dialog.findChildren(QScrollArea)
    wide_height = dialog.fields.height()
    assert dialog.fields.height() == dialog.field_layout.totalHeightForWidth(dialog.fields.width())

    def assert_matches_manifest():
        clip = window.catalogue.clip(ids[0])
        manifest = prepare_export_manifest(
            [clip], window.registry, tmp_path / "output", window.catalogue.folders(),
            dialog.options["formats"], lowercase=window.settings["lowercase_generated_titles"],
        )
        assert dialog.preview.text() == f"{manifest['items'][0]['stem']}.mp4"

    assert_matches_manifest()
    spans = dialog.preview.spans
    assert [dialog.preview.text()[start:start + length] for start, length in spans] == [
        "clutch win" if theme == "light" else "Clutch Win"
    ]
    before = dialog.preview.text()
    controls["agent"].setChecked(False)
    assert dialog.preview.text() != before
    assert_matches_manifest()
    prefix.setChecked(False)
    assert dialog.preview.text().startswith("3")
    assert_matches_manifest()
    artifact = ROOT / "cache/verification/project-export-dialog"
    artifact.mkdir(parents=True, exist_ok=True)
    application.processEvents()
    dialog.grab().save(str(artifact / f"{theme}-underlined.png"))
    dialog.game.showPopup()
    application.processEvents()
    dialog.game.view().grab().save(str(artifact / f"{theme}-underlined-popup.png"))
    dialog.game.hidePopup()
    for control in controls.values():
        control.setChecked(False)
    assert dialog.preview.text() == "clip-000.mp4"
    assert not dialog.preview.spans
    assert_matches_manifest()
    artifact = ROOT / "cache/verification/project-export-dialog"
    artifact.mkdir(parents=True, exist_ok=True)
    dialog.grab().save(str(artifact / f"{theme}-wide.png"))
    dialog.resize(340, 540)
    application.processEvents()
    assert len({control.y() for control in controls.values()}) > 1
    assert all(control.geometry().right() < fields.width() for control in controls.values())
    assert dialog.fields.height() > wide_height
    assert dialog.fields.height() == dialog.field_layout.totalHeightForWidth(dialog.fields.width())
    assert all(control.geometry().bottom() < fields.height() for control in controls.values())
    dialog.grab().save(str(artifact / f"{theme}-narrow.png"))
    dialog.game.setCurrentIndex(dialog.game.findData("Apex Legends"))
    assert dialog.prefix.text() == "Game code [APX]"
    dialog.game.setCurrentIndex(dialog.game.findData("VALORANT"))
    assert not dialog.prefix.isChecked()
    assert dialog.preview.text() == "clip-000.mp4"
    dialog.reject()
    assert window.catalogue.projects()[0]["output_preferences"] == {}


@pytest.mark.parametrize("prefix", [False, True])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_export_rating_preview(window, application, tmp_path, prefix, theme):
    ids, project = seed_workspace(window, tmp_path, 1)
    window.set_theme(theme, persist=False)
    window.settings["lowercase_generated_titles"] = theme == "light"
    window.catalogue.patch(ids[0], {"rating": 4, "mainline": "Clutch: Win?"})
    window.catalogue.batch_membership(project, ids, True)
    dialog = ProjectExportDialog(window, project)
    dialog.prefix.setChecked(prefix)
    clip = window.catalogue.clip(ids[0])
    for included in (True, False):
        dialog.include_rating.setChecked(included)
        manifest = prepare_export_manifest(
            [clip], window.registry, tmp_path / "output", window.catalogue.folders(),
            dialog.options["formats"], include_rating=included,
            lowercase=theme == "light",
        )
        assert dialog.preview.text() == f"{manifest['items'][0]['stem']}.mp4"
        spans = dialog.preview.spans
        assert [dialog.preview.text()[start:start + length] for start, length in spans] == [
            "clutch_ win_" if theme == "light" else "Clutch_ Win_"
        ]
    dialog.include_rating.setChecked(True)
    for control in dialog.field_layout.itemAt(1).widget().findChildren(QCheckBox):
        control.setChecked(False)
    token = "r4" if theme == "light" else "R4"
    assert dialog.preview.text() == f"{'VAL_' if prefix else ''}{token} clip-000.mp4"
    assert not dialog.preview.spans
    dialog.show()
    application.processEvents()
    artifact = ROOT / "cache/verification/export-rating"
    artifact.mkdir(parents=True, exist_ok=True)
    dialog.grab().save(str(artifact / f"{theme}-{prefix}.png"))
    dialog.reject()


@pytest.mark.parametrize("prefix", [False, True])
def test_export_preview_tracks_mainline_through_sanitizing_and_custom_order(
    window, tmp_path, prefix
):
    ids, project = seed_workspace(window, tmp_path, 1)
    window.registry.game("VALORANT").display_order = ["mainline", "kill", "agent"]
    window.catalogue.patch(ids[0], {
        "mainline": "  CON: highlight?  ", "metadata": {"kill": 3, "agent": "Jett"},
    })
    window.catalogue.batch_membership(project, ids, True)
    dialog = ProjectExportDialog(window, project)
    dialog.prefix.setChecked(prefix)
    spans = dialog.preview.spans
    rendered = dialog.preview.text()
    mainline = rendered[spans[0][0]:sum(spans[0])]
    assert mainline == ("  con_ highlight_  " if prefix else "con_ highlight_  ")
    assert "3k jett.mp4" in rendered
    dialog.reject()


@pytest.mark.parametrize("include_rating", [False, True])
def test_export_dialog_isolation_blockers_cancel_and_enqueue(
    window, tmp_path, monkeypatch, include_rating
):
    ids, project = seed_workspace(window, tmp_path, 3)
    window.catalogue.batch_membership(project, ids, True)
    window.catalogue.patch(ids[1], {"triage": None})
    window.catalogue.patch(ids[2], {"triage": "discard"})
    window.catalogue.patch(ids[0], {"rating": 5})
    window.workspace.refresh()
    assert window.export_button.isEnabled()
    dialog = ProjectExportDialog(window, project)
    dialog.destination.setText(str(tmp_path / "out"))
    assert not dialog.submit_button.isEnabled()
    assert "Pending 1" in dialog.blockers.text()
    dialog.group_rating.setChecked(True)
    assert dialog.include_rating.isChecked()
    dialog.include_rating.setChecked(False)
    dialog.reject()
    assert window.catalogue.projects()[0]["output_preferences"] == {}
    assert not window.catalogue.export_jobs()
    window.catalogue.patch(ids[1], {"triage": "discard"})
    dialog = ProjectExportDialog(window, project)
    assert dialog.group_rating.isChecked()
    assert dialog.include_rating.isChecked()
    dialog.destination.setText(str(tmp_path / "out"))
    dialog.group_rating.setChecked(True)
    dialog.include_rating.setChecked(include_rating)
    monkeypatch.setattr(window, "add_export_job", lambda *args: None)
    dialog.submit()
    assert dialog.job_id
    record = window.catalogue.export_jobs()[0]
    assert len(record["manifest"]["items"]) == 1
    assert ("r5 " in record["manifest"]["items"][0]["stem"]) == include_rating
    assert record["manifest"]["choices"]["include_rating"] == include_rating
    assert ProjectExportDialog(window, project).include_rating.isChecked() == include_rating
    assert ProjectExportDialog(window, project).group_rating.isChecked()
    other = window.catalogue.save_project("Other")
    assert ProjectExportDialog(window, other).group_rating.isChecked()
    assert ProjectExportDialog(window, other).include_rating.isChecked()
    window.catalogue.patch(ids[0], {"mainline": "Later", "rating": 1})
    assert window.catalogue.export_jobs()[0]["manifest"] == record["manifest"]
    for clip in window.catalogue.clips():
        assert Path(clip["source_path"]).read_bytes() == b"original"


def test_compact_controls_no_pane_and_auto_add(window, application, tmp_path):
    ids, project = seed_workspace(window, tmp_path, 3)
    assert window.splitter.count() == 2
    assert not hasattr(window, "projects_toggle")
    settings = SettingsDialog(window)
    tabs = settings.findChild(QTabWidget)
    assert [tabs.tabText(i) for i in range(tabs.count())] == ["General", "Appearance"]
    settings.deleteLater()
    for clip_id in ids:
        window.catalogue.patch(clip_id, {"triage": None})
    window.catalogue.enable_folder(window.catalogue.folders()[0]["folder_id"], True)
    window.catalogue.create_session(ids)
    window.panel("Editing")
    window.catalogue.set_state("review_destination", project)
    window.update_collection_controls()
    assert not window.auto_collect_enabled
    window.edit({"triage": "keep"})
    assert not window.catalogue.member_ids(project)
    window.auto_collect_enabled = True
    window.update_collection_controls()
    window.edit({"rating": 4})
    assert not window.catalogue.member_ids(project)
    window.edit({"triage": None})
    window.edit({"triage": "keep"})
    assert window.catalogue.member_ids(project) == {ids[0]}
    window.navigate(1)
    window.show_memberships()
    window.membership_menu.actions()[0].setChecked(True)
    assert ids[1] in window.catalogue.member_ids(project)
    window.catalogue.set_state("review_destination", None)
    window.update_collection_controls()
    assert not window.auto_collect_enabled and not window.add_project_next.isEnabled()
    window.panel("Session")
    window.showMaximized()
    application.processEvents()
    assert window.splitter.count() == 2



@pytest.mark.parametrize("theme", ["light", "dark"])
def test_merged_projects_menu_membership_and_collection_gestures(
    window, application, tmp_path, theme
):
    ids, project = seed_workspace(window, tmp_path, 2)
    other = window.catalogue.save_project("Other")
    for clip_id in ids:
        window.catalogue.patch(clip_id, {"triage": None})
    folder = window.catalogue.folders()[0]["folder_id"]
    window.catalogue.enable_folder(folder, True)
    window.catalogue.create_session(ids)
    window.catalogue.enable_folder(folder, False)
    window.refresh_references()
    window.panel("Editing")
    window.set_theme(theme, persist=False)
    assert test_ui.wait_for(application, lambda: not window.transition_pending)
    assert not hasattr(window, "review_destination")
    assert not hasattr(window, "auto_add_keep")
    menu = window.membership_menu
    menu.popup(window.membership_button.mapToGlobal(QPoint(0, window.membership_button.height())))
    application.processEvents()
    actions = {action.data(): action for action in menu.actions()}
    QTest.mouseClick(menu, Qt.MouseButton.RightButton, pos=menu.actionGeometry(actions[project]).center())
    assert window.auto_add_destination() == project
    assert window.membership_button.property("autoCollection")
    assert actions[project].property("autoCollection")
    assert not window.catalogue.memberships(ids[0])
    QTest.mouseClick(menu, Qt.MouseButton.RightButton, pos=menu.actionGeometry(actions[other]).center())
    assert window.auto_add_destination() == other
    assert not actions[project].property("autoCollection")
    assert actions[other].property("autoCollection")
    QTest.mouseClick(menu, Qt.MouseButton.RightButton, pos=menu.actionGeometry(actions[other]).center())
    assert window.auto_add_destination() is None
    assert window.catalogue.state("review_destination") == other
    assert not window.membership_button.property("autoCollection")
    menu.setActiveAction(actions[project])
    QTest.keyClick(menu, Qt.Key.Key_Menu)
    assert window.auto_add_destination() == project
    QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(actions[other]).center())
    assert window.catalogue.member_ids(other) == {ids[0]}
    assert window.auto_add_destination() == project
    assert menu.isVisible()
    artifact = ROOT / "cache/verification/editing-project-controls/merged-menu"
    artifact.mkdir(parents=True, exist_ok=True)
    menu.grab().save(str(artifact / f"{theme}-menu.png"))
    menu.hide()
    window.grab().save(str(artifact / f"{theme}-editing.png"))
    window.edit({"triage": "keep"})
    assert window.catalogue.member_ids(project) == {ids[0]}
    window.panel("Browse")
    window.start_atomic_edit(ids[1], "Browse")
    assert test_ui.wait_for(application, lambda: not window.transition_pending)
    menu.popup(window.membership_button.mapToGlobal(QPoint(0, window.membership_button.height())))
    application.processEvents()
    actions = {action.data(): action for action in menu.actions()}
    QTest.mouseClick(menu, Qt.MouseButton.RightButton, pos=menu.actionGeometry(actions[other]).center())
    assert window.auto_add_destination() == project
    QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(actions[other]).center())
    assert other in window.effective_memberships()
    assert ids[1] not in window.catalogue.member_ids(other)
    menu.grab().save(str(artifact / f"{theme}-atomic-menu.png"))
    menu.hide()
    window.grab().save(str(artifact / f"{theme}-atomic.png"))
    assert window.save_atomic_edit()
    assert window.catalogue.member_ids(other) == set(ids)

def test_filename_preferences_normalize_without_mutation(registry):
    saved = {"formats": {"VALORANT": {"fields": ["agent", "removed"], "prefix": False}}}
    result = normalized_preferences(saved, {"VALORANT", "Apex Legends"}, registry, "last-folder")
    assert result["formats"]["VALORANT"] == {"fields": ["agent"], "prefix": False}
    assert (
        result["formats"]["Apex Legends"]["fields"] == registry.game("Apex Legends").display_order
    )
    assert saved["formats"]["VALORANT"]["fields"] == ["agent", "removed"]
    assert result["include_rating"] is True
    assert "include_rating" not in saved
    assert normalized_preferences(
        {**saved, "include_rating": False}, {"VALORANT"}, registry, "last-folder"
    )["include_rating"] is False


def test_workspace_project_view_state_and_readiness(window, application, tmp_path):
    ids, project = seed_workspace(window, tmp_path)
    workspace = window.workspace
    window.catalogue.batch_membership(project, ids[:4], True)
    window.catalogue.patch(ids[0], {"triage": None})
    window.catalogue.patch(ids[1], {"mainline": None})
    window.catalogue.patch(ids[2], {"triage": "discard"})
    workspace.refresh()
    assert {key: len(value) for key, value in workspace.categories.items()} == {
        "Ready": 1,
        "Pending": 1,
        "Blocked": 1,
        "Skipped": 1,
    }
    workspace.search.setText("no match")
    assert len(workspace.categories["Ready"]) == 1
    workspace.readiness_buttons["Blocked"].click()
    assert workspace.view == "Assigned"
    assert window.library.count() == 1
    assert window.selected_id(window.library) == ids[1]
    workspace.category.click()
    assert window.library.count() == 4
    workspace.search.setText("rating:>=4")
    select_view(window, "Available")
    assert workspace.search.text() == "no match"
    workspace.search.clear()
    assert window.library.count() == len(ids) - 4
    other = window.catalogue.save_project("Other")
    window.refresh_references()
    workspace.select_project(other)
    assert workspace.view == "Assigned" and window.library.count() == 0
    workspace.select_project(project)
    assert workspace.view == "Available"
    select_view(window, "Assigned")
    assert workspace.search.text() == "rating:>=4"
    workspace.search.setText("rating:>=oops")
    select_view(window, "Available")
    select_view(window, "Assigned")
    assert window.library.count() == 0
    assert not workspace.valid


def test_remove_preview_fallback_and_history_invalidation(window, tmp_path):
    ids, project = seed_workspace(window, tmp_path, 4)
    workspace = window.workspace
    workspace.matching_action.trigger()
    select_view(window, "Assigned")
    window.library.setCurrentRow(1)
    workspace.selected_action.click()
    assert window.selected_id(window.library) == ids[2]
    window.undo()
    window.start_atomic_edit(ids[0], "Export")
    window.membership(False, project)
    assert window.save_atomic_edit()
    assert not window.undo_button.isEnabled()
    assert window.editing_histories[ids[0]].undo_stack
    select_view(window, "Available")
    window.library.setCurrentRow(0)
    workspace.selected_action.click()
    assert not window.editing_histories.get(ids[0])
    window.catalogue.remove_folder(window.catalogue.folders()[0]["folder_id"], purge=True)
    window.refresh_references()
    window.refresh_library()
    assert not window.undo_button.isEnabled()


def test_restart_destinations_and_atomic_auto_add(window, application, tmp_path, close_window):
    ids, project = seed_workspace(window, tmp_path, 2)
    other = window.catalogue.save_project("Review")
    window.refresh_references()
    window.catalogue.set_state("review_destination", other)
    window.refresh_references()
    window.auto_collect_enabled = True
    window.update_collection_controls()
    window.catalogue.patch(ids[0], {"triage": None})
    window.start_atomic_edit(ids[0], "Export")
    window.edit({"triage": "keep"})
    assert other in window.effective_memberships()
    assert not window.catalogue.member_ids(other)
    assert window.save_atomic_edit()
    assert window.catalogue.member_ids(other) == {ids[0]}
    window.close()
    application.processEvents()
    restarted = Window(window.root)
    try:
        assert restarted.catalogue.state("review_destination") == other
        assert not restarted.auto_collect_enabled
        assert restarted.workspace.project_id == project
        assert restarted.workspace.view == "Assigned"
    finally:
        close_window(restarted, application)


def test_no_empty_jobs_and_submission_failure(window, tmp_path, monkeypatch):
    ids, project = seed_workspace(window, tmp_path, 1)
    window.catalogue.batch_membership(project, ids, True)
    window.catalogue.patch(ids[0], {"triage": "discard"})
    dialog = ProjectExportDialog(window, project)
    dialog.destination.setText(str(tmp_path / "out"))
    dialog.submit()
    assert not window.catalogue.export_jobs()
    window.catalogue.patch(ids[0], {"triage": "keep"})

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("database unavailable")

    monkeypatch.setattr(window.catalogue, "enqueue_project_export", fail)
    dialog.submit()
    assert "database unavailable" in dialog.error.text()
    assert not window.catalogue.export_jobs()
    assert window.catalogue.projects()[0]["output_preferences"] == {}


@pytest.mark.parametrize("blocking", ["pending", "metadata", "source", "game", "pending_only"])
def test_export_setup_prevents_blocked_submission(
    window, tmp_path, monkeypatch, blocking
):
    ids, project = seed_workspace(window, tmp_path, 2)
    window.catalogue.batch_membership(project, ids, True)
    if blocking.startswith("pending"):
        window.catalogue.patch(ids[0], {"triage": None})
        if blocking == "pending_only":
            window.catalogue.patch(ids[1], {"triage": None})
    elif blocking == "metadata":
        window.catalogue.patch(ids[0], {"metadata": {}, "mainline": None})
    elif blocking == "source":
        Path(window.catalogue.clip(ids[0])["source_path"]).unlink()
    else:
        window.catalogue.patch(ids[0], {"game": None})
    dialog = ProjectExportDialog(window, project)
    destination = tmp_path / "out"
    dialog.destination.setText(str(destination))
    dialog.group_rating.setChecked(True)
    monkeypatch.setattr(window, "add_export_job", lambda *_: None)
    assert not dialog.submit_button.isEnabled()
    assert "Resolve Pending and Blocked" in dialog.blockers.text()
    assert not dialog.blocker_notice.isHidden()
    assert dialog.submit_button.toolTip() == dialog.blockers.text()
    dialog.submit()
    assert not dialog.job_id and not destination.exists()
    assert not window.catalogue.projects()[0]["output_preferences"]
    assert not window.catalogue.export_jobs()



@pytest.mark.parametrize("theme", ["light", "dark"])
def test_workspace_visual_states(window, application, tmp_path, theme):
    ids, project = seed_workspace(window, tmp_path, 30)
    window.set_theme(theme, persist=False)
    window.catalogue.save_project("Long project name · " * 8, project)
    window.catalogue.batch_membership(project, ids[:6], True)
    window.catalogue.patch(ids[1], {"mainline": None})
    window.catalogue.patch(ids[2], {"triage": None})
    Path(window.catalogue.clip(ids[3])["source_path"]).unlink()
    window.refresh_references()
    select_view(window, "Assigned")
    window.library.item(1).setSelected(True)
    window.library.item(3).setSelected(True)
    artifact = (
        ROOT / "cache/verification/project-workspace" / os.environ.get("QT_SCALE_FACTOR", "1")
    )
    artifact.mkdir(parents=True, exist_ok=True)
    for maximized in (False, True):
        window.showMaximized() if maximized else window.showNormal()
        application.processEvents()
        for view in ("Available", "Assigned"):
            select_view(window, view)
            application.processEvents()
            workspace = window.workspace
            assert workspace.category.isHidden() == (view != "Assigned")
            if view == "Assigned":
                assert workspace.category.text() == "Clear filters"
                assert workspace.category.parentWidget() is workspace.search.parentWidget()
                assert abs(workspace.category.geometry().center().y()
                           - workspace.search.geometry().center().y()) <= 1
            assert workspace.list_footer.y() > window.library.y()
            assert workspace.matching_action in workspace.bulk_actions.menu().actions()
            assert workspace.selector.itemText(workspace.selector.count() - 1) == "New project…"
            assert [action.text() for action in workspace.more.menu().actions()] == [
                "Rename…", "Delete…"
            ]
            assert workspace.views.geometry().right() < workspace.unavailable.x()
            assert abs(workspace.views.geometry().center().y()
                       - workspace.unavailable.geometry().center().y()) <= 1
            assert workspace.unavailable.width() == 28
            assert not workspace.unavailable.text()
        assert window.workspace.readiness_buttons["Pending"].property("statusEmphasis") == "warning"
        assert window.workspace.readiness_buttons["Blocked"].property("statusEmphasis") == "error"
        assert "prevent export" in window.workspace.readiness_buttons["Blocked"].toolTip()
        assert window.splitter.count() == 2
        assert window.workspace.controls.width() <= window.left.width()
        assert window.library.horizontalScrollBar().maximum() == 0
        window.grab().save(str(artifact / f"{theme}-{'maximized' if maximized else 'normal'}.png"))
    dialog = ProjectExportDialog(window, project)
    dialog.show()
    application.processEvents()
    assert not dialog.submit_button.isEnabled()
    dialog.grab().save(str(artifact / f"{theme}-setup.png"))
    dialog.reject()
    Path(window.catalogue.clip(ids[1])["source_path"]).unlink()
    window.start_atomic_edit(ids[1], "Export")
    assert test_ui.wait_for(application, lambda: not window.transition_pending)
    assert not window.membership_menu.collection_changes_enabled
    assert not window.membership_menu.collection_changes_enabled
    window.grab().save(str(artifact / f"{theme}-editing.png"))
    window.discard_atomic_edit()


def test_export_refined_filters_and_contextual_actions(window, application, tmp_path):
    ids, project = seed_workspace(window, tmp_path, 3)
    workspace = window.workspace
    assert workspace.date_filters.isHidden()
    window.library.clearSelection()
    assert workspace.selection_actions.isHidden()
    assert workspace.matching_action.isEnabled()
    workspace.dates_toggle.click()
    assert not workspace.date_filters.isHidden()
    workspace.from_date.setText("2000-1-1")
    workspace.dates_toggle.click()
    assert workspace.date_filters.isHidden()
    assert "Active" in workspace.dates_toggle.text()
    assert workspace.state.from_date == "2000-1-1"
    select_view(window, "Assigned")
    assert not workspace.date_filters.isHidden()
    workspace.from_date.setText("not a date")
    workspace.dates_toggle.click()
    select_view(window, "Available")
    assert not workspace.date_filters.isHidden()
    assert not workspace.valid and not workspace.matching_action.isEnabled()
    select_view(window, "Assigned")
    workspace.category.click()
    assert not workspace.state.from_date and not workspace.state.through_date
    assert not workspace.date_filters.isHidden()
    workspace.history().apply(ids, True)
    workspace.refresh()
    workspace.readiness_buttons["Ready"].click()
    assert workspace.readiness_buttons["Ready"].isChecked()
    assert workspace.scope.text() == "Ready only"
    dialog = ProjectExportDialog(window, project)
    assert dialog.blocker_notice.isHidden()
    dialog.reject()
    workspace.category.click()
    assert not any(control.isChecked() for control in workspace.readiness_buttons.values())
    window.library.clearSelection()
    assert workspace.selection_actions.isHidden()
    window.library.setCurrentRow(0)
    assert not workspace.selected_action.isHidden()
    assert workspace.skip_action.isHidden()
    window.panel("Browse")
    assert workspace.list_footer.isHidden()
    window.panel("Export")
    workspace.select_project(None)
    assert workspace.more.isEnabled() and workspace.selector.isEnabled()
    assert not workspace.rename_action.isEnabled() and not workspace.delete_action.isEnabled()


def test_export_submission_rechecks_changed_sources(window, tmp_path):
    ids, project = seed_workspace(window, tmp_path, 1)
    window.catalogue.batch_membership(project, ids, True)
    dialog = ProjectExportDialog(window, project)
    dialog.destination.setText(str(tmp_path / "out"))
    assert dialog.submit_button.isEnabled()
    Path(window.catalogue.clip(ids[0])["source_path"]).unlink()
    dialog.submit()
    assert not dialog.submit_button.isEnabled()
    assert "Blocked 1" in dialog.blockers.text()
    assert not window.catalogue.export_jobs()
    assert not window.catalogue.projects()[0]["output_preferences"]


def test_ready_size_unavailable_after_validation(window, tmp_path, monkeypatch):
    from dfsorter.project_summary import ready_source_bytes

    ids, project = seed_workspace(window, tmp_path, 1)
    window.catalogue.batch_membership(project, ids, True)
    window.workspace.refresh()
    clip = window.catalogue.clip(ids[0])
    Path(clip["source_path"]).unlink()
    assert ready_source_bytes([clip], set(ids)) is None
    window.workspace.update_export_size([clip])
    assert window.workspace.export_size.text() == "1 ready · Estimated export: — GB"
    assert "could not be read" in window.workspace.export_size.toolTip()
    # Exercise the same race between readiness validation and size estimation in setup.
    monkeypatch.setattr("dfsorter.project_export_dialog.ready_source_bytes", lambda *_: None)
    dialog = ProjectExportDialog(window, project)
    assert dialog.summary.text().endswith("Estimated size: — GB")
    assert "could not be read" in dialog.summary.toolTip()


def test_export_selected_hotkeys_and_inline_dates(window, application, tmp_path):
    ids, project = seed_workspace(window, tmp_path, 4)
    workspace = window.workspace
    window.library.setCurrentRow(0)
    window.library.setFocus()
    assert workspace.selected_action.text() == "Add selected"
    assert workspace.skip_action.text() == "Skip selected"
    QTest.keyClick(window.library, Qt.Key.Key_A)
    assert window.catalogue.member_ids(project) == {ids[0]}
    assert workspace.view == "Available"
    window.library.setCurrentRow(0)
    QTest.keyClick(window.library, Qt.Key.Key_R)
    assert window.catalogue.member_ids(project) == {ids[0]}
    skipped = window.selected_id(window.library)
    QTest.keyClick(window.library, Qt.Key.Key_S)
    assert workspace.skipped_ids[project] == {skipped}
    window.library.clearSelection()
    QTest.keyClick(window.library, Qt.Key.Key_A)
    assert window.catalogue.member_ids(project) == {ids[0]}
    workspace.search.setFocus()
    QTest.keyClicks(workspace.search, "asr")
    assert workspace.search.text() == "asr"
    assert window.catalogue.member_ids(project) == {ids[0]}
    workspace.search.clear()
    select_view(window, "Assigned")
    window.library.setCurrentRow(0)
    window.library.setFocus()
    assert workspace.selected_action.text() == "Remove selected"
    QTest.keyClick(window.library, Qt.Key.Key_A)
    QTest.keyClick(window.library, Qt.Key.Key_S)
    assert window.catalogue.member_ids(project) == {ids[0]}
    QTest.keyClick(window.library, Qt.Key.Key_R)
    assert not window.catalogue.member_ids(project)
    select_view(window, "Available")
    window.library.clearSelection()
    for row in range(2):
        window.library.item(row).setSelected(True)
    assert workspace.selected_action.text() == "Add selected (2)"
    assert workspace.skip_action.text() == "Skip selected (2)"
    QApplication.sendEvent(window.library, QKeyEvent(
        QKeyEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier, "a", True,
    ))
    assert not window.catalogue.member_ids(project)
    modal = QDialog(window)
    modal.setModal(True)
    modal.show()
    application.processEvents()
    QTest.keyClick(modal, Qt.Key.Key_A)
    assert not window.catalogue.member_ids(project)
    modal.reject()
    application.processEvents()
    height = workspace.controls.height()
    toggle_width = workspace.dates_toggle.width()
    assert workspace.dates_toggle.property("iconName") == "chevron-right"
    workspace.dates_toggle.click()
    application.processEvents()
    assert workspace.controls.height() == height
    assert workspace.dates_toggle.width() == toggle_width
    assert workspace.dates_toggle.property("iconName") == "chevron-left"
    assert workspace.date_filters.x() > workspace.dates_toggle.geometry().right()
    assert abs(workspace.date_filters.geometry().center().y()
               - workspace.dates_toggle.geometry().center().y()) <= 1
    assert workspace.from_date.width() >= workspace.from_date.fontMetrics().horizontalAdvance("2026-10-09")
    counter = workspace.readiness_buttons["Ready"]
    top_gap = counter.y() - workspace.selector.geometry().bottom() - 1
    video_top = workspace.player.video_container.mapTo(counter.parentWidget(), QPoint()).y()
    bottom_gap = video_top - counter.geometry().bottom() - 1
    assert abs(top_gap - bottom_gap) <= 2
    assert workspace.selector.font().pixelSize() == 13
    assert workspace.selector.view().font().pixelSize() == 13
    workspace.from_date.setFocus()
    QTest.keyClicks(workspace.from_date, "asr")
    assert workspace.from_date.text() == "asr"
    assert not window.catalogue.member_ids(project)
    workspace.from_date.clear()
    application.processEvents()
    artifact = ROOT / "cache/verification/export-refinement"
    artifact.mkdir(parents=True, exist_ok=True)
    window.grab().save(str(artifact / "dark-inline-dates.png"))


def test_export_label_setting_and_shared_pane_width(window, application, tmp_path):
    import yaml

    ids, project = seed_workspace(window, tmp_path, 4)
    workspace = window.workspace
    window.library.setCurrentRow(0)
    assert workspace.selected_action.text() == "Add selected"
    assert workspace.selected_action.toolTip().endswith(" · A")
    assert workspace.skip_action.toolTip().endswith(" · S")
    dialog = SettingsDialog(window)
    assert not dialog.nier_hotkey_labels.isChecked()
    tabs = dialog.findChild(QTabWidget)
    tabs.setCurrentIndex(1)
    dialog.show()
    application.processEvents()
    assert dialog.nier_hotkey_labels.isVisible()
    dialog.nier_hotkey_labels.setChecked(True)
    assert workspace.selected_action.text() == "[A]dd selected"
    assert workspace.skip_action.text() == "[S]kip selected"
    assert yaml.safe_load(window.settings_path.read_text(encoding="utf-8"))["nier_automata_hotkey_labels"]
    artifact = ROOT / "cache/verification/export-refinement"
    artifact.mkdir(parents=True, exist_ok=True)
    dialog.grab().save(str(artifact / "dark-hotkey-label-setting.png"))
    dialog.reject()
    reopened = SettingsDialog(window)
    assert reopened.nier_hotkey_labels.isChecked()
    reopened.reject()
    workspace.history().apply(ids[:1], True)
    select_view(window, "Assigned")
    window.library.setCurrentRow(0)
    assert workspace.selected_action.text() == "[R]emove selected"
    assert workspace.selected_action.toolTip().endswith(" · R")
    dialog = SettingsDialog(window)
    dialog.nier_hotkey_labels.setChecked(False)
    assert workspace.selected_action.text() == "Remove selected"
    dialog.reject()
    assert not yaml.safe_load(window.settings_path.read_text(encoding="utf-8"))["nier_automata_hotkey_labels"]
    # Export must preserve both the shared minimum width and a manually widened pane.
    window.catalogue.enable_folder(window.catalogue.folders()[0]["folder_id"], True)
    window.catalogue.patch(ids[0], {"triage": None})
    window.catalogue.create_session([ids[0]])
    window.refresh_references()
    window.panel("Home")
    application.processEvents()
    window.splitter.setSizes([320, 1080])
    application.processEvents()
    width = window.left.width()
    for pane in ("Browse", "Editing", "Export", "Home"):
        window.panel(pane)
        application.processEvents()
        assert window.current_panel == pane
        assert window.left.width() == width
    window.splitter.setSizes([500, 870])
    application.processEvents()
    width = window.left.width()
    for pane in ("Export", "Editing", "Browse", "Home"):
        window.panel(pane)
        application.processEvents()
        assert window.current_panel == pane
        assert window.left.width() == width
    window.panel("Export")
    workspace.dates_toggle.setChecked(True)
    application.processEvents()
    assert window.left.width() == width


def test_export_sidebar_preserves_editing_minimum_width(window, application, tmp_path):
    ids, _project = seed_workspace(window, tmp_path, 2)
    window.catalogue.enable_folder(window.catalogue.folders()[0]["folder_id"], True)
    window.catalogue.patch(ids[0], {"triage": None})
    window.catalogue.create_session([ids[0]])
    window.refresh_references()
    window.panel("Editing")
    application.processEvents()
    window.splitter.setSizes([320, window.width() - 320])
    application.processEvents()
    width = window.left.width()
    for pane in ("Export", "Editing", "Export"):
        window.panel(pane)
        application.processEvents()
        if pane == "Export":
            window.workspace.dates_toggle.setChecked(True)
            application.processEvents()
        assert window.left.width() == width


def test_dates_drawer_focus_geometry_and_no_automatic_retraction(window, application, tmp_path):
    ids, project = seed_workspace(window, tmp_path, 2)
    workspace = window.workspace
    window.activateWindow()
    assert test_ui.wait_for(application, window.isActiveWindow)
    window.library.setFocus()
    application.processEvents()
    initial_size = workspace.dates_toggle.size()
    initial_toolbar_height = workspace.controls.height()
    for expanded in (True, False, True):
        QTest.mouseClick(workspace.dates_toggle, Qt.MouseButton.LeftButton)
        application.processEvents()
        assert workspace.dates_toggle.hasFocus()
        assert workspace.dates_toggle.size() == initial_size
        assert workspace.controls.height() == initial_toolbar_height
        assert workspace.date_filters.isHidden() == (not expanded)
    workspace.load_controls()
    assert not workspace.date_filters.isHidden()
    select_view(window, "Assigned")
    assert not workspace.date_filters.isHidden()
    workspace.from_date.setText("2000-1-1")
    workspace.from_date.clear()
    assert not workspace.date_filters.isHidden()
    workspace.category.click()
    assert not workspace.date_filters.isHidden()
    workspace.readiness_buttons["Ready"].click()
    assert not workspace.date_filters.isHidden()
    workspace.dates_toggle.click()
    assert workspace.date_filters.isHidden()


def test_export_folder_structure_defaults_and_pointer_states(window, application, tmp_path, monkeypatch):
    ids, project = seed_workspace(window, tmp_path, 1)
    window.catalogue.batch_membership(project, ids, True)
    dialog = ProjectExportDialog(window, project)
    dialog.destination.setText(str(tmp_path / "out"))
    dialog.show()
    application.processEvents()
    assert dialog.group_rating.isChecked() and not dialog.flat.isChecked()
    assert dialog.group_rating.x() < dialog.flat.x()
    artifact = ROOT / "cache/verification/project-export-dialog"
    artifact.mkdir(parents=True, exist_ok=True)
    for name, control in (("by-rating", dialog.group_rating), ("flat", dialog.flat)):
        QTest.mousePress(control, Qt.MouseButton.LeftButton)
        application.processEvents()
        assert control.hasFocus() and control.isDown()
        dialog.grab().save(str(artifact / f"dark-{name}-pressed.png"))
        QTest.mouseRelease(control, Qt.MouseButton.LeftButton)
        application.processEvents()
    assert dialog.flat.isChecked() and not dialog.group_rating.isChecked()
    monkeypatch.setattr(window, "add_export_job", lambda *_: None)
    dialog.submit()
    assert dialog.job_id
    assert window.catalogue.export_jobs()[0]["manifest"]["items"][0]["directory"] == ""
    assert not ProjectExportDialog(window, project).group_rating.isChecked()
    assert normalized_preferences(
        {"group_rating": False}, {"VALORANT"}, window.registry, ""
    )["group_rating"] is False
