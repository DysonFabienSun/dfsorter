"""Disposable Browse stills, extracted outside the Qt event loop."""

import hashlib
import os
import subprocess
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from .app_paths import tool


class ThumbnailCache(QObject):
    ready = Signal(str, str, object)

    def __init__(self, root, parent=None):
        super().__init__(parent)
        self.directory = Path(root) / "cache" / "thumbnails"
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="thumbnail")
        self.memory = OrderedDict()
        self.pending = set()
        self.futures = {}
        self.failed = set()
        self.closed = False
        self.ready.connect(self._finished)

    def signature(self, clip):
        source = Path(clip["source_path"])
        try:
            stat = source.stat()
            if not source.is_file():
                return None
        except OSError:
            return None
        raw = f'v2\0{clip["clip_id"]}\0{source.resolve()}\0{stat.st_size}\0{stat.st_mtime_ns}\0{bool(clip.get("hdr"))}'
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, clip):
        key = self.signature(clip)
        if key is None:
            return None, None
        if key in self.memory:
            self.memory.move_to_end(key)
            return key, self.memory[key]
        path = self.directory / f"{key}.png"
        if path.is_file():
            image = QImage(str(path))
            if not image.isNull():
                self._remember(key, image)
                return key, image
        return key, None

    def request(self, clip):
        key, image = self.get(clip)
        if key is None or image is not None or key in self.pending or key in self.failed:
            return key, image
        self.pending.add(key)
        clip_id = clip["clip_id"]
        source = clip["source_path"]
        duration = clip.get("duration") or 0
        future = self.executor.submit(self._extract, key, source, duration, bool(clip.get("hdr")))
        self.futures[key] = future

        def completed(result):
            if self.closed or result.cancelled():
                return
            try:
                image = result.result()
            except Exception:
                image = None
            try:
                self.ready.emit(clip_id, key, image)
            except RuntimeError:
                pass

        future.add_done_callback(completed)
        return key, None

    def retain(self, keys):
        for key, future in list(self.futures.items()):
            if key not in keys and future.cancel():
                self.futures.pop(key, None)
                self.pending.discard(key)

    def _extract(self, key, source, duration, hdr=False):
        executable = tool("ffmpeg")
        if not executable:
            return None
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{key}.png"
        temporary = self.directory / f"{key}.tmp.png"
        points = [max(0.0, duration / 2) if duration and duration < 1 else 1.0, 0.0]
        for point in dict.fromkeys(points):
            treatment = "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p," if hdr else ""
            command = [executable, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                       "-ss", str(point), "-i", source, "-frames:v", "1",
                       "-vf", treatment + "scale=168:96:force_original_aspect_ratio=decrease,pad=168:96:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1",
                       str(temporary)]
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    timeout=20,
                    check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                image = QImage(str(temporary)) if result.returncode == 0 else QImage()
                if not image.isNull():
                    temporary.replace(path)
                    return image
            except (OSError, subprocess.TimeoutExpired):
                pass
            temporary.unlink(missing_ok=True)
        return None

    def _remember(self, key, image):
        self.memory[key] = image
        self.memory.move_to_end(key)
        while len(self.memory) > 128:
            self.memory.popitem(last=False)

    def _finished(self, clip_id, key, image):
        self.pending.discard(key)
        self.futures.pop(key, None)
        if image is None:
            self.failed.add(key)
        else:
            self._remember(key, image)

    def close(self):
        self.closed = True
        self.executor.shutdown(wait=False, cancel_futures=True)
