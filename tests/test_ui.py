import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")

import PySide6
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QTextDocument
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QInputDialog, QLabel, QProgressDialog

from dfsorter.catalogue import Catalogue
from dfsorter.deletion import preview
from dfsorter.deletion_dialog import DeletionDialog
from dfsorter.settings_dialog import SettingsDialog
from dfsorter.theme import FONT_SIZES
from dfsorter.ui import ROOT, Window, style_application
from dfsorter.widgets import CLIP_ROLE, FOLDER_ROLE, CaptureFolderDelegate


@pytest.fixture(scope="module")
def application():
    QCoreApplication.addLibraryPath(str(Path(PySide6.__file__).parent / "plugins"))
    instance = QApplication.instance() or QApplication([])
    style_application(instance)
    yield instance


@pytest.fixture
def window(tmp_path, application):
    shutil.copytree(ROOT / "configs", tmp_path / "configs")
    result = Window(tmp_path)
    result.show()
    application.processEvents()
    yield result
    result.close()
    application.processEvents()


def wait_for(application, predicate, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        application.processEvents()
        if predicate():
            return True
        QTest.qWait(20)
    return False


def test_video_surface_fits_landscape_and_portrait_sources(application):
    from PySide6.QtWidgets import QWidget

    from dfsorter.playback import AspectVideoContainer

    surface = QWidget()
    container = AspectVideoContainer(surface)
    container.resize(1000, 500)
    container.show()
    application.processEvents()
    try:
        container.set_video_size(1920, 1080)
        assert surface.geometry().getRect() == (55, 0, 889, 500)
        container.set_video_size(1080, 1920)
        assert surface.geometry().getRect() == (359, 0, 281, 500)
        container.set_video_size(0, 0)
        assert surface.geometry() == container.rect()
    finally:
        container.close()


def test_player_volume_geometry_and_media_colors(window, application):
    from dfsorter.theme import COLORS, THEMES

    window.panel("Browse")
    application.processEvents()
    player = window.browse.player
    assert player.volume.height() == 18
    volume_center = player.volume.mapTo(player, player.volume.rect().center()).y()
    time_center = player.time.mapTo(player, player.time.rect().center()).y()
    assert abs(volume_center - time_center) <= 1
    assert COLORS["component_timeline_progress"] == COLORS["accent_default"]
    assert COLORS["component_volume_progress"] != COLORS["component_timeline_progress"]
    assert COLORS["component_clip_scrollbar_track"] != COLORS["component_timeline_track"]
    assert COLORS["component_clip_scrollbar_thumb"] != COLORS["component_clip_scrollbar_track"]
    assert (
        THEMES["dark"]["component_clip_scrollbar_thumb"]
        != THEMES["dark"]["component_clip_scrollbar_track"]
    )
    assert THEMES["light"]["component_volume_track"] != THEMES["light"]["border_default"]


def catalogue_dump(window):
    with window.catalogue.connection() as database:
        return list(database.iterdump())


def test_atomic_single_clip_edit_save_revert_and_session_preservation(
    window, application, tmp_path, monkeypatch
):
    root = tmp_path / "atomic-captures"
    root.mkdir()
    folder = window.catalogue.add_folder(root)
    paths = [root / f"clip-{index}.mp4" for index in range(2)]
    for path in paths:
        path.write_bytes(b"video")
    window.catalogue.ingest(
        folder, [{"path": str(path), "game": "VALORANT"} for path in paths]
    )
    ids = [clip["clip_id"] for clip in window.catalogue.clips()]
    window.catalogue.create_session(ids)
    session = window.catalogue.state("session")
    history = list(window.catalogue.undo_stack)

    window.start_atomic_edit(ids[1], "Home")
    application.processEvents()
    assert window.current_panel == "Editing"
    assert window.session_heading.text() == "Single clip"
    assert window.library.count() == 1
    assert not window.next_undefined_button.isVisible()
    assert not window.player.previous_button.isEnabled()
    assert not window.player.next_button.isEnabled()
    window.edit({"rating": 4, "mainline": "Atomic title"})
    assert window.rating.value == 4
    assert window.catalogue.clip(ids[1])["rating"] is None
    assert window.catalogue.undo_stack == history
    assert window.atomic_save_button.isEnabled()
    window.save_atomic_edit()
    application.processEvents()
    assert window.current_panel == "Home"
    assert window.selected_id(window.library) == ids[1]
    assert window.catalogue.clip(ids[1])["mainline"] == "Atomic title"
    assert window.catalogue.state("session") == session
    assert len(window.catalogue.undo_stack) == len(history) + 1
    window.undo()
    assert window.catalogue.clip(ids[1])["mainline"] is None

    window.start_atomic_edit(ids[0], "Browse")
    window.edit({"tag": "temporary"})
    monkeypatch.setattr(window, "confirm_revert_atomic", lambda: True)
    window.revert_atomic_edit()
    application.processEvents()
    assert window.current_panel == "Browse"
    assert window.selected_id(window.library) == ids[0]
    assert window.browse_selected_id == ids[0]
    assert window.catalogue.clip(ids[0])["tag"] is None
    assert window.catalogue.state("session") == session


def test_atomic_return_restores_origin_scroll_position(
    window, application, tmp_path, monkeypatch
):
    root = tmp_path / "atomic-scroll"
    root.mkdir()
    folder = window.catalogue.add_folder(root)
    paths = [root / f"clip-{index:02}.mp4" for index in range(30)]
    for path in paths:
        path.write_bytes(b"video")
    window.catalogue.ingest(
        folder, [{"path": str(path), "game": "VALORANT"} for path in paths]
    )
    window.refresh_library()
    application.processEvents()
    clip_id = window.library.item(15).data(Qt.ItemDataRole.UserRole)
    scrollbar = window.library.verticalScrollBar()
    scrollbar.setValue(scrollbar.maximum() // 2)
    home_scroll = scrollbar.value()
    assert home_scroll > 0

    window.start_atomic_edit(clip_id, "Home")
    window.edit({"rating": 4})
    window.save_atomic_edit()
    application.processEvents()
    assert window.current_panel == "Home"
    assert window.selected_id(window.library) == clip_id
    assert scrollbar.value() == home_scroll

    window.panel("Browse")
    application.processEvents()
    scrollbar.setValue(scrollbar.maximum() // 3)
    browse_scroll = scrollbar.value()
    assert browse_scroll > 0
    window.start_atomic_edit(clip_id, "Browse")
    monkeypatch.setattr(window, "confirm_revert_atomic", lambda: True)
    window.revert_atomic_edit()
    application.processEvents()
    assert window.current_panel == "Browse"
    assert window.selected_id(window.library) == clip_id
    assert scrollbar.value() == browse_scroll


def test_atomic_entry_controls_and_context_target(window, application, tmp_path, monkeypatch):
    root = tmp_path / "atomic-controls"
    root.mkdir()
    path = root / "clip.mp4"
    path.write_bytes(b"video")
    folder = window.catalogue.add_folder(root)
    window.catalogue.ingest(folder, [{"path": str(path), "game": None}])
    clip_id = window.catalogue.clips()[0]["clip_id"]
    window.panel("Browse")
    application.processEvents()
    assert window.browse.edit_button.toolTip() == "Edit clip…"
    assert window.browse.edit_button.accessibleName() == "Edit clip"
    assert window.browse.edit_button.isEnabled()
    window.browse.edit_button.click()
    assert window.atomic_edit.clip_id == clip_id
    monkeypatch.setattr(window, "confirm_revert_atomic", lambda: True)
    window.revert_atomic_edit()
    window.panel("Config")
    window.context_clip_id = clip_id
    window.edit_context_clip()
    assert window.atomic_edit.origin == "Config"


def test_atomic_navigation_reverts_and_shift_enter_is_disabled(
    window, application, tmp_path, monkeypatch
):
    root = tmp_path / "atomic-prompt"
    root.mkdir()
    path = root / "clip.mp4"
    path.write_bytes(b"video")
    folder = window.catalogue.add_folder(root)
    window.catalogue.ingest(folder, [{"path": str(path), "game": "VALORANT"}])
    clip_id = window.catalogue.clips()[0]["clip_id"]

    window.start_atomic_edit(clip_id, "Home")
    window.edit({"rating": 3})
    monkeypatch.setattr(window, "confirm_revert_atomic", lambda: False)
    window.panel("Config")
    assert window.current_panel == "Editing"
    assert window.atomic_edit is not None

    window.command.setText("invalid command")
    assert not window.atomic_save_button.isEnabled()
    draft = window.atomic_edit.draft
    QTest.keyClick(window.command, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert window.atomic_edit.draft == draft
    assert window.command.text() == "invalid command"
    window.review_mode()
    QTest.keyClick(window.player, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert window.atomic_edit.draft == draft

    window.pending_in = 100
    monkeypatch.setattr(window, "confirm_revert_atomic", lambda: True)
    window.panel("Config")
    application.processEvents()
    assert window.current_panel == "Config"
    assert window.atomic_edit is None
    assert window.catalogue.clip(clip_id)["rating"] is None


def test_atomic_save_conflict_keeps_draft(window, tmp_path):
    root = tmp_path / "atomic-conflict"
    root.mkdir()
    path = root / "clip.mp4"
    path.write_bytes(b"video")
    folder = window.catalogue.add_folder(root)
    window.catalogue.ingest(folder, [{"path": str(path), "game": "VALORANT"}])
    clip_id = window.catalogue.clips()[0]["clip_id"]

    window.start_atomic_edit(clip_id, "Home")
    window.edit({"rating": 5})
    window.catalogue.patch(clip_id, {"tag": "external"})
    assert not window.save_atomic_edit()
    assert window.current_panel == "Editing"
    assert window.atomic_edit is not None
    assert window.catalogue.clip(clip_id)["rating"] is None
    assert window.catalogue.clip(clip_id)["tag"] == "external"


def test_atomic_membership_and_close_discard(window, application, tmp_path):
    root = tmp_path / "atomic-membership"
    root.mkdir()
    path = root / "clip.mp4"
    path.write_bytes(b"video")
    folder = window.catalogue.add_folder(root)
    window.catalogue.ingest(folder, [{"path": str(path), "game": "VALORANT"}])
    clip_id = window.catalogue.clips()[0]["clip_id"]
    project_id = window.catalogue.save_project("Project")
    window.refresh_references()
    window.start_atomic_edit(clip_id, "Home")
    for index in range(window.projects.count()):
        if window.projects.item(index).data(Qt.ItemDataRole.UserRole) == project_id:
            window.projects.setCurrentRow(index)
            break
    history = list(window.catalogue.undo_stack)
    window.membership(True)
    window.command.setText("jett")
    window.submit()
    assert project_id in window.effective_memberships()
    assert not window.catalogue.member_ids(project_id)
    assert window.history[clip_id] == []
    assert window.atomic_edit.history == ["jett"]
    window.save_atomic_edit()
    assert window.catalogue.member_ids(project_id) == {clip_id}
    assert len(window.catalogue.undo_stack) == len(history) + 1
    window.undo()
    assert not window.catalogue.member_ids(project_id)

    window.start_atomic_edit(clip_id, "Home")
    window.command.setText("jett")
    window.submit()
    window.edit({"rating": 2})
    window.close()
    application.processEvents()
    assert window.atomic_edit is None
    assert window.catalogue.clip(clip_id)["rating"] is None
    assert window.history[clip_id] == []


def test_browse_library_is_read_only(window, application, tmp_path, monkeypatch):
    root = tmp_path / "browse-captures"
    root.mkdir()
    folder = window.catalogue.add_folder(root)
    window.catalogue.ingest(
        folder,
        [
            {"path": str(root / f"clip-{index}.mp4"), "game": "VALORANT" if index else None}
            for index in range(3)
        ],
    )
    ids = [clip["clip_id"] for clip in window.catalogue.clips()]
    window.catalogue.patch(ids[0], {"triage": "keep"})
    window.catalogue.patch(ids[1], {"triage": "discard"})
    for index, clip in enumerate(window.catalogue.clips()):
        window.media_info[clip["source_path"]] = {"created": f"2026-09-{index + 1:02}T00:00:00Z"}
    window.refresh_references()
    before = catalogue_dump(window)
    history = list(window.catalogue.undo_stack)
    window.panel("Browse")
    assert list(window.nav) == ["Home", "Browse", "Session", "Editing", "Export", "Config"]
    assert list(window.pages) == list(window.nav)
    assert window.catalogue.state("session") is None
    assert window.library.count() == 0
    window.unavailable_toggle.click()
    assert window.library.count() == 2
    window.clip_filter.menu().actions()[0].trigger()
    assert window.library.count() == 3
    for index in range(window.library.count()):
        item = window.library.item(index)
        assert "undefined" not in item.text().lower()
        assert "2026-09-" in item.data(CLIP_ROLE)["browse_details"]
        assert "browse-captures" in item.data(CLIP_ROLE)["browse_details"]
        assert str(root) not in item.data(CLIP_ROLE)["browse_details"]
    assert window.browse_id == ids[2]
    assert window.browse.clip["clip_id"] == ids[2]
    assert window.browse.player.status.text() == "Source unavailable"
    assert not window.browse.player.play.isEnabled()
    assert not window.browse.share_button.isEnabled()
    assert not window.filters.isHidden() and window.search.isHidden()
    assert not window.browse_filters.isHidden()
    assert window.command_area.isHidden() and window.right.isHidden()
    assert not window.undo_button.isEnabled()
    assert not window.projects_toggle.isEnabled()
    window.toggle_browse_sort()
    assert window.library.item(0).data(Qt.ItemDataRole.UserRole) == ids[0]
    assert window.browse_id == ids[2]
    window.navigate(-1)
    assert window.browse_id == ids[1]
    window.browse.custom_title.setText("Disposable")
    window.browse.in_ms = 120
    window.navigate(-1)
    assert window.browse_id == ids[0]
    assert not window.browse.custom_title.text()
    assert window.browse.in_ms is None
    window.navigate(-1)
    assert window.browse_id == ids[0]
    for action in [
        lambda: window.edit({"triage": "discard"}),
        window.undo,
        lambda: window.undo(True),
        window.reset_metadata,
        window.edit_tag,
        window.new_project,
        window.delete_project,
        window.activate_project,
        lambda: window.membership(True),
        lambda: window.create_session("all"),
        window.end_session,
        window.delete_rejected,
        lambda: window.save_range(10, 20),
    ]:
        action()
    for action in window.game_filter.menu().actions():
        if action.text() == "Uncategorized":
            action.trigger()
            break
    assert window.library.count() == 2
    window.browse_search.setText("missing text")
    window.refresh_library()
    assert window.library.count() == 0
    assert window.browse.clip is None
    assert window.browse.player.status.text() == "No clip selected"
    window.panel("Home")
    assert window.clip_filter.all_selected()
    assert catalogue_dump(window) == before
    assert window.catalogue.undo_stack == history


def test_browse_temporary_range_and_share(window, application, tmp_path, monkeypatch):
    ids = add_clips(window, tmp_path, valid=True)
    window.catalogue.patch(ids[0], {"in_ms": 500, "out_ms": 1500})
    before = catalogue_dump(window)
    window.panel("Browse")
    browse = window.browse
    assert wait_for(application, lambda: not browse.player.awaiting_frame)
    assert browse.player.media.position() == 500
    assert browse.mode.currentData() is True
    browse.destination.setText(str(tmp_path / "shares"))
    browse.custom_title.setText(" ")
    assert not browse.share_button.isEnabled()
    browse.custom_title.setText("My Custom 中文 Clip")
    assert browse.share_button.isEnabled()
    browse.player.media.setPosition(800)
    window.mark_in()
    assert browse.in_ms == 800
    window.toggle_browse_sort()
    assert browse.in_ms == 800
    assert browse.custom_title.text() == "My Custom 中文 Clip"
    calls = []
    monkeypatch.setattr(
        "dfsorter.browse.share_clip", lambda *args, **kwargs: calls.append((args, kwargs))
    )
    work = []
    monkeypatch.setattr(window, "background", lambda function, done: work.append(function))
    browse.share()
    browse.custom_title.setText("Changed after snapshot")
    browse.in_ms = 1000
    work[0](lambda: False, lambda text: None)
    args, kwargs = calls[0]
    assert args[0]["in_ms"] == 800
    assert args[0]["out_ms"] == 1500
    assert kwargs["custom"] == "My Custom 中文 Clip"
    assert kwargs["selected_range"] is True
    window.clear_range()
    browse.player.media.setPosition(1800)
    window.mark_in()
    assert not browse.valid_range()
    assert browse.mode.currentData() is False
    assert browse.share_button.isEnabled()  # Whole clip needs no valid markers.
    window.panel("Home")
    assert browse.clip is None
    assert not browse.custom_title.text()
    assert catalogue_dump(window) == before
    window.panel("Browse")
    assert wait_for(application, lambda: not browse.player.awaiting_frame)
    assert (browse.in_ms, browse.out_ms) == (500, 1500)
    assert not browse.custom_title.text()


def test_all_players_mix_tracks_and_ignore_stale_loads(window, application, tmp_path):
    ids = add_clips(window, tmp_path, valid=True)
    original = window.catalogue.clip(ids[0])
    sources = []
    for count in (0, 2):
        target = tmp_path / f"tracks-{count}.mp4"
        args = ["ffmpeg", "-v", "error", "-i", original["source_path"], "-map", "0:v"]
        for _ in range(count):
            args += ["-map", "0:a:0"]
        subprocess.run(args + ["-c", "copy", str(target)], check=True, capture_output=True)
        sources.append({**original, "source_path": str(target), "in_ms": None, "out_ms": None})
    for player in (window.player, window.export_player, window.browse.player):
        player.audio.setMuted(True)
        player.load(sources[0])
        assert wait_for(application, lambda: not player.awaiting_frame)
        assert player.media.duration() > 0
        assert not player.media.hasAudio()
        assert not player.media.engine.lavfi_complex
        for clip in [sources[1], sources[0], sources[1]]:
            player.load(clip)
        assert wait_for(application, lambda: not player.awaiting_frame)
        assert Path(player.media.source().toLocalFile()) == Path(sources[1]["source_path"])
        assert player.media.hasAudio()
        assert "amix=inputs=2" in player.media.engine.lavfi_complex
        assert player.media.engine.audio_params["channel-count"] == 2
        assert not player.media.frame_image().isNull()
        status = player.media.mediaStatus()
        player.media._receive(player.media.generation - 1, "error", "obsolete source failure")
        assert player.media.mediaStatus() == status
        assert not player.status.text()
        player.load(None)


def test_browse_runtime_failure_reveals_page(window, application, tmp_path, monkeypatch):
    add_clips(window, tmp_path, valid=True)

    def missing():
        raise OSError("Playback runtime missing. Run setup-playback.ps1.")

    monkeypatch.setattr("dfsorter.mpv_backend.load_mpv", missing)
    window.panel("Browse")
    assert wait_for(application, lambda: not window.transition_pending)
    assert window.browse.player.status.text() == "Playback runtime missing. Run setup-playback.ps1."
    assert not window.browse.player.awaiting_frame
    assert not window.browse.player.play.isEnabled()


def test_browse_layout(window, application, tmp_path):
    ids = add_clips(window, tmp_path, valid=True)
    clip = window.catalogue.clip(ids[0])
    window.catalogue.patch(
        ids[0],
        {
            "mainline": "残局 中文 English — accurate shot",
            "triage": "keep",
            "metadata": {"agent": "Jett", "weapon": ["Vandal", "Sheriff"], "kill": 3},
            "in_ms": 500,
            "out_ms": 1500,
        },
    )
    window.catalogue.ingest(
        window.catalogue.folders()[0]["folder_id"],
        [
            {"path": str(tmp_path / "captures" / "unavailable.mp4"), "game": None},
        ],
    )
    window.media_info[clip["source_path"]] = {"created": "2026-09-20T00:00:00Z"}
    window.panel("Browse")
    window.browse.custom_title.setText("Weekend highlights — 精选")
    window.browse.destination.setText(str(tmp_path / "share-output"))
    assert wait_for(application, lambda: not window.transition_pending)
    scale = os.environ.get("QT_SCALE_FACTOR", "1")
    artifact = ROOT / "cache/verification/browse" / scale
    artifact.mkdir(parents=True, exist_ok=True)
    for name, show in [("normal", window.showNormal), ("maximized", window.showMaximized)]:
        show()
        window.activateWindow()
        window.raise_()
        QTest.qWait(200)
        browse = window.browse
        assert browse.player.video.height() >= 150
        assert browse.player.media._video_size == (320, 180)
        surface = browse.player.video.geometry()
        assert abs(surface.width() * 180 - surface.height() * 320) <= 320
        assert (
            browse.share_button.mapTo(browse, QPoint(0, browse.share_button.height())).y()
            <= browse.height()
        )
        assert browse.custom_title.width() > 200
        assert window.right.isHidden()
        # Capture the composed desktop region: HWND capture omits D3D child surfaces.
        rect = window.geometry()
        window.screen().grabWindow(0, rect.x(), rect.y(), rect.width(), rect.height()).save(
            str(artifact / f"{name}.png")
        )


def test_export_player_grows_with_window(window, application, tmp_path):
    ids = add_clips(window, tmp_path)
    project = window.catalogue.save_project("Export layout")
    window.catalogue.patch(ids[0], {}, membership=(project, True))
    window.refresh_references()
    window.export_project.setCurrentIndex(window.export_project.findData(project))
    window.panel("Export")
    window.resize(1400, 900)
    application.processEvents()
    normal_height = window.export_player.video.height()
    window.resize(1400, 1200)
    application.processEvents()
    assert window.export_player.video.height() >= normal_height + 250
    assert window.export_button.geometry().bottom() < window.pages["Export"][0].height()
    artifact = ROOT / "cache/verification/export-layout"
    artifact.mkdir(parents=True, exist_ok=True)
    for state, show in [("maximized", window.showMaximized), ("fullscreen", window.showFullScreen)]:
        show()
        QTest.qWait(150)
        assert window.export_player.height() > 300
        window.grab().save(str(artifact / f"{state}.png"))


def test_deletion_confirmation_and_settings(window, application, tmp_path, monkeypatch):
    ids = add_clips(window, tmp_path)
    window.catalogue.patch(ids[0], {"triage": "discard"})
    window.refresh_references()
    dialog = DeletionDialog(preview(window.catalogue), window)
    dialog.show()
    application.processEvents()
    assert dialog.tree.topLevelItemCount() == 1
    assert dialog.tree.topLevelItem(0).child(0).text(0).endswith("libx264.mp4")
    assert dialog.delete_button.isEnabled()
    dialog.reject()
    assert Path(window.catalogue.clip(ids[0])["source_path"]).exists()
    project_id = window.catalogue.save_project("Example")
    window.refresh_references()
    settings = SettingsDialog(window)
    assert not hasattr(settings, "folders")
    assert window.pages["Home"][0].isAncestorOf(window.folders)
    assert settings.projects.count() == 1
    settings.projects.setCurrentRow(0)
    settings.run_action(settings.projects, window.projects, window.activate_project)
    assert window.catalogue.state("active_project") == project_id
    window.folders.setCurrentRow(0)
    window.toggle_folder()
    assert not window.catalogue.folders()[0]["enabled"]
    monkeypatch.setattr(window, "confirm", lambda message: True)
    settings.run_action(settings.projects, window.projects, window.delete_project)
    assert not window.catalogue.projects()
    assert Path(window.catalogue.clip(ids[0])["source_path"]).exists()
    assert not window.settings_button.icon().isNull()
    settings.close()


@pytest.mark.parametrize("enabled", [True, False])
def test_home_folder_context_toggle(window, application, tmp_path, enabled):
    ids = add_clips(window, tmp_path)
    session = window.catalogue.state("session")
    target = window.catalogue.folders()[0]["folder_id"]
    other_path = tmp_path / "other-captures"
    other_path.mkdir()
    other = window.catalogue.add_folder(other_path)
    window.catalogue.enable_folder(target, enabled)
    window.refresh_references()
    window.panel("Home")
    items = {
        window.folders.item(i).data(Qt.ItemDataRole.UserRole): window.folders.item(i)
        for i in range(window.folders.count())
    }
    window.folders.setCurrentItem(items[other])
    position = window.folders.visualItemRect(items[target]).center()
    window.folders.customContextMenuRequested.emit(position)
    application.processEvents()
    menu = window.folder_context_menu
    assert menu.isVisible()
    assert window.selected_id(window.folders) == target
    assert [action.text() for action in menu.actions()] == [
        "Pause scanning" if enabled else "Resume scanning"
    ]
    action = menu.actions()[0]
    assert action.isEnabled()
    QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(action).center())
    folders = {folder["folder_id"]: folder for folder in window.catalogue.folders()}
    assert bool(folders[target]["enabled"]) is not enabled
    assert folders[other]["enabled"]
    assert window.catalogue.clip(ids[0]) is not None
    assert window.catalogue.state("session") == session
    assert window.folders.currentItem().data(FOLDER_ROLE)["status"] == (
        "Paused" if enabled else "Enabled"
    )


def test_home_folder_context_guards(window, application, tmp_path):
    add_clips(window, tmp_path)
    window.panel("Home")
    menu = window.folder_context_menu
    window.folders.customContextMenuRequested.emit(QPoint(-1, -1))
    assert not menu.isVisible()
    item = window.folders.item(0)
    position = window.folders.visualItemRect(item).center()
    window.worker = object()
    try:
        window.folders.customContextMenuRequested.emit(position)
        assert menu.isVisible()
        assert not menu.actions()[0].isEnabled()
        menu.hide()
    finally:
        window.worker = None
    item.setData(Qt.ItemDataRole.UserRole, "__unlinked__")
    window.folders.customContextMenuRequested.emit(position)
    assert not menu.isVisible()


def test_home_folder_hierarchy_and_summary(window, application, tmp_path):
    first = tmp_path / "MEDAL-EXP"
    second = tmp_path / "NVIDIA"
    first.mkdir()
    second.mkdir()
    first_id = window.catalogue.add_folder(first)
    second_id = window.catalogue.add_folder(second)
    window.catalogue.ingest(
        first_id,
        [
            {"path": str(first / "valorant-1.mp4"), "game": "VALORANT"},
            {"path": str(first / "valorant-2.mp4"), "game": "VALORANT"},
            {"path": str(first / "eft.mp4"), "game": "Escape from Tarkov"},
        ],
    )
    window.catalogue.ingest(
        second_id,
        [{"path": str(second / "unknown.mp4"), "game": None}],
    )
    window.catalogue.enable_folder(second_id, False)
    for index, clip in enumerate(window.catalogue.clips(), start=1):
        window.media_info[clip["source_path"]] = {"duration": float(index * 10)}
    window.refresh_references()
    window.panel("Home")
    application.processEvents()

    assert isinstance(window.folders.itemDelegate(), CaptureFolderDelegate)
    assert window.folder_summary.text() == "2 folders · 4 clips"
    assert window.folder_more.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon
    items = {
        window.folders.item(row).data(Qt.ItemDataRole.UserRole): window.folders.item(row)
        for row in range(window.folders.count())
    }
    first_data = items[first_id].data(FOLDER_ROLE)
    second_data = items[second_id].data(FOLDER_ROLE)
    assert first_data == {
        "path": str(first),
        "status": "Enabled",
        "enabled": True,
        "summary": "3 clips · Avg 20.0s",
        "details": "VALORANT 2   Escape from Tarkov 1",
    }
    assert second_data["status"] == "Paused"
    assert second_data["details"] == "Unknown 1"
    assert (FONT_SIZES["md"], FONT_SIZES["sm"], FONT_SIZES["xs"]) == (13, 12, 11)

    artifact = ROOT / "cache/verification/home-folders"
    artifact.mkdir(parents=True, exist_ok=True)
    window.resize(1100, 720)
    window.grab().save(str(artifact / "hierarchy-light.png"))
    window.set_theme("dark")
    application.processEvents()
    window.grab().save(str(artifact / "hierarchy-dark.png"))


def test_home_removes_folder_entries_after_confirmation(window, application, tmp_path, monkeypatch):
    ids = add_clips(window, tmp_path)
    source = Path(window.catalogue.clip(ids[0])["source_path"])
    window.panel("Home")
    window.folders.setCurrentRow(0)
    window.update_folder_actions()
    assert window.folder_toggle_action.text() == "Pause scanning"
    assert window.folder_remove_action.isEnabled()
    monkeypatch.setattr(window, "confirm_folder_removal", lambda folder, clips: False)
    window.remove_folder()
    assert len(window.catalogue.clips()) == 1
    monkeypatch.setattr(window, "confirm_folder_removal", lambda folder, clips: True)
    window.remove_folder()
    assert not window.catalogue.clips() and not window.catalogue.folders()
    assert window.catalogue.state("session") is None
    assert not window.nav["Editing"].isEnabled()
    assert source.read_bytes() == b"test"
    backup = next((window.root / "data/backups").glob("*.db"))
    assert Catalogue(backup).clip(ids[0])["source_path"] == str(source.resolve())
    artifact = ROOT / "cache/verification/home-folders"
    artifact.mkdir(parents=True, exist_ok=True)
    application.processEvents()
    window.grab().save(str(artifact / "home.png"))


def test_settings_preserves_capture_folder_case(window, tmp_path):
    captures = tmp_path / "My Captures 游戏"
    captures.mkdir()
    window.catalogue.add_folder(captures)
    window.catalogue = Catalogue(window.catalogue.path)
    window.refresh_references()
    settings = SettingsDialog(window)
    assert str(captures.resolve()) in window.folders.item(0).text()
    settings.close()


def test_playback_preferences_persist(window, application):
    settings = SettingsDialog(window)
    assert settings.start_near_end.isChecked()
    assert settings.start_offset.value() == 40
    assert settings.paused_typing.isChecked()
    settings.paused_typing.setChecked(False)
    settings.start_offset.setValue(17)
    settings.start_near_end.setChecked(False)
    assert not settings.start_offset.isEnabled()
    settings.close()
    restarted = Window(window.root)
    try:
        restored = SettingsDialog(restarted)
        assert restored.start_offset.value() == 17
        assert not restored.start_near_end.isChecked()
        assert not restored.paused_typing.isChecked()
        assert restarted.player.settings["start_near_end_seconds"] == 17
        assert restarted.export_player.settings["start_near_end_enabled"] is False
        restored.close()
    finally:
        restarted.close()
        application.processEvents()


def test_theme_switching_and_persistence(window, application):
    import yaml

    from dfsorter.theme import COLORS, THEMES

    settings = SettingsDialog(window)
    assert settings.theme.currentData() == "light"
    assert COLORS["surface_canvas"] == THEMES["light"]["surface_canvas"]
    assert (
        len(
            {
                COLORS["surface_canvas"],
                COLORS["surface_workspace"],
                COLORS["surface_sidebar"],
            }
        )
        == 3
    )
    assert window.left.property("role") == "sidebar"
    assert window.right.property("role") == "sidebar"
    assert window.shortcut_hint.property("role") == "helper"
    assert window.theme_button.toolTip() == "Switch to dark mode"

    settings.theme.setCurrentIndex(settings.theme.findData("dark"))
    application.processEvents()
    assert COLORS["surface_canvas"] == THEMES["dark"]["surface_canvas"]
    assert window.theme_button.toolTip() == "Switch to light mode"
    assert yaml.safe_load(window.settings_path.read_text(encoding="utf-8"))["theme"] == "dark"
    settings.close()

    restarted = Window(window.root)
    try:
        assert restarted.settings["theme"] == "dark"
        assert restarted.theme_button.toolTip() == "Switch to light mode"
        assert COLORS["surface_canvas"] == THEMES["dark"]["surface_canvas"]
    finally:
        restarted.close()
        application.processEvents()

    window.set_theme("light")
    settings = SettingsDialog(window)
    settings.theme.setCurrentIndex(settings.theme.findData("system"))
    assert window.settings["theme"] == "system"
    resolved_before_toggle = COLORS["surface_canvas"]
    settings.close()
    window.theme_button.click()
    assert window.settings["theme"] in {"light", "dark"}
    assert COLORS["surface_canvas"] != resolved_before_toggle
    window.set_theme("light")


def add_clips(window, tmp_path, valid=False, codec="libx264"):
    captures = tmp_path / "captures"
    captures.mkdir(exist_ok=True)
    path = captures / f"{codec}.mp4"
    if valid:
        codec_options = ["-cpu-used", "8"] if codec == "libaom-av1" else []
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=320x180:rate=24",
                "-f",
                "lavfi",
                "-i",
                # Keep an audio track for playback coverage without audible test tones.
                "anullsrc=channel_layout=mono:sample_rate=44100",
                "-t",
                "3",
                "-c:v",
                codec,
                *codec_options,
                "-threads",
                "2",
                "-c:a",
                "aac",
                str(path),
            ],
            check=True,
            capture_output=True,
        )
    else:
        path.write_bytes(b"test")
    folder_id = window.catalogue.add_folder(captures)
    window.catalogue.ingest(folder_id, [{"path": str(path), "game": "VALORANT"}])
    ids = [clip["clip_id"] for clip in window.catalogue.clips()]
    window.catalogue.create_session(ids)
    window.refresh_references()
    return ids


def test_keyboard_and_session_ui(window, application, tmp_path):
    assert not window.nav["Editing"].isEnabled()
    ids = add_clips(window, tmp_path)
    window.panel("Editing")
    application.processEvents()
    window.command.setFocus()
    window.command.setText("jett vandal R4")
    QTest.keyClick(window.command, Qt.Key.Key_Return)
    assert window.catalogue.clip(ids[0])["triage"] is None
    assert window.catalogue.clip(ids[0])["rating"] == 4
    assert application.focusWidget() is window.command
    window.command.setFocus()
    window.command.setText("sage jett")
    QTest.keyClick(window.command, Qt.Key.Key_Return)
    assert window.command.text() == "sage jett"
    assert window.catalogue.clip(ids[0])["metadata"]["agent"] == "Jett"
    window.command.setText("abc")
    QTest.keyClick(window.command, Qt.Key.Key_Backspace)
    assert window.command.text() == "ab"
    window.command.clear()
    QTest.keyClick(window.command, Qt.Key.Key_Backspace)
    assert window.catalogue.clip(ids[0])["triage"] is None
    QTest.keyClick(window.command, Qt.Key.Key_Escape)
    QTest.keyClick(window.player, Qt.Key.Key_Backspace)
    assert window.catalogue.clip(ids[0])["triage"] == "discard"
    window.command.setFocus()
    QTest.keyClick(window.command, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert window.catalogue.clip(ids[0])["triage"] == "discard"
    window.edit({"triage": None})
    window.command.setFocus()
    QTest.keyClick(window.command, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert window.catalogue.clip(ids[0])["triage"] == "keep"
    QTest.keyClick(window.command, Qt.Key.Key_Escape)
    QTest.keyClick(window.player, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert window.catalogue.clip(ids[0])["triage"] == "keep"
    assert window.search.isHidden() and window.filters.isHidden()
    window.panel("Export")
    assert window.right.isHidden() and window.command_area.isHidden()
    window.panel("Session")
    assert not window.filters.isHidden()


def test_review_advance_is_separate_from_submission(window, application, tmp_path):
    ids = add_clips(window, tmp_path)
    captures = tmp_path / "captures"
    second = captures / "second.mp4"
    second.write_bytes(b"test")
    window.catalogue.ingest(
        window.catalogue.folders()[0]["folder_id"], [{"path": str(second), "game": "VALORANT"}]
    )
    next_id = next(
        clip["clip_id"] for clip in window.catalogue.clips() if clip["clip_id"] != ids[0]
    )
    window.catalogue.create_session([ids[0], next_id], replace=True)
    window.panel("Editing")
    QTest.keyClick(window.player, Qt.Key.Key_Return)
    assert application.focusWidget() is window.command
    assert window.command.text() == ""
    assert window.catalogue.clip(ids[0])["triage"] is None
    QTest.keyClick(window.command, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert window.current_id == ids[0]
    assert application.focusWidget() is window.command
    assert "at least one metadata field or mainline" in window.command_error.text()
    QTest.keyClick(window.command, Qt.Key.Key_Escape)
    QTest.keyClick(window.player, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert window.current_id == ids[0]
    assert "at least one metadata field or mainline" in window.command_error.text()
    window.command.setFocus()
    window.command.setText("jett vandal")
    QTest.keyClick(window.command, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert window.catalogue.clip(ids[0])["metadata"] == {}
    assert window.command.text() == "jett vandal"
    QTest.keyClick(window.command, Qt.Key.Key_Escape)
    window.edit({"triage": "discard"})
    QTest.keyClick(window.player, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert window.current_id == ids[0]
    assert "submit existing commands" in window.command_error.text()
    window.command.clear()
    window.command.setFocus()
    window.command.setText(" ")
    QTest.keyClick(window.command, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert window.current_id == ids[0]
    assert window.command.text() == " "
    window.command.clear()
    QTest.keyClick(window.command, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert window.current_id == next_id
    assert window.catalogue.clip(ids[0])["triage"] == "discard"
    window.command.setFocus()
    window.command.setText("jett vandal")
    QTest.keyClick(window.command, Qt.Key.Key_Return)
    assert window.current_id == next_id
    assert window.catalogue.clip(next_id)["triage"] is None
    QTest.keyClick(window.command, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert window.catalogue.clip(next_id)["triage"] == "keep"
    assert "Session complete" in window.statusBar().currentMessage()


def test_field_checklist_previews_commands_without_saving(window, application, tmp_path):
    ids = add_clips(window, tmp_path)
    window.panel("Editing")
    saved = window.catalogue.clip(ids[0])
    original = window.field_reminder.text()
    window.command.setFocus()
    QTest.keyClicks(window.command, "jett R3 -- Example")
    for key in ("agent", "rating", "mainline"):
        assert f"✓&nbsp;{key}" in window.field_reminder.text()
    assert "press Enter to save" in window.field_reminder.toolTip()
    assert window.catalogue.clip(ids[0]) == saved
    window.render_clip()
    assert "✓&nbsp;agent" in window.field_reminder.text()
    window.command.setText('jett tag:"unfinished')
    assert "✓&nbsp;agent" in window.field_reminder.text()
    assert window.command.property("validationState") == "incomplete"
    assert window.command_error.isHidden()
    window.command.clear()
    assert window.field_reminder.text() == original
    window.command.setText("jett tag:Example")
    window.submit()
    assert window.catalogue.clip(ids[0])["metadata"]["agent"] == "Jett"
    window.command.setText('tag:""')
    assert "o&nbsp;tag" in window.field_reminder.text()
    assert "✓&nbsp;agent" in window.field_reminder.text()
    assert window.catalogue.clip(ids[0])["tag"] == "Example"
    window.command.clear()
    assert "✓&nbsp;tag" in window.field_reminder.text()


def test_bracket_tag_rating_preview_and_third_party_title(window, application, tmp_path):
    ids = add_clips(window, tmp_path)
    window.catalogue.patch(ids[0], {"tag": "3RD", "mainline": "Player clutch"})
    window.panel("Editing")
    window.render_clip()
    assert "!&nbsp;agent" in window.field_reminder.text()
    assert "!&nbsp;weapon" in window.field_reminder.text()
    assert "<u>player</u> clutch" in window.working_title.text().lower()
    assert "<u>player</u> clutch" in window.library.item(0).data(CLIP_ROLE)["rich_title"].lower()
    window.command.setText("[3rd] R4")
    assert "[3rd] · Existing" in window.command_feedback.text()
    original_clips = window.catalogue.clips
    try:
        window.catalogue.clips = lambda: (_ for _ in ()).throw(AssertionError("full scan"))
        window.command.setText("[3RD] R4")
        assert "[3RD] · Existing" in window.command_feedback.text()
    finally:
        window.catalogue.clips = original_clips
    assert window.rating.command_preview == 4
    assert not window.rating_clear.isEnabled()
    assert window.rating_clear.toolTip() == "Rating pending · press Enter"
    window.command.setText("[3rd] R9")
    assert window.rating.command_preview is None
    assert window.rating_clear.isEnabled()
    window.command.setText("[3rd] R4")
    window.panel("Session")
    assert not window.rating_preview_timer.isActive()
    window.panel("Editing")
    assert window.rating.command_preview == 4
    window.submit()
    assert window.catalogue.clip(ids[0])["rating"] == 4
    assert window.rating.command_preview is None


def test_reject_then_enter_is_one_shot(window, application, tmp_path):
    ids = add_clips(window, tmp_path)
    second = tmp_path / "captures" / "second.mp4"
    second.write_bytes(b"test")
    window.catalogue.ingest(
        window.catalogue.folders()[0]["folder_id"], [{"path": str(second), "game": "VALORANT"}]
    )
    next_id = next(
        clip["clip_id"] for clip in window.catalogue.clips() if clip["clip_id"] != ids[0]
    )
    window.catalogue.create_session([ids[0], next_id], replace=True)
    window.panel("Editing")
    QTest.keyClick(window.player, Qt.Key.Key_Backspace)
    assert window.reject_enter_armed
    QTest.keyClick(window.player, Qt.Key.Key_Return)
    assert window.current_id == next_id
    assert not window.reject_enter_armed
    QTest.keyClick(window.player, Qt.Key.Key_Backspace)
    QTest.keyClick(window.player, Qt.Key.Key_Left)
    assert not window.reject_enter_armed
    QTest.keyClick(window.player, Qt.Key.Key_Return)
    assert application.focusWidget() is window.command


def test_command_validation_colors_and_save_feedback(window, application, tmp_path):
    ids = add_clips(window, tmp_path)
    window.panel("Editing")
    window.command.setFocus()
    artifact = ROOT / "cache/verification/command-validation"
    artifact.mkdir(parents=True, exist_ok=True)
    for text, state in [
        ("", "empty"),
        ("je", "typing"),
        ("jett", "valid"),
        ("jett va", "typing"),
        ("jett tag:", "incomplete"),
        ("jett nonsense ", "invalid"),
        ("R9", "invalid"),
    ]:
        window.command.setText(text)
        window.update_command_state()
        assert window.command.property("validationState") == state
        application.processEvents()
        window.command_area.grab().save(str(artifact / f"{state}.png"))
    window.command.setText("je")
    window.submit()
    assert window.command.property("validationState") == "invalid"
    assert "Unknown metadata" in window.command_feedback.text()
    window.command.setText("jett")
    assert window.command_error.isHidden()
    assert window.command.property("validationState") == "valid"
    window.submit()
    assert window.command.property("validationState") == "saved"
    assert window.command_feedback.text() == "Saved"
    window.command_area.grab().save(str(artifact / "saved.png"))
    assert window.catalogue.clip(ids[0])["metadata"]["agent"] == "Jett"
    assert wait_for(application, lambda: window.command.property("validationState") == "empty", 3)
    assert window.command_feedback.text() == ""


def test_editing_session_counts_and_list_height(window, application, tmp_path):
    ids = add_clips(window, tmp_path)
    folder = window.catalogue.folders()[0]
    window.catalogue.ingest(
        folder["folder_id"],
        [{"path": str(tmp_path / "captures" / "outside-session.mp4"), "game": None}],
    )
    window.panel("Editing")
    application.processEvents()
    assert window.session_position.text() == "1 / 1"
    assert window.session_counts.text() == "0/1 (0 rejected)"
    item = window.library.item(0)
    window.edit({"triage": "keep"})
    assert window.session_counts.text() == "1/1 (0 rejected)"
    window.edit({"triage": "discard"})
    assert window.session_counts.text() == "1/1 (1 rejected)"
    assert window.library.item(0) is item
    window.undo()
    assert "1/1 (0 rejected)" in window.session_counts.text()
    window.undo()
    assert "0/1 (0 rejected)" in window.session_counts.text()
    assert window.catalogue.state("session")["ids"] == ids
    assert window.description.isHidden()
    assert window.command_history.isHidden()
    assert window.command_error.isHidden()
    command_y = window.command.mapTo(window.center_column, QPoint(0, 0)).y()
    area_y = window.command_area.y()
    window.command.setText("-- Example title -- Notes <keep literal>")
    window.submit()
    application.processEvents()
    assert not window.command_history.isHidden()
    assert abs(window.command.mapTo(window.center_column, QPoint(0, 0)).y() - command_y) <= 1
    assert window.command_area.y() < area_y
    assert window.command_area.height() - window.field_reminder.geometry().bottom() <= 5
    assert window.description.text() == "Notes <keep literal>"
    assert not window.description.isHidden()
    assert window.catalogue.clip(ids[0])["description"] == "Notes <keep literal>"
    window.edit({"description": None})
    assert window.description.isHidden()
    assert window.add_project_next.parentWidget() is window.player
    application.processEvents()
    assert window.library_error.isHidden()
    assert window.left.objectName() == "clipLibraryPane"
    assert window.splitter.objectName() == "workspaceSplitter"
    assert window.splitter.handleWidth() == 5
    assert window.next_undefined_button.property("sessionAction") is True
    assert window.session_header.geometry().bottom() < window.library.geometry().top()
    assert window.left.height() == window.center_column.height()
    assert window.session_counts.geometry().bottom() >= window.left.height() - 8
    assert window.left.mapTo(window, QPoint(0, 0)).x() == 13
    heading = window.session_header.findChild(QLabel)
    heading_x = heading.mapTo(window.left, QPoint(0, 0)).x()
    footer_x = window.session_counts.mapTo(window.left, QPoint(0, 0)).x() + 8
    card_title_x = window.library.mapTo(window.left, QPoint(0, 0)).x() + 1 + 7
    assert heading_x == footer_x == card_title_x
    artifact = ROOT / "cache/verification/session-counts"
    artifact.mkdir(parents=True, exist_ok=True)
    assert wait_for(application, lambda: not window.transition_pending)
    window.grab().save(str(artifact / "editing.png"))
    window.set_theme("dark")
    application.processEvents()
    window.grab().save(str(artifact / "editing-dark.png"))
    window.panel("Export")
    assert window.session_counts.isHidden()
    window.panel("Session")
    application.processEvents()
    card_title_x = window.library.mapTo(window, QPoint(0, 0)).x() + 1 + 7
    assert window.search.mapTo(window, QPoint(0, 0)).x() == card_title_x
    assert window.clip_filter.mapTo(window, QPoint(0, 0)).x() == card_title_x
    window.panel("Browse")
    application.processEvents()
    card_title_x = window.library.mapTo(window, QPoint(0, 0)).x() + 1 + 7
    assert window.browse_search.mapTo(window, QPoint(0, 0)).x() == card_title_x
    assert window.clip_filter.mapTo(window, QPoint(0, 0)).x() == card_title_x
    assert wait_for(application, lambda: not window.transition_pending)
    window.grab().save(str(artifact / "browse-dark.png"))


def test_review_advance_skips_verdicts_without_wrapping(window, application, tmp_path):
    add_clips(window, tmp_path)
    folder = window.catalogue.folders()[0]
    window.catalogue.ingest(
        folder["folder_id"],
        [
            {"path": str(tmp_path / "captures" / f"extra-{index}.mp4"), "game": None}
            for index in range(4)
        ],
    )
    ids = [clip["clip_id"] for clip in window.catalogue.clips()]
    window.catalogue.create_session(ids, replace=True)
    for index, triage in [(0, "discard"), (1, "keep"), (2, "discard"), (4, "keep")]:
        window.catalogue.patch(ids[index], {"triage": triage})
    window.panel("Editing")
    QTest.keyClick(window.player, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert window.current_id == ids[3]
    assert window.catalogue.state("session")["index"] == 3
    assert window.catalogue.clip(ids[0])["triage"] == "discard"
    window.catalogue.patch(ids[1], {"triage": None})
    window.edit({"triage": "discard"})
    window.advance_review()
    assert window.current_id == ids[3]
    assert "earlier" in window.statusBar().currentMessage()
    window.catalogue.patch(ids[1], {"triage": "keep"})
    window.advance_review()
    assert window.current_id == ids[3]
    assert "Session complete" in window.statusBar().currentMessage()
    assert window.catalogue.state("session")["ids"] == ids


def test_startup_rescans_enabled_folders(application, tmp_path):
    from dfsorter.catalogue import Catalogue

    shutil.copytree(ROOT / "configs", tmp_path / "configs")
    catalogue = Catalogue(tmp_path / "data/dfsorter.db")
    enabled = tmp_path / "VALORANT"
    disabled = tmp_path / "disabled"
    enabled.mkdir()
    disabled.mkdir()
    enabled_id = catalogue.add_folder(enabled)
    disabled_id = catalogue.add_folder(disabled)
    catalogue.enable_folder(disabled_id, False)
    original = enabled / "original.mp4"
    original.write_bytes(b"test")
    catalogue.ingest(enabled_id, [{"path": str(original), "game": "VALORANT"}])
    clip_id = catalogue.clips()[0]["clip_id"]
    catalogue.patch(clip_id, {"triage": "discard", "mainline": "Preserved"})
    catalogue.create_session([clip_id])
    original.unlink()
    (enabled / "new.mp4").write_bytes(b"test")
    (disabled / "ignored.mp4").write_bytes(b"test")
    result = Window(tmp_path)
    result.show()
    try:
        assert wait_for(
            application, lambda: result.worker is None and len(result.catalogue.clips()) == 2
        )
        assert result.catalogue.clip(clip_id)["mainline"] == "Preserved"
        assert result.catalogue.clip(clip_id)["triage"] == "discard"
        assert result.catalogue.state("session")["ids"] == [clip_id]
        assert all(
            Path(clip["source_path"]).name != "ignored.mp4" for clip in result.catalogue.clips()
        )
    finally:
        result.close()
        application.processEvents()


def test_cards_and_verdict_state(window, application, tmp_path):
    ids = add_clips(window, tmp_path)
    window.panel("Editing")
    window.edit({"mainline": "discard keep 中文 title", "triage": None})
    window.refresh_library()
    item = window.library.item(0)
    assert item.data(Qt.ItemDataRole.UserRole) == ids[0]
    assert item.data(CLIP_ROLE)["triage"] is None
    assert "discard keep" in item.data(CLIP_ROLE)["title"]
    assert "pending" in item.text().lower()
    assert window.triage_buttons[None].isChecked()
    assert window.triage_buttons[None].text() == "Pending"
    assert window.triage_buttons[None].toolTip() == "Clear verdict and mark as pending"
    QTest.mouseClick(window.triage_buttons["keep"], Qt.MouseButton.LeftButton)
    assert window.catalogue.clip(ids[0])["triage"] == "keep"
    assert window.triage_buttons["keep"].isChecked()
    assert not window.triage_buttons[None].isChecked()
    window.edit({"triage": "discard"})
    assert window.triage_buttons["discard"].isChecked()
    window.undo()
    assert window.triage_buttons["keep"].isChecked()
    window.undo(True)
    assert window.triage_buttons["discard"].isChecked()
    window.edit({"rating": 2})
    application.processEvents()
    position = QPointF(window.rating.step * 3 + 4, 10)
    application.sendEvent(
        window.rating,
        QMouseEvent(
            QEvent.Type.MouseMove,
            position,
            position,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    assert window.rating.preview == 4
    assert window.catalogue.clip(ids[0])["rating"] == 2
    QTest.mouseClick(
        window.rating, Qt.MouseButton.LeftButton, pos=QPoint(window.rating.step * 3 + 4, 10)
    )
    assert window.catalogue.clip(ids[0])["rating"] == 4
    QTest.mouseClick(window.rating, Qt.MouseButton.RightButton)
    assert window.catalogue.clip(ids[0])["rating"] is None
    assert window.catalogue.clip(ids[0])["triage"] == "discard"


@pytest.mark.parametrize("codec", ["libx264", "libaom-av1"])
def test_real_playback(window, application, tmp_path, codec):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg required for playback fixtures")
    ids = add_clips(window, tmp_path, valid=True, codec=codec)
    window.panel("Editing")
    player = window.player
    assert wait_for(application, lambda: player.media.duration() > 0 and not player.awaiting_frame)
    assert not player.media.frame_image().isNull()
    assert player.media.playbackState() == QMediaPlayer.PlaybackState.PausedState
    window.catalogue.patch(ids[0], {"in_ms": 500, "out_ms": 1500})
    clip = window.catalogue.clip(ids[0])
    for preview_player in [window.player, window.export_player]:
        preview_player.load(clip)
        assert wait_for(application, lambda: not preview_player.awaiting_frame)
        assert preview_player.media.position() == 500
        assert preview_player.seek.value() == 500
        assert preview_player.media.playbackState() == QMediaPlayer.PlaybackState.PausedState
        for start, end in [(None, None), (500, None), (1500, 500), (500, 999999)]:
            preview_player.load({**clip, "in_ms": start, "out_ms": end})
            assert wait_for(application, lambda: not preview_player.awaiting_frame)
            assert preview_player.media.position() == 0
        # A smaller offset exercises seeking from the end with the short real fixture.
        settings = SettingsDialog(window)
        settings.start_offset.setValue(1)
        for start, end in [(None, None), (500, None), (1500, 500), (500, 999999)]:
            preview_player.load({**clip, "in_ms": start, "out_ms": end})
            assert wait_for(application, lambda: not preview_player.awaiting_frame)
            assert preview_player.media.position() == preview_player.media.duration() - 1000
            assert preview_player.media.playbackState() == QMediaPlayer.PlaybackState.PausedState
        preview_player.load(clip)
        assert wait_for(application, lambda: not preview_player.awaiting_frame)
        assert preview_player.media.position() == 500
        settings.start_near_end.setChecked(False)
        preview_player.load({**clip, "in_ms": None, "out_ms": None})
        assert wait_for(application, lambda: not preview_player.awaiting_frame)
        assert preview_player.media.position() == 0
        # Natural completion must not leave either player unable to seek/resume.
        for drag in (False, True):
            preview_player.media.setPosition(preview_player.media.duration() - 200)
            preview_player.media.play()
            assert wait_for(application, lambda: preview_player.ended)
            if drag:
                preview_player.begin_scrub()
                preview_player.queue_seek(700)
                preview_player.preview_seek()
                assert (
                    preview_player.media.playbackState() == QMediaPlayer.PlaybackState.PausedState
                )
                preview_player.seek.setSliderPosition(700)
                preview_player.end_scrub()
            else:
                preview_player.seek_to(700)
            assert wait_for(
                application,
                lambda: (
                    preview_player.media.playbackState() == QMediaPlayer.PlaybackState.PlayingState
                    and 700 < preview_player.media.position() < 2000
                    and not preview_player.media.frame_image().isNull()
                ),
            )
            preview_player.media.pause()
        preview_player.seek_to(500)
        assert preview_player.media.playbackState() == QMediaPlayer.PlaybackState.PausedState
        settings.start_offset.setValue(40)
        settings.start_near_end.setChecked(True)
        settings.close()
    window.export_player.load(None)
    window.command.setFocus()
    window.command.setText("jett")
    QTest.keyClick(window.command, Qt.Key.Key_Space)
    assert window.command.text() == "jett "
    assert player.media.playbackRate() == 1
    window.command.clear()
    QTest.keyClick(window.command, Qt.Key.Key_Space)
    assert window.command.text() == " "
    QTest.keyClick(window.command, Qt.Key.Key_Escape)
    QTest.keyPress(window.player, Qt.Key.Key_Space)
    QTest.qWait(250)
    assert player.media.playbackRate() == 3
    QTest.keyRelease(window.player, Qt.Key.Key_Space)
    assert player.media.playbackRate() == 1
    assert player.media.hasAudio()
    player.media.setPosition(500)
    assert wait_for(application, lambda: player.media.position() >= 450)
    window.mark_in()
    player.media.setPosition(1500)
    assert wait_for(application, lambda: player.media.position() >= 1450)
    window.mark_out()
    assert window.catalogue.clip(ids[0])["out_ms"] > window.catalogue.clip(ids[0])["in_ms"]
    player.fast(True)
    assert player.media.playbackRate() == 3
    player.fast(False)
    assert player.media.playbackRate() == 1
    assert player.media.playbackState() == QMediaPlayer.PlaybackState.PausedState
    player.mute.setChecked(True)
    assert player.audio.isMuted()
    player.media.setPosition(1000)
    QTest.qWait(300)
    artifact = ROOT / "cache/verification"
    artifact.mkdir(parents=True, exist_ok=True)
    window.grab().save(str(artifact / f"editing-{codec}.png"))
    window.screen().grabWindow(int(window.winId())).save(str(artifact / f"screen-{codec}.png"))
    player.media.frame_image().save(str(artifact / f"decoded-video-{codec}.png"))
    left_width, _, right_width = window.splitter.sizes()
    window.showMaximized()
    QTest.qWait(300)
    assert abs(window.splitter.sizes()[0] - left_width) < 10
    assert right_width == 0
    assert window.right.isVisible()
    window.grab().save(str(artifact / f"maximized-{codec}.png"))


def test_paused_typing_and_submit_resume(window, application, tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg required for playback fixtures")
    ids = add_clips(window, tmp_path, valid=True)
    window.panel("Editing")
    assert wait_for(application, window.editing_paused)
    window.review_mode()
    assert window.command.property("commandState") == "paused"
    artifact = ROOT / "cache/verification/command-states"
    artifact.mkdir(parents=True, exist_ok=True)
    window.grab().save(str(artifact / "paused.png"))
    QTest.keyClick(window.player, Qt.Key.Key_I)
    assert application.focusWidget() is window.player
    QTest.keyClick(window.player, Qt.Key.Key_R)
    assert application.focusWidget() is window.command
    QTest.keyClick(window.command, Qt.Key.Key_4)
    assert window.command.text() == "r4"
    assert window.catalogue.clip(ids[0])["rating"] is None
    QTest.keyClick(window.command, Qt.Key.Key_Return)
    assert window.catalogue.clip(ids[0])["rating"] == 4
    QTest.keyClick(window.command, Qt.Key.Key_Escape)
    QTest.keyClick(window.player, Qt.Key.Key_B)
    assert window.command.text() == "b"
    assert window.command.property("commandState") == "input"
    window.grab().save(str(artifact / "input.png"))
    QTest.keyClicks(window.command, "rim tag:LOW_FPS")
    QTest.keyClick(window.command, Qt.Key.Key_Return)
    assert application.focusWidget() is window.command
    assert window.command.property("commandState") == "resume"
    window.grab().save(str(artifact / "resume.png"))
    assert window.library.item(0).data(CLIP_ROLE)["title"].startswith("[LOW_FPS] VAL_")
    assert window.catalogue.clip(ids[0])["metadata"]["agent"] == "Brimstone"
    QTest.keyPress(window.command, Qt.Key.Key_Space)
    QTest.qWait(250)
    QTest.keyRelease(window.player, Qt.Key.Key_Space)
    assert window.command.text() == ""
    assert application.focusWidget() is window.player
    assert window.player.media.playbackRate() == 1
    assert window.player.media.playbackState() == QMediaPlayer.PlaybackState.PlayingState
    window.player.media.pause()
    QTest.keyClick(window.player, Qt.Key.Key_J)
    QTest.keyClicks(window.command, "ett")
    QTest.keyClick(window.command, Qt.Key.Key_Return)
    QTest.keyClick(window.command, Qt.Key.Key_V)
    QTest.keyClick(window.command, Qt.Key.Key_Space)
    assert window.command.text() == "v "
    assert window.command.property("commandState") == "input"
    assert window.editing_paused()
    window.command.setText("invalid command")
    QTest.keyClick(window.command, Qt.Key.Key_Return)
    assert not window.submit_resume
    assert window.command.text() == "invalid command"
    QTest.keyClick(window.command, Qt.Key.Key_Escape)
    window.settings["paused_typing_enabled"] = False
    window.update_command_state()
    assert window.command.property("commandState") == "review"
    QTest.keyClick(window.player, Qt.Key.Key_B)
    assert application.focusWidget() is window.player
    window.settings["paused_typing_enabled"] = True
    window.command.setCursorPosition(0)
    QTest.keyClick(window.player, Qt.Key.Key_B)
    assert window.command.text() == "binvalid command"
    for cancel in ("mouse", "focus", "playback", "paste"):
        window.command.setText("R3")
        window.command.setFocus()
        QTest.keyClick(window.command, Qt.Key.Key_Return)
        assert window.submit_resume
        if cancel == "mouse":
            QTest.mouseClick(window.command, Qt.MouseButton.LeftButton)
        elif cancel == "focus":
            window.player.setFocus()
            window.command.setFocus()
        elif cancel == "playback":
            window.player.media.play()
            window.player.media.pause()
        else:
            # Exercise the same insertion path as paste without changing the system clipboard.
            window.command.insert("jett")
        assert not window.submit_resume
        QTest.keyClick(window.command, Qt.Key.Key_Space)
        assert window.command.text().endswith(" ")
        assert window.editing_paused()


def test_session_arrow_navigation_and_tag_display(window, application, tmp_path):
    ids = add_clips(window, tmp_path)
    folder = window.catalogue.folders()[0]["folder_id"]
    for name in ("kept", "rejected"):
        path = tmp_path / "captures" / f"{name}.mp4"
        path.write_bytes(b"test")
        window.catalogue.ingest(folder, [{"path": str(path), "game": "VALORANT"}])
    ids += [clip["clip_id"] for clip in window.catalogue.clips() if clip["clip_id"] not in ids]
    window.catalogue.patch(ids[1], {"triage": "keep"})
    window.catalogue.patch(ids[2], {"triage": "discard"})
    window.catalogue.patch(ids[0], {"tag": "<bad>"})
    window.catalogue.create_session(ids, replace=True)
    window.panel("Editing")
    data = window.library.item(0).data(CLIP_ROLE)
    assert data["title"].startswith("[<bad>] VAL_")
    assert "[&lt;bad&gt;]" in data["rich_title"]
    assert "[&lt;bad&gt;]" in window.working_title.text()
    window.command.setFocus()
    window.command.setText("draft")
    QTest.keyClick(window.command, Qt.Key.Key_Down)
    assert window.current_id == ids[0]
    QTest.keyClick(window.command, Qt.Key.Key_Escape)
    for target in (ids[1], ids[2], ids[2]):
        QTest.keyClick(window.player, Qt.Key.Key_Down)
        assert window.current_id == target
    for target in (ids[1], ids[0], ids[0]):
        QTest.keyClick(window.player, Qt.Key.Key_Up)
        assert window.current_id == target
    assert window.command.text() == "draft"


def test_review_drafts_rating_and_panes(window, application, tmp_path):
    ids = add_clips(window, tmp_path)
    window.panel("Editing")
    window.settings["paused_typing_enabled"] = False
    QTest.keyClick(window.player, Qt.Key.Key_R)
    QTest.keyClick(window.player, Qt.Key.Key_3)
    assert window.catalogue.clip(ids[0])["rating"] is None
    assert application.focusWidget() is window.player
    QTest.keyClick(window.player, Qt.Key.Key_Slash)
    assert application.focusWidget() is window.command
    assert window.command.text() == ""
    window.command.setText("unfinished")
    QTest.keyClick(window.command, Qt.Key.Key_Escape)
    window.panel("Session")
    window.panel("Editing")
    assert window.command.text() == "unfinished"
    assert application.focusWidget() is window.player
    assert window.right.isHidden()


def test_input_undo_and_title_presentation(window, application, tmp_path):
    ids = add_clips(window, tmp_path)
    window.panel("Editing")
    window.edit(
        {
            "mainline": "<great aim> " * 8,
            "metadata": {"agent": "Chamber", "weapon": ["Operator", "Headhunter"], "kill": 3},
            "tag": "LOW_FPS",
            "rating": 4,
        }
    )
    assert "&lt;great aim&gt;" in window.working_title.text()
    assert "[LOW_FPS]" in window.working_title.text()
    assert not hasattr(window, "tag")
    window.command.setFocus()
    QTest.keyClicks(window.command, "jett")
    QTest.keyClick(window.command, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert window.command.text() == ""
    QTest.keyClick(
        window.command,
        Qt.Key.Key_Z,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
    )
    assert window.command.text() == "jett"
    assert window.catalogue.clip(ids[0])["rating"] == 4
    window.refresh_library()
    application.processEvents()
    assert window.library.horizontalScrollBar().maximum() == 0
    artifact = ROOT / "cache/verification"
    artifact.mkdir(parents=True, exist_ok=True)
    window.grab().save(str(artifact / "editing-populated.png"))
    window.toggle_projects()
    assert window.right.isVisible()
    window.showMaximized()
    application.processEvents()
    window.toggle_projects()
    assert window.right.isHidden()
    window.showNormal()
    application.processEvents()
    assert window.right.isVisible()
    window.reset_layout()
    assert window.right.isHidden()


def test_filename_fallback_deduplicates_game_prefix(window, application, tmp_path):
    captures = tmp_path / "captures"
    captures.mkdir()
    source = captures / "Counter-strike 2 2026.09.22.DVR.mp4"
    source.write_bytes(b"test")
    folder = window.catalogue.add_folder(captures)
    window.catalogue.ingest(folder, [{"path": str(source), "game": "Counter-strike 2"}])
    window.refresh_references()
    window.catalogue.create_session([window.catalogue.clips()[0]["clip_id"]])
    window.panel("Editing")
    application.processEvents()

    document = QTextDocument()
    document.setHtml(window.working_title.text())
    assert "CS2_2026.09.22.DVR.mp4" in document.toPlainText()
    assert "Counter-strike 2 2026" not in document.toPlainText()
    assert window.filename.text() == source.name
    assert window.library.item(0).data(CLIP_ROLE)["title"] == "CS2_2026.09.22.DVR"


@pytest.mark.parametrize("first", ["in", "out"])
def test_range_markers_in_either_order(window, tmp_path, monkeypatch, first):
    ids = add_clips(window, tmp_path)
    window.panel("Editing")
    assert window.range_warning.isHidden()
    assert window.range_warning_icon.isHidden()
    position = [0]
    monkeypatch.setattr(window.player.media, "position", lambda: position[0])

    def mark(endpoint, milliseconds):
        position[0] = milliseconds
        (window.mark_in if endpoint == "in" else window.mark_out)()

    mark(first, 0 if first == "in" else 3000)
    assert window.has_pending_range()
    assert not window.range_warning.isHidden()
    assert window.range_warning.text() == "I/O not set"
    assert window.player.controls.itemAt(1).layout() is window.range_warning_slot
    assert window.range_warning.mapToGlobal(QPoint(0, 0)).x() < (
        window.player.controls.itemAt(2).widget().mapToGlobal(QPoint(0, 0)).x()
    )
    assert window.command_error.isHidden()
    assert not window.ensure_range_complete()
    assert window.catalogue.clip(ids[0])["in_ms"] is None
    assert window.catalogue.clip(ids[0])["out_ms"] is None
    assert getattr(window.player.seek, f"pending_{first}") == position[0]
    mark("out" if first == "in" else "in", 3000 if first == "in" else 0)
    assert not window.has_pending_range()
    assert window.ensure_range_complete()
    assert window.catalogue.clip(ids[0])["in_ms"] == 0
    assert window.range_warning.isHidden()
    assert window.catalogue.clip(ids[0])["out_ms"] == 3000
    mark("in", 500)
    assert not window.has_pending_range()
    assert window.catalogue.clip(ids[0])["in_ms"] == 500
    mark("out", 4000)
    assert not window.has_pending_range()
    assert window.catalogue.clip(ids[0])["out_ms"] == 4000
    mark("in", 4500)
    assert window.has_pending_range()
    assert window.range_warning.text() == "I/O invalid"
    assert window.command_error.isHidden()
    assert window.catalogue.clip(ids[0])["in_ms"] == 500
    mark("out", 4500)
    assert window.has_pending_range()
    assert window.catalogue.clip(ids[0])["out_ms"] == 4000
    mark("out", 5000)
    assert not window.has_pending_range()
    assert window.catalogue.clip(ids[0])["in_ms"] == 4500
    window.clear_range()
    mark("out", 1000)
    window.clear_range()
    assert window.ensure_range_complete()
    assert window.range_warning.isHidden()
    assert window.range_warning_icon.isHidden()
    assert window.player.seek.pending_out is None
    assert window.catalogue.clip(ids[0])["out_ms"] is None


def test_pending_range_blocks_clip_and_session_changes(window, application, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QStyle

    ids = add_clips(window, tmp_path)
    folder = window.catalogue.folders()[0]["folder_id"]
    second = tmp_path / "captures/second.mp4"
    second.write_bytes(b"test")
    window.catalogue.ingest(folder, [{"path": str(second), "game": "VALORANT"}])
    next_id = next(
        clip["clip_id"] for clip in window.catalogue.clips() if clip["clip_id"] != ids[0]
    )
    window.catalogue.create_session([ids[0], next_id], replace=True)
    project = window.catalogue.save_project("No premature membership")
    window.catalogue.set_state("active_project", project)
    window.catalogue.patch(ids[0], {"metadata": {"agent": "Jett", "weapon": ["Vandal"]}})
    window.panel("Editing")
    position = [1000]
    monkeypatch.setattr(window.player.media, "position", lambda: position[0])
    window.mark_out()
    original_session = window.catalogue.state("session")
    confirmations = []
    monkeypatch.setattr(window, "confirm", lambda message: confirmations.append(message) or True)
    for action in (
        lambda: window.navigate(1),
        lambda: window.library.setCurrentRow(1),
        window.navigate_next_undefined,
        window.advance_review,
        window.add_to_project_next,
        lambda: window.panel("Home"),
        window.end_session,
        lambda: window.create_session("all"),
        lambda: window.load_clip(next_id),
    ):
        action()
        assert window.current_id == ids[0]
        assert window.current_panel == "Editing"
        assert window.catalogue.state("session") == original_session
        assert window.selected_id(window.library) == ids[0]
    assert not confirmations
    assert window.catalogue.clip(ids[0])["triage"] is None
    assert not window.catalogue.member_ids(project)
    assert window.player.play.style().styleHint(QStyle.StyleHint.SH_ToolTip_WakeUpDelay) == 200
    position[0] = 0
    window.mark_in()
    window.navigate(1)
    assert window.current_id == next_id
    window.mark_in()
    window.clear_range()
    window.panel("Home")
    assert window.current_panel == "Home"


def test_scrub_coalesces_and_finishes_exactly(window, monkeypatch):
    player = window.player
    calls = []
    monkeypatch.setattr(player.media, "setPosition", calls.append)
    monkeypatch.setattr(player.media, "duration", lambda: 10000)
    player.seek.setMaximum(10000)
    player.begin_scrub()
    for position in range(1000, 1235):
        player.queue_seek(position)
    assert calls == []
    player.preview_seek()
    assert calls == [1200]
    player.seek.setSliderPosition(1234)
    player.end_scrub()
    assert calls == [1200, 1234]
    assert not player.seek_timer.isActive()


def test_page_reveal_waits_and_delays_indicator(window, application):
    application.processEvents()
    window.current_panel = "Editing"
    window.player.awaiting_frame = True
    window.begin_page_transition()
    generation = window.transition_generation
    window.queue_page_reveal()
    application.processEvents()
    assert window.transition_pending
    assert window.player.video.isHidden()
    assert window.loading_label.isHidden()
    QTest.qWait(1100)
    assert window.loading_label.isVisible()
    window.begin_page_transition()
    window.player.awaiting_frame = False
    window.reveal_page(generation)
    assert window.transition_pending
    window.queue_page_reveal()
    application.processEvents()
    assert not window.transition_pending
    assert window.transition_cover.isHidden()
    assert not window.player.video.isHidden()
    window.player.awaiting_frame = True
    window.begin_page_transition()
    window.player.load_error(None, "Invalid media")
    application.processEvents()
    assert not window.transition_pending
    assert window.player.status.text() == "Invalid media"


@pytest.mark.parametrize("panel", ["Editing", "Export"])
def test_clip_click_keeps_list_and_viewport(
    window, application, tmp_path, monkeypatch, panel
):
    root = tmp_path / "LongLibrary"
    root.mkdir()
    folder = window.catalogue.add_folder(root)
    window.catalogue.ingest(
        folder,
        [{"path": str(root / f"clip-{index:03}.mp4"), "game": "VALORANT"} for index in range(80)],
    )
    ids = [clip["clip_id"] for clip in window.catalogue.clips()]
    if panel == "Editing":
        window.catalogue.create_session(ids)
    else:
        project = window.catalogue.save_project("Long project")
        for clip_id in ids:
            window.catalogue.patch(clip_id, {}, membership=(project, True))
        window.refresh_references()
        window.export_project.setCurrentIndex(window.export_project.findData(project))
    window.panel(panel)
    application.processEvents()
    player = window.active_player()
    loads = []

    def slow_load(clip):
        loads.append(clip["clip_id"])
        player.awaiting_frame = True
        player.loading_started.emit()

    monkeypatch.setattr(player, "load", slow_load)
    monkeypatch.setattr(window, "refresh_library", lambda: pytest.fail("Rebuilt clip list"))
    monkeypatch.setattr(window, "refresh_references", lambda: pytest.fail("Rebuilt references"))
    item = window.library.item(65)
    window.library.scrollToItem(item, window.library.ScrollHint.PositionAtCenter)
    application.processEvents()
    scroll = window.library.verticalScrollBar().value()
    for row in (65, 66, 67):
        target = window.library.item(row)
        QTest.mouseClick(
            window.library.viewport(),
            Qt.MouseButton.LeftButton,
            pos=window.library.visualItemRect(target).center(),
        )
        application.processEvents()
        assert window.library.verticalScrollBar().value() == scroll
        assert window.library.item(65) is item
        assert window.transition_scope == "clip"
        assert not window.transition_cover.geometry().intersects(window.left.geometry())
        assert window.transition_pending
    assert loads == ids[65:68]
    QTest.mouseClick(
        window.library.viewport(),
        Qt.MouseButton.LeftButton,
        pos=window.library.visualItemRect(window.library.item(67)).center(),
    )
    assert len(loads) == 3
    old_generation = window.transition_generation - 1
    player.awaiting_frame = False
    window.reveal_page(old_generation)
    assert window.transition_pending
    player.loading_finished.emit()
    application.processEvents()
    assert not window.transition_pending
    if panel == "Editing":
        window.navigate(1)
        assert window.current_id == ids[68]
        assert window.catalogue.state("session")["index"] == 68
        assert window.library.item(65) is item
        assert window.library.verticalScrollBar().value() == scroll


@pytest.mark.parametrize("panel", ["Browse", "Session", "Editing", "Export"])
def test_clip_list_positions_only_on_first_page_open(
    window, application, tmp_path, monkeypatch, panel
):
    root = tmp_path / "SelectionLibrary"
    root.mkdir()
    paths = [root / f"clip-{index:03}.mp4" for index in range(50)]
    for path in paths:
        path.touch()
    folder = window.catalogue.add_folder(root)
    window.catalogue.ingest(
        folder,
        [{"path": str(path), "game": "VALORANT"} for path in paths],
    )
    ids = [clip["clip_id"] for clip in window.catalogue.clips()]
    if panel == "Editing":
        window.catalogue.create_session(ids)
    elif panel == "Export":
        project = window.catalogue.save_project("Selection project")
        for clip_id in ids:
            window.catalogue.patch(clip_id, {}, membership=(project, True))
        window.refresh_references()
        window.export_project.setCurrentIndex(window.export_project.findData(project))
    window.panel(panel)
    application.processEvents()
    if window.library.currentRow() != 0:
        window.library.setCurrentRow(0)
    application.processEvents()
    assert window.library.visualItemRect(window.library.item(0)).top() == 0
    assert window.library_top_fade.isHidden()
    assert window.library_bottom_fade.isVisible()
    assert window.library_top_fade.testAttribute(
        Qt.WidgetAttribute.WA_TransparentForMouseEvents
    )
    assert window.library_bottom_fade.testAttribute(
        Qt.WidgetAttribute.WA_TransparentForMouseEvents
    )
    window.library.scrollToItem(window.library.item(30), window.library.ScrollHint.PositionAtCenter)
    application.processEvents()
    scroll = window.library.verticalScrollBar().value()
    window.library.setCurrentRow(30)
    application.processEvents()
    assert window.library.verticalScrollBar().value() == scroll
    assert window.library_top_fade.isVisible()
    assert window.library_bottom_fade.isVisible()
    assert window.library_top_fade.height() == 16
    assert window.library_bottom_fade.geometry().bottom() == (
        window.library.viewport().rect().bottom()
    )
    if panel == "Editing":
        assert window.session_position.text() == "31 / 50"
    assert panel in window.positioned_clip_pages
    monkeypatch.setattr(
        window,
        "position_selected_clip",
        lambda: pytest.fail("Repositioned after the page's first opening"),
    )
    window.refresh_library()
    application.processEvents()
    assert window.library.verticalScrollBar().value() == scroll
    window.panel("Home")
    window.panel(panel)
    application.processEvents()
    window.resize(window.width() + 1, window.height() + 1)
    application.processEvents()


def test_home_clip_left_click_retains_inert_highlight_without_context_menu(
    window, application, tmp_path, monkeypatch
):
    add_clips(window, tmp_path)
    window.panel("Home")
    application.processEvents()
    item = window.library.item(0)
    popups = []
    monkeypatch.setattr(window.clip_context_menu, "popup", popups.append)

    position = window.library.visualItemRect(item).center()
    QTest.mousePress(
        window.library.viewport(),
        Qt.MouseButton.LeftButton,
        pos=position,
    )

    assert not popups
    assert window.library.currentItem() is item
    assert item.isSelected()
    QTest.mouseRelease(
        window.library.viewport(),
        Qt.MouseButton.LeftButton,
        pos=position,
    )
    assert window.library.currentItem() is item
    assert window.library.selectedItems() == [item]
    assert window.current_id is None
    assert not popups


def test_library_rebuild_keeps_viewport(window, application, tmp_path):
    root = tmp_path / "LongLibrary"
    root.mkdir()
    folder = window.catalogue.add_folder(root)
    window.catalogue.ingest(
        folder, [{"path": str(root / f"clip-{index:03}.mp4"), "game": None} for index in range(80)]
    )
    window.refresh_library()
    window.library.scrollToItem(window.library.item(65))
    application.processEvents()
    scroll = window.library.verticalScrollBar().value()
    window.refresh_library()
    application.processEvents()
    assert window.library.verticalScrollBar().value() == scroll


def test_real_clip_switch_reveals_local_preview(window, application, tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg required for playback fixtures")
    ids = add_clips(window, tmp_path, valid=True)
    source = Path(window.catalogue.clip(ids[0])["source_path"])
    second = source.with_name("second.mp4")
    shutil.copyfile(source, second)
    window.catalogue.ingest(
        window.catalogue.folders()[0]["folder_id"], [{"path": str(second), "game": "VALORANT"}]
    )
    ids = [clip["clip_id"] for clip in window.catalogue.clips()]
    window.catalogue.create_session(ids, replace=True)
    project = window.catalogue.save_project("Preview project")
    for clip_id in ids:
        window.catalogue.patch(clip_id, {}, membership=(project, True))
    window.refresh_references()
    window.export_project.setCurrentIndex(window.export_project.findData(project))
    for panel in ("Editing", "Export"):
        window.panel(panel)
        assert wait_for(application, lambda: not window.transition_pending)
        row = 1 - window.library.currentRow()
        expected = window.catalogue.clip(ids[row])["source_path"]
        window.library.setCurrentRow(row)
        assert window.transition_pending
        assert window.transition_scope == "clip"
        artifact = ROOT / "cache/verification/clip-navigation"
        artifact.mkdir(parents=True, exist_ok=True)
        window.grab().save(str(artifact / f"{panel.lower()}-loading.png"))
        assert wait_for(application, lambda: not window.transition_pending)
        assert wait_for(application, lambda: window.active_player().media.duration() > 0)
        assert not window.active_player().media.frame_image().isNull()
        assert Path(window.active_player().media.source().toLocalFile()) == Path(expected)
        window.grab().save(str(artifact / f"{panel.lower()}-ready.png"))


def test_background_completion(window, application):
    results = []
    window.background(lambda cancelled, progress: 42, results.append)
    assert wait_for(application, lambda: window.worker is None)
    assert results == [42]


def test_background_locks_immediately_until_cancel_finishes(window, application):
    release = threading.Event()
    results = []

    def operation(cancelled, progress):
        release.wait(5)
        return cancelled()

    window.background(operation, results.append)
    dialog = QApplication.activeModalWidget()
    assert isinstance(dialog, QProgressDialog)
    assert dialog.isVisible()
    worker = window.worker
    window.background(lambda cancelled, progress: "duplicate", results.append)
    assert window.worker is worker
    dialog.canceled.emit()
    assert dialog.isVisible()
    assert dialog.labelText() == "Cancelling… Please wait."
    release.set()
    assert wait_for(application, lambda: window.worker is None)
    assert results == [True]
    assert QApplication.activeModalWidget() is None


def test_export_shows_progress_before_preparation(window, application, tmp_path, monkeypatch):
    project = window.catalogue.save_project("Immediate progress")
    window.refresh_references()
    window.export_project.setCurrentIndex(window.export_project.findData(project))
    window.export_destination.setText(str(tmp_path / "output"))
    preparation = []

    def member_ids(project_id):
        preparation.append(project_id)
        raise ValueError("Preparation failed")

    monkeypatch.setattr(window.catalogue, "member_ids", member_ids)
    window.run_export()
    assert not preparation
    assert isinstance(QApplication.activeModalWidget(), QProgressDialog)
    assert QApplication.activeModalWidget().isVisible()
    assert wait_for(application, lambda: window.worker is None)
    assert preparation == [project]
    assert QApplication.activeModalWidget() is None


def test_game_change_confirmation_and_undo(window, application, tmp_path, monkeypatch):
    ids = add_clips(window, tmp_path)
    window.panel("Editing")
    window.edit({"metadata": {"agent": "Jett"}, "mainline": "Note", "rating": 2})
    monkeypatch.setattr(QInputDialog, "getItem", lambda *args, **kwargs: ("Battlefield 6", True))
    monkeypatch.setattr(window, "confirm", lambda message: False)
    window.change_game()
    assert window.catalogue.clip(ids[0])["game"] == "VALORANT"
    monkeypatch.setattr(window, "confirm", lambda message: True)
    window.change_game()
    clip = window.catalogue.clip(ids[0])
    assert clip["game"] == "Battlefield 6" and not clip["metadata"]
    assert clip["mainline"] == "Note" and clip["rating"] == 2
    window.undo()
    assert window.catalogue.clip(ids[0])["metadata"] == {"agent": "Jett"}


@pytest.mark.parametrize("folder_name, game", [("VALORANT", "VALORANT"), ("NVIDIA", None)])
def test_folder_dialogs_and_background_scan(
    window, application, tmp_path, monkeypatch, folder_name, game
):
    from PySide6.QtWidgets import QFileDialog

    captures = tmp_path / folder_name
    captures.mkdir()
    (captures / "clip.mp4").write_bytes(b"test")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(captures))
    monkeypatch.setattr(
        QInputDialog,
        "getItem",
        lambda *args, **kwargs: ("Automatic (nearest recognized ancestor)", True),
    )

    def confirm(message):
        # Reproduce a modal dialog processing worker-finished events.
        QTest.qWait(100)
        application.processEvents()
        return True

    monkeypatch.setattr(window, "confirm", confirm)
    window.panel("Home")
    window.add_folder()
    assert wait_for(application, lambda: window.worker is None)
    assert len(window.catalogue.clips()) == 1
    assert window.catalogue.clips()[0]["game"] == game
    assert Path(window.catalogue.folders()[0]["path"]) == captures
    window.rescan()
    assert wait_for(application, lambda: window.worker is None)
    assert len(window.catalogue.clips()) == 1


def test_rescan_modal_cache_restart(window, application, tmp_path, monkeypatch):
    from dfsorter.scanning import ScanCoordinator

    add_clips(window, tmp_path)
    calls = []

    def probe(path, *args):
        calls.append(path)
        return dict(duration=15, created="2026-09-17", error=None)

    monkeypatch.setattr("dfsorter.scanning.inspect_media", probe)
    monkeypatch.setattr("dfsorter.scanning.shutil.which", lambda name: "ffprobe")
    ScanCoordinator(window.catalogue, window.registry).run(window.catalogue.folders())
    restarted = Window(tmp_path)
    assert next(iter(restarted.media_info.values()))["duration"] == 15
    restarted.show()
    application.processEvents()
    assert isinstance(QApplication.activeModalWidget(), QProgressDialog)
    assert wait_for(application, lambda: restarted.worker is None)
    assert len(calls) == 1
    restarted.reinspect()
    assert isinstance(QApplication.activeModalWidget(), QProgressDialog)
    assert wait_for(application, lambda: restarted.worker is None)
    assert len(calls) == 2
    restarted.close()


def test_disabled_folder_session_selection(window, application, tmp_path):
    ids = add_clips(window, tmp_path)
    original_session = window.catalogue.state("session")
    window.panel("Session")
    assert window.library.count() == 1
    window.folders.setCurrentRow(0)
    window.toggle_folder()
    assert window.library.count() == 0
    assert window.catalogue.state("session") == original_session
    window.panel("Editing")
    assert window.library.count() == len(ids)
    window.panel("Session")
    window.toggle_folder()
    assert window.library.count() == 1


def test_all_panel_layouts(window, application, tmp_path):
    add_clips(window, tmp_path)
    project = window.catalogue.save_project("Example montage")
    clip = window.catalogue.clips()[0]
    window.catalogue.patch(clip["clip_id"], {}, membership=(project, True))
    window.refresh_references()
    artifact = ROOT / "cache/verification"
    artifact.mkdir(parents=True, exist_ok=True)
    for name in ["Home", "Session", "Export", "Config"]:
        window.panel(name)
        if name == "Export":
            window.export_project.setCurrentIndex(window.export_project.findData(project))
            assert not window.export_button.isEnabled()
        application.processEvents()
        window.grab().save(str(artifact / f"{name.lower()}.png"))


def test_add_project_next_requires_active_and_preserves_triage(window, application, tmp_path):
    add_clips(window, tmp_path)
    folder = window.catalogue.folders()[0]
    window.catalogue.ingest(
        folder["folder_id"], [{"path": str(tmp_path / "captures" / "extra.mp4"), "game": None}]
    )
    ids = [clip["clip_id"] for clip in window.catalogue.clips()]
    window.catalogue.create_session(ids, replace=True)
    window.catalogue.patch(ids[0], {"triage": "keep"})
    window.catalogue.patch(ids[1], {"triage": "discard"})
    window.panel("Editing")
    project = window.catalogue.save_project("Shortlist")
    window.refresh_references()
    assert not window.add_project_next.isEnabled()
    QTest.keyClick(window.player, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert window.current_id == ids[0]
    assert not window.catalogue.member_ids(project)
    window.catalogue.set_state("active_project", project)
    window.refresh_references()
    assert window.add_project_next.isEnabled()
    window.command.setFocus()
    window.command.setText("unfinished note")
    QTest.keyClick(window.command, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert not window.catalogue.member_ids(project)
    QTest.keyClick(window.command, Qt.Key.Key_Escape)
    QTest.keyClick(window.player, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert window.current_id == ids[1]
    assert window.catalogue.member_ids(project) == {ids[0]}
    window.add_project_next.click()
    window.add_project_next.click()
    assert window.current_id == ids[1]
    assert window.catalogue.member_ids(project) == set(ids)
    assert [window.catalogue.clip(i)["triage"] for i in ids] == ["keep", "discard"]
    window.navigate(-1)
    assert window.command.text() == "unfinished note"
    window.deactivate()
    assert not window.add_project_next.isEnabled()


def test_next_undefined_navigation_is_editing_only(window, application, tmp_path):
    add_clips(window, tmp_path)
    folder = window.catalogue.folders()[0]
    window.catalogue.ingest(
        folder["folder_id"],
        [{"path": str(tmp_path / "captures" / f"next-{i}.mp4"), "game": None} for i in range(3)],
    )
    ids = [clip["clip_id"] for clip in window.catalogue.clips()]
    window.catalogue.create_session(ids, replace=True)
    window.catalogue.patch(ids[1], {"triage": "keep"})
    window.catalogue.patch(ids[2], {"triage": "discard"})
    window.panel("Editing")
    assert not window.session_header.isHidden()
    assert "Next pending clip" in window.next_undefined_button.toolTip()
    window.command.setText("draft")
    window.next_undefined_button.click()
    assert window.current_id == ids[3]
    assert window.catalogue.clip(ids[0])["triage"] is None
    window.next_undefined_button.click()
    assert window.current_id == ids[3]
    assert "No pending clips ahead" in window.statusBar().currentMessage()
    window.navigate(-3)
    assert window.command.text() == "draft"
    for panel in ["Home", "Session", "Export", "Config"]:
        window.panel(panel)
        assert window.session_header.isHidden()


def test_settings_cog_preserves_actions_without_menu_bar(window, application, tmp_path):
    from PySide6.QtWidgets import QMenuBar, QToolButton

    assert not window.findChildren(QMenuBar)
    assert window.settings_button.popupMode() == QToolButton.ToolButtonPopupMode.InstantPopup
    actions = {action.text(): action for action in window.settings_menu.actions()}
    assert {
        "Settings…",
        "Capture folders…",
        "Reset clip metadata…",
        "Edit tag…",
        "Delete rejected originals…",
        "Reset window and panes",
        "Exit",
    } <= actions.keys()
    window.panel("Session")
    actions["Capture folders…"].trigger()
    assert window.current_panel == "Home"
    assert window.folders.isVisible()
    assert actions["Exit"].shortcut().toString() == "Ctrl+Q"
    ids = add_clips(window, tmp_path)
    window.panel("Editing")
    window.edit({"rating": 4})
    window.review_mode()
    QTest.keyClick(window.player, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert window.catalogue.clip(ids[0])["rating"] is None
    QTest.keyClick(
        window.player,
        Qt.Key.Key_Z,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
    )
    assert window.catalogue.clip(ids[0])["rating"] == 4
    assert "Undo" not in actions and "Redo" not in actions
    window.undo_button.click()
    assert window.catalogue.clip(ids[0])["rating"] is None
    window.redo_button.click()
    assert window.catalogue.clip(ids[0])["rating"] == 4
    assert window.projects_toggle.height() == window.settings_button.height()
    assert (
        abs(
            window.projects_toggle.geometry().center().y()
            - window.settings_button.geometry().center().y()
        )
        <= 1
    )


def test_history_controls_availability(window, tmp_path):
    from PySide6.QtGui import QIcon

    from dfsorter.theme import COLORS

    def available(undo, redo):
        assert window.undo_button.isEnabled() is undo
        assert window.redo_button.isEnabled() is redo

    available(False, False)
    for control in (window.undo_button, window.redo_button):
        for mode, color in [
            (QIcon.Mode.Normal, COLORS["text_secondary"]),
            (QIcon.Mode.Disabled, COLORS["text_disabled"]),
        ]:
            image = control.icon().pixmap(16, 16, mode).toImage()
            pixels = [image.pixelColor(x, y) for x in range(16) for y in range(16)]
            assert max(pixels, key=lambda pixel: pixel.alpha()).name() == color.lower()
    add_clips(window, tmp_path)
    window.panel("Editing")
    window.edit({"rating": 4})
    available(True, False)
    window.undo_button.click()
    available(False, True)
    window.redo_button.click()
    available(True, False)
    window.edit({"rating": 5})
    window.undo()
    available(True, True)
    window.edit({"rating": 3})
    available(True, False)
    while window.catalogue.undo_stack:
        window.undo()
    window.panel("Home")
    project = window.catalogue.save_project("History controls")
    window.refresh_references()
    window.projects.setCurrentRow(0)
    window.library.setCurrentRow(0)
    window.membership(True)
    available(True, False)
    window.catalogue.delete_project(project)
    window.refresh_references()
    available(False, False)


def test_title_casing_settings_refresh(window, application, tmp_path, monkeypatch):
    import yaml
    from PySide6.QtGui import QTextDocument

    ids = add_clips(window, tmp_path)
    window.panel("Editing")
    window.edit(
        {
            "metadata": {"agent": "Clove", "weapon": ["Phantom"], "kill": 4},
            "mainline": "My BEST 中文",
            "tag": "LOW_FPS",
        }
    )
    before = window.catalogue.clip(ids[0])
    selected = window.library.currentRow()
    scroll = window.library.verticalScrollBar().value()
    position = window.player.media.position()
    monkeypatch.setattr(
        window, "load_clip", lambda *args: pytest.fail("Title toggle reloaded clip")
    )
    dialog = SettingsDialog(window)
    assert dialog.lowercase_titles.isChecked()
    for enabled, expected in [
        (True, "4k clove phantom | my best 中文"),
        (False, "4K Clove Phantom | My BEST 中文"),
        (True, "4k clove phantom | my best 中文"),
    ]:
        dialog.lowercase_titles.setChecked(enabled)
        document = QTextDocument()
        document.setHtml(window.working_title.text())
        assert document.toPlainText() == "[LOW_FPS] VAL_" + expected
        data = window.library.item(selected).data(CLIP_ROLE)
        assert data["title"] == document.toPlainText()
        assert data["title"] in window.library.item(selected).toolTip()
        assert window.catalogue.clip(ids[0]) == before
        assert window.library.currentRow() == selected
        assert window.library.verticalScrollBar().value() == scroll
        assert window.player.media.position() == position
    assert yaml.safe_load(window.settings_path.read_text(encoding="utf-8"))[
        "lowercase_generated_titles"
    ]
    dialog.close()


def test_browse_entry_selects_newest(window, tmp_path, application):
    add_clips(window, tmp_path)
    second = tmp_path / "captures" / "second.mp4"
    second.write_bytes(b"test")
    window.catalogue.ingest(
        window.catalogue.folders()[0]["folder_id"],
        [{"path": str(second), "game": None}],
    )
    clips = window.catalogue.clips()
    for index, clip in enumerate(clips):
        window.media_info[clip["source_path"]] = {"created": f"2026-09-{index + 1:02}T12:00:00Z"}
    window.catalogue.patch(clips[-1]["clip_id"], {"triage": "keep"})
    window.panel("Home")
    application.processEvents()
    assert window.library.count() == 2
    window.nav["Browse"].click()
    application.processEvents()
    newest = clips[-1]["clip_id"]
    assert window.browse_id == newest
    assert window.browse_selected_id is None
    assert window.library.count() == 2
    window.panel("Home")
    window.media_info[clips[0]["source_path"]] = {"created": "2026-09-30T12:00:00Z"}
    window.panel("Browse")
    newest = clips[0]["clip_id"]
    assert window.browse_id == newest
    window.toggle_browse_sort()
    window.library.setCurrentRow(0)
    assert window.browse_id != newest
    selected = window.browse_id
    window.panel("Home")
    window.panel("Browse")
    assert window.browse_id == selected
    assert window.browse.clip["clip_id"] == selected
    assert window.browse_newest
    assert window.library.visualItemRect(window.library.currentItem()).intersects(
        window.library.viewport().rect()
    )
    # A fresh window has no remembered manual selection.
    restarted = Window(tmp_path)
    try:
        restarted.media_info = window.media_info.copy()
        restarted.panel("Browse")
        assert restarted.browse_id == newest
    finally:
        restarted.close()
    Path(window.catalogue.clip(selected)["source_path"]).unlink()
    with window.catalogue.connection() as database:
        database.execute("INSERT INTO deleted_sources VALUES (?)", (selected,))
    window.panel("Home")
    window.panel("Browse")
    assert window.browse_id == newest


def test_library_filter_menus_and_unavailable_persistence(window, tmp_path, application):
    captures = tmp_path / "filter-captures"
    captures.mkdir()
    available = captures / "available.mp4"
    available.write_bytes(b"test")
    missing = captures / "missing.mp4"
    folder_id = window.catalogue.add_folder(captures)
    window.catalogue.ingest(
        folder_id,
        [
            {"path": str(available), "game": "VALORANT"},
            {"path": str(missing), "game": None},
        ],
    )
    ids = [clip["clip_id"] for clip in window.catalogue.clips()]
    window.catalogue.patch(ids[0], {"triage": "discard"})
    window.refresh_references()
    window.panel("Home")

    assert window.clip_filter.text() == "Clips"
    assert window.game_filter.text() == "Games"
    assert window.project_filter.text() == "Projects"
    assert window.clip_filter.selected_values() == {None, "keep"}
    assert window.game_filter.all_selected()
    assert window.project_filter.all_selected()
    assert [action.text() for action in window.project_filter.menu().actions()] == [
        "All projects",
        "",
        "No projects",
    ]
    assert window.library.count() == 0

    for action in window.clip_filter.menu().actions():
        if action.text() == "Discard":
            action.trigger()
            break
    assert window.library.count() == 1
    window.unavailable_toggle.click()
    assert window.settings["show_unavailable_clips"] is True
    assert window.library.count() == 2

    restarted = Window(tmp_path)
    try:
        restarted.show()
        application.processEvents()
        assert restarted.unavailable_toggle.isChecked()
        assert restarted.unavailable_toggle.property("iconName") == "eye"
    finally:
        restarted.close()


@pytest.mark.parametrize("remaining", [False, True])
def test_browse_delete_confirmation(window, application, tmp_path, monkeypatch, remaining):
    from PySide6.QtWidgets import QMessageBox

    add_clips(window, tmp_path)
    if remaining:
        second = tmp_path / "second"
        second.mkdir()
        second_source = second / "second.mp4"
        second_source.write_bytes(b"video")
        folder = window.catalogue.add_folder(second)
        window.catalogue.ingest(folder, [{"path": str(second_source), "game": None}])
    window.panel("Browse")
    source = Path(window.browse.clip["source_path"])
    deleted_id = window.browse_id
    count = window.library.count()
    before = catalogue_dump(window)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Cancel)
    window.browse.delete_button.click()
    assert source.exists()
    assert catalogue_dump(window) == before
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Yes)
    window.browse.delete_button.click()
    assert wait_for(application, lambda: window.worker is None)
    assert not source.exists()
    assert [
        line
        for line in catalogue_dump(window)
        if not line.startswith('INSERT INTO "deleted_sources"')
    ] == before
    assert window.library.count() == count - 1
    assert deleted_id not in {
        window.library.item(index).data(Qt.ItemDataRole.UserRole)
        for index in range(window.library.count())
    }
    assert window.browse_id != deleted_id
    if remaining:
        assert window.browse.clip["clip_id"] == window.browse_id
    else:
        assert window.browse.clip is None
        assert window.browse_id is None
        assert not window.browse.delete_button.isEnabled()
    window.panel("Home")
    window.catalogue = Catalogue(window.catalogue.path)
    window.panel("Browse")
    assert window.library.count() == count - 1
    restarted = Window(tmp_path)
    restarted.show()
    try:
        application.processEvents()
        assert wait_for(application, lambda: restarted.worker is None)
        restarted.panel("Browse")
        assert restarted.library.count() == count - 1
        assert restarted.browse_id != deleted_id
    finally:
        restarted.close()
    source.write_bytes(b"restored")
    window.refresh_library()
    assert window.library.count() == count


def test_auto_scan_discovers_without_modal_or_selection_reset(window, application, tmp_path):
    ids = add_clips(window, tmp_path)
    folder = window.catalogue.folders()[0]
    sources = []
    for index in range(25):
        path = tmp_path / "captures" / f"existing-{index}.mp4"
        path.write_bytes(b"video")
        sources.append({"path": str(path), "game": None})
    window.catalogue.ingest(folder["folder_id"], sources)
    window.panel("Browse")
    window.library.setCurrentRow(15)
    window.library.scrollToItem(window.library.currentItem())
    anchor = window.library.itemAt(1, 1)
    anchor_id = anchor.data(Qt.ItemDataRole.UserRole)
    anchor_offset = window.library.visualItemRect(anchor).top()
    selected_id = window.browse_id
    window.browse.custom_title.setText("Keep draft")
    original_clip = window.browse.clip
    new_source = tmp_path / "captures" / "new.mp4"
    new_source.write_bytes(b"new video")
    assert window.scan_timer.interval() == 30_000
    assert window.scan_timer.isActive()
    window.statusBar().clearMessage()
    window.scan_timer.timeout.emit()
    assert window.scan_retry_timer.isActive()
    assert wait_for(application, lambda: window.worker is None and window.library.count() == 27)
    assert QApplication.activeModalWidget() is None
    assert window.statusBar().currentMessage() == ""
    assert window.browse_id == selected_id
    anchor = window.library.itemAt(1, 1)
    assert anchor.data(Qt.ItemDataRole.UserRole) == anchor_id
    assert window.library.visualItemRect(anchor).top() == anchor_offset
    assert window.browse.clip is original_clip
    assert window.browse.custom_title.text() == "Keep draft"
    assert window.catalogue.state("session")["ids"] == ids


def test_auto_scan_defers_busy_and_modal_and_runs_on_focus(window, application, monkeypatch):
    calls = []
    monkeypatch.setattr(window, "rescan", lambda **kwargs: calls.append(kwargs))
    window.worker = object()
    window.auto_scan()
    assert not calls
    assert window.scan_retry_timer.isActive()
    window.worker = None
    monkeypatch.setattr(QApplication, "activeModalWidget", lambda: window)
    window.auto_scan()
    assert not calls
    monkeypatch.setattr(QApplication, "activeModalWidget", lambda: None)
    window.scan_retry_timer.stop()
    window.eventFilter(application, QEvent(QEvent.Type.ApplicationActivate))
    assert window.scan_retry_timer.isActive()
    assert wait_for(application, lambda: bool(calls))
    assert calls == [{"quiet": True}]


def test_browse_form_alignment_and_title_style(window, application):
    window.panel("Browse")
    application.processEvents()
    browse = window.browse
    for width in (1100, 1600):
        window.resize(width, 900)
        application.processEvents()
        title_left = browse.custom_title.mapTo(browse, QPoint(0, 0)).x()
        title_right = title_left + browse.custom_title.width()
        mode_right = browse.mode.mapTo(browse, QPoint(0, 0)).x() + browse.mode.width()
        assert title_right == mode_right
        assert browse.custom_title.width() > browse.destination.width() == 480
        assert browse.working_title.font() == window.working_title.font()


@pytest.mark.parametrize("maximized", [False, True])
def test_browse_fullscreen_restores_player_and_window(window, application, tmp_path, maximized):
    add_clips(window, tmp_path, valid=True)
    if maximized:
        window.showMaximized()
        application.processEvents()
    window.panel("Browse")
    application.processEvents()
    browse = window.browse
    player = browse.player
    assert wait_for(application, lambda: player.media.duration() > 0 and not player.awaiting_frame)
    surface_id = int(player.video.winId())
    clip_id = browse.clip["clip_id"]
    browse.custom_title.setText("Share draft")
    browse.in_ms, browse.out_ms = 100, 200
    sizes = window.splitter.sizes()
    geometry = window.geometry()
    playback_state = player.media.playbackState()
    position = player.media.position()
    browse.fullscreen_button.click()
    application.processEvents()
    assert window.isFullScreen()
    assert window.navigation_strip.isHidden() and window.left.isHidden()
    assert browse.details.isHidden() and window.statusBar().isHidden()
    assert player.isVisible() and browse.fullscreen_button.isVisible()
    assert int(player.video.winId()) == surface_id
    assert player.media.playbackState() == playback_state
    assert player.media.position() == position
    QTest.keyClick(player, Qt.Key.Key_Escape)
    application.processEvents()
    assert not window.isFullScreen()
    assert window.isMaximized() == maximized
    assert window.geometry() == geometry
    assert window.splitter.sizes() == sizes
    assert window.navigation_strip.isVisible() and window.left.isVisible()
    assert browse.details.isVisible()
    assert browse.custom_title.text() == "Share draft"
    assert (browse.in_ms, browse.out_ms) == (100, 200)
    assert browse.clip["clip_id"] == clip_id
    QTest.keyClick(player, Qt.Key.Key_F11)
    assert window.isFullScreen()
    QTest.keyClick(player, Qt.Key.Key_F11)
    assert not window.isFullScreen()
    browse.fullscreen_button.click()
    window.panel("Home")
    assert not window.isFullScreen()
    assert browse.fullscreen_state is None
    for panel in ["Editing", "Export"]:
        window.panel(panel)
        QTest.keyClick(window.active_player(), Qt.Key.Key_F11)
        assert not window.isFullScreen()
