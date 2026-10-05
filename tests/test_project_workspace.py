import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import test_ui
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QInputDialog, QTabWidget

from dfsorter.catalogue import Catalogue
from dfsorter.output import prepare_export_manifest, run_export_manifest
from dfsorter.playback import playback_start_settings
from dfsorter.project_export_dialog import ProjectExportDialog, normalized_preferences
from dfsorter.project_workspace import MembershipHistory, WorkspaceView, filter_candidates
from dfsorter.settings_dialog import SettingsDialog
from dfsorter.ui import ROOT, Window

application = test_ui.application
window = test_ui.window


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
    assert migrated.rows("PRAGMA user_version")[0]["user_version"] == 9


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
    window.new_project()
    created = window.workspace.project_id
    assert created != original
    assert window.workspace.view == "Library"
    assert window.catalogue.state("review_destination") == original
    window.workspace.matching_action.click()
    window.catalogue.save_export_job("frozen", {"items": [{"frozen": True}]}, "Cancelled")
    monkeypatch.setattr(QInputDialog, "getText", lambda *_args, **_kwargs: ("Renamed", True))
    window.rename_project()
    assert window.workspace.project_id == created
    assert window.workspace.selector.currentText() == "Renamed"
    assert window.catalogue.member_ids(created) == set(ids)
    window.catalogue.set_state("review_destination", created)
    window.update_collection_controls()
    assert window.auto_collect_enabled
    monkeypatch.setattr(window, "confirm", lambda *_: True)
    window.delete_project()
    assert window.workspace.project_id is None
    assert window.catalogue.state("review_destination") is None
    assert not window.auto_collect_enabled
    assert not window.workspace.export_button.isEnabled()
    assert len(window.catalogue.export_jobs()) == 1
    assert len(window.catalogue.clips()) == len(ids)
    assert all(Path(clip["source_path"]).is_file() for clip in window.catalogue.clips())


def test_filters_local_dates_unknown_and_query(catalogue, clips, registry):
    clips[0].update(triage="keep", rating=4, metadata={"agent": "Jett"})
    clips[1].update(triage="keep", rating=3)
    clips[2].update(triage="discard", rating=5)
    local = datetime(2026, 10, 5, tzinfo=datetime.now().astimezone().tzinfo)
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
        WorkspaceView(verdict="all", from_date="2026-10-05", through_date="2026-10-05")
    )
    assert result == clips[:2] and unknown == 1
    assert len(filtered(WorkspaceView(verdict="all"))[0]) == 3
    assert filtered(WorkspaceView(query="agent:Jett rating:>=4"))[0] == clips[:1]
    assert filtered(WorkspaceView(outside=True))[0] == clips[1:2]
    assert filtered(WorkspaceView(verdict="all"), member_view=True)[0] == clips[:1]
    with pytest.raises(ValueError, match="From"):
        filtered(WorkspaceView(from_date="2026-10-06", through_date="2026-10-05"))
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


def select_view(window, view):
    window.workspace.views.setCurrentText(view)
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
    for view, clip_id in (("Project clips", ids[1]), ("Library", ids[0])):
        previous_view = window.workspace.view
        previous_row = window.library.item(0)
        window.workspace.views.setCurrentText(view)
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
    window.workspace.views.setCurrentText("Project clips")
    assert window.workspace.pending_view is not None
    window.workspace.views.setCurrentText("Library")
    assert window.workspace.pending_view is None
    player.awaiting_frame = False
    player.loading_finished.emit()
    application.processEvents()
    assert window.workspace.view == "Library"
    assert window.library.count() == 2
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
    window.workspace.views.setCurrentText("Project clips")
    assert window.workspace.view == "Library"
    assert window.library.currentItem() is previous
    assert window.workspace.pending_view is not None
    assert test_ui.wait_for(application, lambda: window.workspace.pending_view is None)
    assert window.workspace.view == "Project clips"
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
    workspace.matching_action.click()
    assert window.catalogue.member_ids(project) == set(ids)
    assert window.undo_button.isEnabled()
    select_view(window, "Project clips")
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
    assert workspace.view == "Library"
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
    select_view(window, "Project clips")
    assert window.library.count() == 0
    select_view(window, "Library")
    assert window.library.count() == len(ids)


def test_export_dialog_isolation_blockers_cancel_and_enqueue(window, tmp_path, monkeypatch):
    ids, project = seed_workspace(window, tmp_path, 3)
    window.catalogue.batch_membership(project, ids, True)
    window.catalogue.patch(ids[1], {"triage": None})
    window.catalogue.patch(ids[2], {"triage": "discard"})
    window.workspace.refresh()
    assert window.export_button.isEnabled()
    dialog = ProjectExportDialog(window, project)
    dialog.destination.setText(str(tmp_path / "out"))
    assert not dialog.submit_button.isEnabled()
    assert "verdict is pending" in dialog.details.toPlainText()
    dialog.group_rating.setChecked(True)
    dialog.reject()
    assert window.catalogue.projects()[0]["output_preferences"] == {}
    assert not window.catalogue.export_jobs()
    window.catalogue.patch(ids[1], {"triage": "discard"})
    dialog = ProjectExportDialog(window, project)
    assert not dialog.group_rating.isChecked()
    dialog.destination.setText(str(tmp_path / "out"))
    dialog.group_rating.setChecked(True)
    monkeypatch.setattr(window, "add_export_job", lambda *args: None)
    dialog.submit()
    assert dialog.job_id
    record = window.catalogue.export_jobs()[0]
    assert len(record["manifest"]["items"]) == 1
    assert ProjectExportDialog(window, project).group_rating.isChecked()
    other = window.catalogue.save_project("Other")
    assert not ProjectExportDialog(window, other).group_rating.isChecked()
    window.catalogue.patch(ids[0], {"mainline": "Later"})
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
    assert workspace.view == "Project clips"
    assert window.library.count() == 1
    assert window.selected_id(window.library) == ids[1]
    workspace.category.click()
    assert window.library.count() == 4
    workspace.search.setText("rating:>=4")
    select_view(window, "Library")
    assert workspace.search.text() == "no match"
    workspace.search.clear()
    workspace.outside.setChecked(True)
    assert window.library.count() == len(ids) - 4
    other = window.catalogue.save_project("Other")
    window.refresh_references()
    workspace.select_project(other)
    assert workspace.view == "Project clips" and window.library.count() == 0
    workspace.select_project(project)
    assert workspace.view == "Library" and workspace.outside.isChecked()
    select_view(window, "Project clips")
    assert workspace.search.text() == "rating:>=4"
    workspace.search.setText("rating:>=oops")
    select_view(window, "Library")
    select_view(window, "Project clips")
    assert window.library.count() == 0
    assert not workspace.valid


def test_remove_preview_fallback_and_history_invalidation(window, tmp_path):
    ids, project = seed_workspace(window, tmp_path, 4)
    workspace = window.workspace
    workspace.matching_action.click()
    select_view(window, "Project clips")
    window.library.setCurrentRow(1)
    workspace.selected_action.click()
    assert window.selected_id(window.library) == ids[2]
    window.undo()
    window.start_atomic_edit(ids[0], "Export")
    window.membership(False, project)
    assert window.save_atomic_edit()
    assert not window.undo_button.isEnabled()
    assert window.editing_histories[ids[0]].undo_stack
    select_view(window, "Library")
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
        assert restarted.workspace.view == "Project clips"
    finally:
        close_window(restarted, application)


@pytest.mark.parametrize("verdict", [None, "discard"])
def test_no_empty_jobs_and_submission_failure(window, tmp_path, monkeypatch, verdict):
    ids, project = seed_workspace(window, tmp_path, 1)
    window.catalogue.batch_membership(project, ids, True)
    window.catalogue.patch(ids[0], {"triage": verdict})
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
    select_view(window, "Project clips")
    window.library.item(1).setSelected(True)
    window.library.item(3).setSelected(True)
    artifact = (
        ROOT / "cache/verification/project-workspace" / os.environ.get("QT_SCALE_FACTOR", "1")
    )
    artifact.mkdir(parents=True, exist_ok=True)
    for maximized in (False, True):
        window.showMaximized() if maximized else window.showNormal()
        application.processEvents()
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
