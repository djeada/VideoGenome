"""Review and distribution sidecars written next to a rendered programme.

Subtitle files carry exactly the compiled caption cues; posters and contact
sheets are frames decoded from the verified output, not separate renders.
"""
from __future__ import annotations

import math
from pathlib import Path

from videogenome.compiler import ProductionError
from videogenome.plugins import Exporter


def _timestamp(frame: int, fps: int, separator: str) -> str:
    milliseconds = round(frame * 1000 / fps)
    hours, rest = divmod(milliseconds, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{millis:03d}"


def subtitles(plan: dict) -> tuple[str, str] | None:
    """Return (SRT, WebVTT) text for the plan's caption cues, if any."""
    cues = plan.get("timeline", {}).get("captions", {}).get("cues", [])
    if not cues:
        return None
    fps = plan["output"]["fps"]
    srt, vtt = [], ["WEBVTT", ""]
    for number, cue in enumerate(cues, 1):
        body = "\n".join(cue["lines"])
        srt += [str(number), f"{_timestamp(cue['start_frame'], fps, ',')} --> "
                f"{_timestamp(cue['end_frame'], fps, ',')}", body, ""]
        vtt += [cue["id"], f"{_timestamp(cue['start_frame'], fps, '.')} --> "
                f"{_timestamp(cue['end_frame'], fps, '.')}", body, ""]
    return "\n".join(srt), "\n".join(vtt)


def review_frames(plan: dict) -> tuple[int, list[int]]:
    """Poster frame and one representative frame per shot (after entrances)."""
    frames = []
    for segment in plan["segments"]:
        frames.append(segment["start_frame"] + (2 * segment["duration_frames"]) // 3)
    poster = plan["output"].get("poster_frame", frames[0])
    return poster, frames


def _guard(paths: list[Path], protected: set[Path]) -> None:
    for path in paths:
        if path.resolve() in protected:
            raise ProductionError(f"Deliverable would overwrite a source asset: {path.name}")


def _ffmpeg(arguments: list[str]) -> None:
    from videogenome.render import _run
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *arguments])


class SubtitleExporter(Exporter):
    """SRT and WebVTT carrying exactly the compiled caption cues."""

    summary = "SRT + WebVTT caption sidecars"
    config_schema = {"type": "object", "additionalProperties": False,
                     "properties": {"formats": {"type": "array", "items": {"enum": ["srt", "vtt"]}}}}

    def export(self, plan: dict, output: Path, protected: set[Path]) -> dict[str, Path]:
        texts = subtitles(plan)
        if not texts:
            return {}
        formats = self.config.get("formats", ["srt", "vtt"])
        written = {kind: output.with_suffix(f".{kind}") for kind in formats}
        _guard(list(written.values()), protected)
        for kind, path in written.items():
            path.write_text(texts[0] if kind == "srt" else texts[1], encoding="utf-8")
        return written


class PosterExporter(Exporter):
    """One poster frame decoded from the verified output."""

    summary = "Poster JPEG (output.poster_frame or two-thirds into the first shot)"

    def export(self, plan: dict, output: Path, protected: set[Path]) -> dict[str, Path]:
        path = Path(f"{output.with_suffix('')}.poster.jpg")
        _guard([path], protected)
        poster, _ = review_frames(plan)
        _ffmpeg(["-i", str(output), "-vf", f"select='eq(n,{poster})'", "-fps_mode", "passthrough",
                 "-frames:v", "1", "-q:v", "2", str(path)])
        return {"poster": path}


class ContactSheetExporter(Exporter):
    """One tile per shot, sampled after entrances complete."""

    summary = "Contact sheet JPEG, one tile per shot"
    config_schema = {"type": "object", "additionalProperties": False,
                     "properties": {"columns": {"type": "integer", "minimum": 1, "maximum": 12},
                                    "tile_width": {"type": "integer", "minimum": 64, "maximum": 1920}}}

    def export(self, plan: dict, output: Path, protected: set[Path]) -> dict[str, Path]:
        path = Path(f"{output.with_suffix('')}.contact.jpg")
        _guard([path], protected)
        _, frames = review_frames(plan)
        columns = min(len(frames), self.config.get("columns", 4))
        rows = math.ceil(len(frames) / columns)
        tile_width = min(self.config.get("tile_width", 480), plan["output"]["width"])
        picks = "+".join(f"eq(n,{frame})" for frame in frames)
        _ffmpeg(["-i", str(output), "-vf",
                 f"select='{picks}',scale={tile_width}:-2,"
                 f"tile={columns}x{rows}:padding=8:margin=8:color=0x101010",
                 "-fps_mode", "passthrough", "-frames:v", "1", "-q:v", "3", str(path)])
        return {"contact_sheet": path}
