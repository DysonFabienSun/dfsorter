from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget


class VideoSurface(QWidget):
    def __init__(self):
        super().__init__()
        self.sink = QVideoSink(self)
        self.frame_image = QImage()
        self.sink.videoFrameChanged.connect(self.frame_changed)

    def videoSink(self):
        return self.sink

    def frame_changed(self, frame):
        if frame.isValid():
            self.frame_image = frame.toImage()
            self.update()

    def clear(self):
        self.frame_image = QImage()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#101318"))
        if not self.frame_image.isNull():
            size = self.frame_image.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
            left = (self.width() - size.width()) // 2
            top = (self.height() - size.height()) // 2
            painter.drawImage(
                left,
                top,
                self.frame_image.scaled(
                    size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                ),
            )


class RangeSlider(QSlider):
    def __init__(self):
        super().__init__(Qt.Orientation.Horizontal)
        self.marker_range = (None, None)

    def paintEvent(self, event):
        super().paintEvent(event)
        start, end = self.marker_range
        if start is None or end is None or self.maximum() <= 0:
            return
        painter = QPainter(self)
        painter.setPen(QColor("#75c6ab"))
        for value in (start, end):
            position = 8 + int((self.width() - 16) * value / self.maximum())
            painter.drawLine(position, 0, position, self.height())


class Player(QWidget):
    position_changed = Signal(int)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        self.video = VideoSurface()
        self.video.setMinimumSize(260, 150)
        layout.addWidget(self.video, 1)
        self.media = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.6)
        self.media.setAudioOutput(self.audio)
        self.media.setVideoSink(self.video.videoSink())
        self.seek = RangeSlider()
        self.seek.sliderMoved.connect(self.media.setPosition)
        layout.addWidget(self.seek)
        controls = QHBoxLayout()
        self.play = QPushButton("Play / Pause")
        self.play.clicked.connect(self.toggle)
        controls.addWidget(self.play)
        self.mute = QPushButton("Mute")
        self.mute.setCheckable(True)
        self.mute.toggled.connect(self.audio.setMuted)
        controls.addWidget(self.mute)
        volume = QSlider(Qt.Orientation.Horizontal)
        volume.setRange(0, 100)
        volume.setValue(60)
        volume.setMaximumWidth(100)
        volume.valueChanged.connect(lambda value: self.audio.setVolume(value / 100))
        controls.addWidget(volume)
        self.time = QLabel("0:00 / 0:00")
        controls.addWidget(self.time)
        layout.addLayout(controls)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.media.durationChanged.connect(self.seek.setMaximum)
        self.media.positionChanged.connect(self.position)
        self.media.errorOccurred.connect(lambda error, message: self.status.setText(message))
        self.video.videoSink().videoFrameChanged.connect(self.first_frame)
        self.awaiting_frame = False
        self.fast_state = None

    def load(self, clip):
        self.fast(False)
        self.media.stop()
        self.video.clear()
        self.status.clear()
        self.seek.marker_range = (clip["in_ms"], clip["out_ms"]) if clip else (None, None)
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
        self.time.setText(f"{milliseconds / 1000:.1f}s / {self.media.duration() / 1000:.1f}s")
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
