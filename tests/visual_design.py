import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import PySide6
from PySide6.QtCore import QCoreApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from dfsorter.app_paths import tool
from dfsorter.settings_dialog import SettingsDialog
from dfsorter.ui import ROOT, Window, style_application


def main():
    QCoreApplication.addLibraryPath(str(Path(PySide6.__file__).parent / "plugins"))
    application = QApplication([])
    style_application(application)
    scale = os.environ.get("QT_SCALE_FACTOR", "1")
    destination = ROOT / "cache/verification/facelift" / scale
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        shutil.copytree(ROOT / "configs", root / "configs")
        captures = root / "captures"
        captures.mkdir()
        fixture_video = root / "fixture.mp4"
        subprocess.run(
            [tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-f", "lavfi",
             "-i", "testsrc2=size=320x180:rate=25:duration=1.4", "-c:v", "mpeg4",
             "-y", str(fixture_video)],
            check=True,
        )
        folder = Window(root)
        source_id = folder.catalogue.add_folder(captures)
        for position in range(12):
            source = captures / f"clip-{position}.mp4"
            shutil.copyfile(fixture_video, source)
            folder.catalogue.ingest(source_id, [{"path": str(source), "game": "VALORANT"}])
        clips = folder.catalogue.clips()
        folder.catalogue.create_session([clip["clip_id"] for clip in clips])
        folder.refresh_references()
        folder.panel("Editing")
        for position, clip in enumerate(clips):
            folder.current_id = clip["clip_id"]
            folder.edit(
                {
                    "mainline": [
                        "Clean finish",
                        "残局 中文 English — accurate shot",
                        "A long working title " * 7,
                    ][position % 3],
                    "triage": ["keep", "discard", None][position % 3],
                    "metadata": {"agent": "Jett", "weapon": ["Vandal", "Sheriff"], "kill": 3},
                    "rating": 4,
                }
            )
        (captures / "clip-2.mp4").unlink()
        folder.load_clip(clips[0]["clip_id"])
        folder.refresh_library()
        folder.show()
        folder.resize(1400, 900)
        for theme in os.environ.get("DFSORTER_VISUAL_THEMES", "light,dark").split(","):
            target = destination / theme
            target.mkdir(parents=True, exist_ok=True)
            folder.showNormal()
            folder.resize(1400, 900)
            folder.set_theme(theme)
            for panel in ("Home", "Browse", "Session", "Editing", "Export", "Config"):
                folder.panel(panel)
                if panel in {"Browse", "Editing", "Export"}:
                    folder.active_player().awaiting_frame = False
                    folder.queue_page_reveal()
                QTest.qWait(100)
                folder.grab().save(str(target / f"{panel.lower()}.png"))
                if panel in {"Home", "Browse", "Session"}:
                    folder.showMaximized()
                    QTest.qWait(120)
                    folder.grab().save(str(target / f"{panel.lower()}-maximized.png"))
                    folder.showNormal()
                    folder.resize(1400, 900)
                    QTest.qWait(100)
            folder.panel("Session")
            folder.grab().save(str(target / "projects-empty.png"))
            project_id = folder.catalogue.save_project("Highlights")
            folder.refresh_references()
            folder.projects.setCurrentRow(0)
            folder.activate_project()
            for panel in ("Session", "Home", "Editing"):
                folder.panel(panel)
                if not folder.right.isVisible():
                    folder.toggle_projects()
                if panel == "Editing":
                    folder.active_player().awaiting_frame = False
                    folder.queue_page_reveal()
                QTest.qWait(120)
                folder.grab().save(str(target / f"{panel.lower()}-projects.png"))
            for clip in clips:
                folder.catalogue.patch(clip["clip_id"], {"triage": "keep"})
            folder.panel("Session")
            QTest.qWait(120)
            folder.grab().save(str(target / "session-completed.png"))
            for position, clip in enumerate(clips):
                folder.catalogue.patch(
                    clip["clip_id"], {"triage": ["keep", "discard", None][position % 3]}
                )
            folder.catalogue.delete_project(project_id)
            folder.refresh_references()
            folder.panel("Browse")
            folder.unavailable_toggle.click()
            folder.clip_filter.set_selected_values({None, "keep", "discard"})
            QTest.qWait(100)
            for index in range(folder.library.count()):
                item = folder.library.item(index)
                if "[unavailable]" in item.text():
                    folder.library.scrollToItem(item)
                    break
            QTest.qWait(250)
            folder.grab().save(str(target / "browse-unavailable.png"))
            folder.unavailable_toggle.click()
            folder.panel("Editing")
            folder.command.setFocus()
            QTest.qWait(100)
            folder.grab().save(str(target / "focused.png"))
            folder.splitter.setSizes([260, 1100, 0])
            QTest.qWait(100)
            folder.grab().save(str(target / "narrow.png"))
            folder.showMaximized()
            QTest.qWait(150)
            folder.grab().save(str(target / "maximized.png"))
            dialog = QDialog(folder)
            dialog.setWindowTitle("Project name")
            layout = QVBoxLayout(dialog)
            layout.addWidget(QLabel("Rename project"))
            layout.addWidget(QLineEdit("Montage — 精选"))
            layout.addWidget(
                QDialogButtonBox(
                    QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
                )
            )
            dialog.show()
            QTest.qWait(100)
            dialog.grab().save(str(target / "dialog.png"))
            dialog.close()
            settings = SettingsDialog(folder)
            settings.show()
            QTest.qWait(100)
            settings.grab().save(str(target / "settings.png"))
            settings.close()
        folder.close()
        application.processEvents()
    print(destination)


if __name__ == "__main__":
    main()
