"""Paths shared by source checkouts and portable Windows releases."""

import hashlib
import json
import shutil
import sys
from pathlib import Path

import yaml

from .config_merge import apply_valid_changes, merge
from .config_store import GameFile, validate_candidate


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


def prepare_game_configs() -> list[str]:
    """Merge packaged defaults into active game definitions where possible."""
    if not getattr(sys, "frozen", False):
        return []
    defaults = ROOT / "defaults" / "games"
    if not defaults.is_dir():
        raise FileNotFoundError(f"Packaged game definitions missing: {defaults}")
    active = ROOT / "configs" / "games"
    active.mkdir(parents=True, exist_ok=True)
    baseline = ROOT / "data" / "default-games"
    baseline.mkdir(parents=True, exist_ok=True)
    revisions = ROOT / "configs" / "default-updates"
    report = revisions / "merge-conflicts.txt"
    record = ROOT / "data" / "default-game-hashes.json"
    try:
        previous = json.loads(record.read_text(encoding="utf-8"))
        if not isinstance(previous, dict):
            previous = {}
    except (OSError, ValueError):
        previous = {}
    current = {}
    notices = []
    for source in sorted(defaults.glob("*.yaml")):
        target = active / source.name
        digest = _sha256(source)
        current[source.name] = digest
        old_default = baseline / source.name
        if (
            not target.exists()
            or _sha256(target) == digest
            or previous.get(source.name) == _sha256(target)
        ):
            shutil.copy2(source, target)
        elif previous.get(source.name) != digest:
            conflicts = []
            merged = None
            if old_default.is_file() and previous.get(source.name) == _sha256(old_default):
                try:
                    base = yaml.safe_load(old_default.read_text(encoding="utf-8"))
                    local = yaml.safe_load(target.read_text(encoding="utf-8"))
                    incoming = yaml.safe_load(source.read_text(encoding="utf-8"))
                    if all(isinstance(item, dict) for item in (base, local, incoming)):
                        merged = merge(base, local, incoming, conflicts=conflicts)
                        if merged.get("name") != local.get("name"):
                            raise ValueError("canonical name changed")
                        if merged != local:
                            merged = apply_valid_changes(
                                local, merged,
                                lambda candidate: validate_candidate(active, source.name, candidate),
                                conflicts,
                            )
                            if merged != local:
                                GameFile(target).save(merged, active)
                    else:
                        raise ValueError("configuration is not a mapping")
                except (OSError, ValueError, TypeError, yaml.YAMLError) as error:
                    merged = None
                    conflicts = [f"merge failed: {error}"]
            else:
                conflicts = ["previous default unavailable; edited configuration preserved"]
            if conflicts:
                revisions.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, revisions / source.name)
                notices.extend(f"{source.name}: {path}" for path in conflicts)
        shutil.copy2(source, old_default)
    if notices:
        revisions.mkdir(parents=True, exist_ok=True)
        report.write_text(
            "Skipped game configuration conflicts:\n" + "\n".join(notices) + "\n",
            encoding="utf-8",
        )
    record.parent.mkdir(parents=True, exist_ok=True)
    temporary = record.with_suffix(".tmp")
    temporary.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    temporary.replace(record)
    return notices


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
