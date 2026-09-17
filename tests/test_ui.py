import os
import shutil
import subprocess
import time
from pathlib import Path

os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")

import PySide6
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QInputDialog

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
    assert application.focusWidget() is window.player
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
    assert window.catalogue.clip(ids[0])["triage"] is None
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
    QTest.keyClick(window.player, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert window.current_id == next_id
    assert window.catalogue.clip(ids[0])["triage"] == "discard"
    window.command.setFocus()
    window.command.setText("jett vandal")
    QTest.keyClick(window.command, Qt.Key.Key_Return)
    assert window.current_id == next_id
    assert window.catalogue.clip(next_id)["triage"] is None
    QTest.keyClick(window.player, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert window.catalogue.clip(next_id)["triage"] == "keep"
    assert "Session complete" in window.statusBar().currentMessage()


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
            "technical_condition": "LOW_FPS",
            "rating": 4,
        }
    )
    assert "&lt;great aim&gt;" in window.working_title.text()
    assert window.technical.isVisible()
    window.command.setFocus()
    QTest.keyClicks(window.command, "jett")
    QTest.keyClick(window.command, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert window.command.text() == ""
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


def test_scrub_coalesces_and_finishes_exactly(window, monkeypatch):
    player = window.player
    calls = []
    monkeypatch.setattr(player.media, "setPosition", calls.append)
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


def test_background_completion(window, application):
    results = []
    window.background(lambda cancelled, progress: 42, results.append)
    assert wait_for(application, lambda: window.worker is None)
    assert results == [42]


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
