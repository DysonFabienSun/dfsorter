import os
import subprocess
from pathlib import Path

import pytest
import yaml

SCRIPT = Path(__file__).resolve().parents[1] / "packaging/read-release-notes.ps1"
NOTES = """## DFSorter v1.2.3 Changelog

### Improvements
- Keep filters responsive — including 中文 labels.

### UI fixes
- Center the checkmark; preserve `literal` formatting and $characters.

Full Changelog: https://github.com/DysonFabienSun/dfsorter/compare/v1.2.2...v1.2.3
"""


@pytest.fixture
def repository(tmp_path):
    def git(*args):
        return subprocess.run(
            ["git", "-c", "user.name=Release test", "-c", "user.email=test@example.com", *args],
            cwd=tmp_path, check=True, capture_output=True,
        )

    git("init")
    git("commit", "--allow-empty", "-m", "Fixture")
    return tmp_path, git


@pytest.mark.parametrize("invalid", [None, "lightweight", "wrong-heading", "missing-link"])
def test_release_annotation_extraction_preserves_notes_or_rejects_invalid_tags(repository, invalid):
    root, git = repository
    notes = NOTES
    if invalid == "wrong-heading":
        notes = notes.replace("## DFSorter v1.2.3 Changelog", "## DFSorter v1.2.2 Changelog")
    elif invalid == "missing-link":
        notes = notes.split("Full Changelog:")[0]
    source = root / "annotation.md"
    source.write_text(notes, encoding="utf-8")
    if invalid == "lightweight":
        git("tag", "v1.2.3")
    else:
        git("tag", "--annotate", "v1.2.3", "--cleanup=verbatim", "--file", str(source))
    output = root / "release-notes.md"
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(SCRIPT), "-Tag", "v1.2.3", "-OutputPath", str(output)],
        cwd=root, capture_output=True,
    )
    if invalid:
        assert result.returncode != 0
        assert not output.exists()
    else:
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        assert output.read_text(encoding="utf-8") == NOTES


@pytest.mark.parametrize("different_source", [False, True])
def test_workflow_restores_annotation_after_checkout_and_checks_source(repository, different_source):
    root, git = repository
    source = root / "annotation.md"
    source.write_text(NOTES, encoding="utf-8")
    git("tag", "--annotate", "v1.2.3", "--cleanup=verbatim", "--file", str(source))
    runner = root / "runner"
    git("clone", str(root), str(runner))
    subprocess.run(
        ["git", "update-ref", "refs/tags/v1.2.3", "HEAD"], cwd=runner, check=True,
        capture_output=True,
    )
    if different_source:
        subprocess.run(
            ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
             "commit", "--allow-empty", "-m", "Different source"],
            cwd=runner, check=True, capture_output=True,
        )
    workflow = yaml.load(
        (SCRIPT.parents[1] / ".github/workflows/release-windows.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    restore = next(
        step["run"] for step in workflow["jobs"]["release"]["steps"]
        if step.get("name") == "Restore original annotated tag after checkout"
    )
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", restore], cwd=runner, capture_output=True,
        env={**os.environ, "RELEASE_TAG": "v1.2.3"},
    )
    assert (result.returncode == 0) is not different_source
    restored = subprocess.run(
        ["git", "cat-file", "-t", "refs/tags/v1.2.3"], cwd=runner,
        check=True, capture_output=True, text=True,
    )
    assert restored.stdout.strip() == "tag"


@pytest.mark.parametrize("invalid", [None, "bundle", "dll"])
def test_workflow_restores_only_verified_published_runtime(tmp_path, invalid):
    import hashlib
    import zipfile

    workflow = yaml.load(
        (SCRIPT.parents[1] / ".github/workflows/release-windows.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    restore = next(step["run"] for step in workflow["jobs"]["release"]["steps"]
                   if step.get("name") == "Restore pinned libmpv from published release")
    fixture = tmp_path / "runtime-fixture.zip"
    dll = b"verified runtime fixture"
    with zipfile.ZipFile(fixture, "w") as archive:
        for name in ("libmpv-2.dll", "Copyright", "LICENSE.GPL", "LICENSE.LGPL"):
            archive.writestr("DFSorter/runtime/mpv/" + name, dll if name.endswith(".dll") else b"license")
    restore = restore.replace(
        "1cceba7837a9ba731e766e21b24a620033ab8bce5cd1e8cc906f7923163194af",
        "0" * 64 if invalid == "bundle" else hashlib.sha256(fixture.read_bytes()).hexdigest(),
    ).replace(
        "673e6397920ab64a9c5b3a618f7f16d38854efe72b58665f1f84e4e873b763a4",
        "0" * 64 if invalid == "dll" else hashlib.sha256(dll).hexdigest(),
    )
    command = (
        "$ErrorActionPreference = 'Stop'; "
        "function Invoke-WebRequest { param($Uri, $OutFile) "
        "Copy-Item -LiteralPath $env:FIXTURE_BUNDLE -Destination $OutFile };\n" + restore
    )
    runner = tmp_path / "runner"
    runner.mkdir()
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", command], cwd=checkout, capture_output=True,
        env={**os.environ, "RUNNER_TEMP": str(runner), "FIXTURE_BUNDLE": str(fixture)},
    )
    assert (result.returncode == 0) is (invalid is None), result.stderr.decode(errors="replace")
    target = checkout / "runtime/mpv/libmpv-2.dll"
    if invalid:
        assert not target.exists()
    else:
        assert target.read_bytes() == dll
        assert {path.name for path in target.parent.iterdir()} == {
            "libmpv-2.dll", "Copyright", "LICENSE.GPL", "LICENSE.LGPL"
        }
