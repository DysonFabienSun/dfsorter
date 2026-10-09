import os
import subprocess

import pytest
from PySide6.QtCore import QLockFile

from dfsorter import ui


def test_second_process_exits_before_initialization(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    lock = QLockFile(str(data / "dfsorter.lock"))
    lock.setStaleLockTime(0)
    assert lock.tryLock(0)
    script = """
import sys
from pathlib import Path
from dfsorter import ui
ui.ROOT = Path(sys.argv[1])
def unexpected():
    raise AssertionError('Startup continued while another process holds the lock')
ui.prepare_game_configs = unexpected
raise SystemExit(ui.main())
"""
    try:
        result = subprocess.run(
            [os.sys.executable, "-c", script, str(tmp_path)],
            capture_output=True, text=True, timeout=20,
        )
        assert result.returncode == 0, result.stderr
        assert not (data / "dfsorter.log").exists()
    finally:
        lock.unlock()


def test_other_folder_and_relaunch_can_start(tmp_path, monkeypatch):
    first = tmp_path / "first"
    second = tmp_path / "second"
    (first / "data").mkdir(parents=True)
    second.mkdir()
    lock = QLockFile(str(first / "data/dfsorter.lock"))
    assert lock.tryLock(0)
    monkeypatch.setattr(ui, "ROOT", second)

    def stop_startup():
        raise RuntimeError("Startup reached configuration preparation")

    monkeypatch.setattr(ui, "prepare_game_configs", stop_startup)
    try:
        with pytest.raises(RuntimeError, match="Startup reached"):
            ui.main()
    finally:
        lock.unlock()
    monkeypatch.setattr(ui, "ROOT", first)
    with pytest.raises(RuntimeError, match="Startup reached"):
        ui.main()


def test_lock_recovers_after_process_crash(tmp_path):
    path = tmp_path / "dfsorter.lock"
    script = """
import os
import sys
from PySide6.QtCore import QLockFile
lock = QLockFile(sys.argv[1])
lock.setStaleLockTime(0)
assert lock.tryLock(0)
os._exit(0)
"""
    subprocess.run([os.sys.executable, "-c", script, str(path)], check=True, timeout=20)
    lock = QLockFile(str(path))
    lock.setStaleLockTime(0)
    assert lock.tryLock(0)
    lock.unlock()
