import json
import os
import subprocess
import time
from pathlib import Path

from .app_paths import tool
from .folder_assignment import assigned_game, validate_assignment


def inspect_media(path: Path, executable=None, cancelled=lambda: False, timeout=20) -> dict:
    info = {"duration": None, "created": None, "error": None, "hdr": None}
    executable = executable or tool("ffprobe")
    if not executable:
        info["error"] = "ffprobe unavailable; duration and media capture time unavailable"
        return info
    process = None
    try:
        if cancelled():
            raise InterruptedError("Scan cancelled")
        process = subprocess.Popen(
            [executable, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        deadline = time.monotonic() + timeout
        while True:
            if cancelled():
                raise InterruptedError("Scan cancelled")
            if time.monotonic() >= deadline:
                raise ValueError(f"Media inspection timed out after {timeout} seconds")
            try:
                stdout, stderr = process.communicate(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                pass
        if process.returncode:
            raise ValueError(stderr.strip() or "Media inspection failed")
        result = json.loads(stdout)
        data = result["format"]
        info["duration"] = float(data["duration"]) if "duration" in data else None
        info["created"] = data.get("tags", {}).get("creation_time")
        video = next((stream for stream in result.get("streams", []) if stream.get("codec_type") == "video"), None)
        info["hdr"] = int(video.get("color_transfer") in {"smpte2084", "arib-std-b67"}) if video else 0
    except InterruptedError:
        raise
    except FileNotFoundError:
        info["error"] = "ffprobe unavailable; duration and media capture time unavailable"
        info["tool_unavailable"] = True
    except (OSError, ValueError, KeyError, TypeError) as error:
        info["error"] = str(error)
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate()
    return info


def discover_paths(
    root: Path, registry, forced_game=None, cancelled=lambda: False, progress=lambda text: None,
    *, assignment_mode=None,
):
    assignment_mode, forced_game = validate_assignment(assignment_mode, forced_game, registry.games)
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"Capture folder unavailable: {root}")
    found = []

    def walk_error(error):
        raise error

    for directory, subdirectories, filenames in os.walk(
        root, followlinks=False, onerror=walk_error
    ):
        if cancelled():
            raise InterruptedError("Scan cancelled")
        subdirectories[:] = sorted(
            (name for name in subdirectories if not (Path(directory) / name).is_symlink()),
            key=str.casefold,
        )
        progress(f"Discovering files: {len(found)} videos")
        for filename in sorted(filenames, key=str.casefold):
            if cancelled():
                raise InterruptedError("Scan cancelled")
            path = Path(directory) / filename
            if path.suffix.casefold() != ".mp4" or path.is_symlink():
                continue
            game = None
            parent = path.parent
            while not game and parent.is_relative_to(root):
                game = registry.resolve(parent.name)
                if parent == root:
                    break
                parent = parent.parent
            found.append({"path": str(path), "game": assigned_game(game, assignment_mode, forced_game)})
    return found


def discover(root, registry, forced_game=None, cancelled=lambda: False, progress=lambda text: None):
    return [
        {**item, **inspect_media(Path(item["path"]))}
        for item in discover_paths(root, registry, forced_game, cancelled, progress)
    ]
