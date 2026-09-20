import os
import shutil
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

from dfsorter.ui import ROOT, Window, style_application


def main():
    QCoreApplication.addLibraryPath(str(Path(PySide6.__file__).parent / "plugins"))
    application = QApplication([])
    style_application(application)
    scale = os.environ.get("QT_SCALE_FACTOR", "1")
    destination = ROOT / "cache/verification/design" / scale
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        shutil.copytree(ROOT / "configs", root / "configs")
        captures = root / "captures"
        captures.mkdir()
        folder = Window(root)
        source_id = folder.catalogue.add_folder(captures)
        for position in range(12):
            source = captures / f"clip-{position}.mp4"
            source.write_bytes(b"visual fixture")
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
        for panel in ("Home", "Session", "Editing", "Export", "Config"):
            folder.panel(panel)
            QTest.qWait(100)
            folder.grab().save(str(destination / f"{panel.lower()}.png"))
        folder.panel("Editing")
        folder.command.setFocus()
        QTest.qWait(100)
        folder.grab().save(str(destination / "focused.png"))
        folder.splitter.setSizes([260, 1100, 0])
        QTest.qWait(100)
        folder.grab().save(str(destination / "narrow.png"))
        folder.showMaximized()
        QTest.qWait(150)
        folder.grab().save(str(destination / "maximized.png"))
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
        dialog.grab().save(str(destination / "dialog.png"))
        dialog.close()
        folder.close()
        application.processEvents()
    print(destination)


if __name__ == "__main__":
    main()
