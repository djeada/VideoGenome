"""FFmpeg reference adapter: ordered, frame-accurate shots with preserved speech.

Supports programmatic title cards, still-image holds, and already-rendered
video clips (filmed, 3D, generated, screen recordings, animations). It also
mixes locked audio tracks and burns timed captions into the picture. It
does not generate footage or speech, or evaluate aesthetic gates.
"""
from __future__ import annotations

import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from videogenome.compiler import ProductionError, confined_file, sha256_file

VIDEO_KINDS = {
    "footage", "talking_head", "screen_capture", "generated_video",
    "3d", "animation", "composite"
}


def _run(command: list[str], *, cwd: Path | None = None) -> None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False, cwd=cwd)
    except OSError as exc:
        raise ProductionError(f"Cannot run media tool {command[0]}: {exc}") from exc
    if result.returncode:
        raise ProductionError(
            f"Media tool failed (exit {result.returncode}): {result.stderr[-1800:]}"
        )


def probe(path: Path, *, count_frames: bool = False) -> dict[str, Any]:
    completed = subprocess.run(
        ["ffprobe", "-v", "error", *(["-count_frames"] if count_frames else []), "-show_entries",
         "format=duration:stream=index,codec_type,width,height,avg_frame_rate,duration,nb_read_frames",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=False
    )
    if completed.returncode:
        raise ProductionError(f"ffprobe failed for {path}: {completed.stderr[-400:]}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ProductionError(f"Invalid ffprobe response for {path}") from exc


def _color_from_palette(plan: dict) -> str:
    return "0x" + plan["palette"][0][1:]


def _text_color(background: str) -> str:
    hexcode = background[2:]
    red, green, blue = (int(hexcode[i:i+2], 16) for i in (0, 2, 4))
    luminance = (0.2126 * red + 0.7152 * green + 0.0722 * blue)
    return "black" if luminance > 155 else "white"


def _video_filter(width: int, height: int, fps: int, fit: str) -> str:
    if fit == "cover":
        spatial = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}"
        )
    else:
        spatial = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
        )
    return spatial + f",setsar=1,fps={fps},format=yuv420p"


def _assert_source_duration(path: Path, in_seconds: float, seconds: float) -> bool:
    metadata = probe(path)
    if not any(stream.get("codec_type") == "video" for stream in metadata.get("streams", [])):
        raise ProductionError(f"Asset is not a readable video: {path}")
    try:
        total_seconds = float(metadata["format"]["duration"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ProductionError(f"Cannot determine video duration: {path}") from exc
    if total_seconds + 0.04 < in_seconds + seconds:
        raise ProductionError(
            f"Video too short: {path.name} needs {in_seconds + seconds:.3f}s "
            f"but has {total_seconds:.3f}s"
        )
    return any(stream.get("codec_type") == "audio" for stream in metadata["streams"])


def _render_segment(
    plan: dict, segment: dict, root: Path, destination: Path, scratch: Path
) -> None:
    w, h, fps = (plan["output"][k] for k in ("width", "height", "fps"))
    frames = segment["duration_frames"]
    seconds = frames / fps
    color = _color_from_palette(plan)
    no_audio = ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    kind = segment["kind"]
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    if kind == "motion_graphics":
        command += ["-f", "lavfi", "-i", f"color=c={color}:s={w}x{h}:r={fps}:d={seconds:.9f}"]
        command += no_audio
        text = segment["text"]
        filtergraph = "format=yuv420p"
        if text:
            text_path = scratch / f"{segment['shot_id']}.txt"
            text_path.write_text(text, encoding="utf-8")
            # Keep untrusted copy out of both filter syntax and drawtext's
            # percent/backslash expansion language, even when using textfile.
            # Paths live in a controlled temp directory (no shell interpolation).
            filtergraph += (
                f",drawtext=textfile='{text_path.name}':expansion=none:font=Sans:"
                f"fontcolor={_text_color(color)}:fontsize={max(24, w // 18)}:"
                "x=(w-text_w)/2:y=(h-text_h)/2"
            )
        audio_map = ["-map", "1:a:0"]
    else:
        asset = plan["assets"][segment["asset_id"]]
        path = confined_file(root, asset["path"])
        if sha256_file(path) != asset["sha256"]:
            raise ProductionError(f"Asset changed since compilation: {asset['path']}")
        if kind == "still_image":
            command += ["-loop", "1", "-framerate", str(fps), "-i", str(path)]
            command += no_audio
            audio_map = ["-map", "1:a:0"]
        elif kind in VIDEO_KINDS:
            in_seconds = segment["in_seconds"]
            has_audio = _assert_source_duration(path, in_seconds, seconds)
            command += ["-ss", str(in_seconds), "-i", str(path)]
            command += no_audio
            audio_map = ["-map", "0:a:0"] if has_audio else ["-map", "1:a:0"]
        else:
            raise ProductionError(f"No reference renderer for shot type {kind!r}")
        filtergraph = _video_filter(w, h, fps, segment["fit"])

    command += [
        "-map", "0:v:0", *audio_map,
        "-vf", filtergraph,
        "-frames:v", str(frames),
        "-t", f"{seconds:.9f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-r", str(fps),
        "-af", "apad", "-ar", "48000", "-ac", "2",
    ]
    # Timeline renders keep PCM between cuts: independently encoded AAC clips
    # introduce encoder-delay gaps before the music/caption finishing pass.
    if destination.suffix == ".mkv":
        command += ["-c:a", "pcm_s16le"]
    else:
        command += ["-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart"]
    command.append(str(destination))
    _run(command, cwd=scratch)


def _samples(frame: int, fps: int) -> int:
    """Map frame coordinates to the nearest 48 kHz sample, ties rounding up."""
    return (frame * 48000 + fps // 2) // fps


def _audio_sources(plan: dict, root: Path) -> list[Path]:
    sources = []
    fps = plan["output"]["fps"]
    for track in plan.get("timeline", {}).get("audio_tracks", []):
        asset = plan["assets"][track["asset_id"]]
        path = confined_file(root, asset["path"])
        if sha256_file(path) != asset["sha256"]:
            raise ProductionError(f"Asset changed since compilation: {asset['path']}")
        metadata = probe(path)
        streams = [s for s in metadata.get("streams", []) if s.get("codec_type") == "audio"]
        if not streams:
            raise ProductionError(f"Audio track {track['id']!r} has no readable audio stream")
        try:
            duration = float(streams[0].get("duration", metadata.get("format", {}).get("duration")))
        except (TypeError, ValueError) as exc:
            raise ProductionError(f"Cannot determine audio duration: {path}") from exc
        needed = (track["in_frame"] + track["duration_frames"]) / fps
        if not math.isfinite(duration) or duration + 1 / 48000 < needed:
            raise ProductionError(f"Audio track {track['id']!r} is too short: needs {needed:.3f}s, has {duration:.3f}s")
        sources.append(path)
    return sources


def _caption_filters(captions: dict, height: int, scratch: Path) -> list[str]:
    style = captions["style"]
    size = style["font_size"]
    filters = []
    for index, cue in enumerate(captions["cues"]):
        block_height = len(cue["lines"]) * size + (len(cue["lines"]) - 1) * 6
        for line_number, line in enumerate(cue["lines"]):
            filename = scratch / f"caption_{index}_{line_number}.txt"
            filename.write_text(line, encoding="utf-8")
            y = height - style["margin_bottom"] - block_height + line_number * (size + 6)
            filters.append(
                f"drawtext=textfile='{filename.name}':expansion=none:font=Sans:"
                f"fontsize={size}:fontcolor=white:box=1:boxcolor=black@0.75:boxborderw=8:"
                f"x=(w-text_w)/2:y={y}:enable='gte(n,{cue['start_frame']})*lt(n,{cue['end_frame']})'"
            )
    return filters


def _finish_timeline(plan: dict, assembled: Path, sources: list[Path], destination: Path, scratch: Path) -> None:
    timeline = plan["timeline"]
    fps = plan["output"]["fps"]
    total = _samples(plan["total_frames"], fps)
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(assembled)]
    for path in sources:
        command += ["-i", str(path)]
    gain = "0" if timeline["source_audio"] == "mute" else f"{timeline['source_audio_gain_db']}dB"
    graph = [f"[0:a:0]aresample=48000,apad,atrim=end_sample={total},asetpts=PTS-STARTPTS,volume={gain}[base]"]
    labels = ["[base]"]
    for index, track in enumerate(timeline["audio_tracks"], 1):
        start = _samples(track["in_frame"], fps)
        end = _samples(track["in_frame"] + track["duration_frames"], fps)
        filters = ["aresample=48000", "aformat=sample_fmts=fltp:channel_layouts=stereo",
                   f"atrim=start_sample={start}:end_sample={end}", "asetpts=PTS-STARTPTS",
                   f"volume={track['gain_db']}dB"]
        if track["fade_in_frames"]:
            filters.append(f"afade=t=in:ss=0:ns={_samples(track['fade_in_frames'], fps)}")
        if track["fade_out_frames"]:
            fade = _samples(track["fade_out_frames"], fps)
            filters.append(f"afade=t=out:ss={end - start - fade}:ns={fade}")
        filters.append(f"adelay={_samples(track['start_frame'], fps)}S:all=1")
        graph.append(f"[{index}:a:0]" + ",".join(filters) + f"[track{index}]")
        labels.append(f"[track{index}]")
    graph.append("".join(labels) + f"amix=inputs={len(labels)}:duration=first:normalize=0,"
                 f"alimiter=limit=0.95:level=false:latency=true,atrim=end_sample={total}[mix]")
    video_filters = [f"setpts=N/({fps}*TB)"]
    if "captions" in timeline:
        video_filters += _caption_filters(timeline["captions"], plan["output"]["height"], scratch)
    graph.append("[0:v:0]" + ",".join(video_filters) + "[picture]")
    command += ["-filter_complex", ";".join(graph), "-map", "[picture]", "-map", "[mix]",
                "-frames:v", str(plan["total_frames"]), "-t", f"{plan['total_frames'] / fps:.9f}",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                "-r", str(fps), "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "128k",
                "-movflags", "+faststart", str(destination)]
    _run(command, cwd=scratch)


def render(plan: dict, job_directory: Path, output_path: Path) -> dict:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise ProductionError("FFmpeg and ffprobe must be installed to render")
    if not plan["segments"]:
        raise ProductionError("No segments in render plan")
    output_path = output_path.resolve()
    for asset in plan["assets"].values():
        source_path = confined_file(job_directory.resolve(), asset["path"])
        if source_path == output_path:
            raise ProductionError("Output would overwrite a source asset")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    audio_sources = _audio_sources(plan, job_directory.resolve())

    with tempfile.TemporaryDirectory(prefix="videogenome-") as directory:
        scratch = Path(directory).resolve()
        destinations = []
        for index, segment in enumerate(plan["segments"]):
            suffix = ".mkv" if "timeline" in plan else ".mp4"
            dest = scratch / f"clip_{index:04d}{suffix}"
            _render_segment(plan, segment, job_directory.resolve(), dest, scratch)
            destinations.append(dest)
        # Whitelisted generated paths, never values pasted from model output.
        concat = scratch / "concat.txt"
        concat.write_text(
            "".join(f"file '{path.name}'\n" for path in destinations),
            encoding="utf-8"
        )
        assembled = scratch / ("assembled.mkv" if "timeline" in plan else "assembled.mp4")
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat),
            "-map", "0:v:0", "-map", "0:a:0",
            "-c", "copy",
        ]
        if "timeline" not in plan:
            command += ["-movflags", "+faststart"]
        _run([*command, str(assembled)])
        if "timeline" in plan:
            finished = scratch / "finished.mp4"
            _finish_timeline(plan, assembled, audio_sources, finished, scratch)
            assembled = finished
        shutil.copy2(assembled, output_path)

    data = probe(output_path, count_frames=True)
    video_streams = [s for s in data["streams"] if s.get("codec_type") == "video"]
    if len(video_streams) != 1:
        raise ProductionError("Output must have exactly one video stream")
    v = video_streams[0]
    actual_frames = int(v.get("nb_read_frames", 0))
    if actual_frames != plan["total_frames"]:
        raise ProductionError(f"Output frame count differs from blueprint: {actual_frames} vs {plan['total_frames']}")
    if (v.get("width"), v.get("height")) != (
        plan["output"]["width"], plan["output"]["height"]
    ):
        raise ProductionError("Output resolution differs from blueprint")
    actual = float(data["format"]["duration"])
    expected = plan["total_frames"] / plan["output"]["fps"]
    if abs(actual - expected) > 0.12:
        raise ProductionError(f"Output duration drift: {actual:.3f}s vs {expected:.3f}s")

    return {
        "job_id": plan["job_id"], "template_id": plan["template_id"],
        "template_version": plan["template_version"],
        "template_sha256": plan["template_sha256"],
        "job_sha256": plan["job_sha256"],
        "output_path": str(output_path), "output_sha256": sha256_file(output_path),
        "frames_planned": plan["total_frames"], "duration_expected_seconds": expected,
        "frames_observed": actual_frames,
        "duration_observed_seconds": actual,
        "verified": ["output_exists", "container_readable", "resolution", "frame_count", "duration_tolerance"],
        "assets": plan["assets"],
        "timeline": plan.get("timeline"),
        "quality_gates": plan["quality_gates"],
        "caveats": [
            "Asset rights, consent and external origin are self-attested, not independently verified.",
            "Human gates are not assessed by this renderer.",
            "Declared automated aesthetic/legibility gates are not executed by this renderer.",
            "No speech generation, transcription, automatic ducking or general picture compositing.",
            "Caption line and reading-speed limits do not certify accessibility or font coverage."
        ]
    }
