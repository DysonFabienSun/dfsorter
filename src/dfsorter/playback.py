from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget

from .mpv_backend import MpvBackend
from .theme import COLORS, SIZES, font, role
from .widgets import icon, tool


def start_offset_seconds(settings):
    value = settings.get("start_near_end_seconds", 40)
    return value if type(value) is int and 1 <= value <= 86400 else 40


def playback_volume(settings):
    value = settings.get("playback_volume", 60)
    return value if type(value) is int and 0 <= value <= 100 else 60


class VideoSurface(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("videoSurface")
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(COLORS["surface_video"]))
        self.setPalette(palette)
        self.setAutoFillBackground(True)
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)

    def clear(self):
        self.update()


class AspectVideoContainer(QWidget):
    """Fit the native video surface without asking libmpv to add black bars."""

    def __init__(self, surface):
        super().__init__()
        self.surface = surface
        self.aspect_ratio = None
        surface.setParent(self)

    def set_video_size(self, width, height):
        self.aspect_ratio = width / height if width > 0 and height > 0 else None
        self.layout_surface()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.layout_surface()

    def layout_surface(self):
        bounds = self.rect()
        if not self.aspect_ratio or bounds.width() <= 0 or bounds.height() <= 0:
            self.surface.setGeometry(bounds)
            return
        if bounds.width() / bounds.height() > self.aspect_ratio:
            height = bounds.height()
            width = round(height * self.aspect_ratio)
        else:
            width = bounds.width()
            height = round(width / self.aspect_ratio)
        self.surface.setGeometry(
            bounds.x() + (bounds.width() - width) // 2,
            bounds.y() + (bounds.height() - height) // 2,
            width,
            height,
        )


class RangeSlider(QSlider):
    def __init__(self):
        super().__init__(Qt.Orientation.Horizontal)
        self.setObjectName("timeline")
        self.marker_range = (None, None)
        self.pending_in = None
        self.pending_out = None
        self.setMinimumHeight(30)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName("Clip timeline")

    def move_pointer(self, event):
        fraction = (event.position().x() - 8) / max(1, self.width() - 16)
        self.setSliderPosition(round(max(0, min(1, fraction)) * self.maximum()))
        self.sliderMoved.emit(self.sliderPosition())

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setSliderDown(True)
            self.move_pointer(event)

    def mouseMoveEvent(self, event):
        if self.isSliderDown():
            self.move_pointer(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.move_pointer(event)
            self.setSliderDown(False)

    def paintEvent(self, event):
        super().paintEvent(event)
        start, end = self.marker_range
        if self.maximum() <= 0:
            return
        painter = QPainter(self)
        if start is not None and end is not None:
            left = 8 + int((self.width() - 16) * start / self.maximum())
            width = int((self.width() - 16) * (end - start) / self.maximum())
            tint = QColor(COLORS["accent_default"])
            tint.setAlphaF(0.18)
            painter.fillRect(left, self.height() // 2 - 3, width, SIZES["timeline"], tint)
        for value, color, label in [
            (start, COLORS["focus"], "I"),
            (end, COLORS["focus"], "O"),
            (self.pending_in, COLORS["accent_default"], "·I"),
            (self.pending_out, COLORS["accent_default"], "·O"),
        ]:
            if value is None:
                continue
            painter.setPen(QColor(color))
            position = 8 + int((self.width() - 16) * value / self.maximum())
            painter.drawLine(position, 0, position, self.height())
            painter.drawText(position + 3, 11, label)


class VolumeSlider(QSlider):
    def __init__(self):
        super().__init__(Qt.Orientation.Horizontal)
        self.setObjectName("volume")

    def move_pointer(self, event):
        handle_radius = 5
        fraction = (event.position().x() - handle_radius) / max(
            1, self.width() - handle_radius * 2
        )
        self.setValue(
            round(self.minimum() + max(0, min(1, fraction)) * (self.maximum() - self.minimum()))
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setSliderDown(True)
            self.move_pointer(event)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.isSliderDown():
            self.move_pointer(event)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.isSliderDown():
            self.move_pointer(event)
            self.setSliderDown(False)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class Player(QWidget):
    loading_started = Signal()
    loading_finished = Signal()
    position_changed = Signal(int)
    previous = Signal()
    next = Signal()
    volume_changed = Signal(int)

    def __init__(self, settings=None):
        super().__init__()
        self.settings = settings if settings is not None else {}
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        layout = QVBoxLayout(self)
        self.video = VideoSurface()
        self.video_container = AspectVideoContainer(self.video)
        self.video_container.setObjectName("videoContainer")
        self.video_container.setMinimumSize(260, 150)
        layout.addWidget(self.video_container, 1)
        self.media = MpvBackend(self.video, self)
        self.media.videoSizeChanged.connect(self.video_container.set_video_size)
        self.audio = self.media
        initial_volume = playback_volume(self.settings)
        self.audio.setVolume(initial_volume / 100)
        self.seek = RangeSlider()
        self.seek.sliderPressed.connect(self.begin_scrub)
        self.seek.sliderMoved.connect(self.queue_seek)
        self.seek.sliderReleased.connect(self.end_scrub)
        self.seek_timer = QTimer(self)
        self.seek_timer.setInterval(50)
        self.seek_timer.timeout.connect(self.preview_seek)
        self.pending_seek = None
        self.scrub_playing = False
        self.ended = False
        self.media.mediaStatusChanged.connect(self.media_status_changed)
        layout.addWidget(self.seek)
        self.fast_indicator = QLabel(">>>")
        self.fast_indicator.setTextFormat(Qt.TextFormat.RichText)
        self.fast_indicator.setObjectName("fastIndicator")
        self.fast_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.fast_indicator.setFont(font("sm", "bold"))
        self.fast_indicator.setAccessibleName("Fast-forward 3×")
        indicator_policy = self.fast_indicator.sizePolicy()
        indicator_policy.setRetainSizeWhenHidden(True)
        self.fast_indicator.setSizePolicy(indicator_policy)
        self.fast_indicator.hide()
        self.fast_indicator_phase = 0
        self.fast_indicator_timer = QTimer(self)
        self.fast_indicator_timer.setInterval(120)
        self.fast_indicator_timer.timeout.connect(self.animate_fast_indicator)
        controls = QHBoxLayout()
        self.previous_button = tool("skip-back", "Previous clip", self.previous.emit)
        controls.addWidget(self.previous_button)
        self.play = tool("play", "Play / Pause · Space", self.toggle)
        controls.addWidget(self.play)
        self.next_button = tool("skip-forward", "Next clip", self.next.emit)
        controls.addWidget(self.next_button)
        self.mute = tool("volume-2", "Mute / unmute", lambda: None)
        self.mute.setCheckable(True)
        self.mute.toggled.connect(self.audio.setMuted)
        self.audio.mutedChanged.connect(
            lambda muted: self.mute.setIcon(icon("volume-x" if muted else "volume-2"))
        )
        controls.addWidget(self.mute)
        self.volume = VolumeSlider()
        self.volume.setRange(0, 100)
        self.volume.setValue(initial_volume)
        self.volume.setFixedHeight(18)
        self.volume.setMaximumWidth(100)
        self.volume.setAccessibleName("Volume")
        self.volume.valueChanged.connect(self.set_volume)
        controls.addWidget(self.volume, 0, Qt.AlignmentFlag.AlignVCenter)
        self.time = QLabel("0:00 / 0:00")
        controls.addWidget(self.time, 0, Qt.AlignmentFlag.AlignVCenter)
        controls.addStretch()
        self.controls = QHBoxLayout()
        self.controls.addStretch()
        controls_row = QGridLayout()
        controls_row.addLayout(controls, 0, 0)
        controls_row.addWidget(self.fast_indicator, 0, 1)
        controls_row.addLayout(self.controls, 0, 2)
        controls_row.setColumnStretch(0, 1)
        controls_row.setColumnStretch(2, 1)
        layout.addLayout(controls_row)
        self.status = QLabel()
        role(self.status, "warning")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.status.hide()
        self.media.durationChanged.connect(self.seek.setMaximum)
        self.media.positionChanged.connect(self.position)

        self.media.playbackStateChanged.connect(
            lambda state: self.play.setIcon(
                icon("pause" if state == QMediaPlayer.PlaybackState.PlayingState else "play")
            )
        )
        self.media.playbackStateChanged.connect(self.playback_state_changed)
        self.media.errorOccurred.connect(self.load_error)
        self.media.frameReady.connect(self.first_frame)
        self.awaiting_frame = False
        self.fast_state = None
        self.load_timeout = QTimer(self)
        self.load_timeout.setSingleShot(True)
        self.load_timeout.setInterval(15000)
        self.load_timeout.timeout.connect(self.load_timed_out)
        self.loaded_clip = None
        self.retry_load = False

    def set_volume(self, value):
        self.audio.setVolume(value / 100)
        self.volume_changed.emit(value)

    def set_status(self, message):
        self.status.setText(message)
        self.status.setVisible(bool(message))

    def begin_scrub(self):
        self.awaiting_frame = False
        self.scrub_playing = self.ended or (
            self.media.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        )
        self.media.pause()
        self.seek_timer.start()

    def queue_seek(self, position):
        self.pending_seek = position

    def preview_seek(self):
        if self.pending_seek is not None:
            self.seek_to((self.pending_seek // 100) * 100, preview=True)
            self.pending_seek = None

    def end_scrub(self):
        self.seek_timer.stop()
        self.pending_seek = None
        self.seek_to(self.seek.sliderPosition(), preview=True)
        if self.scrub_playing:
            self.media.play()

    def media_status_changed(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.ended = True
        elif status in {QMediaPlayer.MediaStatus.NoMedia, QMediaPlayer.MediaStatus.InvalidMedia}:
            self.ended = False

    def playback_state_changed(self, state):
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.ended = False

    def seek_to(self, position, preview=False):
        position = max(0, min(self.media.duration(), position))
        recover = self.ended and position < self.media.duration()
        if recover:
            # Qt stops the backend at EOF. Re-enter paused playback before seeking.
            self.media.pause()
            self.ended = False
        self.media.setPosition(position)
        if recover and not preview:
            self.media.play()

    def load(self, clip):
        self.loaded_clip = clip
        self.retry_load = False
        self.initial_seek_done = False
        self.ended = False
        self.load_timeout.stop()
        self.awaiting_frame = False
        self.loading_started.emit()
        self.fast(False)
        self.seek_timer.stop()
        self.pending_seek = None
        self.media.stop()
        self.video.clear()
        self.set_status("")
        self.play.setEnabled(False)
        self.seek.setEnabled(False)
        self.seek.marker_range = (clip["in_ms"], clip["out_ms"]) if clip else (None, None)
        self.initial_range = self.seek.marker_range
        self.seek.pending_in = None
        self.seek.pending_out = None
        self.seek.update()
        self.awaiting_frame = False
        if not clip or not Path(clip["source_path"]).is_file():
            self.media.setSource(QUrl())
            self.set_status("Source unavailable" if clip else "No clip selected")
            self.loading_finished.emit()
            return
        self.awaiting_frame = True
        self.load_timeout.start()
        self.media.setSource(QUrl.fromLocalFile(clip["source_path"]))

    def first_frame(self):
        if self.awaiting_frame and not self.initial_seek_done:
            self.initial_seek_done = True
            self.media.pause()
            start, end = self.initial_range
            valid_range = (
                isinstance(start, int)
                and isinstance(end, int)
                and 0 <= start < end <= self.media.duration()
            )
            fallback = 0
            if self.settings.get("start_near_end_enabled", True):
                fallback = max(
                    0, self.media.duration() - start_offset_seconds(self.settings) * 1000
                )
            self.media.setPosition(start if valid_range else fallback)
        elif self.awaiting_frame:
            self.awaiting_frame = False
            self.play.setEnabled(True)
            self.seek.setEnabled(True)
            self.load_timeout.stop()
            self.loading_finished.emit()

    def load_error(self, error, message):
        self.set_status(message)
        self.play.setEnabled(False)
        self.seek.setEnabled(False)
        if self.awaiting_frame:
            self.awaiting_frame = False
            self.load_timeout.stop()
            self.loading_finished.emit()

    def load_timed_out(self):
        if self.awaiting_frame:
            self.awaiting_frame = False
            self.media.stop()
            self.retry_load = True
            self.play.setEnabled(True)
            self.set_status("Video preview timed out. Press Play to retry.")
            self.loading_finished.emit()

    def position(self, milliseconds):
        if not self.seek.isSliderDown():
            self.seek.setValue(milliseconds)
        self.time.setText(
            f"{milliseconds // 60000:02d}:{milliseconds // 1000 % 60:02d} / {self.media.duration() // 60000:02d}:{self.media.duration() // 1000 % 60:02d}"
        )
        self.position_changed.emit(milliseconds)

    def toggle(self):
        if self.retry_load:
            self.load(self.loaded_clip)
            return
        if self.awaiting_frame or not self.play.isEnabled():
            return
        if self.media.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.media.pause()
        else:
            self.media.play()

    def animate_fast_indicator(self):
        colors = [COLORS["focus"], COLORS["accent_default"], COLORS["text_disabled"]]
        self.fast_indicator.setText(
            "".join(
                f'<span style="color:{colors[(self.fast_indicator_phase - index) % 3]}">&gt;</span>'
                for index in range(3)
            )
        )
        self.fast_indicator_phase = (self.fast_indicator_phase + 1) % 3

    def fast(self, enabled):
        if enabled and (self.awaiting_frame or not self.play.isEnabled()):
            return
        if enabled and self.fast_state is None:
            self.awaiting_frame = False
            self.fast_state = (self.media.playbackState(), self.media.playbackRate())
            self.media.setPlaybackRate(3)
            self.media.play()
        elif not enabled and self.fast_state is not None:
            state, rate = self.fast_state
            self.fast_state = None
            self.media.setPlaybackRate(rate)
            if state != QMediaPlayer.PlaybackState.PlayingState:
                self.media.pause()
        self.fast_indicator.setVisible(self.fast_state is not None)
        if self.fast_state is not None and not self.fast_indicator_timer.isActive():
            self.animate_fast_indicator()
            self.fast_indicator_timer.start()
        elif self.fast_state is None:
            self.fast_indicator_timer.stop()
            self.fast_indicator_phase = 0
