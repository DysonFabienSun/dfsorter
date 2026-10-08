"""Content checks for seeking past multiple keyframes before a Share cut."""

import array
import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

from dfsorter.sharing import encode_share, probe


def ffmpeg(*arguments):
    return subprocess.check_output(["ffmpeg", "-v", "error", *map(str, arguments)])


def frame_times(path):
    data = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_frames",
        "-show_entries", "frame=best_effort_timestamp_time", "-of", "json", str(path),
    ]))
    origin = float(probe(path)["format"].get("start_time", 0))
    return [float(frame["best_effort_timestamp_time"]) - origin for frame in data["frames"]]


def frames(path):
    raw = ffmpeg(
        "-i", path, "-map", "0:v:0", "-vf", "scale=32:18,format=gray",
        "-fps_mode", "passthrough", "-f", "rawvideo", "-",
    )
    return [raw[index:index + 576] for index in range(0, len(raw), 576)]


@pytest.mark.parametrize("codec,offset,audio,vfr", [
    ("libx264", 0, True, False),
    ("libx264", 5, True, False),
    ("libaom-av1", 0, True, False),
    ("libx264", 0, False, True),
])
def test_late_range_preserves_frames_audio_and_timing(tmp_path, codec, offset, audio, vfr):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg required")
    source = tmp_path / "source.mp4"
    args = ["-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24:duration=12"]
    if audio:
        args += [
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=12",
            "-itsoffset", "9.2", "-f", "lavfi", "-i",
            "sine=frequency=660:sample_rate=48000:duration=2.8",
        ]
    args += ["-map", "0:v:0"]
    if audio:
        args += ["-map", "1:a:0", "-map", "2:a:0", "-c:a", "aac"]
    if vfr:
        args += ["-vf", "select='if(between(t,9,10),not(mod(n,2)),1)'", "-fps_mode", "vfr"]
    args += ["-c:v", codec, "-g", "48", "-threads", "2"]
    if codec == "libaom-av1":
        args += ["-cpu-used", "8"]
    ffmpeg(*args, "-output_ts_offset", offset, source)

    start, end = 8.375, 10.375
    updates = []
    target = encode_share(
        {"source_path": str(source), "in_ms": 8375, "out_ms": 10375},
        tmp_path, "result", True, lambda: False, lambda text: None,
        detailed_progress=lambda percent, phase: updates.append((percent, phase)),
    )
    assert updates[:2] == [(-1, "Inspecting source…"), (-1, "Starting encoding…")]
    assert (90, "Validating output") in updates
    assert abs(float(probe(target)["format"]["duration"]) - (end - start)) < 0.1
    times = frame_times(source)
    selected = [index for index, value in enumerate(times) if start <= value < end]
    original, actual = frames(source), frames(target)
    assert len(actual) == len(selected)
    for position in (0, len(actual) - 1):
        expected = original[selected[position]]
        assert sum(abs(a - b) for a, b in zip(actual[position], expected)) / 576 < 4
    assert frame_times(target) == pytest.approx(
        [times[index] - times[selected[0]] for index in selected], abs=0.001
    )

    if audio:
        info = probe(source)
        origin = float(info["format"].get("start_time", 0))
        streams = [stream for stream in info["streams"] if stream["codec_type"] == "audio"]
        filters = []
        for index, stream in enumerate(streams):
            delay = float(stream.get("start_time", origin)) - origin
            filters.append(
                f"[0:{stream['index']}]asetpts=PTS-STARTPTS+{delay}/TB,"
                f"aresample=48000:async=1:first_pts=0,aformat=channel_layouts=stereo[a{index}]"
            )
        filters.append(
            f"[a0][a1]amix=inputs=2:duration=longest:dropout_transition=0:normalize=1,"
            f"atrim=start={start}:end={end},asetpts=PTS-STARTPTS[out]"
        )
        # Full decoding is the oracle, including the delayed second track's
        # silence and onset. Compare PCM samples, not merely stream metadata.
        expected = array.array("f", ffmpeg(
            "-i", source, "-filter_complex", ";".join(filters), "-map", "[out]",
            "-f", "f32le", "-",
        ))
        actual = array.array("f", ffmpeg(
            "-i", target, "-map", "0:a", "-ar", "48000", "-ac", "2", "-f", "f32le", "-",
        ))
        assert len(actual) >= len(expected) - 2
        error = math.sqrt(sum((a - b) ** 2 for a, b in zip(actual, expected)) / len(expected))
        assert error < 0.006
    else:
        assert not any(stream["codec_type"] == "audio" for stream in probe(target)["streams"])


def test_startup_progress_fallback_and_cancellation(tmp_path, monkeypatch):
    from dfsorter import sharing

    source = tmp_path / "source.mp4"
    source.touch()
    monkeypatch.setattr(sharing, "tool", lambda name: name)
    monkeypatch.setattr(sharing, "probe", lambda *args: {
        "streams": [{"codec_type": "video", "codec_name": "h264", "index": 0}],
        "format": {"duration": "120"},
    })
    updates = []

    def run(arguments, cancelled, *, progress_file, progress):
        assert updates[-1][0] == -1
        progress(0)
        assert updates[-1][0] == -1
        if "h264_nvenc" in arguments:
            progress(1)
            raise OSError("GPU unavailable")
        assert updates[-1] == (-1, "Retrying with software encoding…")
        progress(0.001)
        assert updates[-1][0] == 0  # A real output timestamp below 1%.
        Path(arguments[-1]).write_bytes(b"partial output")
        raise InterruptedError("Share cancelled")

    monkeypatch.setattr(sharing, "run_process", run)
    with pytest.raises(InterruptedError):
        encode_share(
            {"source_path": str(source), "in_ms": 100000, "out_ms": 110000},
            tmp_path, "cancelled", True, lambda: False, lambda text: None,
            detailed_progress=lambda percent, phase: updates.append((percent, phase)),
        )
    assert updates[0] == (-1, "Inspecting source…")
    assert not list(tmp_path.glob(".dfsorter*"))
    assert not (tmp_path / "cancelled.mp4").exists()
