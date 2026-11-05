"""Non-destructive HDR interpretation and versioned SDR rendering policy."""

import os
import re
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime
from ntpath import basename
from pathlib import Path

HDR_RANGES = (("Automatic", "automatic"), ("File metadata", "metadata"), ("Limited", "limited"), ("Full", "full"))
HDR_MAPPINGS = (("BT.2390", "bt2390"), ("Legacy — Hable", "hable"))
RECIPE_VERSION = "hdr-v2"
BT2390_ERROR = (
    "BT.2390 HDR processing is unavailable. Select Legacy — Hable in Settings → Video "
    "or use FFmpeg with working Vulkan and libplacebo support."
)


_NVIDIA_SUFFIX = re.compile(
    r".*\S +(?P<date>(?:[0-9]{4}\.[0-9]{2}\.[0-9]{2}|[0-9]{2}\.[0-9]{2}\.[0-9]{4}))"
    r" +- +(?P<clock>[0-9]{2}\.[0-9]{2}\.[0-9]{2})\.[0-9]+(?:\.DVR)?(?:_[0-9]+)?\.mp4",
    re.IGNORECASE,
)


def nvidia_filename(source):
    """Recognize supported capture naming conventions, not recording provenance."""
    match = _NVIDIA_SUFFIX.fullmatch(basename(str(source)))
    if not match:
        return False
    date = match["date"]
    pattern = "%Y.%m.%d" if len(date.split(".")[0]) == 4 else "%d.%m.%Y"
    try:
        datetime.strptime(f'{date} {match["clock"]}', pattern + " %H.%M.%S")
    except ValueError:
        return False
    return True


@dataclass(frozen=True)
class ColorPolicy:
    input_range: str = "automatic"
    mapping: str = "bt2390"
    effective_range: str | None = None
    nvidia_override: bool = True

    @classmethod
    def from_settings(cls, settings=None):
        settings = settings or {}
        source_range = settings.get("hdr_input_range", "automatic")
        mapping = settings.get("hdr_sdr_mapping", "bt2390")
        return cls(
            source_range if source_range in tuple(value for _, value in HDR_RANGES) else "automatic",
            mapping if mapping in tuple(value for _, value in HDR_MAPPINGS) else "bt2390",
            nvidia_override=settings.get("nvidia_hdr_override", True) is not False,
        )

    def for_source(self, source):
        """Freeze filename interpretation; HDR transfer detection gates its application."""
        if self.input_range != "automatic" or self.effective_range is not None:
            return self
        return replace(self, effective_range=(
            "limited" if self.nvidia_override and nvidia_filename(source) else "metadata"
        ))

    @property
    def source_range(self):
        return self.effective_range or ("metadata" if self.input_range == "automatic" else self.input_range)

    @property
    def signature(self):
        return f"{RECIPE_VERSION}:{self.input_range}:{self.source_range}:{self.mapping}"

    @property
    def summary(self):
        source_range = dict((value, label) for label, value in HDR_RANGES)[self.source_range]
        if self.input_range == "automatic" and self.source_range == "limited":
            source_range += " · NVIDIA filename"
        mapping = dict((value, label) for label, value in HDR_MAPPINGS)[self.mapping]
        return f"HDR → SDR: {mapping} · Input range: {source_range}"

    def device_arguments(self):
        return (["-init_hw_device", "vulkan=dfsorter", "-filter_hw_device", "dfsorter"]
                if self.mapping == "bt2390" else [])

    def sdr_filter(self):
        source_range = f"setparams=range={self.source_range}," if self.source_range != "metadata" else ""
        if self.mapping == "hable":
            return (
                source_range + "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
                "tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p"
            )
        return (
            source_range + "format=yuv420p10le,hwupload,"
            "libplacebo=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv:"
            "format=yuv420p:tonemapping=bt.2390:gamut_mode=perceptual:peak_detect=1:"
            "smoothing_period=100:scene_threshold_low=5.5:scene_threshold_high=10:"
            "percentile=99.995:contrast_recovery=0.3:contrast_smoothness=3.5:"
            "inverse_tonemapping=0:deband=0:dithering=blue:dither_temporal=0,"
            "hwdownload,format=yuv420p"
        )

    def playback_filter(self, hdr):
        if not hdr or self.source_range == "metadata":
            return ""
        return f"format=colorlevels={self.source_range}"


_capabilities = {}
_capability_lock = threading.Lock()


def require_bt2390(executable, cancelled=lambda: False):
    """Exercise the actual shader path once per FFmpeg identity, off the UI thread."""
    path = Path(executable).resolve()
    stat = path.stat()
    key = (str(path), stat.st_size, stat.st_mtime_ns, RECIPE_VERSION)
    while not _capability_lock.acquire(timeout=0.1):
        if cancelled():
            raise InterruptedError("HDR processing cancelled")
    try:
        if cancelled():
            raise InterruptedError("HDR processing cancelled")
        if key in _capabilities:
            if _capabilities[key]:
                raise OSError(_capabilities[key])
            return
        policy = ColorPolicy()
        arguments = [
            str(path), "-hide_banner", "-loglevel", "error", "-nostdin",
            *policy.device_arguments(), "-f", "lavfi", "-i", "color=s=64x36:r=1:d=1",
            "-vf", "format=yuv420p10le,setparams=color_primaries=bt2020:"
            "color_trc=smpte2084:colorspace=bt2020nc," + policy.sdr_filter(),
            "-frames:v", "1", "-an", "-f", "null", "-",
        ]
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(
                arguments, stdout=subprocess.DEVNULL, stderr=errors,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            try:
                deadline = time.monotonic() + 15
                while process.poll() is None:
                    if cancelled():
                        raise InterruptedError("HDR processing cancelled")
                    if time.monotonic() >= deadline:
                        _capabilities[key] = BT2390_ERROR + " Capability check timed out."
                        raise OSError(_capabilities[key])
                    try:
                        process.wait(timeout=0.1)
                    except subprocess.TimeoutExpired:
                        pass
                errors.seek(0)
                detail = errors.read().decode("utf-8", "replace").strip()[-1200:]
                _capabilities[key] = (
                    BT2390_ERROR + (f"\n{detail}" if detail else "")
                    if process.returncode else ""
                )
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
        if _capabilities[key]:
            raise OSError(_capabilities[key])
    except InterruptedError:
        raise
    except OSError as error:
        if str(error).startswith(BT2390_ERROR):
            raise
        raise OSError(f"{BT2390_ERROR}\n{error}") from error
    finally:
        _capability_lock.release()
