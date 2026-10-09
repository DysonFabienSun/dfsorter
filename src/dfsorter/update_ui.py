"""Qt-facing portable release updates."""

import logging
import os
import shutil
import subprocess
import threading
from html import escape

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog

from .app_paths import ROOT
from .release_update import (
    DEFAULT_DOWNLOAD_SOURCE,
    download_release,
    installed_release,
    latest_release,
    release_download_url,
    release_filename,
    verify_release,
    version_tuple,
)


class UpdateController(QObject):
    checked = Signal(object)
    downloaded = Signal(object)
    download_progress = Signal(object, object)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.progress = None
        self.checking = False
        self.quiet = False
        self.cancelled = threading.Event()
        self.release = None
        self.source = DEFAULT_DOWNLOAD_SOURCE
        self.local_archive = False
        self.checked.connect(self._checked)
        self.downloaded.connect(self._downloaded)
        self.download_progress.connect(self._download_progress)

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
        self.progress.setAutoClose(False)
        self.progress.setAutoReset(False)
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
        self.release = result
        self.source = self.window.settings.get("update_download_source", DEFAULT_DOWNLOAD_SOURCE)
        archive = ROOT / release_filename(result)
        self.local_archive = archive.is_file()
        prompt = (
            f"An install ZIP for version {result['version']} was located in the installation "
            "folder. Verify and install it now?"
            if self.local_archive else
            f"Version {result['version']} is available. Download and install it now?"
        )
        answer = QMessageBox.question(
            self.window,
            "DFSorter update available",
            prompt,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._busy("Verifying install ZIP…" if self.local_archive else "Downloading update…", cancel=True)
        destination = archive if self.local_archive else (
            ROOT / "cache" / "update" / f"DFSorter-{result['version']}.zip"
        )
        threading.Thread(
            target=self._download_worker, args=(result, destination), daemon=True
        ).start()

    def _download_worker(self, release, destination):
        try:
            if self.local_archive:
                verify_release(release, destination, self.cancelled.is_set, self.download_progress.emit)
            else:
                download_release(
                    release, destination, self.cancelled.is_set, self.download_progress.emit,
                    source=self.source,
                )
            self.downloaded.emit((release, destination))
        except Exception as error:
            self.downloaded.emit(error)

    def _download_progress(self, downloaded, total):
        if self.progress is None or self.cancelled.is_set():
            return
        received = downloaded / 1_000_000
        phase = "Verifying install ZIP…" if self.local_archive else "Downloading update…"
        if total > 0:
            percent = min(99, downloaded * 100 // total)
            self.progress.setRange(0, 100)
            self.progress.setValue(percent)
            self.progress.setLabelText(
                f"{phase} {percent}%\n{received:.1f} / {total / 1_000_000:.1f} MB"
            )
        else:
            self.progress.setRange(0, 0)
            self.progress.setLabelText(f"{phase}\n{received:.1f} MB downloaded")

    def _downloaded(self, result):
        if not isinstance(result, Exception):
            self.progress.setRange(0, 100)
            self.progress.setValue(100)
        self.progress.close()
        self.progress = None
        if isinstance(result, InterruptedError):
            return
        if isinstance(result, Exception):
            self._download_failed(result)
            return
        release, archive = result
        helper = ROOT / "DFSorterUpdater.exe"
        if not helper.is_file():
            QMessageBox.warning(self.window, "Update unavailable", "Update helper is missing.")
            return
        copied = ROOT / "cache" / "update" / f"DFSorterUpdater-{release['version']}.exe"
        try:
            copied.parent.mkdir(parents=True, exist_ok=True)
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

    def _download_failed(self, error):
        dialog = QMessageBox(self.window)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle("Update verification failed" if self.local_archive else "Update download failed")
        dialog.setTextFormat(Qt.TextFormat.RichText)
        dialog.setText(
            f"{escape(str(error))}<br><br>"
            f'<a href="{escape(release_download_url(self.release, self.source), quote=True)}">'
            "Download the release ZIP</a> and save it in the installation folder as "
            f"<b>{escape(release_filename(self.release))}</b>.<br>"
            f"Installation folder: {escape(str(ROOT))}<br>"
            "Run Check for updates again to locate, verify and install the ZIP."
        )
        dialog.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
        )
        dialog.exec()
