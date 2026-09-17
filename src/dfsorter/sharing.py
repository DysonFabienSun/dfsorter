import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def run_process(arguments, cancelled=lambda: False):
    if cancelled():
        raise InterruptedError("Share cancelled")
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(
            arguments,
            stdout=output,
            stderr=errors,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            while True:
                if cancelled():
                    raise InterruptedError("Share cancelled")
                try:
                    process.wait(timeout=0.1)
                    break
                except subprocess.TimeoutExpired:
                    continue
            errors.seek(0)
            if process.returncode:
                raise OSError(
                    errors.read().decode("utf-8", "replace")[-4000:] or "Media processing failed"
                )
            output.seek(0)
            return output.read()
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()


def probe(path, cancelled=lambda: False):
    executable = shutil.which("ffprobe")
    if not executable:
        raise ValueError("Share requires ffprobe on PATH")
    return json.loads(
        run_process(
            [executable, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
            cancelled,
        )
    )


def encode_share(clip, destination, stem, selected_range, cancelled, progress):
    executable = shutil.which("ffmpeg")
    if not executable:
        raise ValueError("Share requires ffmpeg on PATH")
    source = Path(clip["source_path"])
    before = source.stat()
    info = probe(source, cancelled)
    videos = [stream for stream in info["streams"] if stream["codec_type"] == "video"]
    audio = [stream for stream in info["streams"] if stream["codec_type"] == "audio"]
    if not videos:
        raise ValueError("Source has no video stream")
    duration = float(info["format"]["duration"])
    start, end = 0.0, duration
    if selected_range:
        if clip["in_ms"] is None or clip["out_ms"] is None:
            raise ValueError("A saved valid In/Out range is required")
        start, end = clip["in_ms"] / 1000, clip["out_ms"] / 1000
        if not 0 <= start < end <= duration + 0.001:
            raise ValueError("Saved range is outside the source duration")
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".dfsorter-share-", dir=destination) as directory:
        temporary = Path(directory) / "share.mp4"
        filters = []
        origin = float(info["format"].get("start_time", 0))
        for position, stream in enumerate(audio):
            offset = float(stream.get("start_time", origin)) - origin
            filters.append(
                f"[0:{stream['index']}]asetpts=PTS-STARTPTS+{offset}/TB,aresample=48000:async=1:first_pts=0,aformat=channel_layouts=stereo[a{position}]"
            )
        if audio:
            inputs = "".join(f"[a{position}]" for position in range(len(audio)))
            filters.append(
                f"{inputs}amix=inputs={len(audio)}:duration=longest:dropout_transition=0:normalize=1,apad,atrim=start={start}:end={end},asetpts=PTS-STARTPTS[mixed]"
            )
        reencode = selected_range or videos[0]["codec_name"] != "h264"
        if reencode:
            filters.append(
                f"[0:{videos[0]['index']}]setpts=PTS-STARTPTS,trim=start={start}:end={end},setpts=PTS-STARTPTS,format=yuv420p[video]"
            )
        arguments = [
            executable,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-i",
            str(source),
        ]
        if filters:
            arguments += ["-filter_complex", ";".join(filters)]
        arguments += ["-map", "[video]" if reencode else f"0:{videos[0]['index']}"]
        if audio:
            arguments += ["-map", "[mixed]", "-c:a", "aac", "-b:a", "192k"]
        encoders = [["-c:v", "copy"]]
        if reencode:
            encoders = [
                ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "19", "-b:v", "0"],
                ["-c:v", "libx264", "-preset", "medium", "-crf", "18"],
            ]
        for attempt, encoder in enumerate(encoders):
            progress(f"Sharing {source.name}: {encoder[1]} · {end - start:.2f} seconds")
            try:
                run_process(
                    arguments
                    + encoder
                    + [
                        "-fps_mode",
                        "passthrough",
                        "-t",
                        str(end - start),
                        "-movflags",
                        "+faststart",
                        str(temporary),
                    ],
                    cancelled,
                )
                break
            except InterruptedError:
                raise
            except OSError:
                if attempt == len(encoders) - 1:
                    raise
                logging.warning(
                    "NVIDIA Share encoding unavailable; retrying with x264", exc_info=True
                )
                progress("NVIDIA encoding unavailable; retrying with software encoding")
        result = probe(temporary, cancelled)
        output_video = [stream for stream in result["streams"] if stream["codec_type"] == "video"]
        output_audio = [stream for stream in result["streams"] if stream["codec_type"] == "audio"]
        if (
            not output_video
            or output_video[0]["codec_name"] != "h264"
            or len(output_audio) != bool(audio)
        ):
            raise OSError("Share output failed codec/stream validation")
        if any(stream["codec_name"] != "aac" or stream["channels"] != 2 for stream in output_audio):
            raise OSError("Share output failed audio validation")
        if abs(float(result["format"]["duration"]) - (end - start)) > 0.15:
            raise OSError("Share output failed duration validation")
        after = source.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise OSError("Source changed during sharing")
        suffix = 0
        while True:
            target = destination / f"{stem}{f' ({suffix})' if suffix else ''}.mp4"
            if target.exists():
                suffix += 1
                continue
            try:
                output = target.open("xb")
            except FileExistsError:
                suffix += 1
                continue
            try:
                with output, temporary.open("rb") as input_file:
                    while chunk := input_file.read(1024 * 1024):
                        if cancelled():
                            raise InterruptedError("Share cancelled")
                        output.write(chunk)
                return str(target)
            except BaseException:
                output.close()
                target.unlink(missing_ok=True)
                raise
