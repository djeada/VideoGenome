"""FFmpeg reference adapter: ordered, frame-accurate shots with preserved speech.

Supports programmatic title cards, still-image holds, and already-rendered
video clips (filmed, 3D, generated, screen recordings, animations). It does
not generate or edit footage, perform compositing, or evaluate aesthetic gates.
"""
from __future__ import annotations

import hashlib
import json
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


def _run(command: list[str]) -> None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise ProductionError(f"Cannot run media tool {command[0]}: {exc}") from exc
    if result.returncode:
        raise ProductionError(
            f"Media tool failed (exit {result.returncode}): {result.stderr[-1800:]}"
        )


def probe(path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=index,codec_type,width,height,avg_frame_rate",
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
            # drawtext reads untrusted copy as file data, never filter syntax.
            # Paths live in a controlled temp directory (no shell interpolation).
            safe_path = str(text_path).replace("\\", "\\\\").replace(":", "\\:")
            filtergraph += (
                f",drawtext=textfile='{safe_path}':font=Sans:"
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
        "-c:a", "aac", "-ar", "48000", "-ac", "2",
        "-b:a", "128k", "-movflags", "+faststart",
        str(destination)
    ]
    _run(command)


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

    with tempfile.TemporaryDirectory(prefix="videogenome-") as directory:
        scratch = Path(directory)
        destinations = []
        for index, segment in enumerate(plan["segments"]):
            dest = scratch / f"clip_{index:04d}.mp4"
            _render_segment(plan, segment, job_directory.resolve(), dest, scratch)
            destinations.append(dest)
        # Whitelisted generated paths, never values pasted from model output.
        concat = scratch / "concat.txt"
        concat.write_text(
            "".join(f"file '{path}'\n" for path in destinations),
            encoding="utf-8"
        )
        assembled = scratch / "assembled.mp4"
        _run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat),
            "-map", "0:v:0", "-map", "0:a:0",
            "-c", "copy", "-movflags", "+faststart", str(assembled)
        ])
        shutil.copy2(assembled, output_path)

    data = probe(output_path)
    video_streams = [s for s in data["streams"] if s.get("codec_type") == "video"]
    if len(video_streams) != 1:
        raise ProductionError("Output must have exactly one video stream")
    v = video_streams[0]
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
        "duration_observed_seconds": actual,
        "verified": ["output_exists", "container_readable", "resolution", "duration_tolerance"],
        "quality_gates": plan["quality_gates"],
        "caveats": [
            "Asset rights, consent and external origin are self-attested, not independently verified.",
            "Human gates are not assessed by this renderer.",
            "Declared automated aesthetic/legibility gates are not executed by this renderer.",
            "No synthesis, generation, compositing or nonlinear timeline support."
        ]
    }
