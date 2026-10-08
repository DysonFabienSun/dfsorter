import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

import pytest

from dfsorter.output import share_clip
from dfsorter.share_profiles import frame_rate
from dfsorter.sharing import probe


@pytest.mark.parametrize("size,rate,expected_size,expected_rate,software", [
    ("2560x1440", "60", (1920, 1080), "60", False),
    ("1440x2560", "30000/1001", (1080, 1920), "30000/1001", False),
    ("640x360", "60000/1001", (640, 360), "60000/1001", False),
    ("320x180", "120", (320, 180), "60", False),
    ("320x180", "120000/1001", (320, 180), "60000/1001", True),
])
def test_web_share_resolution_rate_and_encoding(
    tmp_path, registry, monkeypatch, size, rate, expected_size, expected_rate, software,
):
    from dfsorter import sharing

    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg required")
    source = tmp_path / "source.mp4"
    subprocess.run([
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={rate}",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
        "-t", "1", "-c:v", "libx264", "-preset", "ultrafast", "-threads", "2",
        "-c:a", "aac", str(source),
    ], check=True, capture_output=True)
    before = source.stat()
    original = sharing.run_process
    commands = []

    def run(arguments, *args, **kwargs):
        if "-c:v" in arguments:
            commands.append(arguments)
            if software and "h264_nvenc" in arguments:
                raise OSError("GPU unavailable")
        return original(arguments, *args, **kwargs)

    monkeypatch.setattr(sharing, "run_process", run)
    result = share_clip(
        {"source_path": str(source)}, registry, tmp_path / "shares", [],
        custom="web", quality="web_1080p",
    )
    info = probe(result)
    video = next(stream for stream in info["streams"] if stream["codec_type"] == "video")
    audio = next(stream for stream in info["streams"] if stream["codec_type"] == "audio")
    assert (video["width"], video["height"]) == expected_size
    assert video["codec_name"] == "h264" and video["profile"] == "High"
    assert video["pix_fmt"] == "yuv420p"
    assert frame_rate(video) == Fraction(expected_rate)
    assert audio["codec_name"] == "aac" and audio["channels"] == 2
    assert audio["sample_rate"] == "48000"
    assert abs(float(info["format"]["duration"]) - float(probe(source)["format"]["duration"])) < 0.1
    bitrate, peak = (8, 12) if Fraction(expected_rate) <= 30 else (12, 18)
    for command in commands:
        assert command[command.index("-b:v") + 1] == f"{bitrate}M"
        assert command[command.index("-maxrate") + 1] == f"{peak}M"
        assert command[command.index("-bufsize") + 1] == f"{bitrate * 2}M"
        assert "-cq" not in command and "-crf" not in command
        assert "copy" not in command
    if software:
        assert "libx264" in commands[-1]
    assert (source.stat().st_size, source.stat().st_mtime_ns) == (before.st_size, before.st_mtime_ns)
    assert Path(result).is_file()


def test_web_range_keeps_seeking_and_boundaries(tmp_path, registry, monkeypatch):
    from dfsorter import sharing

    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg required")
    source = tmp_path / "source.mp4"
    subprocess.run([
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24",
        "-t", "4", "-c:v", "libx264", "-g", "48", "-threads", "2", str(source),
    ], check=True, capture_output=True)
    original = sharing.run_process
    commands = []

    def run(arguments, *args, **kwargs):
        if "-c:v" in arguments:
            commands.append(arguments)
        return original(arguments, *args, **kwargs)

    monkeypatch.setattr(sharing, "run_process", run)
    result = share_clip(
        {"source_path": str(source), "in_ms": 2375, "out_ms": 3375}, registry,
        tmp_path / "shares", [], custom="web-range", selected_range=True, quality="web_1080p",
    )
    command = commands[-1]
    assert command.index("-ss") < command.index("-i")
    assert command[command.index("-ss") + 1] == "2.375"
    assert abs(float(probe(result)["format"]["duration"]) - 1) < 0.1

    def frames(path):
        raw = subprocess.check_output([
            "ffmpeg", "-v", "error", "-i", str(path), "-vf", "scale=32:18,format=gray",
            "-fps_mode", "passthrough", "-f", "rawvideo", "-",
        ])
        return [raw[index:index + 576] for index in range(0, len(raw), 576)]

    expected, actual = frames(source), frames(result)
    assert len(actual) == 24
    for output, index in ((actual[0], 57), (actual[-1], 80)):
        assert sum(abs(a - b) for a, b in zip(output, expected[index])) / 576 < 4


def test_web_rotated_anamorphic_source_does_not_upscale(tmp_path, registry):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg required")
    original, source = tmp_path / "original.mp4", tmp_path / "rotated.mp4"
    subprocess.run([
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24",
        "-t", "1", "-vf", "setsar=2", "-c:v", "libx264", "-threads", "2", str(original),
    ], check=True, capture_output=True)
    subprocess.run([
        "ffmpeg", "-v", "error", "-display_rotation:v:0", "90", "-i", str(original),
        "-c", "copy", str(source),
    ], check=True, capture_output=True)
    result = share_clip(
        {"source_path": str(source)}, registry, tmp_path / "shares", [],
        custom="rotated", quality="web_1080p",
    )
    video = probe(result)["streams"][0]
    assert (video["width"], video["height"]) == (90, 320)
    assert video["sample_aspect_ratio"] == "1:1"
