from dfsorter.unavailable_dialog import match_unavailable, unavailable_groups


def test_unavailable_groups_by_immediate_parent(catalogue, tmp_path):
    root = tmp_path / "old"
    root.mkdir()
    (root / "A").mkdir()
    (root / "B").mkdir()
    folder_id = catalogue.add_folder(root)
    paths = [root / "root.mp4", root / "A" / "a.mp4", root / "B" / "b.mp4"]
    catalogue.ingest(folder_id, [{"path": str(path), "game": None} for path in paths])

    groups = unavailable_groups(catalogue)

    assert set(groups) == {str(root), str(root / "A"), str(root / "B")}
    assert all(len(items) == 1 for items in groups.values())


def test_match_unavailable_previews_partial_matches_and_size_mismatches(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    clips = [
        {"clip_id": name, "source_path": str(old / f"{name}.mp4")}
        for name in ("matched", "missing", "wrong_size")
    ]
    (new / "matched.mp4").write_bytes(b"1234")
    (new / "wrong_size.mp4").write_bytes(b"different")
    cache = {item["source_path"]: {"size": 4} for item in clips}

    matches, missing, mismatched = match_unavailable(clips, new, cache)

    assert matches == {"matched": (str(old / "matched.mp4"), str(new / "matched.mp4"), 4)}
    assert missing == [str(old / "missing.mp4")]
    assert mismatched == [str(old / "wrong_size.mp4")]
