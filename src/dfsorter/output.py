import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import title


def safe_stem(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")[:160].rstrip(" .")
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
    return value


def validate(clips, registry):
    errors = []
    for clip in clips:
        reasons = []
        if clip["triage"] == "discard":
            continue
        if clip["triage"] is None:
            reasons.append("triage is undefined")
        else:
            game = registry.game(clip["game"])
            if not game:
                reasons.append("assign a configured game")
            else:
                reasons.extend(
                    f"missing required field: {key}"
                    for key in game.required_for_export
                    if clip["metadata"].get(key) in (None, "", [])
                )
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
        stem = title(clip, registry, options.get("fields"), options.get("prefix", True))
        directory = destination
        if group_rating:
            directory /= f"Rating {clip['rating']}" if clip["rating"] else "Unrated"
        progress(f"Copying {Path(clip['source_path']).name}")
        try:
            result.completed.append(copy_one(clip, directory, stem, cancelled=cancelled))
        except (OSError, InterruptedError) as error:
            result.error = str(error)
            result.cancelled = isinstance(error, InterruptedError)
            break
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
    selected_range=False,
    progress=lambda text: None,
):
    from .sharing import encode_share

    destination = check_destination(destination, folders)
    stem = custom if custom is not None else title(clip, registry, fields, prefix)
    return encode_share(clip, destination, safe_stem(stem), selected_range, cancelled, progress)
