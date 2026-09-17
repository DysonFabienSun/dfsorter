from pathlib import Path

import pytest

from dfsorter.catalogue import Catalogue
from dfsorter.config import Registry


@pytest.fixture
def registry():
    return Registry(Path(__file__).resolve().parents[1] / "configs/games")


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
