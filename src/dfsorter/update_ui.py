"""Qt-facing portable release updates."""

import logging
import os
import shutil
import subprocess
import threading

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog

from .app_paths import ROOT
from .release_update import (
    download_release,
    installed_release,
    latest_release,
    version_tuple,
)


class UpdateController(QObject):
    checked = Signal(object)
    downloaded = Signal(object)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.progress = None
        self.checking = False
        self.quiet = False
        self.cancelled = threading.Event()
        self.checked.connect(self._checked)
        self.downloaded.connect(self._downloaded)

    def check(self, *, quiet=False):
        if self.checking or self.progress is not None:
            if not quiet:
                self.quiet = False
            return
        if not installed_release():
            if not quiet:
                QMessageBox.information(
                    self.window,
                    "Portable updates",
                    "Update checks are available in packaged Windows releases.",
                )
            return
        self.checking = True
        self.quiet = quiet
        if not quiet:
            self._busy("Checking for updates…", cancel=False)
        threading.Thread(target=self._check_worker, daemon=True).start()

    def _busy(self, label, *, cancel):
        self.progress = QProgressDialog(label, "Cancel" if cancel else "", 0, 0, self.window)
        self.progress.setWindowTitle("DFSorter update")
        self.progress.setMinimumDuration(0)
        if cancel:
            self.cancelled.clear()
            self.progress.canceled.connect(self.cancelled.set)
        else:
            self.progress.setCancelButton(None)
        self.progress.show()

    def _check_worker(self):
        try:
            self.checked.emit(latest_release())
        except Exception as error:
            self.checked.emit(error)

    def _checked(self, result):
        self.checking = False
        if self.progress is not None:
            self.progress.close()
            self.progress = None
        if isinstance(result, Exception):
            if self.quiet:
                logging.warning("Automatic update check failed: %s", result)
            else:
                QMessageBox.warning(self.window, "Update check failed", str(result))
            return
        installed = installed_release()
        if version_tuple(result["version"]) <= version_tuple(installed["version"]):
            if not self.quiet:
                QMessageBox.information(self.window, "DFSorter updates", "This copy is up to date.")
            return
        answer = QMessageBox.question(
            self.window,
            "DFSorter update available",
            f"Version {result['version']} is available. Download and install it now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._busy("Downloading update…", cancel=True)
        destination = ROOT / "cache" / "update" / f"DFSorter-{result['version']}.zip"
        threading.Thread(
            target=self._download_worker, args=(result, destination), daemon=True
        ).start()

    def _download_worker(self, release, destination):
        try:
            download_release(release, destination, self.cancelled.is_set)
            self.downloaded.emit((release, destination))
        except Exception as error:
            self.downloaded.emit(error)

    def _downloaded(self, result):
        self.progress.close()
        self.progress = None
        if isinstance(result, InterruptedError):
            return
        if isinstance(result, Exception):
            QMessageBox.warning(self.window, "Update download failed", str(result))
            return
        release, archive = result
        helper = ROOT / "DFSorterUpdater.exe"
        if not helper.is_file():
            QMessageBox.warning(self.window, "Update unavailable", "Update helper is missing.")
            return
        copied = ROOT / "cache" / "update" / f"DFSorterUpdater-{release['version']}.exe"
        try:
            shutil.copy2(helper, copied)
        except OSError as error:
            QMessageBox.warning(self.window, "Update unavailable", str(error))
            return

        def launch_helper():
            subprocess.Popen(
                [
                    str(copied),
                    "--root",
                    str(ROOT),
                    "--archive",
                    str(archive),
                    "--version",
                    release["version"],
                    "--parent-pid",
                    str(os.getpid()),
                    "--sha256",
                    release["sha256"],
                ],
                cwd=ROOT,
            )

        application = QApplication.instance()
        application.aboutToQuit.connect(launch_helper)
        if not self.window.close():
            application.aboutToQuit.disconnect(launch_helper)
