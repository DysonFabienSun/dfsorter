"""Session-scoped output jobs and their navigation menu."""

import logging
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPoint, QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
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

from .theme import COLORS, role
from .widgets import icon, set_icon


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
    subtitle: str = ""
    state: str = "Queued"
    percent: int = 0
    detail: str = "Waiting to start"
    worker: OutputWorker | None = None
    result: object = None
    row: QWidget | None = None
    status: QLabel | None = None
    status_dot: QLabel | None = None
    phase: QLabel | None = None
    bar: QProgressBar | None = None
    action: QPushButton | None = None
    dismiss_button: QPushButton | None = None
    open_button: QToolButton | None = None
    destination: str | None = None
    record_id: str | None = None
    forget: object = None
    menu_action: QWidgetAction | None = None
    clip_id: str | None = None


class Activities(QObject):
    changed = Signal()
    idle = Signal()

    def __init__(self, parent, button: QToolButton):
        super().__init__(parent)
        self.jobs: list[OutputJob] = []
        self.button = button
        self.menu = QMenu(button)
        self.menu.setObjectName("activitiesMenu")
        self._auto_opening = False
        self.auto_close_timer = QTimer(self)
        self.auto_close_timer.setSingleShot(True)
        self.auto_close_timer.timeout.connect(self.menu.hide)
        self.menu.aboutToShow.connect(self._menu_shown)
        self.menu.aboutToHide.connect(self.auto_close_timer.stop)
        self.menu.installEventFilter(self)
        header = QWidget(self.menu)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(10, 5, 10, 0)
        header_layout.setSpacing(0)
        heading_row = QHBoxLayout()
        heading_row.setContentsMargins(0, 0, 0, 5)
        heading = QLabel("Output Jobs")
        role(heading, "paneHeading")
        heading_row.addWidget(heading, 1)
        self.close_button = QToolButton(header)
        self.close_button.setObjectName("activitiesClose")
        self.close_button.setToolTip("Close Output Jobs")
        self.close_button.setAccessibleName("Close Output Jobs")
        set_icon(self.close_button, "x", size=16)
        self.close_button.setFixedSize(24, 24)
        self.close_button.installEventFilter(self)
        self.close_button.clicked.connect(self.menu.hide)
        heading_row.addWidget(self.close_button)
        header_layout.addLayout(heading_row)
        self.header_divider = QWidget(header)
        role(self.header_divider, "divider")
        self.header_divider.setFixedHeight(1)
        header_layout.addWidget(self.header_divider)
        header.installEventFilter(self)
        header_action = QWidgetAction(self.menu)
        header_action.setDefaultWidget(header)
        self.menu.addAction(header_action)
        empty = QWidget(self.menu)
        empty.setFixedWidth(370)
        empty.setMinimumHeight(156)
        empty_layout = QVBoxLayout(empty)
        empty_layout.setContentsMargins(16, 24, 16, 24)
        empty_layout.setSpacing(6)
        empty_layout.addStretch()
        empty_icon = QLabel(empty)
        empty_icon.setProperty("headingIcon", "inbox")
        empty_icon.setProperty("headingIconSize", 20)
        empty_icon.setProperty("headingIconColorRole", "text_muted")
        empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_icon.setFixedSize(24, 24)
        empty_icon.setPixmap(icon("inbox", COLORS["text_muted"], size=20).pixmap(20, 20))
        empty_layout.addWidget(empty_icon, 0, Qt.AlignmentFlag.AlignHCenter)
        empty_title = QLabel("No active jobs")
        role(empty_title, "paneHeading")
        empty_layout.addWidget(empty_title, 0, Qt.AlignmentFlag.AlignHCenter)
        empty_hint = QLabel("Exports and shared clips will appear here.")
        role(empty_hint, "secondary")
        empty_layout.addWidget(empty_hint, 0, Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addStretch()
        self.empty = QWidgetAction(self.menu)
        self.empty.setDefaultWidget(empty)
        self.menu.addAction(self.empty)
        button.setMenu(self.menu)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._update_button()

    def busy(self):
        return any(job.state in {"Queued", "Running", "Cancelling"} for job in self.jobs)

    def active_share(self, clip_id):
        return next(
            (job for job in self.jobs if job.kind == "Share" and job.clip_id == clip_id
             and self._active(job)), None
        ) if clip_id else None

    def submit(self, kind, title, function, *, record_id=None, forget=None, paused=False,
               clip_id=None, subtitle="", destination=None):
        if kind == "Share" and (existing := self.active_share(clip_id)):
            return existing
        was_busy = self.busy()
        job = OutputJob(kind, title, function, subtitle=subtitle,
                        state="Paused" if paused else "Queued",
                        record_id=record_id, forget=forget, clip_id=clip_id,
                        destination=destination)
        if paused:
            job.detail = "Resume to continue unfinished copies"
        self.jobs.append(job)
        self._add_row(job)
        self._update_button()
        self.changed.emit()
        if not paused:
            QTimer.singleShot(0, self._schedule)
            if not was_busy:
                QTimer.singleShot(0, self._open_for_first_job)
        return job

    def _menu_shown(self):
        if not self._auto_opening:
            self.auto_close_timer.stop()

    def _open_for_first_job(self):
        if not self.busy() or self.menu.isVisible() or not self.button.isVisible():
            return
        self._auto_opening = True
        width = self.menu.sizeHint().width()
        self.menu.popup(self.button.mapToGlobal(QPoint(self.button.width() - width,
                                                       self.button.height())))
        self.menu.windowHandle().installEventFilter(self)
        self._auto_opening = False
        self.auto_close_timer.start(4000)

    def eventFilter(self, watched, event):
        if self.auto_close_timer.isActive() and event.type() in {
            QEvent.Type.Enter,
            QEvent.Type.HoverEnter,
            QEvent.Type.MouseMove,
            QEvent.Type.HoverMove,
            QEvent.Type.MouseButtonPress,
            QEvent.Type.KeyPress,
        }:
            self.auto_close_timer.stop()
        return super().eventFilter(watched, event)

    def _add_row(self, job):
        self.empty.setVisible(False)
        self.header_divider.setVisible(False)
        row = QWidget(self.menu)
        row.setObjectName("outputJobRow")
        row.setFixedWidth(370)
        outer = QVBoxLayout(row)
        outer.setContentsMargins(8, 5, 8, 5)
        card = QWidget(row)
        card.setObjectName("outputJobCard")
        outer.addWidget(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 9, 10, 9)
        layout.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(8)
        metadata = QVBoxLayout()
        metadata.setSpacing(2)
        heading = QLabel(job.title, card)
        heading.setObjectName("outputJobTitle")
        heading.setWordWrap(True)
        metadata.addWidget(heading)
        subtitle = QLabel(job.subtitle, card)
        subtitle.setObjectName("outputJobSubtitle")
        subtitle.setWordWrap(True)
        metadata.addWidget(subtitle)
        subtitle.setVisible(bool(job.subtitle))
        top.addLayout(metadata, 1)
        actions = QVBoxLayout()
        actions.setSpacing(4)
        job.status = QLabel()
        job.status.setObjectName("outputJobStatus")
        job.status_dot = QLabel("●", card)
        job.status_dot.setObjectName("outputJobStatusDot")
        job.action = QPushButton("Cancel")
        job.action.setObjectName("outputJobAction")
        job.action.clicked.connect(lambda: self.cancel(job) if self._active(job)
                                   else self.resume(job) if self._resumable(job)
                                   else self.dismiss(job))
        actions.addWidget(job.action)
        job.dismiss_button = QPushButton("Forget")
        job.dismiss_button.clicked.connect(lambda: self.dismiss(job))
        actions.addWidget(job.dismiss_button)
        actions.addStretch()
        top.addLayout(actions)
        layout.addLayout(top)
        status_row = QHBoxLayout()
        status_row.setSpacing(5)
        status_row.addWidget(job.status_dot)
        status_row.addWidget(job.status)
        status_row.addStretch()
        layout.addLayout(status_row)
        phase_row = QHBoxLayout()
        phase_row.setSpacing(5)
        job.phase = QLabel(card)
        job.phase.setObjectName("outputJobPhase")
        job.phase.setWordWrap(True)
        phase_row.addWidget(job.phase, 1)
        job.open_button = QToolButton(card)
        job.open_button.setObjectName("outputJobOpen")
        job.open_button.setProperty("navUtilityStyle", "ghost")
        job.open_button.setFixedSize(24, 24)
        job.open_button.setIconSize(QSize(16, 16))
        set_icon(job.open_button, "folder-open", size=16)
        job.open_button.clicked.connect(lambda: self.open_destination(job))
        phase_row.addWidget(job.open_button, 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(phase_row)
        job.bar = QProgressBar()
        job.bar.setObjectName("outputJobProgress")
        job.bar.setRange(0, 100)
        job.bar.setTextVisible(False)
        layout.addWidget(job.bar)
        action = QWidgetAction(self.menu)
        action.setDefaultWidget(row)
        self.menu.addAction(action)
        job.row = row
        job.menu_action = action
        for widget in row.findChildren(QWidget):
            widget.installEventFilter(self)
        row.installEventFilter(self)
        self._refresh(job)

    @staticmethod
    def _active(job):
        return job.state in {"Queued", "Running", "Cancelling"}

    @staticmethod
    def _resumable(job):
        return bool(job.record_id and job.state in {"Paused", "Failed", "Cancelled"})

    def _refresh(self, job):
        color = {
            "Running": "accent_default", "Completed": "status_success",
            "Failed": "status_danger",
        }.get(job.state, "text_muted")
        for widget in (job.status, job.status_dot):
            widget.setProperty("statusColor", color)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        job.status.setText(f"{job.state} · {job.percent}%")
        job.phase.setText(job.detail)
        job.phase.setVisible(bool(job.detail))
        job.phase.setToolTip(job.detail)
        job.phase.setProperty("failed", job.state == "Failed")
        job.phase.style().unpolish(job.phase)
        job.phase.style().polish(job.phase)
        reveal_file = (job.kind == "Share" and job.state == "Completed"
                       and isinstance(job.result, str) and Path(job.result).is_file())
        set_icon(job.open_button, "file-search" if reveal_file else "folder-open", size=16)
        open_label = "Show shared file in Explorer" if reveal_file else "Open output folder in Explorer"
        job.open_button.setToolTip(open_label)
        job.open_button.setAccessibleName(open_label)
        job.open_button.setVisible(bool(job.destination))
        job.bar.setValue(job.percent)
        job.bar.setProperty("statusColor", color)
        job.bar.style().unpolish(job.bar)
        job.bar.style().polish(job.bar)
        job.action.setText(
            "Cancel" if self._active(job) else "Resume export" if self._resumable(job) else "Dismiss"
        )
        job.action.setEnabled(job.state != "Cancelling")
        job.dismiss_button.setVisible(bool(job.record_id) and not self._active(job))
        job.dismiss_button.setText("Dismiss" if job.state == "Completed" else "Forget")
        job.bar.setVisible(True)

    def open_destination(self, job):
        if not job.destination:
            return
        target = Path(job.destination)
        reveal_file = (job.kind == "Share" and job.state == "Completed"
                       and isinstance(job.result, str) and Path(job.result).is_file())
        try:
            if reveal_file and sys.platform == "win32":
                subprocess.Popen(["explorer.exe", "/select,", str(Path(job.result))])
            else:
                target.mkdir(parents=True, exist_ok=True)
                if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(target))):
                    raise OSError(f"Could not open output folder: {target}")
        except OSError as error:
            QMessageBox.warning(self.parent(), "Open output folder", str(error))

    def _update_button(self):
        active = sum(self._active(job) for job in self.jobs)
        attention = sum(job.state in {"Paused", "Failed", "Cancelled"} for job in self.jobs)
        count = active + attention
        label = f"Output Jobs ({count})" if count else "Output Jobs"
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
            job.detail = "Export complete"
        elif job.state == "Completed":
            job.detail = "Shared clip saved" if job.kind == "Share" else str(worker.result)
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
        was_busy = self.busy()
        job.state = "Queued"
        job.percent = 0
        job.detail = "Waiting to resume"
        self._refresh(job)
        self._update_button()
        self._schedule()
        if not was_busy:
            QTimer.singleShot(0, self._open_for_first_job)

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
        self.header_divider.setVisible(not self.jobs)
        self._update_button()
        self.changed.emit()
