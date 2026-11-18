"""Disposable Browse stills, extracted outside the Qt event loop."""

import hashlib
import os
import subprocess
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QImage

from .app_paths import tool
from .color import BT2390_ERROR, ColorPolicy, require_bt2390


class ThumbnailCache(QObject):
    ready = Signal(str, str, object)

    def __init__(self, root, parent=None, *, settings=None):
        super().__init__(parent)
        self.directory = Path(root) / "cache" / "thumbnails"
        self.settings = settings if settings is not None else {}
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="thumbnail")
        self.memory = OrderedDict()
        self.queued = {}
        self.futures = {}
        self.running_hdr = None
        self.paused = False
        self.failed = set()
        self.errors = {}
        self.closed = False
        self.ready.connect(self._finished, Qt.ConnectionType.QueuedConnection)

    @property
    def pending(self):
        return self.queued.keys() | self.futures.keys()

    def signature(self, clip):
        source = Path(clip["source_path"])
        try:
            stat = source.stat()
            if not source.is_file():
                return None
        except OSError:
            return None
        raw = f'v2\0{clip["clip_id"]}\0{source.resolve()}\0{stat.st_size}\0{stat.st_mtime_ns}\0{bool(clip.get("hdr"))}'
        if clip.get("hdr"):
            raw += "\0" + ColorPolicy.from_settings(self.settings).for_source(source).signature
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

    def request(self, clip, *, dispatch=True):
        key, image = self.get(clip)
        if (self.closed or key is None or image is not None or key in self.queued
                or key in self.futures or key in self.failed):
            return key, image
        clip_id = clip["clip_id"]
        source = clip["source_path"]
        duration = clip.get("duration") or 0
        policy = ColorPolicy.from_settings(self.settings).for_source(source)
        self.queued[key] = (clip_id, source, duration, bool(clip.get("hdr")), policy)
        if dispatch:
            self._dispatch()
        return key, None

    def pause(self):
        self.paused = True

    def resume(self, first=None):
        if first in self.queued:
            self.queued = {first: self.queued.pop(first), **self.queued}
        self.paused = False
        self._dispatch()

    def retain(self, keys, *, paused=False):
        self.queued = {key: self.queued[key] for key in keys if key in self.queued}
        self.paused = paused
        self._dispatch()

    def _dispatch(self):
        if self.closed or self.paused:
            return
        for key, job in list(self.queued.items()):
            if len(self.futures) >= 2:
                break
            if job[3] and self.running_hdr is not None:
                continue
            del self.queued[key]
            self._start(key, *job)

    def _start(self, key, clip_id, source, duration, hdr, policy):
        if hdr:
            self.running_hdr = key
        future = self.executor.submit(self._extract, key, source, duration, hdr, policy)
        self.futures[key] = future

        def completed(result):
            if self.closed or result.cancelled():
                return
            try:
                image = result.result()
            except Exception as error:
                self.errors[key] = str(error)
                image = None
            try:
                self.ready.emit(clip_id, key, image)
            except RuntimeError:
                pass

        future.add_done_callback(completed)

    def _extract(self, key, source, duration, hdr=False, color_policy=None):
        executable = tool("ffmpeg")
        if not executable:
            return None
        color_policy = (color_policy or ColorPolicy()).for_source(source)
        if hdr and color_policy.mapping == "bt2390":
            require_bt2390(executable, lambda: self.closed)
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{key}.png"
        temporary = self.directory / f"{key}.tmp.png"
        points = [max(0.0, duration / 2) if duration and duration < 1 else 1.0, 0.0]
        for point in dict.fromkeys(points):
            treatment = color_policy.sdr_filter() + "," if hdr else ""
            command = [executable, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                       *(color_policy.device_arguments() if hdr else []),
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
                if result.returncode:
                    detail = (result.stderr or b"").decode("utf-8", "replace")[-1200:]
                    self.errors[key] = (
                        f"{BT2390_ERROR}\n{detail}"
                        if hdr and color_policy.mapping == "bt2390" else detail
                    )
                if not image.isNull():
                    temporary.replace(path)
                    self.errors.pop(key, None)
                    return image
            except (OSError, subprocess.TimeoutExpired) as error:
                self.errors[key] = f"Thumbnail extraction failed: {error}"
            temporary.unlink(missing_ok=True)
        return None

    def _remember(self, key, image):
        self.memory[key] = image
        self.memory.move_to_end(key)
        while len(self.memory) > 128:
            self.memory.popitem(last=False)

    def _finished(self, clip_id, key, image):
        self.futures.pop(key, None)
        if self.running_hdr == key:
            self.running_hdr = None
        if image is None:
            self.failed.add(key)
        else:
            self._remember(key, image)
        self._dispatch()

    def close(self):
        self.closed = True
        self.queued.clear()
        self.executor.shutdown(wait=False, cancel_futures=True)
