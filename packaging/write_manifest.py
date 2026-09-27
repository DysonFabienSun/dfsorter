"""Write the file hashes verified by the portable updater."""

import hashlib
import json
import sys
from pathlib import Path

from dfsorter.release_update import MANAGED, REPO


def main(directory, version):
    directory = Path(directory)
    files = {}
    for name in sorted(MANAGED - {"release.json"}):
        target = directory / name
        if not target.exists():
            raise FileNotFoundError(target)
        for path in target.rglob("*") if target.is_dir() else [target]:
            if path.is_file():
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                files[path.relative_to(directory).as_posix()] = digest.hexdigest()
    (directory / "release.json").write_text(
        json.dumps(
            {"version": version, "repo": REPO, "managed": sorted(MANAGED), "files": files}, indent=2
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main(*sys.argv[1:])
