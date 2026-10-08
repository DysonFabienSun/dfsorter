"""Share quality choices and the bounded 1080p web profile."""

from dataclasses import dataclass
from fractions import Fraction

SHARE_QUALITY_CHOICES = (("Native resolution", "native"), ("Web · 1080p", "web_1080p"))


def share_quality(value):
    return next((key for _, key in SHARE_QUALITY_CHOICES if value == key), "native")


def frame_rate(video):
    for key in ("r_frame_rate", "avg_frame_rate"):
        try:
            rate = Fraction(video.get(key, "0/1"))
            if rate > 0:
                return rate
        except (ValueError, ZeroDivisionError):
            pass
    return Fraction(0)


@dataclass(frozen=True)
class WebProfile:
    width: int
    height: int
    fps: str | None
    bitrate: int
    peak: int


def web_profile(video):
    width, height = Fraction(video["width"]), Fraction(video["height"])
    native_width, native_height = width, height
    try:
        aspect = Fraction(video.get("sample_aspect_ratio", "1:1").replace(":", "/"))
        if aspect > 0:
            width *= aspect
    except (ValueError, ZeroDivisionError):
        pass
    # FFmpeg autorotates before filtering; calculate the post-rotation display size.
    rotation = next(
        (item["rotation"] for item in video.get("side_data_list", []) if "rotation" in item), 0
    )
    if abs(float(rotation)) % 180 == 90:
        width, height = height, width
        native_width, native_height = native_height, native_width
    limit_width, limit_height = (1920, 1080) if width >= height else (1080, 1920)
    factor = min(
        Fraction(1), native_width / width, native_height / height,
        limit_width / width, limit_height / height,
    )
    output_width = max(2, int(width * factor) // 2 * 2)
    output_height = max(2, int(height * factor) // 2 * 2)
    rate = frame_rate(video)
    fps = None
    if rate > 60:
        fps = "60000/1001" if rate == Fraction(120000, 1001) else "60"
    bitrate, peak = (8, 12) if 0 < rate <= 30 else (12, 18)
    return WebProfile(output_width, output_height, fps, bitrate, peak)
