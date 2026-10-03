import array
import hashlib
import math
import shutil
import subprocess
from pathlib import Path

import pytest

from dfsorter.output import share_clip
from dfsorter.sharing import probe


@pytest.mark.parametrize("transfer", ["smpte2084", "arib-std-b67"])
@pytest.mark.parametrize("selected_range", [False, True])
@pytest.mark.parametrize("codec", ["libx265", "libx264"])
def test_hdr_share_is_sdr(tmp_path, registry, transfer, selected_range, codec):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg required")
    source = tmp_path / "hdr.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=64x36:rate=12",
         "-t", "1", "-vf", "format=yuv420p10le", "-c:v", codec, "-threads", "2",
         *(["-x265-params", f"pools=2:log-level=error:colorprim=bt2020:transfer={transfer}:colormatrix=bt2020nc"]
           if codec == "libx265" else ["-x264-params", f"colorprim=bt2020:transfer={transfer}:colormatrix=bt2020nc"]),
         "-y", str(source)],
        check=True, capture_output=True,
    )
    clip = {"source_path": str(source), "in_ms": 250, "out_ms": 750}
    target = share_clip(
        clip, registry, tmp_path / "shares", [], custom="sample", selected_range=selected_range
    )
    video = next(stream for stream in probe(target)["streams"] if stream["codec_type"] == "video")
    assert (video["color_primaries"], video["color_transfer"], video["color_space"]) == (
        "bt709", "bt709", "bt709"
    )
    assert subprocess.check_output(
        ["ffmpeg", "-v", "error", "-i", target, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    )


@pytest.mark.parametrize(
    "codec,audio_count,trim",
    [
        ("libx264", 0, False),
        ("libx264", 1, True),
        ("libx264", 2, False),
        ("libaom-av1", 2, True),
        ("libaom-av1", 1, False),
    ],
)
def test_real_share(tmp_path, registry, codec, audio_count, trim, monkeypatch):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg required")
    source = tmp_path / "source.mp4"
    arguments = ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24"]
    for position in range(audio_count):
        arguments += ["-f", "lavfi", "-i", f"sine=frequency={440 + position * 220}"]
    arguments += ["-map", "0:v"]
    for position in range(audio_count):
        arguments += ["-map", f"{position + 1}:a"]
    arguments += ["-t", "2", "-c:v", codec, "-g", "48", "-threads", "2"]
    if codec == "libaom-av1":
        arguments += ["-cpu-used", "8"]
    subprocess.run(arguments + ["-c:a", "aac", str(source)], check=True, capture_output=True)
    before = hashlib.sha256(source.read_bytes()).digest()
    clip = {"source_path": str(source), "in_ms": 375, "out_ms": 1375}
    destination = tmp_path / "shares"
    result = Path(share_clip(clip, registry, destination, [], custom="sample", selected_range=trim))
    info = probe(result)
    assert info["streams"][0]["codec_name"] == "h264"
    audio = [stream for stream in info["streams"] if stream["codec_type"] == "audio"]
    assert len(audio) == bool(audio_count)
    assert all(stream["codec_name"] == "aac" and stream["channels"] == 2 for stream in audio)
    assert abs(float(info["format"]["duration"]) - (1 if trim else 2)) < 0.1
    assert hashlib.sha256(source.read_bytes()).digest() == before
    if codec == "libx264" and not trim:

        def video_digest(path):
            return subprocess.check_output(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-i",
                    str(path),
                    "-map",
                    "0:v:0",
                    "-c:v",
                    "copy",
                    "-f",
                    "hash",
                    "-",
                ]
            )

        assert video_digest(source) == video_digest(result)
    if audio_count == 2:
        raw_audio = subprocess.check_output(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(result),
                "-map",
                "0:a",
                "-t",
                "0.25",
                "-ar",
                "8000",
                "-ac",
                "1",
                "-f",
                "f32le",
                "-",
            ]
        )
        samples = array.array("f", raw_audio)

        def magnitude(frequency):
            real = sum(
                value * math.cos(2 * math.pi * frequency * position / 8000)
                for position, value in enumerate(samples)
            )
            imaginary = sum(
                value * math.sin(2 * math.pi * frequency * position / 8000)
                for position, value in enumerate(samples)
            )
            return math.hypot(real, imaginary)

        assert magnitude(440) > 5 * magnitude(1000)
        assert magnitude(660) > 5 * magnitude(1000)
    if trim:

        def frames(path):
            raw = subprocess.check_output(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-i",
                    str(path),
                    "-map",
                    "0:v",
                    "-vf",
                    "scale=32:18,format=gray",
                    "-f",
                    "rawvideo",
                    "-",
                ]
            )
            return [raw[position : position + 576] for position in range(0, len(raw), 576)]

        source_frames, output_frames = frames(source), frames(result)
        assert len(output_frames) == 24
        for actual, expected in [
            (output_frames[0], source_frames[9]),
            (output_frames[-1], source_frames[32]),
        ]:
            assert sum(abs(first - second) for first, second in zip(actual, expected)) / 576 < 4
    second = Path(share_clip(clip, registry, destination, [], custom="sample", selected_range=trim))
    assert second.name == "sample (1).mp4"
    with pytest.raises(InterruptedError):
        share_clip(clip, registry, destination, [], custom="cancel", cancelled=lambda: True)
    assert not list(destination.glob("cancel*"))
    assert not list(destination.glob(".dfsorter*"))
    if trim and codec == "libx264":
        from dfsorter import sharing

        original = sharing.run_process
        attempts = []

        def unavailable_gpu(arguments, cancelled=lambda: False):
            attempts.append(arguments)
            if "h264_nvenc" in arguments:
                raise OSError("GPU unavailable")
            return original(arguments, cancelled)

        monkeypatch.setattr(sharing, "run_process", unavailable_gpu)
        fallback = share_clip(
            clip, registry, destination, [], custom="fallback", selected_range=True
        )
        assert Path(fallback).is_file()
        assert any("libx264" in arguments for arguments in attempts)

        def cancel_encoding(arguments, cancelled=lambda: False):
            if "-filter_complex" in arguments:
                Path(arguments[-1]).write_bytes(b"partial")
                raise InterruptedError("Share cancelled")
            return original(arguments, cancelled)

        monkeypatch.setattr(sharing, "run_process", cancel_encoding)
        with pytest.raises(InterruptedError):
            share_clip(clip, registry, destination, [], custom="partial", selected_range=True)
        assert not list(destination.glob("partial*"))
        assert not list(destination.glob(".dfsorter*"))


def test_share_missing_tools(tmp_path, registry, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(ValueError, match="ffmpeg"):
        share_clip({"source_path": "missing"}, registry, tmp_path, [], custom="sample")


def test_share_reports_encoding_and_publication_progress(tmp_path, registry):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg required")
    source = tmp_path / "source.mp4"
    subprocess.run([
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
        "testsrc2=size=320x180:rate=24", "-t", "2", "-c:v", "libx264",
        "-threads", "2", str(source),
    ], check=True, capture_output=True)
    updates = []
    result = share_clip(
        {"source_path": str(source), "in_ms": 0, "out_ms": 1500},
        registry, tmp_path / "shares", [], custom="progress", selected_range=True,
        detailed_progress=lambda percent, phase: updates.append((percent, phase)),
    )
    assert Path(result).is_file()
    assert any(0 < percent < 90 and phase.startswith("Encoding") for percent, phase in updates)
    assert any(phase == "Validating output" for _, phase in updates)
    assert any(phase == "Saving shared clip" for _, phase in updates)
