import hashlib
import json
import os
import subprocess
import sys
import zipfile

import pytest

from dfsorter import app_paths, release_update


def test_packaged_game_defaults_preserve_local_edits(tmp_path, monkeypatch):
    monkeypatch.setattr(app_paths, "ROOT", tmp_path)
    monkeypatch.setattr(app_paths.sys, "frozen", True, raising=False)
    defaults = tmp_path / "defaults/games"
    defaults.mkdir(parents=True)
    (defaults / "Game.yaml").write_text("version: 1", encoding="utf-8")
    app_paths.prepare_game_configs()
    active = tmp_path / "configs/games/Game.yaml"
    assert active.read_text(encoding="utf-8") == "version: 1"
    active.write_text("local edit", encoding="utf-8")
    (defaults / "Game.yaml").write_text("version: 2", encoding="utf-8")
    app_paths.prepare_game_configs()
    assert active.read_text(encoding="utf-8") == "local edit"
    assert (tmp_path / "configs/default-updates/Game.yaml").read_text(
        encoding="utf-8"
    ) == "version: 2"


def release_archive(tmp_path, version):
    package = tmp_path / "package/DFSorter"
    package.mkdir(parents=True)
    files = {}
    for name in release_update.MANAGED - {"release.json"}:
        target = package / name
        if "." not in name and name != "LICENSE":
            target = target / "content.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"{version}: {name}", encoding="utf-8")
        files[target.relative_to(package).as_posix()] = hashlib.sha256(
            target.read_bytes()
        ).hexdigest()
    (package / "release.json").write_text(
        json.dumps(
            {
                "version": version,
                "repo": release_update.REPO,
                "managed": sorted(release_update.MANAGED),
                "files": files,
            }
        ),
        encoding="utf-8",
    )
    archive = tmp_path / "release.zip"
    with zipfile.ZipFile(archive, "w") as output:
        for path in package.rglob("*"):
            if path.is_file():
                output.write(path, path.relative_to(package.parent).as_posix())
    return archive, package


def installed_copy(tmp_path, package):
    root = tmp_path / "installed"
    root.mkdir()
    for name in release_update.MANAGED:
        source = package / name
        target = root / name
        if source.is_dir():
            import shutil

            shutil.copytree(source, target)
        else:
            target.write_bytes(source.read_bytes())
    (root / "release.json").write_text(
        json.dumps({"version": "1.0.0", "managed": sorted(release_update.MANAGED)}),
        encoding="utf-8",
    )
    (root / "data").mkdir()
    (root / "data/dfsorter.db").write_text("catalogue", encoding="utf-8")
    (root / "configs/games").mkdir(parents=True)
    (root / "configs/games/Game.yaml").write_text("local edit", encoding="utf-8")
    return root


def test_update_preserves_state_and_keeps_backup(tmp_path, monkeypatch):
    archive, package = release_archive(tmp_path, "2.0.0")
    root = installed_copy(tmp_path, package)
    launched = []
    monkeypatch.setattr(
        release_update.subprocess, "Popen", lambda *args, **kwargs: launched.append(args)
    )
    backup = release_update.apply_update(root, archive, "2.0.0")
    assert release_update.installed_release(root)["version"] == "2.0.0"
    assert (root / "data/dfsorter.db").read_text(encoding="utf-8") == "catalogue"
    assert (root / "configs/games/Game.yaml").read_text(encoding="utf-8") == "local edit"
    assert (backup / "data/dfsorter.db").is_file()
    assert (backup / "application/DFSorter.exe").is_file()
    assert launched


def test_failed_replacement_restores_old_application(tmp_path, monkeypatch):
    archive, package = release_archive(tmp_path, "2.0.0")
    root = installed_copy(tmp_path, package)
    replace = os.replace

    def fail_new_executable(source, destination):
        if "staged-2.0.0" in str(source) and str(source).endswith("DFSorter.exe"):
            raise OSError("file locked")
        return replace(source, destination)

    monkeypatch.setattr(release_update.os, "replace", fail_new_executable)
    with pytest.raises(OSError, match="file locked"):
        release_update.apply_update(root, archive, "2.0.0")
    assert release_update.installed_release(root)["version"] == "1.0.0"
    assert (root / "DFSorter.exe").is_file()


def test_tampered_archive_is_rejected_before_replacing_files(tmp_path):
    archive, package = release_archive(tmp_path, "2.0.0")
    root = installed_copy(tmp_path, package)
    with pytest.raises(ValueError, match="changed after verification"):
        release_update.apply_update(root, archive, "2.0.0", expected_sha256="0" * 64)
    assert release_update.installed_release(root)["version"] == "1.0.0"


@pytest.mark.skipif(os.name != "nt", reason="Windows process handle check")
def test_update_helper_waits_for_app_process():
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.2)"])
    try:
        release_update._wait_for_exit(process.pid)
        assert process.wait(timeout=2) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
