import os
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class Candidate:
    clip_id: str
    path: str
    size: int
    signature: tuple | None
    date: str
    problem: str = ""
    display_path: str = ""


def display_path(path):
    if os.name != "nt":
        return path
    source = Path(path)
    result = Path(source.anchor.upper())
    for component in source.parts[1:]:
        try:
            with os.scandir(result) as entries:
                component = next(
                    (
                        entry.name
                        for entry in entries
                        if entry.name.casefold() == component.casefold()
                    ),
                    component,
                )
        except OSError:
            pass
        result /= component
    return str(result)


def source_stat(path):
    source = Path(path)
    for part in (source, *source.parents):
        if part.is_symlink() or part.is_junction():
            raise ValueError("Symbolic links and junctions are excluded")
    details = source.stat(follow_symlinks=False)
    if not stat.S_ISREG(details.st_mode):
        raise ValueError("Not a regular video file")
    return details


def signature(details):
    return (
        details.st_dev,
        details.st_ino,
        details.st_size,
        details.st_mtime_ns,
        details.st_birthtime_ns if os.name == "nt" else details.st_ctime_ns,
    )


def preview(catalogue, media_info=None, cancelled=lambda: False, progress=lambda text: None, *, clip_id=None):
    candidates = []
    explicitly_deleted = set() if clip_id is not None else catalogue.hidden_deleted_ids()
    for clip in catalogue.clips():
        if cancelled():
            raise InterruptedError("Deletion preview cancelled; no files deleted")
        if clip_id is not None:
            if clip["clip_id"] != clip_id:
                continue
        elif clip["triage"] != "discard":
            continue
        if clip["clip_id"] in explicitly_deleted:
            continue
        path = clip["source_path"]
        displayed = display_path(path)
        progress(f"Checking {path}")
        try:
            details = source_stat(path)
            captured = (media_info or {}).get(path, {}).get("created")
            date = (
                f"{captured} (media)"
                if captured
                else datetime.fromtimestamp(details.st_mtime)
                .astimezone()
                .isoformat(timespec="seconds")
                + " (file modified)"
            )
            candidates.append(
                Candidate(
                    clip["clip_id"],
                    path,
                    details.st_size,
                    signature(details),
                    date,
                    display_path=displayed,
                )
            )
        except (OSError, ValueError) as error:
            candidates.append(
                Candidate(clip["clip_id"], path, 0, None, "Unavailable", str(error), displayed)
            )
    return tuple(candidates)


def delete_original(path, expected):
    if os.name != "nt":
        raise OSError("Safe permanent deletion currently requires Windows")
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.SetFileInformationByHandle.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    kernel.SetFileInformationByHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(path, 0x80000000 | 0x00010000, 1, None, 3, 0x00200000, None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except Exception:
        kernel.CloseHandle(handle)
        raise
    try:
        if signature(os.fstat(descriptor)) != expected:
            raise ValueError("File changed since preview; review again")
        source_stat(path)
        disposition = wintypes.BOOL(True)
        if not kernel.SetFileInformationByHandle(
            handle, 4, ctypes.byref(disposition), ctypes.sizeof(disposition)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        os.close(descriptor)


def delete_reviewed(
    catalogue,
    candidates,
    delete_file=delete_original,
    cancelled=lambda: False,
    progress=lambda text: None,
    *,
    require_discard=True,
):
    results = []
    seen = set()
    for candidate in candidates:
        if cancelled():
            results.extend(
                (remaining.path, "Cancelled; not deleted")
                for remaining in candidates[len(results) :]
            )
            break
        progress(f"Deleting {candidate.path}")
        try:
            if candidate.problem or candidate.signature is None:
                raise ValueError(candidate.problem or "No reviewed file information")
            if candidate.path in seen:
                raise ValueError("Duplicate path; not deleted again")
            seen.add(candidate.path)
            with catalogue.connection() as database:
                database.execute("BEGIN IMMEDIATE")
                current = database.execute(
                    "SELECT source_path, triage FROM clips WHERE clip_id=?",
                    (candidate.clip_id,),
                ).fetchone()
                if not current or (require_discard and current["triage"] != "discard"):
                    raise ValueError("Clip is no longer discarded")
                if current["source_path"] != candidate.path:
                    raise ValueError("Source path changed; review again")
                if signature(source_stat(candidate.path)) != candidate.signature:
                    raise ValueError("File changed since preview; review again")
                delete_file(candidate.path, candidate.signature)
                database.execute(
                    "INSERT OR IGNORE INTO deleted_sources VALUES (?)", (candidate.clip_id,)
                )
            results.append((candidate.path, "Deleted"))
        except (OSError, ValueError) as error:
            results.append((candidate.path, f"Skipped / failed: {error}"))
    return results
