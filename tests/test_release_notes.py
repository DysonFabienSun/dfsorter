import subprocess
from pathlib import Path

import pytest

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
