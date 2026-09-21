import array
import hashlib
import math
import shutil
import subprocess
import wave
from pathlib import Path

import pytest

from dfsorter.mpv_backend import audio_mix_graph, display_size, load_mpv
from dfsorter.output import copy_one


@pytest.mark.parametrize(
    ("parameters", "expected"),
    [
        ({"dw": 1920, "dh": 1080}, (1920, 1080)),
        ({"dw": 1080.0, "dh": 1920.0}, (1080, 1920)),
        ({"w": 1920, "h": 1080}, (0, 0)),
        (None, (0, 0)),
    ],
)
def test_display_size_uses_display_corrected_dimensions(parameters, expected):
    assert display_size(parameters) == expected


@pytest.mark.parametrize("tracks", [1, 2, 3])
def test_live_mix_preserves_stereo_and_track_timing(tmp_path, tracks):
    """Decode libmpv's actual mix to PCM; distinct tones identify each channel/track."""
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg required")
    source = tmp_path / "multitrack.mp4"
    tones = [
        "aevalsrc=0.1*sin(2*PI*400*t)|0.1*sin(2*PI*600*t):s=48000:d=2",
        "aevalsrc=0.1*sin(2*PI*800*t):s=48000:d=2",
        "aevalsrc=0.1*sin(2*PI*1000*t)|0.1*sin(2*PI*1200*t):s=48000:d=1.5",
    ]
    command = ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=s=64x64:r=24:d=2"]
    for index, tone in enumerate(tones[:tracks]):
        if index == 2:
            command += ["-itsoffset", "0.5"]
        command += ["-f", "lavfi", "-i", tone]
    command += ["-map", "0:v"]
    for index in range(tracks):
        command += ["-map", f"{index + 1}:a"]
    command += ["-c:v", "libx264", "-c:a", "aac", "-t", "2", str(source)]
    subprocess.run(command, check=True, capture_output=True)
    before = hashlib.sha256(source.read_bytes()).digest()
    output = tmp_path / "mixed.wav"
    mpv = load_mpv()
    engine = mpv.MPV(
        config=False,
        vo="null",
        video=False,
        ao="pcm",
        ao_pcm_file=str(output),
        audio_channels="stereo",
        audio_samplerate=48000,
        audio_format="s16",
        load_scripts=False,
        osc=False,
        ytdl=False,
        load_stats_overlay=False,
        load_console=False,
        load_osd_console=False,
        load_auto_profiles=False,
        load_select=False,
        load_positioning=False,
        load_commands=False,
        lavfi_complex=audio_mix_graph(list(range(1, tracks + 1))),
    )
    try:
        engine.play(str(source))
        engine.wait_for_playback(timeout=10)
    finally:
        engine.terminate()
    with wave.open(str(output)) as audio:
        assert audio.getnchannels() == 2
        assert audio.getsampwidth() == 2
        rate = audio.getframerate()
        samples = array.array("h", audio.readframes(audio.getnframes()))

    def amplitude(channel, frequency, start=0.8, end=1.2):
        values = samples[round(start * rate) * 2 + channel : round(end * rate) * 2 : 2]
        real = sum(
            value * math.cos(2 * math.pi * frequency * n / rate) for n, value in enumerate(values)
        )
        imag = sum(
            value * math.sin(2 * math.pi * frequency * n / rate) for n, value in enumerate(values)
        )
        return math.hypot(real, imag) / len(values)

    assert amplitude(0, 400) > 100
    assert amplitude(1, 600) > 100
    assert amplitude(1, 400) < amplitude(0, 400) * 0.03
    assert amplitude(0, 600) < amplitude(1, 600) * 0.03
    if tracks >= 2:
        assert amplitude(0, 800) > 100
        assert amplitude(1, 800) == pytest.approx(amplitude(0, 800), rel=0.05)
    if tracks == 3:
        assert amplitude(0, 1000) > 100
        assert amplitude(1, 1200) > 100
        assert amplitude(1, 1000) < amplitude(0, 1000) * 0.03
        assert amplitude(0, 1200) < amplitude(1, 1200) * 0.03
        assert amplitude(0, 1000, 0.1, 0.3) < 10
    copied = Path(copy_one({"source_path": str(source)}, tmp_path / "export", "original"))
    assert hashlib.sha256(copied.read_bytes()).digest() == before
    assert hashlib.sha256(source.read_bytes()).digest() == before
