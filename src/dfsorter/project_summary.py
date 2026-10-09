"""Project-wide export readiness and original-file size estimates."""

import stat
from pathlib import Path

from .output import validate

SIZE_EXPLANATION = (
    "Total original-file size of Ready project members. "
    "Pending, Blocked and Discard clips are excluded. "
    "Selection, filters, temporary skips and In/Out ranges do not affect this estimate. "
    "1 GB = 2³⁰ bytes (1,073,741,824 bytes)."
)


def project_readiness(clips, registry):
    errors = dict(validate(clips, registry))
    categories = {name: set() for name in ("Ready", "Pending", "Blocked", "Skipped")}
    for clip in clips:
        category = (
            "Pending" if clip["triage"] is None
            else "Skipped" if clip["triage"] == "discard"
            else "Blocked" if clip["clip_id"] in errors
            else "Ready"
        )
        categories[category].add(clip["clip_id"])
    return categories, errors


def ready_source_bytes(clips, ready_ids):
    total = 0
    for clip in clips:
        if clip["clip_id"] not in ready_ids:
            continue
        try:
            source = Path(clip["source_path"]).stat()
            if not stat.S_ISREG(source.st_mode):
                return None
            total += source.st_size
        except OSError:
            return None
    return total
