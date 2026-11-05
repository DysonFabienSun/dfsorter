import hashlib
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def dependency(tmp_path):
    root = tmp_path / "checkout"
    packaging = root / "packaging"
    packaging.mkdir(parents=True)
    shutil.copyfile(ROOT / "packaging/dependencies.ps1", packaging / "dependencies.ps1")
    shutil.copyfile(ROOT / "setup-playback.ps1", root / "setup-playback.ps1")
    archive = tmp_path / "fixture.zip"
    files = {"mpv/libmpv-2.dll": b"runtime", "mpv/LICENSE.GPL": b"licence"}
    with zipfile.ZipFile(archive, "w") as bundle:
        for name, content in files.items():
            bundle.writestr(name, content)
    entry = {
        "archive": archive.name,
        "url": "https://github.com/DysonFabienSun/dfsorter/releases/download/dependencies-test/fixture.zip",
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "files": {name: hashlib.sha256(content).hexdigest() for name, content in files.items()},
    }
    manifest = {"schema_version": 1, "dependencies": {"libmpv": entry}}
    path = packaging / "dependencies.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return root, archive, manifest


def run(dependency, command):
    root, archive, _ = dependency
    script = """
    $ErrorActionPreference = 'Stop'
    function Invoke-WebRequest {
        param($Uri, $OutFile)
        Add-Content -LiteralPath (Join-Path $env:TEST_ROOT 'requests.txt') -Value $Uri
        Copy-Item -LiteralPath $env:TEST_ARCHIVE -Destination $OutFile
    }
    . (Join-Path $env:TEST_ROOT 'packaging/dependencies.ps1')
    """ + command
    return subprocess.run(
        ["pwsh", "-NoProfile", "-Command", script], capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**os.environ, "TEST_ROOT": str(root), "TEST_ARCHIVE": str(archive)},
    )


def test_download_verifies_caches_and_repairs_extracted_files_without_network(dependency):
    root, _, _ = dependency
    result = run(dependency, """
        $first = Get-VerifiedDependency -Name libmpv -Root $env:TEST_ROOT
        Set-Content -LiteralPath (Join-Path $first.Directory 'mpv/libmpv-2.dll') -Value 'damaged'
        $second = Get-VerifiedDependency -Name libmpv -Root $env:TEST_ROOT
        if ($first.Directory -ne $second.Directory) { throw 'Cache identity changed' }
        & (Join-Path $env:TEST_ROOT 'setup-playback.ps1') -NoProxy
        $installed = Join-Path $env:TEST_ROOT 'runtime/mpv/libmpv-2.dll'
        $inUse = [System.IO.File]::Open($installed, 'Open', 'Read', 'Read')
        try {
            & (Join-Path $env:TEST_ROOT 'setup-playback.ps1') -NoProxy
        } finally { $inUse.Dispose() }
    """)
    assert result.returncode == 0, result.stderr
    assert (root / "runtime/mpv/libmpv-2.dll").read_bytes() == b"runtime"
    assert (root / "runtime/mpv/LICENSE.GPL").read_bytes() == b"licence"
    assert len((root / "requests.txt").read_text().splitlines()) == 1


@pytest.mark.parametrize("cached", [False, True])
def test_bad_archive_fails_before_installing_and_cleans_partial_download(dependency, cached):
    root, archive, _ = dependency
    if cached:
        cache = root / "cache/dependencies"
        cache.mkdir(parents=True)
        (cache / archive.name).write_bytes(b"corrupt cached archive")
    else:
        archive.write_bytes(b"corrupt download")
    result = run(dependency, "& (Join-Path $env:TEST_ROOT 'setup-playback.ps1') -NoProxy")
    assert result.returncode != 0 and "checksum mismatch" in result.stderr
    assert not (root / "runtime/mpv").exists()
    assert not list((root / "cache/dependencies").glob("*.partial"))
    if cached:
        assert not (root / "requests.txt").exists()
    else:
        assert not (root / "cache/dependencies" / archive.name).exists()


@pytest.mark.parametrize("problem", ["checksum", "missing-licence", "path-escape"])
def test_required_files_are_verified_before_runtime_installation(dependency, problem):
    root, _, manifest = dependency
    files = manifest["dependencies"]["libmpv"]["files"]
    if problem == "checksum":
        files["mpv/libmpv-2.dll"] = "0" * 64
    elif problem == "missing-licence":
        files["mpv/LICENSE.LGPL"] = "0" * 64
    else:
        files["../../outside.dll"] = "0" * 64
    (root / "packaging/dependencies.json").write_text(json.dumps(manifest), encoding="utf-8")
    result = run(dependency, "& (Join-Path $env:TEST_ROOT 'setup-playback.ps1') -NoProxy")
    assert result.returncode != 0
    assert "checksum mismatch" in result.stderr or "escapes extraction directory" in result.stderr
    assert not (root / "runtime/mpv").exists()
