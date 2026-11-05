import hashlib
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from dfsorter import color, sharing
from dfsorter.color import BT2390_ERROR, ColorPolicy, nvidia_filename, require_bt2390
from dfsorter.sharing import encode_share, probe
from dfsorter.thumbnails import ThumbnailCache


def test_color_preferences_defaults_and_invalid_values():
    assert ColorPolicy.from_settings() == ColorPolicy("automatic", "bt2390")
    assert ColorPolicy.from_settings({"hdr_input_range": "wrong", "hdr_sdr_mapping": None}) == ColorPolicy()
    assert ColorPolicy.from_settings({"hdr_input_range": [], "hdr_sdr_mapping": {}}) == ColorPolicy()
    selected = ColorPolicy.from_settings({"hdr_input_range": "limited", "hdr_sdr_mapping": "hable"})
    assert selected == ColorPolicy("limited", "hable")
    assert selected.playback_filter(False) == ""
    assert selected.playback_filter(True) == "format=colorlevels=limited"
    assert ColorPolicy().playback_filter(True) == ""


@pytest.mark.parametrize("mapping", ["bt2390", "hable"])
@pytest.mark.parametrize("transfer", ["smpte2084", "arib-std-b67"])
def test_range_override_matches_correctly_tagged_hdr(tmp_path, mapping, monkeypatch, transfer):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg required")
    if mapping == "bt2390":
        require_bt2390(ffmpeg)
    reference, mislabeled = tmp_path / "reference.mp4", tmp_path / "游戏  2026.11.06 - 12.34.56.123.DVR.mp4"
    subprocess.run([
        ffmpeg, "-v", "error", "-f", "lavfi", "-i",
        "nullsrc=s=96x54:r=12,format=yuv420p10le,"
        "geq=lum='if(lt(X,W/3),64,if(lt(X,2*W/3),500,700))':cb=512:cr=512",
        "-t", "0.5", "-c:v", "libx265", "-threads", "2", "-x265-params",
        f"pools=2:lossless=1:log-level=error:colorprim=bt2020:transfer={transfer}:colormatrix=bt2020nc:range=limited",
        "-color_range", "tv", str(reference),
    ], check=True, capture_output=True)
    subprocess.run([
        ffmpeg, "-v", "error", "-i", str(reference), "-c", "copy", "-bsf:v",
        "hevc_metadata=video_full_range_flag=1", "-color_range", "pc", str(mislabeled),
    ], check=True, capture_output=True)
    before = hashlib.sha256(mislabeled.read_bytes()).digest()

    def share(source, name, policy):
        return encode_share(
            {"source_path": str(source)}, tmp_path / name, name, False,
            lambda: False, lambda message: None, color_policy=policy,
        )

    correctly_tagged = share(reference, "reference", ColorPolicy("metadata", mapping))
    corrected = share(mislabeled, "corrected", ColorPolicy("automatic", mapping))
    wrong = share(mislabeled, "wrong", ColorPolicy("metadata", mapping))
    explicit_full = share(mislabeled, "full", ColorPolicy("full", mapping))

    def pixels(path):
        return subprocess.check_output([
            ffmpeg, "-v", "error", "-i", str(path), "-frames:v", "1",
            "-pix_fmt", "rgb24", "-f", "rawvideo", "-",
        ])

    actual, expected, incorrect = pixels(corrected), pixels(correctly_tagged), pixels(wrong)
    assert sum(abs(a-b) for a, b in zip(actual, expected)) / len(actual) < 1
    assert sum(abs(a-b) for a, b in zip(actual, incorrect)) / len(actual) > 3
    assert pixels(explicit_full) == incorrect
    assert max(actual[:24*3]) < 4  # Known nominal-black patch stays black.
    video = probe(corrected)["streams"][0]
    assert (video["color_range"], video["color_transfer"], video["color_primaries"], video["color_space"]) == (
        "tv", "bt709", "bt709", "bt709"
    )
    assert hashlib.sha256(mislabeled.read_bytes()).digest() == before
    if mapping == "bt2390":
        original = sharing.run_process
        attempts = []

        def software_only(arguments, *args, **kwargs):
            if "-filter_complex" in arguments:
                attempts.append(arguments)
                if "h264_nvenc" in arguments:
                    raise OSError("NVIDIA encoder unavailable")
            return original(arguments, *args, **kwargs)

        monkeypatch.setattr(sharing, "run_process", software_only)
        fallback = share(mislabeled, "software", ColorPolicy("limited", mapping))
        assert len(attempts) == 2 and "libx264" in attempts[-1]
        assert sum(abs(a-b) for a, b in zip(pixels(fallback), expected)) / len(expected) < 3


def test_bt2390_failure_does_not_fallback_or_publish(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"original")
    monkeypatch.setattr(sharing, "probe", lambda *args: {
        "streams": [{"codec_type": "video", "codec_name": "hevc", "color_transfer": "smpte2084"}],
        "format": {"duration": "1"},
    })
    monkeypatch.setattr(sharing, "require_bt2390", lambda *args: (_ for _ in ()).throw(OSError(BT2390_ERROR)))
    monkeypatch.setattr(sharing, "run_process", lambda *args, **kwargs: pytest.fail("Unexpected encoder fallback"))
    with pytest.raises(OSError, match="Select Legacy"):
        encode_share({"source_path": str(source)}, tmp_path / "shares", "sample", False,
                     lambda: False, lambda message: None)
    assert not (tmp_path / "shares").exists()
    assert source.read_bytes() == b"original"


def test_bt2390_runtime_failure_cleans_output_without_legacy_retry(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"original")
    monkeypatch.setattr(sharing, "probe", lambda *args: {
        "streams": [{"codec_type": "video", "codec_name": "hevc", "color_transfer": "smpte2084", "index": 0}],
        "format": {"duration": "1"},
    })
    monkeypatch.setattr(sharing, "require_bt2390", lambda *args: None)
    calls = []

    def device_lost(arguments, *args, **kwargs):
        calls.append(arguments)
        Path(arguments[-1]).write_bytes(b"partial")
        raise OSError("libplacebo: Vulkan device lost")

    monkeypatch.setattr(sharing, "run_process", device_lost)
    with pytest.raises(OSError, match="Select Legacy"):
        encode_share({"source_path": str(source)}, tmp_path / "shares", "sample", False,
                     lambda: False, lambda message: None)
    assert len(calls) == 1
    assert not list((tmp_path / "shares").iterdir())
    assert source.read_bytes() == b"original"


def test_hdr_thumbnail_keys_follow_policy_only_for_hdr(tmp_path):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"original")
    settings = {}
    cache = ThumbnailCache(tmp_path, settings=settings)
    clip = {"source_path": str(source), "clip_id": "one"}
    try:
        sdr, hdr = cache.signature(clip), cache.signature({**clip, "hdr": True})
        settings.update(hdr_input_range="limited", hdr_sdr_mapping="hable")
        assert cache.signature(clip) == sdr
        assert cache.signature({**clip, "hdr": True}) != hdr
    finally:
        cache.close()


def test_capability_check_respects_cancellation():
    with pytest.raises(InterruptedError):
        require_bt2390(shutil.which("ffmpeg"), lambda: True)


@pytest.mark.parametrize("reason", ["cancel", "timeout"])
def test_capability_check_terminates_child_on_cancel_or_timeout(tmp_path, monkeypatch, reason):
    executable = tmp_path / "ffmpeg.exe"
    executable.write_bytes(b"fake")
    processes = []

    class RunningProcess:
        killed = False
        reaped = False

        def __init__(self, *args, **kwargs):
            processes.append(self)

        def poll(self):
            return -9 if self.killed else None

        def kill(self):
            self.killed = True

        def wait(self, timeout=None):
            if not self.killed:
                raise subprocess.TimeoutExpired("ffmpeg", timeout)
            self.reaped = True
            return -9

    monkeypatch.setattr(color.subprocess, "Popen", RunningProcess)
    if reason == "timeout":
        monkeypatch.setattr(color, "time", SimpleNamespace(monotonic=iter([0, 16]).__next__))
        with pytest.raises(OSError, match="timed out"):
            require_bt2390(executable)
        with pytest.raises(OSError, match="timed out"):
            require_bt2390(executable)
        assert len(processes) == 1  # Cache the failed runtime identity.
    else:
        with pytest.raises(InterruptedError):
            require_bt2390(executable, lambda: bool(processes))
    assert processes[0].killed and processes[0].reaped


@pytest.mark.parametrize("name", [
    "Game 2026.11.06 - 23.59.59.0.DVR.mp4",
    "Game 2026.11.06 - 00.00.00.123456.mp4",
    r"C:\unrelated\游戏  标题  2024.02.29 - 12.34.56.001.dVr.MP4",
    "Title 06.11.2017 - 12.34.56.42.DVR_2.mp4",
    "Title 06.11.2017 - 12.34.56.42_123.mp4",
])
def test_nvidia_supported_filename_conventions(name):
    assert nvidia_filename(name)
    policy = ColorPolicy().for_source(name)
    assert policy.input_range == "automatic" and policy.source_range == "limited"
    assert "Input range: Limited · NVIDIA filename" in policy.summary
    assert policy.playback_filter(True) == "format=colorlevels=limited"
    assert policy.playback_filter(False) == ""
    assert policy.for_source("renamed.mp4") is policy  # Resolved snapshots stay frozen.


@pytest.mark.parametrize("name", [
    "renamed.mp4", "Game.DVR.mp4", "  2026.11.06 - 12.34.56.1.mp4", "2026.11.06 - 12.34.56.1.mp4",
    "Game 2026.02.29 - 12.34.56.1.mp4", "Game 2026.13.01 - 12.34.56.1.mp4",
    "Game 2026.11.06 - 24.00.00.1.mp4", "Game 2026.11.06 - 12.60.00.1.mp4",
    "Game 2026.11.06 - 12.34.60.1.mp4", "Game 2026.11.06 - 1.34.56.1.mp4",
    "Game 2026.1.06 - 12.34.56.1.mp4", "Game 2026.11.06 - 12.34.56.mp4",
    "Game 2026.11.06 - 12.34.56.1.DVR notes.mp4",
    "Game 2026.11.06 - 12.34.56.1.DVR.mp4.bak",
    "Game 2026.11.06 - 12.34.56.1.DVR_x.mp4",
    r"Game 2026.11.06 - 12.34.56.1.DVR.mp4\renamed.mp4",
])
def test_nvidia_rejects_invalid_or_unrelated_names(name):
    assert not nvidia_filename(name)
    assert ColorPolicy().for_source(name).source_range == "metadata"


@pytest.mark.parametrize("choice", ["metadata", "limited", "full"])
def test_explicit_range_bypasses_filename_automation(choice):
    policy = ColorPolicy.from_settings({"hdr_input_range": choice})
    assert policy.input_range == choice
    assert policy.for_source("Game 2026.11.06 - 12.34.56.1.mp4") is policy
    assert "NVIDIA filename" not in policy.summary


@pytest.mark.parametrize("enabled", [True, False, None, "invalid"])
def test_nvidia_override_controls_only_automatic_and_freezes_resolution(tmp_path, enabled):
    source = tmp_path / "Game 2026.11.06 - 12.34.56.1.mp4"
    source.write_bytes(b"video")
    settings = {"nvidia_hdr_override": enabled}
    policy = ColorPolicy.from_settings(settings).for_source(source)
    assert policy.source_range == ("metadata" if enabled is False else "limited")
    settings["nvidia_hdr_override"] = not policy.nvidia_override
    assert policy.for_source(source) is policy
    for choice in ("metadata", "limited", "full"):
        explicit = ColorPolicy.from_settings({"hdr_input_range": choice, "nvidia_hdr_override": enabled})
        assert explicit.for_source(source).source_range == choice
    cache = ThumbnailCache(tmp_path, settings=settings)
    clip = {"clip_id": "one", "source_path": str(source), "hdr": True}
    try:
        hdr_key = cache.signature(clip)
        sdr_key = cache.signature({**clip, "hdr": False})
        settings["nvidia_hdr_override"] = policy.nvidia_override
        assert cache.signature(clip) != hdr_key
        assert cache.signature({**clip, "hdr": False}) == sdr_key
    finally:
        cache.close()
