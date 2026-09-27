"""Public release lookup, download, and safe replacement of a portable copy."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

from .app_paths import ROOT

REPO = "DysonFabienSun/dfsorter"
ASSET_SUFFIX = "-Windows-x64.zip"
MANAGED = {
    "DFSorter.exe",
    "DFSorterUpdater.exe",
    "_internal",
    "bin",
    "runtime",
    "resources",
    "defaults",
    "licenses",
    "LICENSE",
    "THIRD-PARTY-NOTICES.txt",
    "release.json",
}


def installed_release(root=ROOT):
    manifest = root / "release.json"
    return json.loads(manifest.read_text(encoding="utf-8")) if manifest.is_file() else None


def version_tuple(version):
    value = version.removeprefix("v").split(".")
    if len(value) != 3 or not all(part.isdigit() for part in value):
        raise ValueError(f"Invalid release version: {version}")
    return tuple(map(int, value))


def latest_release():
    request = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "DFSorter-Updater"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        release = json.load(response)
    tag = release["tag_name"]
    version_tuple(tag)
    asset_name = f"DFSorter-{tag}{ASSET_SUFFIX}"
    asset = next((item for item in release["assets"] if item["name"] == asset_name), None)
    if not asset or not asset.get("digest", "").startswith("sha256:"):
        raise ValueError("Release ZIP or SHA-256 digest missing")
    return {
        "version": release["tag_name"].removeprefix("v"),
        "url": asset["browser_download_url"],
        "sha256": asset["digest"][7:],
    }


def download_release(release, destination, cancelled=lambda: False):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".partial")
    digest = hashlib.sha256()
    try:
        request = urllib.request.Request(release["url"], headers={"User-Agent": "DFSorter-Updater"})
        with (
            urllib.request.urlopen(request, timeout=30) as response,
            temporary.open("wb") as output,
        ):
            while chunk := response.read(1024 * 1024):
                if cancelled():
                    raise InterruptedError("Update download cancelled")
                output.write(chunk)
                digest.update(chunk)
        if digest.hexdigest().lower() != release["sha256"].lower():
            raise ValueError("Release ZIP SHA-256 mismatch")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _verify_archive(archive, destination, version):
    with zipfile.ZipFile(archive) as package:
        entries = package.infolist()
        seen = set()
        for entry in entries:
            path = PurePosixPath(entry.filename)
            if (
                "\\" in entry.filename
                or ":" in entry.filename
                or not path.parts
                or path.parts[0] != "DFSorter"
                or ".." in path.parts
                or path.is_absolute()
                or (len(path.parts) > 1 and path.parts[1] not in MANAGED)
                or (entry.external_attr >> 16) & 0o170000 == 0o120000
            ):
                raise ValueError(f"Invalid release ZIP entry: {entry.filename}")
            if not entry.is_dir():
                if entry.filename in seen:
                    raise ValueError(f"Duplicate release ZIP entry: {entry.filename}")
                seen.add(entry.filename)
        package.extractall(destination)
    staged = destination / "DFSorter"
    manifest = json.loads((staged / "release.json").read_text(encoding="utf-8"))
    if manifest.get("version") != version or manifest.get("repo") != REPO:
        raise ValueError("Release manifest does not match the selected version")
    if set(manifest.get("managed", [])) != MANAGED:
        raise ValueError("Release manifest has an unexpected file layout")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("Release file hashes missing")
    actual = {path.relative_to(staged).as_posix() for path in staged.rglob("*") if path.is_file()}
    if actual != set(files) | {"release.json"}:
        raise ValueError("Release ZIP contains unexpected or missing files")
    for name, expected in files.items():
        path = PurePosixPath(name)
        if (
            not path.parts
            or path.is_absolute()
            or ".." in path.parts
            or path.parts[0] not in MANAGED
        ):
            raise ValueError(f"Invalid release file path: {name}")
        target = staged.joinpath(*path.parts)
        digest = hashlib.sha256()
        if not target.is_file():
            raise ValueError(f"Release file missing: {name}")
        with target.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise ValueError(f"Release file verification failed: {name}")
    return staged


def _wait_for_exit(pid):
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x00100000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:  # Process already exited.
            return
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if kernel.WaitForSingleObject(handle, 120_000) != 0:
            raise TimeoutError("DFSorter did not close before the update")
    finally:
        kernel.CloseHandle(handle)


def apply_update(root, archive, version, parent_pid=0, expected_sha256=None):
    root = Path(root).resolve()
    old = installed_release(root)
    if not old or version_tuple(version) <= version_tuple(old["version"]):
        raise ValueError("Update must be newer than the installed portable release")
    if set(old.get("managed", [])) != MANAGED:
        raise ValueError("Installed release layout is not recognized")
    if expected_sha256:
        digest = hashlib.sha256()
        with Path(archive).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected_sha256.lower():
            raise ValueError("Downloaded release ZIP changed after verification")
    work = root / "cache" / "update"
    staged_directory = work / f"staged-{version}"
    if staged_directory.exists():
        shutil.rmtree(staged_directory)
    staged = _verify_archive(archive, staged_directory, version)
    if parent_pid:
        _wait_for_exit(parent_pid)
    backup = root / "backups" / "updates" / f"before-{version}-{int(time.time())}"
    backup.mkdir(parents=True)
    for name in ("data", "configs"):
        source = root / name
        if source.exists():
            shutil.copytree(source, backup / name)
    previous = backup / "application"
    previous.mkdir()
    moved_old = []
    moved_new = []
    try:
        for name in sorted(MANAGED):
            source = root / name
            if source.exists():
                os.replace(source, previous / name)
                moved_old.append(name)
        for name in sorted(MANAGED):
            os.replace(staged / name, root / name)
            moved_new.append(name)
    except Exception:
        for name in reversed(moved_new):
            target = root / name
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink(missing_ok=True)
        for name in reversed(moved_old):
            os.replace(previous / name, root / name)
        raise
    finally:
        shutil.rmtree(staged_directory, ignore_errors=True)
    subprocess.Popen([str(root / "DFSorter.exe")], cwd=root)
    return backup


def updater_main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--parent-pid", type=int, required=True)
    parser.add_argument("--sha256", required=True)
    args = parser.parse_args()
    try:
        apply_update(args.root, args.archive, args.version, args.parent_pid, args.sha256)
    except Exception as error:
        log = args.root / "cache" / "update" / "update-error.txt"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(str(error), encoding="utf-8")
        if os.name == "nt":
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, str(error), "DFSorter update failed", 0x10)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(updater_main())
