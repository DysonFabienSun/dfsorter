import hashlib
import io
import json
import os
import subprocess
import sys
import zipfile

import pytest

from dfsorter import app_paths, release_update
from dfsorter.config_merge import merge


def test_latest_release_selects_asset_matching_tag(monkeypatch):
    release = {
        "tag_name": "v0.2.2",
        "assets": [
            {"name": "DFSorter-Windows-x64.zip", "digest": "sha256:" + "0" * 64},
            {
                "name": "DFSorter-v0.2.2-Windows-x64.zip",
                "browser_download_url": "https://example.com/versioned.zip",
                "digest": "sha256:" + "a" * 64,
            },
        ],
    }
    monkeypatch.setattr(
        release_update.urllib.request,
        "urlopen",
        lambda *args, **kwargs: io.BytesIO(json.dumps(release).encode()),
    )

    assert release_update.latest_release() == {
        "version": "0.2.2",
        "url": "https://example.com/versioned.zip",
        "sha256": "a" * 64,
    }


def test_latest_release_rejects_unrecognized_version(monkeypatch):
    release = {"tag_name": "v0.2.2-beta.1", "assets": []}
    monkeypatch.setattr(
        release_update.urllib.request,
        "urlopen",
        lambda *args, **kwargs: io.BytesIO(json.dumps(release).encode()),
    )

    with pytest.raises(ValueError, match="Invalid release version"):
        release_update.latest_release()


def test_packaged_game_defaults_preserve_local_edits(tmp_path, monkeypatch):
    monkeypatch.setattr(app_paths, "ROOT", tmp_path)
    monkeypatch.setattr(app_paths.sys, "frozen", True, raising=False)
    defaults = tmp_path / "defaults/games"
    defaults.mkdir(parents=True)
    (defaults / "Game.yaml").write_text("version: 1", encoding="utf-8")
    assert app_paths.prepare_game_configs() == []
    active = tmp_path / "configs/games/Game.yaml"
    assert active.read_text(encoding="utf-8") == "version: 1"
    active.write_text("local edit", encoding="utf-8")
    (defaults / "Game.yaml").write_text("version: 2", encoding="utf-8")
    notices = app_paths.prepare_game_configs()
    assert notices == ["Game.yaml: merge failed: configuration is not a mapping"]
    assert active.read_text(encoding="utf-8") == "local edit"
    assert (tmp_path / "configs/default-updates/Game.yaml").read_text(
        encoding="utf-8"
    ) == "version: 2"


def test_legacy_game_default_preserves_local_edits_without_baseline(tmp_path, monkeypatch):
    monkeypatch.setattr(app_paths, "ROOT", tmp_path)
    monkeypatch.setattr(app_paths.sys, "frozen", True, raising=False)
    defaults = tmp_path / "defaults/games"
    defaults.mkdir(parents=True)
    old = (
        "name: Example\ncode: EXM\nfields: {kill: {}}\n"
        "display_order: [kill, mainline]\n"
    )
    (defaults / "Example.yaml").write_text(old, encoding="utf-8")
    app_paths.prepare_game_configs()
    active = tmp_path / "configs/games/Example.yaml"
    active.write_text(old + "# local\n", encoding="utf-8")
    (tmp_path / "data/default-games/Example.yaml").unlink()
    (defaults / "Example.yaml").write_text(old.replace("EXM", "NEW"), encoding="utf-8")
    assert app_paths.prepare_game_configs() == [
        "Example.yaml: previous default unavailable; edited configuration preserved"
    ]
    assert active.read_text(encoding="utf-8") == old + "# local\n"


def test_packaged_game_defaults_merge_distinct_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(app_paths, "ROOT", tmp_path)
    monkeypatch.setattr(app_paths.sys, "frozen", True, raising=False)
    defaults = tmp_path / "defaults/games"
    defaults.mkdir(parents=True)
    original = (
        "name: Example\ncode: EXM\nfields:\n  kill: {}\n  weapon:\n"
        "    type: enum\n    values: [Pistol]\n    aliases: {sidearm: Pistol}\n"
        "display_order: [kill, weapon, mainline]\n"
    )
    (defaults / "Example.yaml").write_text(original, encoding="utf-8")
    assert app_paths.prepare_game_configs() == []
    active = tmp_path / "configs/games/Example.yaml"
    active.write_text(original.replace("[Pistol]", "[Pistol, Rifle]"), encoding="utf-8")
    (defaults / "Example.yaml").write_text(
        original.replace("[Pistol]", "[Pistol, SMG]")
        .replace("{sidearm: Pistol}", "{sidearm: Pistol, automatic: SMG}"),
        encoding="utf-8",
    )
    assert app_paths.prepare_game_configs() == []
    merged = app_paths.yaml.safe_load(active.read_text(encoding="utf-8"))
    assert merged["fields"]["weapon"]["values"] == ["Pistol", "Rifle", "SMG"]
    assert merged["fields"]["weapon"]["aliases"]["automatic"] == "SMG"


def test_packaged_game_defaults_skip_conflicting_setting(tmp_path, monkeypatch):
    monkeypatch.setattr(app_paths, "ROOT", tmp_path)
    monkeypatch.setattr(app_paths.sys, "frozen", True, raising=False)
    defaults = tmp_path / "defaults/games"
    defaults.mkdir(parents=True)
    original = (
        "name: Example\ncode: EXM\ncommand_example: original\nfields:\n  kill: {}\n"
        "  weapon:\n    type: enum\n    values: [Pistol]\n"
        "display_order: [kill, weapon, mainline]\n"
    )
    (defaults / "Example.yaml").write_text(original, encoding="utf-8")
    app_paths.prepare_game_configs()
    active = tmp_path / "configs/games/Example.yaml"
    active.write_text(original.replace("original", "local"), encoding="utf-8")
    (defaults / "Example.yaml").write_text(
        original.replace("original", "incoming").replace("[Pistol]", "[Pistol, Rifle]"),
        encoding="utf-8",
    )
    assert app_paths.prepare_game_configs() == ["Example.yaml: command_example"]
    merged = app_paths.yaml.safe_load(active.read_text(encoding="utf-8"))
    assert merged["command_example"] == "local"
    assert merged["fields"]["weapon"]["values"] == ["Pistol", "Rifle"]
    assert "Example.yaml: command_example" in (
        tmp_path / "configs/default-updates/merge-conflicts.txt"
    ).read_text(encoding="utf-8")


def test_packaged_game_defaults_keep_local_alias_and_yaml_comment(tmp_path, monkeypatch):
    monkeypatch.setattr(app_paths, "ROOT", tmp_path)
    monkeypatch.setattr(app_paths.sys, "frozen", True, raising=False)
    defaults = tmp_path / "defaults/games"
    defaults.mkdir(parents=True)
    original = (
        "name: Example\ncode: EXM\nfields:\n  kill: {}\n"
        "  weapon:\n    type: enum\n    values: [Pistol, Rifle, SMG]\n"
        "    aliases: {short: Pistol}\n"
        "display_order: [kill, weapon, mainline]\n"
    )
    (defaults / "Example.yaml").write_text(original, encoding="utf-8")
    app_paths.prepare_game_configs()
    active = tmp_path / "configs/games/Example.yaml"
    active.write_text("# Personal note\n" + original.replace("short: Pistol", "short: Rifle"), encoding="utf-8")
    (defaults / "Example.yaml").write_text(
        original.replace("short: Pistol", "short: SMG")
        .replace("[Pistol, Rifle, SMG]", "[Pistol, Rifle, SMG, Sniper]"),
        encoding="utf-8",
    )
    assert app_paths.prepare_game_configs() == ["Example.yaml: fields.weapon.aliases.short"]
    text = active.read_text(encoding="utf-8")
    assert text.startswith("# Personal note\n")
    assert "short: Rifle" in text
    assert "Sniper" in text
    assert app_paths.prepare_game_configs() == []


def test_game_default_merge_keeps_local_on_competing_list_reorders():
    conflicts = []
    assert merge(
        {"display_order": ["kill", "map", "weapon", "mainline"]},
        {"display_order": ["weapon", "kill", "map", "mainline"]},
        {"display_order": ["map", "kill", "weapon", "mainline"]},
        conflicts=conflicts,
    ) == {"display_order": ["weapon", "kill", "map", "mainline"]}
    assert conflicts == ["display_order"]


def test_packaged_game_defaults_skip_invalid_item_but_apply_other_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(app_paths, "ROOT", tmp_path)
    monkeypatch.setattr(app_paths.sys, "frozen", True, raising=False)
    defaults = tmp_path / "defaults/games"
    defaults.mkdir(parents=True)
    original = (
        "name: Example\ncode: EXM\ncommand_example: original\nfields:\n  kill: {}\n"
        "  weapon:\n    type: enum\n    values: [Pistol]\n"
        "display_order: [kill, weapon, mainline]\n"
    )
    (defaults / "Example.yaml").write_text(original, encoding="utf-8")
    app_paths.prepare_game_configs()
    active = tmp_path / "configs/games/Example.yaml"
    active.write_text(
        original.replace("values: [Pistol]", "values: [Pistol, Rifle]"), encoding="utf-8"
    )
    (defaults / "Example.yaml").write_text(
        original.replace("command_example: original", "command_example: new")
        .replace("values: [Pistol]", "values: [Pistol, SMG]\n    aliases: {rifle: SMG}"),
        encoding="utf-8",
    )
    notices = app_paths.prepare_game_configs()
    merged = app_paths.yaml.safe_load(active.read_text(encoding="utf-8"))
    assert merged["command_example"] == "new"
    assert merged["fields"]["weapon"]["values"] == ["Pistol", "Rifle", "SMG"]
    assert "aliases" not in merged["fields"]["weapon"]
    assert notices == ["Example.yaml: fields.weapon.aliases"]


def test_packaged_tip_defaults_preserve_local_edits(tmp_path, monkeypatch):
    monkeypatch.setattr(app_paths, "ROOT", tmp_path)
    monkeypatch.setattr(app_paths.sys, "frozen", True, raising=False)
    defaults = tmp_path / "defaults/tips"
    defaults.mkdir(parents=True)
    (defaults / "default.yaml").write_text("tips: [First]", encoding="utf-8")
    app_paths.prepare_tip_configs()
    active = tmp_path / "configs/tips/default.yaml"
    assert active.read_text(encoding="utf-8") == "tips: [First]"
    active.write_text("tips: [Local]", encoding="utf-8")
    (defaults / "default.yaml").write_text("tips: [Second]", encoding="utf-8")
    app_paths.prepare_tip_configs()
    assert active.read_text(encoding="utf-8") == "tips: [Local]"
    assert (tmp_path / "configs/default-updates/tips/default.yaml").read_text(
        encoding="utf-8"
    ) == "tips: [Second]"


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
