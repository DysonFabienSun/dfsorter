import json
import os
import shutil
import subprocess
from pathlib import Path


def inspect_media(path: Path) -> dict:
    info = {"duration": None, "created": None, "error": None}
    executable = shutil.which("ffprobe")
    if not executable:
        info["error"] = "ffprobe unavailable; duration and media capture time unavailable"
        return info
    try:
        process = subprocess.run(
            [executable, "-v", "error", "-show_format", "-of", "json", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if process.returncode:
            raise ValueError(process.stderr.strip() or "Media inspection failed")
        data = json.loads(process.stdout)["format"]
        info["duration"] = float(data["duration"]) if "duration" in data else None
        info["created"] = data.get("tags", {}).get("creation_time")
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
        info["error"] = str(error)
    return info


def discover(
    root: Path, registry, forced_game=None, cancelled=lambda: False, progress=lambda text: None
):
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"Capture folder unavailable: {root}")
    found = []
    for directory, subdirectories, filenames in os.walk(root, followlinks=False):
        subdirectories[:] = [
            name for name in subdirectories if not (Path(directory) / name).is_symlink()
        ]
        for filename in sorted(filenames, key=str.casefold):
            if cancelled():
                raise InterruptedError("Scan cancelled")
            path = Path(directory) / filename
            if path.suffix.casefold() != ".mp4" or path.is_symlink():
                continue
            game = forced_game
            parent = path.parent
            while not game and parent.is_relative_to(root):
                game = registry.resolve(parent.name)
                if parent == root:
                    break
                parent = parent.parent
            progress(f"Inspecting {path.name}")
            found.append({"path": str(path), "game": game, **inspect_media(path)})
    return found
