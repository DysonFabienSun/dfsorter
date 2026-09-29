from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPropertyAnimation, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QCursor, QPainter, QPalette, QPixmap
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .mpv_backend import MpvBackend
from .theme import COLORS, SIZES, font, role
from .widgets import set_icon, tool


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
        # Native ancestors keep the first embedded mpv frame at the correct screen position.
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)

    def clear(self):
        self.update()


class AspectVideoContainer(QWidget):
    """Fit the native video surface without asking libmpv to add black bars."""

    def __init__(self, surface):
        super().__init__()
        self.surface = surface
        self.aspect_ratio = None
        self.layout_paused = False
        surface.setParent(self)
        self.prepared_frame = QLabel(self)
        self.prepared_frame.setScaledContents(True)
        self.prepared_frame.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.prepared_frame.hide()

    def show_prepared_frame(self, image):
        if image.isNull():
            return
        self.prepared_frame.setPixmap(QPixmap.fromImage(image))
        self.prepared_frame.setGeometry(self.surface.geometry())
        self.prepared_frame.show()
        self.prepared_frame.raise_()

    def clear_prepared_frame(self):
        self.prepared_frame.hide()
        self.prepared_frame.clear()

    def set_video_size(self, width, height):
        self.aspect_ratio = width / height if width > 0 and height > 0 else None
        self.layout_surface()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.layout_surface()

    def layout_surface(self):
        if self.layout_paused:
            return
        bounds = self.rect()
        if not self.aspect_ratio or bounds.width() <= 0 or bounds.height() <= 0:
            self.surface.setGeometry(bounds)
            self.prepared_frame.setGeometry(bounds)
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
        self.prepared_frame.setGeometry(self.surface.geometry())


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
        painter.setFont(font("md", "bold", base=painter.font()))
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
        value = round(
            self.minimum() + max(0, min(1, fraction)) * (self.maximum() - self.minimum())
        )
        self.setValue(value)

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


class FullscreenChromePanel(QWidget):
    """Floating chrome window with animatable Qt content."""

    def __init__(self, parent, position):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.content = QWidget(self)
        self.content.setObjectName("fullscreenChromeContent")
        self.content.setProperty("chromePosition", position)
        outer.addWidget(self.content)
        self.effect = QGraphicsOpacityEffect(self.content)
        self.content.setGraphicsEffect(self.effect)
        self.animation = QPropertyAnimation(self.effect, b"opacity", self)
        self.animation.setDuration(180)
        self.animation.finished.connect(self.finish_fade)
        self.target_opacity = 1
        self.effect.setOpacity(1)
        self.hide()

    def finish_fade(self):
        if self.target_opacity == 0 and self.effect.opacity() == 0:
            self.hide()

    def fade_to(self, opacity):
        self.target_opacity = opacity
        self.animation.stop()
        if opacity:
            self.show()
            self.raise_()
        self.animation.setStartValue(self.effect.opacity())
        self.animation.setEndValue(opacity)
        self.animation.start()


class Player(QWidget):
    loading_started = Signal()
    preview_render_ready = Signal()
    loading_finished = Signal()
    position_changed = Signal(int)
    previous = Signal()
    next = Signal()
    volume_changed = Signal(int)

    def __init__(self, settings=None):
        super().__init__()
        self.settings = settings if settings is not None else {}
        self.chrome_enabled = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        layout = QVBoxLayout(self)
        self.video = VideoSurface()
        self.video_container = AspectVideoContainer(self.video)
        self.video_container.setObjectName("videoContainer")
        self.video_container.setMinimumSize(260, 150)
        self.video_container.installEventFilter(self)
        layout.addWidget(self.video_container, 1)
        self.media = MpvBackend(self.video, self)
        self.media.videoSizeChanged.connect(self.video_container.set_video_size)
        self.media.videoSizeChanged.connect(self.finish_preview_if_ready)
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
            lambda muted: set_icon(
                self.mute, "volume-x" if muted else "volume-2",
                "player_chrome_text" if self.chrome_enabled else None,
            )
        )
        controls.addWidget(self.mute)
        self.volume = VolumeSlider()
        self.volume.setRange(0, 100)
        self.volume.setSingleStep(1)
        self.volume.setPageStep(10)
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
        self.control_bar = QWidget()
        self.control_bar.setObjectName("playerControlBar")
        controls_row = QGridLayout(self.control_bar)
        controls_row.setContentsMargins(0, 0, 0, 0)
        controls_row.addLayout(controls, 0, 0)
        controls_row.addWidget(self.fast_indicator, 0, 1)
        controls_row.addLayout(self.controls, 0, 2)
        controls_row.setColumnStretch(0, 1)
        controls_row.setColumnStretch(2, 1)
        self.controls_row = controls_row
        layout.addWidget(self.control_bar)
        self.status = QLabel()
        role(self.status, "warning")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.status.hide()
        self.media.durationChanged.connect(self.seek.setMaximum)
        self.media.positionChanged.connect(self.position)
        self.media.positionChanged.connect(self.invalidate_prepared_frame)

        self.media.playbackStateChanged.connect(
            self.update_play_icon
        )
        self.media.playbackStateChanged.connect(self.playback_state_changed)
        self.media.playbackStateChanged.connect(self.update_chrome_for_playback)
        self.media.errorOccurred.connect(self.load_error)
        self.media.frameReady.connect(self.first_frame)
        self.awaiting_frame = False
        self.preview_frame_ready = False
        self.fast_state = None
        self.load_timeout = QTimer(self)
        self.load_timeout.setSingleShot(True)
        self.load_timeout.setInterval(15000)
        self.load_timeout.timeout.connect(self.load_timed_out)
        self.preview_reveal_timer = QTimer(self)
        self.preview_reveal_timer.setSingleShot(True)
        self.preview_reveal_timer.timeout.connect(self.complete_preview)
        self.preview_reveal_generation = None
        self.native_surface_warmed = False
        self.warmed_video_geometry = None
        self.loaded_clip = None
        self.prepared_image = None
        self.prepared_position = None
        self.retry_load = False
        self.chrome_top = FullscreenChromePanel(self.video_container, "top")
        top_layout = QHBoxLayout(self.chrome_top.content)
        top_layout.setContentsMargins(24, 8, 20, 10)
        self.chrome_title = QLabel()
        self.chrome_title.setTextFormat(Qt.TextFormat.RichText)
        self.chrome_title.setWordWrap(True)
        self.chrome_title.setFont(font("fullscreen_title", "bold"))
        top_layout.addWidget(self.chrome_title, 1)
        self.chrome_bottom = FullscreenChromePanel(self.video_container, "bottom")
        self.chrome_bottom_layout = QVBoxLayout(self.chrome_bottom.content)
        self.chrome_bottom_layout.setContentsMargins(16, 0, 16, 12)
        self.chrome_bottom_layout.setSpacing(2)
        self.chrome_timer = QTimer(self)
        self.chrome_timer.setSingleShot(True)
        self.chrome_timer.setInterval(2500)
        self.chrome_timer.timeout.connect(self.hide_chrome)
        self.cursor_timer = QTimer(self)
        self.cursor_timer.setInterval(80)
        self.cursor_timer.timeout.connect(self.check_cursor_motion)
        self.last_cursor_position = None

    def update_play_icon(self, state):
        name = "pause" if state == QMediaPlayer.PlaybackState.PlayingState else "play"
        set_icon(self.play, name, "player_chrome_text" if self.chrome_enabled else None)

    def update_chrome_for_playback(self, state):
        if not self.chrome_enabled:
            return
        self.show_chrome()

    def set_fullscreen_chrome(self, enabled, title=""):
        if enabled == self.chrome_enabled:
            if enabled:
                self.chrome_title.setText(title)
                self.update_chrome_geometry()
            return
        self.chrome_enabled = enabled
        if enabled:
            self.chrome_title.setText(title)
            for panel in (self.chrome_top, self.chrome_bottom):
                panel.setParent(
                    self.window(),
                    Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint,
                )
                panel.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            self.layout().removeWidget(self.seek)
            self.layout().removeWidget(self.control_bar)
            self.chrome_bottom_layout.addWidget(self.seek)
            self.chrome_bottom_layout.addWidget(self.control_bar)
            self.controls_row.setColumnStretch(0, 0)
            self.controls_row.setColumnStretch(1, 1)
            self.controls_row.setColumnStretch(2, 0)
            QApplication.instance().installEventFilter(self)
            self.last_cursor_position = QCursor.pos()
            self.cursor_timer.start()
            self.update_chrome_geometry()
            self.show_chrome()
        else:
            self.chrome_timer.stop()
            self.cursor_timer.stop()
            QApplication.instance().removeEventFilter(self)
            self.chrome_top.animation.stop()
            self.chrome_bottom.animation.stop()
            self.chrome_top.hide()
            self.chrome_bottom.hide()
            self.chrome_top.setParent(self.video_container)
            self.chrome_bottom.setParent(self.video_container)
            self.chrome_bottom_layout.removeWidget(self.seek)
            self.chrome_bottom_layout.removeWidget(self.control_bar)
            self.layout().insertWidget(1, self.seek)
            self.layout().insertWidget(2, self.control_bar)
            self.controls_row.setColumnStretch(0, 1)
            self.controls_row.setColumnStretch(1, 0)
            self.controls_row.setColumnStretch(2, 1)
        for button in [self.previous_button, self.play, self.next_button, self.mute]:
            name = button.property("iconName")
            set_icon(button, name, "player_chrome_text" if enabled else None)
        for item in range(self.controls.count()):
            widget = self.controls.itemAt(item).widget()
            if widget is not None and widget.property("iconName"):
                set_icon(widget, widget.property("iconName"),
                         "player_chrome_text" if enabled else None)
        self.update_play_icon(self.media.playbackState())

    def update_chrome_geometry(self):
        if not self.chrome_enabled:
            return
        width = self.video_container.width()
        top_origin = self.video_container.mapToGlobal(
            self.video_container.rect().topLeft()
        )
        self.chrome_top.setGeometry(
            top_origin.x(), top_origin.y(), width, self.chrome_top.sizeHint().height()
        )
        height = self.chrome_bottom.sizeHint().height()
        origin = self.video_container.mapToGlobal(
            self.video_container.rect().bottomLeft()
        )
        self.chrome_bottom.setGeometry(origin.x(), origin.y() - height + 1, width, height)
        self.chrome_top.raise_()
        self.chrome_bottom.raise_()

    def show_chrome(self):
        if not self.chrome_enabled:
            return
        self.update_chrome_geometry()
        self.chrome_top.fade_to(1)
        self.chrome_bottom.fade_to(1)
        if self.media.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.chrome_timer.start()
        else:
            self.chrome_timer.stop()

    def hide_chrome(self):
        if not self.chrome_enabled or self.media.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            return
        self.chrome_top.fade_to(0)
        self.chrome_bottom.fade_to(0)

    def check_cursor_motion(self):
        position = QCursor.pos()
        if position == self.last_cursor_position:
            return
        self.last_cursor_position = position
        if self.video_container.rect().contains(self.video_container.mapFromGlobal(position)):
            self.show_chrome()

    def eventFilter(self, watched: QObject, event):
        if watched is self.video_container and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self.update_chrome_geometry)
        if self.chrome_enabled and event.type() in {
            QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
            QEvent.Type.Wheel, QEvent.Type.KeyPress,
        }:
            if watched is self or (
                isinstance(watched, QWidget)
                and (
                    self.isAncestorOf(watched)
                    or any(panel is watched or panel.isAncestorOf(watched)
                           for panel in (self.chrome_top, self.chrome_bottom))
                )
            ):
                self.show_chrome()
        return super().eventFilter(watched, event)

    def set_volume(self, value):
        self.audio.setVolume(value / 100)
        self.volume_changed.emit(value)

    def set_status(self, message):
        self.status.setText(message)
        self.status.setVisible(bool(message))

    def invalidate_prepared_frame(self, position):
        if (
            self.prepared_position is not None
            and abs(position - self.prepared_position) > 100
        ):
            self.prepared_image = None
            self.prepared_position = None

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
        self.video_container.clear_prepared_frame()
        self.prepared_image = None
        self.prepared_position = None
        self.loaded_clip = clip
        self.retry_load = False
        self.initial_seek_done = False
        self.preview_frame_ready = False
        self.ended = False
        self.load_timeout.stop()
        self.preview_reveal_timer.stop()
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
            self.preview_frame_ready = True
            self.finish_preview_if_ready()

    def finish_preview_if_ready(self, *_):
        if not self.awaiting_frame or not self.preview_frame_ready:
            return
        if self.video_container.aspect_ratio is None:
            return
        if self.preview_reveal_timer.isActive():
            return
        screen = self.screen()
        refresh_rate = screen.refreshRate() if screen else 60
        if refresh_rate <= 0:
            refresh_rate = 60
        self.preview_reveal_generation = self.media.generation
        self.preview_render_ready.emit()
        frame_delay = max(1, round(2000 / refresh_rate))
        self.preview_reveal_timer.start(
            frame_delay if self.native_surface_warmed else max(100, frame_delay)
        )

    def complete_preview(self):
        if (
            not self.awaiting_frame
            or not self.preview_frame_ready
            or self.video_container.aspect_ratio is None
            or self.preview_reveal_generation != self.media.generation
        ):
            return
        self.awaiting_frame = False
        if self.video.isVisible():
            self.native_surface_warmed = True
            self.warmed_video_geometry = (
                self.video.size(), self.video.devicePixelRatioF()
            )
        self.play.setEnabled(True)
        self.seek.setEnabled(True)
        self.load_timeout.stop()
        self.loading_finished.emit()

    def load_error(self, error, message):
        self.preview_reveal_timer.stop()
        self.set_status(message)
        self.play.setEnabled(False)
        self.seek.setEnabled(False)
        if self.awaiting_frame:
            self.awaiting_frame = False
            self.load_timeout.stop()
            self.loading_finished.emit()

    def load_timed_out(self):
        if self.awaiting_frame:
            self.preview_reveal_timer.stop()
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
