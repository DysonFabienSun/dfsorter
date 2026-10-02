from pathlib import Path
from time import monotonic

import pytest

from dfsorter.catalogue import Catalogue
from dfsorter.config import Registry


@pytest.fixture
def close_window():
    def close(window, application):
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtTest import QTest

        window.close()
        deadline = monotonic() + 12
        while window.isVisible() and monotonic() < deadline:
            application.processEvents()
            QTest.qWait(20)
        assert not window.isVisible(), "Test window did not finish closing"
        application.processEvents()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        application.processEvents()

    return close


@pytest.fixture
def registry():
    return Registry(Path(__file__).resolve().parents[1] / "configs/shipped")


@pytest.fixture
def catalogue(tmp_path):
    return Catalogue(tmp_path / "application/data/catalogue.db")


@pytest.fixture
def clips(catalogue, tmp_path):
    root = tmp_path / "captures"
    root.mkdir()
    folder_id = catalogue.add_folder(root)
    found = []
    for number in range(3):
        path = root / f"clip-{number}.mp4"
        path.write_bytes(bytes(range(256)) * 100)
        found.append({"path": str(path), "game": "VALORANT"})
    catalogue.ingest(folder_id, found)
    return catalogue.clips()
