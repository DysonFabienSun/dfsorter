"""Qt-facing libmpv adapter. Source media is never rewritten for playback."""

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QImage
from PySide6.QtMultimedia import QMediaPlayer


def load_mpv():
    runtime = Path(__file__).resolve().parents[2] / "runtime/mpv"
    if os.name == "nt":
        if not (runtime / "libmpv-2.dll").is_file():
            raise OSError("Playback runtime missing. Run setup-playback.ps1.")
        if str(runtime) not in os.environ.get("PATH", "").split(os.pathsep):
            os.environ["PATH"] = str(runtime) + os.pathsep + os.environ.get("PATH", "")
    import mpv

    return mpv


def audio_mix_graph(track_ids):
    """Mix tracks channel-wise, retaining stereo and libmpv's source timestamps."""
    if len(track_ids) < 2:
        return ""
    filters = [
        f"[aid{track}]aresample=48000:async=1:first_pts=0,aformat=channel_layouts=stereo[a{index}]"
        for index, track in enumerate(track_ids)
    ]
    inputs = "".join(f"[a{index}]" for index in range(len(track_ids)))
    filters.append(
        f"{inputs}amix=inputs={len(track_ids)}:duration=longest:"
        "dropout_transition=0:normalize=1[ao]"
    )
    return ";".join(filters)


def display_size(parameters):
    """Return libmpv's display-corrected video size, or no size while unavailable."""
    if not isinstance(parameters, dict):
        return (0, 0)
    try:
        width = round(float(parameters.get("dw", 0)))
        height = round(float(parameters.get("dh", 0)))
    except (TypeError, ValueError):
        return (0, 0)
    return (width, height) if width > 0 and height > 0 else (0, 0)


class MpvBackend(QObject):
    # Keep Qt's public state enums so existing controls have one state vocabulary.
    durationChanged = Signal(int)
    positionChanged = Signal(int)
    playbackStateChanged = Signal(object)
    mediaStatusChanged = Signal(object)
    errorOccurred = Signal(object, str)
    mutedChanged = Signal(bool)
    frameReady = Signal()
    videoSizeChanged = Signal(int, int)
    _event = Signal(int, str, object)

    def __init__(self, surface, parent=None):
        super().__init__(parent)
        self.surface = surface
        self.engine = None
        self._lifecycle = None
        self._entry_lock = threading.Lock()
        self._entries = {}
        self._event_generation = -1
        self.generation = 0
        self._duration = self._position = 0
        self._volume, self._muted, self._rate = 0.6, False, 1
        self._source = QUrl()
        self._state = QMediaPlayer.PlaybackState.StoppedState
        self._status = QMediaPlayer.MediaStatus.NoMedia
        self._audio = False
        self._video_size = (0, 0)
        self._prepared = False
        self._seeking = False
        self._event.connect(self._receive, Qt.ConnectionType.QueuedConnection)

    def setSource(self, source):
        self.stop()
        self._source = source
        self._duration = self._position = 0
        self._audio = self._prepared = False
        self._video_size = (0, 0)
        self._seeking = False
        self.durationChanged.emit(0)
        self.positionChanged.emit(0)
        self.videoSizeChanged.emit(0, 0)
        if source.isEmpty():
            self._set_status(QMediaPlayer.MediaStatus.NoMedia)
            return
        generation = self.generation
        try:
            if self.engine is None:
                self._initialize()
            self._set_status(QMediaPlayer.MediaStatus.LoadingMedia)
            self._set_state(QMediaPlayer.PlaybackState.PausedState)
            self.engine.pause = True
            with self._entry_lock:
                result = self.engine.command("loadfile", source.toLocalFile(), "replace")
                self._entries = {result["playlist_entry_id"]: generation}
        except Exception as error:
            if self.engine is None and self._lifecycle:
                self._lifecycle.shutdown()
                self._lifecycle = None
            self._receive(generation, "error", str(error))

    def _initialize(self):
        mpv = load_mpv()

        # libmpv's Windows initialization/cleanup must not disturb Qt's UI-thread
        # COM state. Create and destroy each instance on its own lifecycle thread.
        self._lifecycle = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mpv-lifecycle")
        engine = self._lifecycle.submit(
            mpv.MPV,
            wid=str(int(self.surface.winId())),
            config=False,
            input_default_bindings=False,
            input_vo_keyboard=False,
            osc=False,
            idle=True,
            keep_open=True,
            pause=True,
            load_scripts=False,
            load_auto_profiles=False,
            load_osd_console=False,
            ytdl=False,
            load_stats_overlay=False,
            load_console=False,
            load_select=False,
            load_positioning=False,
            load_commands=False,
            focus_on="never",
            hwdec="auto-safe",
            audio_channels="stereo",
            vo="gpu",
            gpu_api="d3d11" if os.name == "nt" else "auto",
            volume=self._volume * 100,
            mute=self._muted,
            speed=self._rate,
        ).result()
        self.engine = engine

        def send(name, value=None):
            self._event.emit(self._event_generation, name, value)

        @engine.event_callback("start-file")
        def started(event):
            with self._entry_lock:
                self._event_generation = self._entries.get(event.data.playlist_entry_id, -1)

        for prop in ("time-pos", "duration", "eof-reached", "video-out-params"):
            engine.observe_property(prop, lambda name, value: send(name, value))

        @engine.event_callback("file-loaded")
        def loaded(event):
            if self._event_generation != self.generation:
                return
            try:
                tracks = [track["id"] for track in engine.track_list if track["type"] == "audio"]
                engine.lavfi_complex = audio_mix_graph(tracks)
                try:
                    size = display_size(engine.command("get_property", "video-out-params"))
                except Exception:
                    size = (0, 0)
                send("loaded", (bool(tracks), engine.duration or 0, size))
            except Exception as error:
                send("error", f"Audio mixing failed: {error}")

        @engine.event_callback("playback-restart")
        def ready(event):
            send("ready")

        @engine.event_callback("end-file")
        def ended(event):
            data = event.data
            if data.reason == 4:
                send("error", f"Playback failed (libmpv error {data.error})")

    def _receive(self, generation, name, value):
        if generation != self.generation:
            return
        if name == "loaded":
            self._audio, duration, size = value
            self._duration = round(duration * 1000)
            self.durationChanged.emit(self._duration)
            self._set_video_size(size)
            self._prepared = True
            self._set_status(QMediaPlayer.MediaStatus.LoadedMedia)
        elif name == "ready" and self._prepared:
            self._seeking = False
            self.frameReady.emit()
        elif name == "duration" and value is not None:
            self._duration = round(value * 1000)
            self.durationChanged.emit(self._duration)
        elif name == "time-pos" and value is not None and not self._seeking:
            self._position = round(value * 1000)
            self.positionChanged.emit(self._position)
        elif name == "eof-reached" and value:
            self._set_state(QMediaPlayer.PlaybackState.StoppedState)
            self._set_status(QMediaPlayer.MediaStatus.EndOfMedia)
        elif name == "video-out-params":
            self._set_video_size(display_size(value))
        elif name == "error":
            self._prepared = False
            if self.engine:
                self.engine.pause = True
            self._set_state(QMediaPlayer.PlaybackState.StoppedState)
            self._set_status(QMediaPlayer.MediaStatus.InvalidMedia)
            self.errorOccurred.emit(QMediaPlayer.Error.ResourceError, value)

    def _set_video_size(self, size):
        if size != (0, 0) and size != self._video_size:
            self._video_size = size
            self.videoSizeChanged.emit(*size)

    def _set_state(self, state):
        self._state = state
        self.playbackStateChanged.emit(state)

    def _set_status(self, status):
        self._status = status
        self.mediaStatusChanged.emit(status)

    def source(self):
        return self._source

    def duration(self):
        return self._duration

    def position(self):
        return self._position

    def playbackState(self):
        return self._state

    def mediaStatus(self):
        return self._status

    def hasAudio(self):
        return self._audio

    def playbackRate(self):
        return self._rate

    def setPlaybackRate(self, rate):
        self._rate = rate
        if self.engine:
            self.engine.speed = rate

    def play(self):
        if self.engine and self._prepared and self._status != QMediaPlayer.MediaStatus.InvalidMedia:
            if self._status == QMediaPlayer.MediaStatus.EndOfMedia:
                self.setPosition(0)
            self.engine.pause = False
            self._set_state(QMediaPlayer.PlaybackState.PlayingState)

    def pause(self):
        if self.engine:
            self.engine.pause = True
            self._set_state(QMediaPlayer.PlaybackState.PausedState)

    def stop(self):
        self.generation += 1
        self._prepared = False
        if self.engine:
            self.engine.command("stop")
            self.engine.lavfi_complex = ""
        self._set_state(QMediaPlayer.PlaybackState.StoppedState)

    def setPosition(self, position):
        if self.engine and self._prepared:
            self._seeking = True
            self.engine.command("seek", position / 1000, "absolute+exact")
            self._position = position
            self.positionChanged.emit(position)
            self._set_status(QMediaPlayer.MediaStatus.LoadedMedia)

    def setVolume(self, volume):
        self._volume = volume
        if self.engine:
            self.engine.volume = volume * 100

    def volume(self):
        return self._volume

    def setMuted(self, muted):
        self._muted = muted
        if self.engine:
            self.engine.mute = muted
        self.mutedChanged.emit(muted)

    def isMuted(self):
        return self._muted

    def frame_image(self):
        if not self.engine or not self._prepared:
            return QImage()
        try:
            shot = self.engine.command("screenshot-raw", "video")
            return QImage(
                shot["data"], shot["w"], shot["h"], shot["stride"], QImage.Format.Format_RGB32
            ).copy()
        except Exception:
            return QImage()

    def shutdown(self):
        self.generation += 1
        engine, self.engine = self.engine, None
        if engine:
            self._lifecycle.submit(engine.terminate).result()
            # Release callbacks capturing this QObject before Qt/Python teardown.
            engine._event_callbacks.clear()
            engine._property_handlers.clear()
        if self._lifecycle:
            self._lifecycle.shutdown()
            self._lifecycle = None
