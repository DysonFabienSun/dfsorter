import random

from dfsorter.tips import TipLibrary


def test_tip_rotation_filters_by_game_and_exhausts_eligible_pool(tmp_path, monkeypatch):
    (tmp_path / "default.yaml").write_text("tips: [Generic A, Generic B]\n", encoding="utf-8")
    (tmp_path / "VALORANT.yaml").write_text(
        "game: VALORANT\ntips: [VALORANT only]\n", encoding="utf-8"
    )
    library = TipLibrary(tmp_path)
    monkeypatch.setattr(random, "choice", lambda options: options[0])
    assert [library.next("VALORANT") for _ in range(3)] == [
        "Generic A", "Generic B", "VALORANT only"
    ]
    assert library.next("VALORANT") in {"VALORANT only", "Generic A", "Generic B"}
    assert library.next(None) in {"Generic A", "Generic B"}


def test_invalid_tip_file_does_not_load_partial_entries(tmp_path):
    (tmp_path / "default.yaml").write_text("tips: [Valid, '']\n", encoding="utf-8")
    library = TipLibrary(tmp_path)
    assert library.tips == []
    assert len(library.errors) == 1
