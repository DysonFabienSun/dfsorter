import argparse
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from dfsorter.catalogue import Catalogue
from dfsorter.config import Registry
from dfsorter.scanning import ScanCoordinator


def main():
    root = Path(__file__).resolve().parents[1]
    registry = Registry(root / "configs/games")
    parser = argparse.ArgumentParser()
    parser.add_argument("capture", type=Path)
    capture = parser.parse_args().capture
    namespace = {}
    source = subprocess.check_output(
        ["git", "show", "HEAD:src/dfsorter/media.py"], text=True, encoding="utf-8"
    )
    exec(compile(source, "baseline_media.py", "exec"), namespace)
    baseline_probe = namespace["inspect_media"]
    probe_seconds = 0.0
    probe_count = 0

    def timed_probe(path):
        nonlocal probe_seconds, probe_count
        started = time.perf_counter()
        result = baseline_probe(path)
        probe_seconds += time.perf_counter() - started
        probe_count += 1
        return result

    namespace["inspect_media"] = timed_probe
    cache = root / "cache"
    cache.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=cache, prefix="scan-benchmark-") as directory:
        catalogue = Catalogue(Path(directory) / "benchmark.db")
        folder_id = catalogue.add_folder(capture)
        started = time.perf_counter()
        found = namespace["discover"](capture, registry)
        traversal = time.perf_counter() - started - probe_seconds
        started = time.perf_counter()
        catalogue.ingest(folder_id, found)
        print(
            json.dumps(
                dict(
                    mode="baseline",
                    videos=len(found),
                    traversal=traversal,
                    probing=probe_seconds,
                    probes=probe_count,
                    database=time.perf_counter() - started,
                )
            ),
            flush=True,
        )
        for mode in ["first", "unchanged", "restart"]:
            if mode == "restart":
                catalogue = Catalogue(catalogue.path)
            result = ScanCoordinator(catalogue, registry).run(catalogue.folders())
            print(json.dumps(dict(mode=mode, **result[2])), flush=True)
        import PySide6
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtWidgets import QApplication

        from dfsorter.ui import Window

        application_root = Path(directory) / "application"
        shutil.copytree(root / "configs", application_root / "configs")
        (application_root / "data").mkdir()
        shutil.copy2(catalogue.path, application_root / "data/dfsorter.db")
        isolated = Catalogue(application_root / "data/dfsorter.db")
        isolated.enable_folder(folder_id, False)
        QCoreApplication.addLibraryPath(str(Path(PySide6.__file__).parent / "plugins"))
        application = QApplication.instance() or QApplication([])
        window = Window(application_root)
        window.show()
        application.processEvents()
        started = time.perf_counter()
        window.refresh_references()
        window.refresh_library()
        print(
            json.dumps(dict(mode="ui_refresh", seconds=time.perf_counter() - started)), flush=True
        )
        window.close()
        application.processEvents()


if __name__ == "__main__":
    main()
