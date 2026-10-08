import hashlib
import os
import re
import tempfile
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

from .config import has_review_metadata, title


def safe_stem(value: str, *, text_spans=None) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value)
    trimmed = len(value) - len(value.lstrip(" ."))
    value = value.strip(" .")[:160].rstrip(" .")
    if text_spans is not None:
        text_spans[:] = [
            (role, max(0, start - trimmed), min(len(value), start + length - trimmed) - max(0, start - trimmed))
            for role, start, length in text_spans
            if min(len(value), start + length - trimmed) > max(0, start - trimmed)
        ]
    if not value:
        value = "clip"
    if value.split(".")[0].upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in range(1, 10)),
    }:
        value = "_" + value
        if text_spans is not None:
            text_spans[:] = [(role, start + 1, length) for role, start, length in text_spans]
    return value


def validate(clips, registry):
    errors = []
    for clip in clips:
        reasons = []
        if clip["triage"] == "discard":
            continue
        if clip["triage"] is None:
            reasons.append("verdict is pending")
        else:
            game = registry.game(clip["game"])
            if not game:
                reasons.append("assign a configured game")
            else:
                if not has_review_metadata(clip, game):
                    reasons.append("add at least one metadata field or mainline")
            if not Path(clip["source_path"]).is_file():
                reasons.append("source unavailable")
        if reasons:
            errors.append(
                (clip["clip_id"], f"{Path(clip['source_path']).name}: " + "; ".join(reasons))
            )
    return errors


@dataclass
class CopyResult:
    completed: list[str] = field(default_factory=list)
    error: str | None = None
    cancelled: bool = False


def check_destination(destination, folders):
    destination = Path(destination).resolve()
    for folder in folders:
        if destination.is_relative_to(Path(folder["path"]).resolve()):
            raise ValueError("Output must be outside all configured capture folders")
    return destination


def copy_one(clip, directory: Path, stem: str, cancelled=lambda: False):
    source = Path(clip["source_path"])
    directory.mkdir(parents=True, exist_ok=True)
    stem = safe_stem(stem)
    suffix = 0
    while True:
        target = directory / f"{stem}{f' ({suffix})' if suffix else ''}{source.suffix}"
        if target.exists():
            suffix += 1
            continue
        try:
            output = target.open("xb")
        except FileExistsError:
            suffix += 1
            continue
        try:
            with output, source.open("rb") as input_file:
                before = source.stat()
                count = 0
                while True:
                    if cancelled():
                        raise InterruptedError("Copy cancelled")
                    chunk = input_file.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    count += len(chunk)
                after = source.stat()
                if count != before.st_size or (after.st_size, after.st_mtime_ns) != (
                    before.st_size,
                    before.st_mtime_ns,
                ):
                    raise OSError("Source changed during copying")
            return str(target)
        except BaseException:
            output.close()
            target.unlink(missing_ok=True)
            raise


def export_project(
    clips,
    registry,
    destination,
    folders,
    formats=None,
    group_rating=False,
    cancelled=lambda: False,
    progress=lambda text: None,
    *,
    lowercase=True,
):
    errors = validate(clips, registry)
    if errors:
        raise ValueError("\n".join(message for clip_id, message in errors))
    destination = check_destination(destination, folders)
    result = CopyResult()
    for clip in clips:
        if clip["triage"] != "keep":
            continue
        options = (formats or {}).get(clip["game"], {})
        stem = title(
            clip, registry, options.get("fields"), options.get("prefix", True), lowercase=lowercase
        )
        directory = destination
        if group_rating:
            directory /= f"R{clip['rating']}" if clip["rating"] else "unrated"
        progress(f"Copying {Path(clip['source_path']).name}")
        try:
            result.completed.append(copy_one(clip, directory, stem, cancelled=cancelled))
        except (OSError, InterruptedError) as error:
            result.error = str(error)
            result.cancelled = isinstance(error, InterruptedError)
            break
    return result


def prepare_export_manifest(clips, registry, destination, folders, formats=None,
                            group_rating=False, *, lowercase=True, defer_validation=False):
    """Freeze export choices, optionally recording eligibility failures for the queued job."""
    errors = validate(clips, registry)
    if errors and not defer_validation:
        raise ValueError("\n".join(message for _, message in errors))
    root = check_destination(destination, folders)
    items = []
    for clip in clips:
        if clip["triage"] != "keep":
            continue
        source = Path(clip["source_path"])
        try:
            source_stat = source.stat()
        except OSError as error:
            if not defer_validation:
                raise
            source_stat = None
            if not any(clip_id == clip["clip_id"] for clip_id, _ in errors):
                errors.append((clip["clip_id"], f"{source.name}: {error}"))
        options = (formats or {}).get(clip["game"], {})
        name = safe_stem(title(
            clip, registry, options.get("fields"), options.get("prefix", True),
            lowercase=lowercase,
        ))
        directory = (
            f"R{clip['rating']}" if clip["rating"] else "unrated"
        ) if group_rating else ""
        items.append({
            "clip_id": clip["clip_id"], "source_path": str(source),
            "source_size": source_stat.st_size if source_stat else 0,
            "source_mtime_ns": source_stat.st_mtime_ns if source_stat else None,
            "stem": name, "directory": directory, "completed": None,
        })
    manifest = {"destination": str(root), "items": items}
    if errors:
        manifest["validation_errors"] = [message for _, message in errors]
    return manifest


def _hash_file(path, cancelled):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        while chunk := source.read(1024 * 1024):
            if cancelled():
                raise InterruptedError("Export cancelled")
            digest.update(chunk)
    return digest.hexdigest()


def _copy_resumable(item, directory, job_id, cancelled, advanced,
                    before_publish=lambda target, temporary, size, checksum: None,
                    on_abort=lambda: None):
    """Build a complete temporary copy, then publish it without overwriting a name."""
    directory.mkdir(parents=True, exist_ok=True)
    source = Path(item["source_path"])
    digest = hashlib.sha256()
    temporary = None
    published = False
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=directory, prefix=f".dfsorter-export-{job_id}-",
            suffix=".part", delete=False,
        ) as output, source.open("rb") as input_file:
            temporary = Path(output.name)
            before = source.stat()
            copied = 0
            while chunk := input_file.read(1024 * 1024):
                if cancelled():
                    raise InterruptedError("Export cancelled")
                output.write(chunk)
                digest.update(chunk)
                copied += len(chunk)
                advanced(len(chunk))
            after = source.stat()
            if (copied != before.st_size or (after.st_size, after.st_mtime_ns)
                    != (before.st_size, before.st_mtime_ns)):
                raise OSError("Source changed during copying")
        suffix = 0
        while True:
            if cancelled():
                raise InterruptedError("Export cancelled")
            target = directory / f"{item['stem']}{f' ({suffix})' if suffix else ''}{source.suffix}"
            before_publish(target, temporary, copied, digest.hexdigest())
            try:
                if os.name == "nt":
                    temporary.rename(target)  # Windows rename refuses an existing destination.
                else:
                    os.link(temporary, target)  # link is exclusive on POSIX.
                published = True
                return str(target), digest.hexdigest()
            except FileExistsError:
                suffix += 1
    finally:
        if temporary is not None:
            if not published:
                on_abort()
            temporary.unlink(missing_ok=True)


def run_export_manifest(catalogue, job_id, cancelled=lambda: False,
                        detailed_progress=lambda percent, message: None):
    """Verify recorded outputs, then continue only the unfinished frozen entries."""
    record = next((job for job in catalogue.export_jobs() if job["job_id"] == job_id), None)
    if record is None:
        raise ValueError("Export job no longer exists")
    manifest = deepcopy(record["manifest"])
    catalogue.save_export_job(job_id, manifest, "Running")
    result = CopyResult()
    total = sum(item["source_size"] for item in manifest["items"])
    done_bytes = 0
    try:
        if manifest.get("validation_errors"):
            raise ValueError("\n".join(manifest["validation_errors"]))
        check_destination(manifest["destination"], catalogue.folders())
        recovered = set()
        for item in manifest["items"]:
            pending = item.get("pending")
            if not pending:
                continue
            target = Path(pending["target"])
            temporary = Path(pending["temporary"])
            owned = target.is_file() and (
                not temporary.exists() or os.path.samefile(target, temporary)
            )
            if owned:
                if (target.stat().st_size != pending["size"]
                        or _hash_file(target, cancelled) != pending["sha256"]):
                    raise ValueError(f"Completed export copy changed: {target}. Repair the file before resuming.")
                item["completed"] = {
                    "path": str(target), "size": pending["size"],
                    "sha256": pending["sha256"],
                }
                recovered.add(str(target))
            temporary.unlink(missing_ok=True)
            item["pending"] = None
            catalogue.save_export_job(job_id, manifest, "Running")
        for directory in {Path(manifest["destination"]) / item["directory"] for item in manifest["items"]}:
            if directory.is_dir():
                for temporary in directory.glob(f".dfsorter-export-{job_id}-*.part"):
                    temporary.unlink(missing_ok=True)
        for item in manifest["items"]:
            completed = item["completed"]
            if not completed:
                continue
            detailed_progress(min(99, int(done_bytes * 100 / max(1, total))),
                              f"Verifying {Path(completed['path']).name}")
            target = Path(completed["path"])
            if (not target.is_file() or target.stat().st_size != completed["size"]
                    or (str(target) not in recovered
                        and _hash_file(target, cancelled) != completed["sha256"])):
                raise ValueError(f"Completed export copy changed: {target}. Repair the file before resuming.")
            result.completed.append(str(target))
            done_bytes += item["source_size"]
        for item in manifest["items"]:
            if item["completed"]:
                continue
            if cancelled():
                raise InterruptedError("Export cancelled")
            source = Path(item["source_path"])
            stat = source.stat()
            if (stat.st_size, stat.st_mtime_ns) != (
                item["source_size"], item["source_mtime_ns"]
            ):
                raise ValueError(f"Source changed since export was queued: {source}")
            directory = Path(manifest["destination"]) / item["directory"]
            def advanced(amount):
                nonlocal done_bytes
                done_bytes += amount
                detailed_progress(min(99, int(done_bytes * 100 / max(1, total))),
                                  f"Copying {source.name}")
            def before_publish(target, temporary, size, checksum):
                item["pending"] = {
                    "target": str(target), "temporary": str(temporary),
                    "size": size, "sha256": checksum,
                }
                catalogue.save_export_job(job_id, manifest, "Running")
            def on_abort():
                item["pending"] = None
                catalogue.save_export_job(job_id, manifest, "Running")
            target, checksum = _copy_resumable(
                item, directory, job_id, cancelled, advanced, before_publish, on_abort,
            )
            copied = Path(target)
            item["completed"] = {
                "path": target, "size": copied.stat().st_size,
                "sha256": checksum,
            }
            item["pending"] = None
            result.completed.append(target)
            catalogue.save_export_job(job_id, manifest, "Running")
        catalogue.save_export_job(job_id, manifest, "Completed")
    except (OSError, ValueError, InterruptedError) as error:
        result.error = str(error)
        result.cancelled = isinstance(error, InterruptedError)
        catalogue.save_export_job(job_id, manifest, "Cancelled" if result.cancelled else "Failed")
    return result


def share_clip(
    clip,
    registry,
    destination,
    folders,
    custom=None,
    fields=None,
    prefix=True,
    cancelled=lambda: False,
    *,
    lowercase=True,
    selected_range=False,
    progress=lambda text: None,
    detailed_progress=None,
    quality="native",
):
    from .sharing import encode_share

    destination = check_destination(destination, folders)
    stem = (
        custom if custom is not None else title(clip, registry, fields, prefix, lowercase=lowercase)
    )
    options = {"detailed_progress": detailed_progress} if detailed_progress else {}
    if quality != "native":
        options["quality"] = quality
    return encode_share(
        clip, destination, safe_stem(stem), selected_range, cancelled, progress, **options
    )
