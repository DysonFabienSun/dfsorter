"""Session-scoped output jobs and their navigation menu."""

import logging
import threading
from dataclasses import dataclass

from PySide6.QtCore import QObject, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from .theme import role
from .widgets import set_icon


class OutputWorker(QThread):
    progressed = Signal(int, str)

    def __init__(self, function):
        super().__init__()
        self.function = function
        self.cancelled = threading.Event()
        self.result = None
        self.error = None

    def run(self):
        try:
            self.result = self.function(self.cancelled.is_set, self.progressed.emit)
        except InterruptedError as error:
            self.error = error
        except Exception as error:
            logging.exception("Output job failed")
            self.error = error


@dataclass
class OutputJob:
    kind: str
    title: str
    function: object
    state: str = "Queued"
    percent: int = 0
    detail: str = "Waiting to start"
    worker: OutputWorker | None = None
    result: object = None
    row: QWidget | None = None
    status: QLabel | None = None
    bar: QProgressBar | None = None
    action: QPushButton | None = None
    dismiss_button: QPushButton | None = None
    record_id: str | None = None
    forget: object = None
    menu_action: QWidgetAction | None = None


class Activities(QObject):
    changed = Signal()
    idle = Signal()

    def __init__(self, parent, button: QToolButton):
        super().__init__(parent)
        self.jobs: list[OutputJob] = []
        self.button = button
        self.menu = QMenu(button)
        self.menu.setObjectName("activitiesMenu")
        self.empty = self.menu.addAction("No activities")
        self.empty.setEnabled(False)
        button.setMenu(self.menu)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._update_button()

    def busy(self):
        return any(job.state in {"Queued", "Running", "Cancelling"} for job in self.jobs)

    def submit(self, kind, title, function, *, record_id=None, forget=None, paused=False):
        job = OutputJob(kind, title, function, state="Paused" if paused else "Queued",
                        record_id=record_id, forget=forget)
        if paused:
            job.detail = "Resume to continue unfinished copies"
        self.jobs.append(job)
        self._add_row(job)
        self._update_button()
        self.changed.emit()
        if not paused:
            QTimer.singleShot(0, self._schedule)
        return job

    def _add_row(self, job):
        self.empty.setVisible(False)
        row = QWidget(self.menu)
        row.setFixedWidth(370)
        layout = QVBoxLayout(row)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(4)
        heading = QLabel(job.title)
        heading.setWordWrap(True)
        layout.addWidget(heading)
        middle = QHBoxLayout()
        job.status = QLabel()
        job.status.setWordWrap(True)
        job.status.setMinimumWidth(0)
        role(job.status, "secondary")
        middle.addWidget(job.status, 1)
        job.action = QPushButton("Cancel")
        job.action.clicked.connect(lambda: self.cancel(job) if self._active(job)
                                   else self.resume(job) if self._resumable(job)
                                   else self.dismiss(job))
        middle.addWidget(job.action)
        job.dismiss_button = QPushButton("Forget")
        job.dismiss_button.clicked.connect(lambda: self.dismiss(job))
        middle.addWidget(job.dismiss_button)
        layout.addLayout(middle)
        job.bar = QProgressBar()
        job.bar.setRange(0, 100)
        job.bar.setTextVisible(True)
        layout.addWidget(job.bar)
        action = QWidgetAction(self.menu)
        action.setDefaultWidget(row)
        self.menu.addAction(action)
        job.row = row
        job.menu_action = action
        self._refresh(job)

    @staticmethod
    def _active(job):
        return job.state in {"Queued", "Running", "Cancelling"}

    @staticmethod
    def _resumable(job):
        return bool(job.record_id and job.state in {"Paused", "Failed", "Cancelled"})

    def _refresh(self, job):
        role(job.status, "error" if job.state == "Failed" else "secondary")
        job.status.setText(f"{job.state} · {job.detail}" if job.detail else job.state)
        job.status.setToolTip(job.status.text())
        job.bar.setValue(job.percent)
        job.action.setText(
            "Cancel" if self._active(job) else "Resume export" if self._resumable(job) else "Dismiss"
        )
        job.action.setEnabled(job.state != "Cancelling")
        job.dismiss_button.setVisible(bool(job.record_id) and not self._active(job))
        job.dismiss_button.setText("Dismiss" if job.state == "Completed" else "Forget")
        job.bar.setVisible(self._active(job) or job.state == "Completed")

    def _update_button(self):
        active = sum(self._active(job) for job in self.jobs)
        attention = sum(job.state in {"Paused", "Failed", "Cancelled"} for job in self.jobs)
        count = active + attention
        label = f"Activities ({count})" if count else "Activities"
        self.button.setText("")
        self.button.setToolTip(label)
        self.button.setAccessibleName(label)
        set_icon(
            self.button, "list-todo",
            "accent_default" if active else "status_warning" if attention else None,
            y_offset=-1,
        )
        self.button.setProperty("activityBusy", bool(active))
        self.button.setProperty("activityAttention", bool(attention) and not active)
        self.button.style().unpolish(self.button)
        self.button.style().polish(self.button)

    def _schedule(self):
        if getattr(self.parent(), "worker", None) is not None:
            return
        running = [job for job in self.jobs if job.state in {"Running", "Cancelling"}]
        capacity = 2 - len(running)
        share_running = any(job.kind == "Share" for job in running)
        for job in self.jobs:
            if capacity == 0:
                break
            if job.state != "Queued" or (job.kind == "Share" and share_running):
                continue
            job.state = "Running"
            job.detail = "Preparing…"
            worker = OutputWorker(job.function)
            job.worker = worker
            worker.progressed.connect(lambda value, detail, current=job: self._progress(current, value, detail))
            worker.finished.connect(lambda current=job: self._finished(current))
            self._refresh(job)
            worker.start()
            capacity -= 1
            share_running |= job.kind == "Share"
        self._update_button()
        self.changed.emit()

    def _progress(self, job, value, detail):
        if job.state != "Running":
            return
        job.percent = max(0, min(99, int(value)))
        job.detail = detail
        self._refresh(job)
        self.changed.emit()

    def _finished(self, job):
        worker = job.worker
        job.result = worker.result
        if (isinstance(worker.error, InterruptedError)
                or getattr(worker.result, "cancelled", False)
                or (worker.cancelled.is_set() and worker.result is None and worker.error is None)):
            job.state = "Cancelled"
        elif worker.error or getattr(worker.result, "error", None):
            job.state = "Failed"
        else:
            job.state = "Completed"
            job.percent = 100
        if worker.error:
            job.detail = str(worker.error)
        elif getattr(worker.result, "error", None):
            count = len(worker.result.completed)
            job.detail = f"{count} copied · {worker.result.error}"
        elif job.kind == "Export" and worker.result is not None:
            job.detail = f"{len(worker.result.completed)} clips copied"
        elif job.state == "Completed":
            job.detail = str(worker.result)
        else:
            job.detail = "Stopped"
        if job.state == "Completed" and job.forget:
            try:
                job.forget(job.record_id)
            except Exception:
                logging.exception("Could not remove completed export job record")
            else:
                job.forget = None
                job.record_id = None
        job.worker = None
        worker.deleteLater()
        self._refresh(job)
        self._schedule()
        if not self.busy():
            self.idle.emit()

    def cancel(self, job):
        if job.state == "Queued":
            job.state = "Cancelled"
            job.detail = "Stopped before starting"
            self._refresh(job)
            self._update_button()
            self.changed.emit()
            if not self.busy():
                self.idle.emit()
        elif job.state == "Running":
            job.state = "Cancelling"
            job.detail = "Waiting for cleanup…"
            job.worker.cancelled.set()
            self._refresh(job)
            self.changed.emit()

    def cancel_all(self):
        for job in list(self.jobs):
            if self._active(job):
                self.cancel(job)

    def resume(self, job):
        if not self._resumable(job):
            return
        job.state = "Queued"
        job.percent = 0
        job.detail = "Waiting to resume"
        self._refresh(job)
        self._update_button()
        self._schedule()

    def dismiss(self, job):
        if self._active(job):
            return
        if job.forget:
            answer = QMessageBox.question(
                self.parent(), "Forget export job?",
                "The saved export job will be removed. Completed copies will remain.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            job.forget(job.record_id)
        self.menu.removeAction(job.menu_action)
        job.menu_action.deleteLater()
        self.jobs.remove(job)
        self.empty.setVisible(not self.jobs)
        self._update_button()
        self.changed.emit()
