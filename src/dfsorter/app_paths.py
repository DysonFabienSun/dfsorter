"""Paths shared by source checkouts and portable Windows releases."""

import hashlib
import json
import shutil
import sys
from pathlib import Path


def root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


ROOT = root()


def tool(name: str) -> str | None:
    bundled = ROOT / "bin" / f"{name}.exe"
    if getattr(sys, "frozen", False) and bundled.is_file():
        return str(bundled)
    return shutil.which(name)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_game_configs() -> None:
    """Seed defaults, updating only game files unchanged since the prior release."""
    if not getattr(sys, "frozen", False):
        return
    defaults = ROOT / "defaults" / "games"
    if not defaults.is_dir():
        raise FileNotFoundError(f"Packaged game definitions missing: {defaults}")
    active = ROOT / "configs" / "games"
    active.mkdir(parents=True, exist_ok=True)
    record = ROOT / "data" / "default-game-hashes.json"
    try:
        previous = json.loads(record.read_text(encoding="utf-8"))
        if not isinstance(previous, dict):
            previous = {}
    except (OSError, ValueError):
        previous = {}
    current = {}
    for source in defaults.glob("*.yaml"):
        target = active / source.name
        digest = _sha256(source)
        current[source.name] = digest
        if not target.exists() or previous.get(source.name) == _sha256(target):
            shutil.copy2(source, target)
        elif previous.get(source.name) != digest:
            revisions = ROOT / "configs" / "default-updates"
            revisions.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, revisions / source.name)
    record.parent.mkdir(parents=True, exist_ok=True)
    temporary = record.with_suffix(".tmp")
    temporary.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    temporary.replace(record)


def prepare_tip_configs() -> None:
    """Seed editable tips, updating files unchanged since the prior release."""
    if not getattr(sys, "frozen", False):
        return
    defaults = ROOT / "defaults" / "tips"
    if not defaults.is_dir():
        raise FileNotFoundError(f"Packaged tips missing: {defaults}")
    active = ROOT / "configs" / "tips"
    active.mkdir(parents=True, exist_ok=True)
    record = ROOT / "data" / "default-tip-hashes.json"
    try:
        previous = json.loads(record.read_text(encoding="utf-8"))
        if not isinstance(previous, dict):
            previous = {}
    except (OSError, ValueError):
        previous = {}
    current = {}
    for source in defaults.glob("*.yaml"):
        target = active / source.name
        digest = _sha256(source)
        current[source.name] = digest
        if not target.exists() or previous.get(source.name) == _sha256(target):
            shutil.copy2(source, target)
        elif previous.get(source.name) != digest:
            revisions = ROOT / "configs" / "default-updates" / "tips"
            revisions.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, revisions / source.name)
    record.parent.mkdir(parents=True, exist_ok=True)
    temporary = record.with_suffix(".tmp")
    temporary.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    temporary.replace(record)
