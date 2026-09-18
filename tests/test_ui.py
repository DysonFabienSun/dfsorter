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
from PySide6.QtGui import QMouseEvent
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QInputDialog, QProgressDialog

from dfsorter.catalogue import Catalogue
from dfsorter.deletion import preview
from dfsorter.deletion_dialog import DeletionDialog
from dfsorter.settings_dialog import SettingsDialog
from dfsorter.ui import ROOT, Window, style_application
from dfsorter.widgets import CLIP_ROLE


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
                "sine=frequency=440",
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
    assert "required fields" in window.command_error.text()
    QTest.keyClick(window.command, Qt.Key.Key_Escape)
    QTest.keyClick(window.player, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert window.current_id == ids[0]
    assert "required fields" in window.command_error.text()
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


def test_editing_session_counts_and_list_height(window, application, tmp_path):
    ids = add_clips(window, tmp_path)
    folder = window.catalogue.folders()[0]
    window.catalogue.ingest(
        folder["folder_id"],
        [{"path": str(tmp_path / "captures" / "outside-session.mp4"), "game": None}],
    )
    window.panel("Editing")
    application.processEvents()
    assert window.session_counts.text() == "Kept 0 · Rejected 0\nUndefined 1 · Total 1"
    item = window.library.item(0)
    window.edit({"triage": "keep"})
    assert window.session_counts.text() == "Kept 1 · Rejected 0\nUndefined 0 · Total 1"
    window.edit({"triage": "discard"})
    assert window.session_counts.text() == "Kept 0 · Rejected 1\nUndefined 0 · Total 1"
    assert window.library.item(0) is item
    window.undo()
    assert "Kept 1" in window.session_counts.text()
    window.undo()
    assert "Undefined 1" in window.session_counts.text()
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
    assert window.session_header.geometry().bottom() < window.library.geometry().top()
    assert window.left.height() == window.center_column.height()
    assert window.session_counts.geometry().bottom() >= window.left.height() - 8
    artifact = ROOT / "cache/verification/session-counts"
    artifact.mkdir(parents=True, exist_ok=True)
    assert wait_for(application, lambda: not window.transition_pending)
    window.grab().save(str(artifact / "editing.png"))
    window.panel("Export")
    assert window.session_counts.isHidden()


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
    assert window.triage_buttons[None].isChecked()
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
    assert player.video.videoSink().videoFrame().isValid()
    assert not player.video.videoSink().videoFrame().toImage().isNull()
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
                    and preview_player.video.videoSink().videoFrame().isValid()
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
    player.video.videoSink().videoFrame().toImage().save(
        str(artifact / f"decoded-video-{codec}.png")
    )
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
    QTest.keyClick(window.player, Qt.Key.Key_4)
    assert window.catalogue.clip(ids[0])["rating"] == 4
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
    QTest.keyClick(window.player, Qt.Key.Key_R)
    QTest.keyClick(window.player, Qt.Key.Key_3)
    assert window.catalogue.clip(ids[0])["rating"] == 3
    QTest.keyClick(window.player, Qt.Key.Key_R)
    window.rating_deadline = 0
    QTest.keyClick(window.player, Qt.Key.Key_5)
    assert window.catalogue.clip(ids[0])["rating"] == 3
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


@pytest.mark.parametrize("first", ["in", "out"])
def test_range_markers_in_either_order(window, tmp_path, monkeypatch, first):
    ids = add_clips(window, tmp_path)
    window.panel("Editing")
    position = [0]
    monkeypatch.setattr(window.player.media, "position", lambda: position[0])

    def mark(endpoint, milliseconds):
        position[0] = milliseconds
        (window.mark_in if endpoint == "in" else window.mark_out)()

    mark(first, 0 if first == "in" else 3000)
    assert window.has_pending_range()
    assert not window.ensure_range_complete()
    assert window.catalogue.clip(ids[0])["in_ms"] is None
    assert window.catalogue.clip(ids[0])["out_ms"] is None
    assert getattr(window.player.seek, f"pending_{first}") == position[0]
    mark("out" if first == "in" else "in", 3000 if first == "in" else 0)
    assert not window.has_pending_range()
    assert window.ensure_range_complete()
    assert window.catalogue.clip(ids[0])["in_ms"] == 0
    assert window.catalogue.clip(ids[0])["out_ms"] == 3000
    mark("in", 500)
    assert not window.has_pending_range()
    assert window.catalogue.clip(ids[0])["in_ms"] == 500
    mark("out", 4000)
    assert not window.has_pending_range()
    assert window.catalogue.clip(ids[0])["out_ms"] == 4000
    mark("in", 4500)
    assert window.has_pending_range()
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
def test_clip_click_keeps_list_and_scroll(window, application, tmp_path, monkeypatch, panel):
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
        assert window.active_player().video.videoSink().videoFrame().isValid()
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


def test_folder_dialogs_and_background_scan(window, application, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    captures = tmp_path / "VALORANT"
    captures.mkdir()
    (captures / "clip.mp4").write_bytes(b"test")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(captures))
    monkeypatch.setattr(
        QInputDialog,
        "getItem",
        lambda *args, **kwargs: ("Automatic (nearest recognized ancestor)", True),
    )
    monkeypatch.setattr(window, "confirm", lambda message: True)
    window.panel("Import")
    window.add_folder()
    assert wait_for(application, lambda: window.worker is None)
    assert len(window.catalogue.clips()) == 1
    assert window.catalogue.clips()[0]["game"] == "VALORANT"
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
    for name in ["Home", "Import", "Session", "Export", "Config"]:
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
    window.command.setText("draft")
    window.next_undefined_button.click()
    assert window.current_id == ids[3]
    assert window.catalogue.clip(ids[0])["triage"] is None
    window.next_undefined_button.click()
    assert window.current_id == ids[3]
    assert "No undefined clips ahead" in window.statusBar().currentMessage()
    window.navigate(-3)
    assert window.command.text() == "draft"
    for panel in ["Home", "Import", "Session", "Export", "Config"]:
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
    window.panel("Import")
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
