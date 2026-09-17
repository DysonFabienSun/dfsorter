from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoFrame
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget

from .widgets import icon, tool


class VideoSurface(QVideoWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet("background: transparent;")

    def clear(self):
        self.videoSink().setVideoFrame(QVideoFrame())


class RangeSlider(QSlider):
    def __init__(self):
        super().__init__(Qt.Orientation.Horizontal)
        self.marker_range = (None, None)
        self.pending_in = None
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
            painter.fillRect(left, self.height() // 2 - 3, width, 7, QColor(78, 190, 200, 95))
        for value, color, label in [
            (start, "#67d7c0", "I"),
            (end, "#e8bb72", "O"),
            (self.pending_in, "#d6dce4", "·I"),
        ]:
            if value is None:
                continue
            painter.setPen(QColor(color))
            position = 8 + int((self.width() - 16) * value / self.maximum())
            painter.drawLine(position, 0, position, self.height())
            painter.drawText(position + 3, 11, label)


class Player(QWidget):
    position_changed = Signal(int)
    previous = Signal()
    next = Signal()

    def __init__(self):
        super().__init__()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        layout = QVBoxLayout(self)
        self.video = VideoSurface()
        self.video.setMinimumSize(260, 150)
        layout.addWidget(self.video, 1)
        self.media = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.6)
        self.media.setAudioOutput(self.audio)
        self.media.setVideoOutput(self.video)
        self.seek = RangeSlider()
        self.seek.sliderPressed.connect(self.begin_scrub)
        self.seek.sliderMoved.connect(self.queue_seek)
        self.seek.sliderReleased.connect(self.end_scrub)
        self.seek_timer = QTimer(self)
        self.seek_timer.setInterval(50)
        self.seek_timer.timeout.connect(self.preview_seek)
        self.pending_seek = None
        self.scrub_playing = False
        layout.addWidget(self.seek)
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
        volume = QSlider(Qt.Orientation.Horizontal)
        volume.setRange(0, 100)
        volume.setValue(60)
        volume.setMaximumWidth(100)
        volume.setAccessibleName("Volume")
        volume.valueChanged.connect(lambda value: self.audio.setVolume(value / 100))
        controls.addWidget(volume)
        self.time = QLabel("0:00 / 0:00")
        controls.addWidget(self.time)
        controls.addStretch()
        layout.addLayout(controls)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.media.durationChanged.connect(self.seek.setMaximum)
        self.media.positionChanged.connect(self.position)
        self.media.playbackStateChanged.connect(
            lambda state: self.play.setIcon(
                icon("pause" if state == QMediaPlayer.PlaybackState.PlayingState else "play")
            )
        )
        self.media.errorOccurred.connect(lambda error, message: self.status.setText(message))
        self.video.videoSink().videoFrameChanged.connect(self.first_frame)
        self.awaiting_frame = False
        self.fast_state = None

    def begin_scrub(self):
        self.awaiting_frame = False
        self.scrub_playing = self.media.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        self.media.pause()
        self.seek_timer.start()

    def queue_seek(self, position):
        self.pending_seek = position

    def preview_seek(self):
        if self.pending_seek is not None:
            self.media.setPosition((self.pending_seek // 100) * 100)
            self.pending_seek = None

    def end_scrub(self):
        self.seek_timer.stop()
        self.pending_seek = None
        self.media.setPosition(self.seek.sliderPosition())
        if self.scrub_playing:
            self.media.play()

    def load(self, clip):
        self.fast(False)
        self.seek_timer.stop()
        self.pending_seek = None
        self.media.stop()
        self.video.clear()
        self.status.clear()
        self.seek.marker_range = (clip["in_ms"], clip["out_ms"]) if clip else (None, None)
        self.seek.pending_in = None
        self.seek.update()
        self.awaiting_frame = False
        if not clip or not Path(clip["source_path"]).is_file():
            self.media.setSource(QUrl())
            self.status.setText("Source unavailable" if clip else "No clip selected")
            return
        self.awaiting_frame = True
        self.media.setSource(QUrl.fromLocalFile(clip["source_path"]))
        self.media.play()

    def first_frame(self, frame):
        if self.awaiting_frame and frame.isValid():
            self.awaiting_frame = False
            self.media.pause()
            self.media.setPosition(0)

    def position(self, milliseconds):
        if not self.seek.isSliderDown():
            self.seek.setValue(milliseconds)
        self.time.setText(
            f"{milliseconds // 60000:02d}:{milliseconds // 1000 % 60:02d} / {self.media.duration() // 60000:02d}:{self.media.duration() // 1000 % 60:02d}"
        )
        self.position_changed.emit(milliseconds)

    def toggle(self):
        self.awaiting_frame = False
        if self.media.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.media.pause()
        else:
            self.media.play()

    def fast(self, enabled):
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
