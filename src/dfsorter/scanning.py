import logging
import shutil
import sqlite3
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

from .catalogue import normalized
from .media import discover_paths, inspect_media


class ScanCoordinator:
    def __init__(
        self, catalogue, registry, cancelled=lambda: False, progress=lambda text: None, force=False
    ):
        self.catalogue = catalogue
        self.registry = registry
        self.cancelled = cancelled
        self.progress = progress
        self.force = force
        self.executable = shutil.which("ffprobe")
        self.cache = catalogue.media_cache()
        self.metrics = dict(
            traversal=0.0, probing=0.0, database=0.0, hits=0, probes=0, warnings=0, updates=0
        )
        self.last_progress = 0.0

    def report(self, phase, force=False):
        current = time.monotonic()
        if force or current - self.last_progress >= 0.1:
            self.progress(
                f"{phase}\nCached: {self.metrics['hits']} · "
                f"Inspected: {self.metrics['probes']} · "
                f"Warnings: {self.metrics['warnings']} · "
                f"Catalogue updates: {self.metrics['updates']}"
            )
            self.last_progress = current

    def inspect(self, item):
        path = Path(item["path"])
        empty = dict(duration=None, created=None, error=None)
        probed = False
        try:
            before = path.stat()
            cached = self.cache.get(item["path"])
            if (
                not self.force
                and cached
                and (cached["size"], cached["mtime_ns"]) == (before.st_size, before.st_mtime_ns)
                and (not cached["error"] or time.time() - cached["inspected_at"] < 86400)
            ):
                return {**cached, **item}, None, True, False
            if not self.executable:
                return {**item, **empty}, None, False, False
            probed = True
            info = inspect_media(path, self.executable, self.cancelled)
            if info.pop("tool_unavailable", False):
                return {**item, **info}, None, False, True
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                return (
                    {**item, **empty, "error": "File changed during inspection; retry next scan"},
                    None,
                    False,
                    True,
                )
            entry = dict(
                path=item["path"],
                size=after.st_size,
                mtime_ns=after.st_mtime_ns,
                inspected_at=time.time(),
                **info,
            )
            return {**item, **info}, entry, False, True
        except InterruptedError:
            raise
        except OSError as error:
            return {**item, **empty, "error": str(error)}, None, False, probed

    def folder(self, folder):
        started = time.perf_counter()
        self.report("Discovering files", True)
        found = discover_paths(
            Path(folder["path"]),
            self.registry,
            folder.get("forced_game"),
            self.cancelled,
            self.report,
        )
        for item in found:
            item["path"] = normalized(item["path"])
        self.metrics["traversal"] += time.perf_counter() - started
        entries = []
        invalidated = []
        started = time.perf_counter()
        self.report("Inspecting media", True)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                pending = {}
                remaining = iter(enumerate(found))
                exhausted = False
                while pending or not exhausted:
                    if self.cancelled():
                        for future in pending:
                            future.cancel()
                        raise InterruptedError("Scan cancelled")
                    while len(pending) < 2 and not exhausted:
                        next_item = next(remaining, None)
                        if next_item is None:
                            exhausted = True
                        else:
                            index, item = next_item
                            pending[pool.submit(self.inspect, item)] = index
                    completed, _ = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
                    for future in completed:
                        index = pending.pop(future)
                        item, entry, hit, probed = future.result()
                        found[index] = item
                        if entry:
                            entries.append(entry)
                        elif not hit:
                            invalidated.append(item["path"])
                        self.metrics["hits"] += hit
                        self.metrics["probes"] += probed
                        self.metrics["warnings"] += bool(item["error"])
                    self.report("Inspecting media")
        finally:
            self.metrics["probing"] += time.perf_counter() - started
            started = time.perf_counter()
            self.catalogue.cache_media(entries, invalidated)
            for path in invalidated:
                self.cache.pop(path, None)
            self.cache.update((entry["path"], entry) for entry in entries)
            self.metrics["database"] += time.perf_counter() - started
        if self.cancelled():
            raise InterruptedError("Scan cancelled")
        return found

    def run(self, folders):
        results, errors = [], []
        if not self.executable:
            errors.append("ffprobe unavailable; uncached media metadata cannot be inspected")
            self.metrics["warnings"] += 1
        for folder in folders:
            try:
                found = self.folder(folder)
                self.report("Updating catalogue", True)
                started = time.perf_counter()
                self.catalogue.ingest(folder["folder_id"], found, self.cancelled)
                self.metrics["database"] += time.perf_counter() - started
                self.metrics["updates"] += len(found)
                results.extend(found)
            except InterruptedError:
                errors.append("Scan cancelled; current folder was not ingested")
                break
            except (OSError, ValueError, sqlite3.Error) as error:
                errors.append(str(error))
                self.metrics["warnings"] += 1
        self.report("Scan finished", True)
        logging.info("Scan metrics: %s", self.metrics)
        return results, errors, self.metrics
