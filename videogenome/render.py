"""FFmpeg reference adapter: ordered, frame-accurate shots with preserved speech.

Supports designed title cards, still-image holds, and already-rendered video
clips (filmed, 3D, generated, screen recordings, animations); crossfade and
dip transitions; locked audio tracks; burned-in captions; loudness mastering;
executed technical measurements and review sidecars. It does not generate
footage or speech, or evaluate aesthetic gates.
"""
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from videogenome import __version__, qa
from videogenome.compiler import ProductionError, confined_file, sha256_file
from videogenome.layout import CAP_HEIGHT, DESCENT, KICKER_GAP, bar_geometry, text_width_px
from videogenome.plugins import Renderer

VIDEO_KINDS = {
    "footage", "talking_head", "screen_capture", "generated_video",
    "3d", "animation", "composite"
}
FONT_SUFFIXES = {".ttf", ".otf", ".ttc", ".woff", ".woff2", ".pfb"}
DEFAULT_TIMELINE = {"source_audio": "preserve", "source_audio_gain_db": 0, "audio_tracks": []}


def _run(command: list[str], *, cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False, cwd=cwd)
    except OSError as exc:
        raise ProductionError(f"Cannot run media tool {command[0]}: {exc}") from exc
    if result.returncode:
        raise ProductionError(
            f"Media tool failed (exit {result.returncode}): {result.stderr[-1800:]}"
        )
    return result.stderr


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


def _hex(color: str) -> str:
    return "0x" + color[1:]


def _samples(frame: int, fps: int) -> int:
    """Map frame coordinates to the nearest 48 kHz sample, ties rounding up."""
    return (frame * 48000 + fps // 2) // fps


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


def _motion_filter(width: int, height: int, fps: int, frames: int, fit: str, motion: dict) -> str:
    """Smooth Ken Burns move: supersample 4x, then zoompan with eased progress."""
    big_w, big_h = 4 * width, 4 * height
    if fit == "cover":
        spatial = f"scale={big_w}:{big_h}:force_original_aspect_ratio=increase,crop={big_w}:{big_h}"
    else:
        spatial = (f"scale={big_w}:{big_h}:force_original_aspect_ratio=decrease,"
                   f"pad={big_w}:{big_h}:(ow-iw)/2:(oh-ih)/2")
    amount = motion.get("amount", 0.08)
    last = max(1, frames - 1)
    ease = f"(3*pow(on/{last},2)-2*pow(on/{last},3))"
    centre_x, centre_y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    kind = motion["type"]
    zoom = {"push_in": f"1+{amount}*{ease}", "pull_out": f"1+{amount}*(1-{ease})"}.get(kind, f"1+{amount}")
    x = {"pan_left": f"(iw-iw/zoom)*(1-{ease})", "pan_right": f"(iw-iw/zoom)*{ease}"}.get(kind, centre_x)
    y = {"pan_up": f"(ih-ih/zoom)*(1-{ease})", "pan_down": f"(ih-ih/zoom)*{ease}"}.get(kind, centre_y)
    return (f"{spatial},zoompan=z='{zoom}':x='{x}':y='{y}':d=1:s={width}x{height}:fps={fps},"
            f"setsar=1,format=yuv420p")


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
            f"(including any crossfade handle) but has {total_seconds:.3f}s"
        )
    return any(stream.get("codec_type") == "audio" for stream in metadata["streams"])


# --------------------------------------------------------------------------
# Typography


def _resolve_font(card: dict, scratch: Path) -> dict:
    """Pin the card font to one file so measurement and drawing agree."""
    requested = card["font_family"]
    record = {"requested_family": requested, "requested_weight": card["font_weight"]}
    if not shutil.which("fc-match"):
        return {**record, "resolved_family": None, "file": None, "sha256": None,
                "substituted": None, "option": "font=Sans",
                "note": "fc-match unavailable; FFmpeg's fontconfig default was used"}
    # The family is schema-restricted to letters, digits and spaces.
    pattern = f"{requested}:weight={card['fontconfig_weight']}"
    completed = subprocess.run(["fc-match", "-f", "%{family[0]}\n%{file}", pattern],
                               capture_output=True, text=True, check=False)
    family, _, source = completed.stdout.partition("\n")
    source_path = Path(source.strip())
    if completed.returncode or not source_path.is_file():
        raise ProductionError(f"Cannot resolve a font for {pattern!r}")
    suffix = source_path.suffix.lower() if source_path.suffix.lower() in FONT_SUFFIXES else ".font"
    pinned = scratch / f"title_font{suffix}"
    shutil.copyfile(source_path, pinned)
    generic = requested.lower() in ("sans", "serif", "monospace")
    return {**record, "resolved_family": family.strip(), "file": str(source_path),
            "sha256": sha256_file(pinned),
            "substituted": (not generic and family.strip().lower() != requested.lower()),
            "option": f"fontfile={pinned.name}"}


def _ink_width(font: dict, text: str, size: int, scratch: Path) -> int:
    """Rendered ink width in pixels, decoded from an actual drawtext frame."""
    # Even dimensions: the yuv420p colour source rounds odd sizes down.
    canvas_w = min(16000, int(len(text) * size * 0.9) + 64) // 2 * 2
    canvas_h = size * 2
    (scratch / "measure.txt").write_text(text, encoding="utf-8")
    completed = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", f"color=c=black:s={canvas_w}x{canvas_h}:d=1",
         "-vf", f"drawtext={font['option']}:textfile=measure.txt:expansion=none:"
                f"fontsize={size}:fontcolor=white:x=16:y={round(size * 1.4)}:y_align=baseline",
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"],
        capture_output=True, check=False, cwd=scratch,
    )
    if completed.returncode or len(completed.stdout) != canvas_w * canvas_h:
        raise ProductionError(f"Cannot measure title text: {completed.stderr[-400:]!r}")
    ink = completed.stdout.translate(bytes(0 if value < 96 else 1 for value in range(256)))
    left, right = canvas_w, -1
    for row in range(canvas_h):
        line = ink[row * canvas_w:(row + 1) * canvas_w]
        first = line.find(1)
        if first >= 0:
            left = min(left, first)
            right = max(right, line.rfind(1))
    return 0 if right < 0 else right - left + 1


def _card_layout(plan: dict, segment: dict, font: dict, scratch: Path) -> dict:
    """Measure real glyphs; shrink (never re-wrap) until copy fits the safe area."""
    card = plan["title_card"]
    width, height = plan["output"]["width"], plan["output"]["height"]
    lines, kicker = segment["lines"], segment["kicker"]
    size = segment["font_size"]
    for _ in range(6):
        available = text_width_px(card, size, width)
        widths = [_ink_width(font, line, size, scratch) for line in lines]
        if max(widths, default=0) <= available:
            break
        size = math.floor(size * available / max(widths)) - 1
        if size < card["min_font_size"]:
            raise ProductionError(
                f"Copy for shot {segment['shot_id']!r} is wider than the locked layout "
                f"at the {card['min_font_size']}px minimum with font "
                f"{font.get('resolved_family')!r}; shorten the copy"
            )
    else:
        raise ProductionError(f"Title layout for {segment['shot_id']!r} did not converge")
    kicker_size = card["kicker_font_size"]
    kicker_width = 0
    if kicker:
        kicker_width = _ink_width(font, kicker, kicker_size, scratch)
        if kicker_width > available:
            kicker_size = max(12, math.floor(kicker_size * available / kicker_width) - 1)
            kicker_width = _ink_width(font, kicker, kicker_size, scratch)

    pitch = size * card["line_spacing"]
    kicker_block = kicker_size * (CAP_HEIGHT + DESCENT) + KICKER_GAP * size if kicker else 0
    text_block = CAP_HEIGHT * size + max(0, len(lines) - 1) * pitch + DESCENT * size if lines else 0
    thickness, indent = bar_geometry(card, size)
    bar_block = size * 0.45 + thickness if card["accent_bar"] and card["align"] == "center" else 0
    block = kicker_block + text_block + bar_block
    top_margin, bottom_margin = card["safe_margin_top"], card["safe_margin_bottom"]
    top = top_margin + max(0.0, (height - top_margin - bottom_margin - block) / 2)
    first_baseline = top + kicker_block + CAP_HEIGHT * size
    text_bottom = top + kicker_block + text_block
    bar = None
    if card["accent_bar"] and lines:
        if card["align"] == "left":
            bar = {"x": card["safe_margin_x"], "y": round(top), "w": thickness,
                   "h": max(thickness, round(text_bottom - top))}
        else:
            bar_width = round(size * 1.5)
            bar = {"x": (width - bar_width) // 2, "y": round(text_bottom + size * 0.45),
                   "w": bar_width, "h": thickness}
    return {
        "shot_id": segment["shot_id"], "font_size": size, "planned_font_size": segment["font_size"],
        "kicker_font_size": kicker_size if kicker else None,
        "line_widths_px": widths, "kicker_width_px": kicker_width if kicker else None,
        "available_width_px": available, "text_x": card["safe_margin_x"] + indent,
        "kicker_baseline": round(top + CAP_HEIGHT * kicker_size) if kicker else None,
        "baselines": [round(first_baseline + index * pitch) for index in range(len(lines))],
        "bar": bar,
    }


def _entrance(card: dict, fps: int, order: int) -> tuple[str, str]:
    """Alpha and vertical-offset expressions for a staggered entrance."""
    if card["entrance"] == "none" or not card["entrance_frames"]:
        return "1", "0"
    seconds = card["entrance_frames"] / fps
    delay = order * seconds * 0.2
    progress = f"clip((t-{delay:.6f})/{seconds:.6f},0,1)"
    alpha = f"{progress}*{progress}*(3-2*{progress})"
    if card["entrance"] == "fade":
        return alpha, "0"
    rise = round(card["font_size"] * 0.35)
    return alpha, f"{rise}*pow(1-{progress},3)"


def _card_graph(plan: dict, segment: dict, layout: dict, font: dict,
                scratch: Path, frames: int, background: str | None = None) -> str:
    card = plan["title_card"]
    width, height, fps = (plan["output"][k] for k in ("width", "height", "fps"))
    seconds = frames / fps
    if background:  # A produced/supplied clip or still behind the type, dimmed for legibility.
        dim = card.get("background_dim", 0)
        # Dim in RGB: a YUV drawbox scrim desaturates colours towards brown.
        keep = 1 - dim
        graph = [f"{background}scale={width}:{height}:force_original_aspect_ratio=increase,"
                 f"crop={width}:{height},setsar=1,fps={fps},format=rgb24,"
                 + (f"colorchannelmixer=rr={keep:.4f}:gg={keep:.4f}:bb={keep:.4f}," if dim else "")
                 + f"format=yuv420p,trim=end_frame={frames},setpts=PTS-STARTPTS[bg]"]
    else:
        graph = [f"color=c={_hex(card['background'])}:s={width}x{height}:r={fps}:d={seconds:.9f}[bg]"]
    base = "[bg]"
    if layout["bar"]:
        bar = layout["bar"]
        fade = (f",fade=t=in:st=0:d={card['entrance_frames'] / fps:.6f}:alpha=1"
                if card["entrance"] != "none" and card["entrance_frames"] else "")
        graph.append(f"color=c={_hex(card['accent_color'])}:s={bar['w']}x{bar['h']}:r={fps}:"
                     f"d={seconds:.9f},format=yuva420p{fade}[bar]")
        graph.append(f"[bg][bar]overlay=x={bar['x']}:y={bar['y']}:shortest=1[base]")
        base = "[base]"
    draws = []
    texts = []
    if segment["kicker"]:
        texts.append((segment["kicker"], layout["kicker_font_size"], layout["kicker_baseline"],
                      card.get("accent_color", card["text_color"])))
    texts += [(line, layout["font_size"], baseline, card["text_color"])
              for line, baseline in zip(segment["lines"], layout["baselines"])]
    for order, (text, size, baseline, color) in enumerate(texts):
        name = f"{segment['shot_id']}_{order}.txt"
        # Untrusted copy stays out of filter syntax and drawtext expansion.
        (scratch / name).write_text(text, encoding="utf-8")
        alpha, offset = _entrance(card, fps, order)
        x = "(w-text_w)/2" if card["align"] == "center" else str(layout["text_x"])
        draws.append(
            f"drawtext={font['option']}:textfile='{name}':expansion=none:fontsize={size}:"
            f"fontcolor={_hex(color)}:x={x}:y='{baseline}+{offset}':y_align=baseline:"
            f"alpha='{alpha}'"
        )
    graph.append(base + ",".join([*draws, "format=yuv420p"]) + "[card]")
    return ";".join(graph)


# --------------------------------------------------------------------------
# Picture assembly


def _segment_effects(plan: dict) -> list[dict]:
    """Per-shot crossfade handles and dip/programme fades, in frames."""
    effects = [{"handle": 0, "fade_in": None, "fade_out": None} for _ in plan["segments"]]
    picture = plan.get("picture", {})
    if picture.get("fade_in_frames"):
        effects[0]["fade_in"] = (picture["fade_in_frames"], "#000000")
    if picture.get("fade_out_frames"):
        effects[-1]["fade_out"] = (picture["fade_out_frames"], "#000000")
    index = {segment["shot_id"]: i for i, segment in enumerate(plan["segments"])}
    for transition in picture.get("transitions", []):
        source = index[transition["from_shot"]]
        frames = transition["duration_frames"]
        if transition["kind"] == "crossfade":
            effects[source]["handle"] = frames
        else:
            effects[source]["fade_out"] = ((frames + 1) // 2, transition["color"])
            if frames // 2:
                effects[source + 1]["fade_in"] = (frames // 2, transition["color"])
    return effects


def _render_segment(plan: dict, segment: dict, effect: dict, root: Path, destination: Path,
                    scratch: Path, font: dict | None) -> dict | None:
    w, h, fps = (plan["output"][k] for k in ("width", "height", "fps"))
    frames = segment["duration_frames"] + effect["handle"]
    seconds = frames / fps
    kind = segment["kind"]
    layout = None
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    if kind == "motion_graphics":
        assert font is not None
        layout = _card_layout(plan, segment, font, scratch)
        command += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        background = None
        asset_id = plan["title_card"].get("background_asset")
        if asset_id:
            asset = plan["assets"][asset_id]
            path = confined_file(root, asset["path"])
            if asset["kind"] == "image":
                command += ["-loop", "1", "-framerate", str(fps), "-i", str(path)]
            else:
                # Continue the background's motion across cards: offset by programme time.
                length = float(probe(path)["format"].get("duration") or 0) or seconds
                offset = (segment["start_frame"] / fps) % max(length, 1 / fps)
                command += ["-stream_loop", "-1", "-ss", f"{offset:.6f}", "-i", str(path)]
            background = "[1:v:0]"
        graph = [_card_graph(plan, segment, layout, font, scratch, frames, background)]
        picture, audio = "[card]", "[0:a:0]"
    else:
        asset = plan["assets"][segment["asset_id"]]
        path = confined_file(root, asset["path"])
        if sha256_file(path) != asset["sha256"]:
            raise ProductionError(f"Asset changed since compilation: {asset['path']}")
        if kind == "still_image":
            command += ["-loop", "1", "-framerate", str(fps), "-i", str(path)]
            command += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
            audio = "[1:a:0]"
        elif kind in VIDEO_KINDS:
            in_seconds = segment["in_seconds"]
            has_audio = _assert_source_duration(path, in_seconds, seconds)
            command += ["-ss", str(in_seconds), "-i", str(path)]
            command += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
            audio = "[0:a:0]" if has_audio else "[1:a:0]"
        else:
            raise ProductionError(f"No reference renderer for shot type {kind!r}")
        motion = segment.get("motion", {"type": "none"})
        if kind == "still_image" and motion["type"] != "none":
            graph = [f"[0:v:0]{_motion_filter(w, h, fps, frames, segment['fit'], motion)}[card]"]
        else:
            graph = [f"[0:v:0]{_video_filter(w, h, fps, segment['fit'])}[card]"]
        picture = "[card]"

    video_fades, audio_fades = [], []
    length = _samples(segment["start_frame"] + frames, fps) - _samples(segment["start_frame"], fps)
    if effect["fade_in"]:
        count, color = effect["fade_in"]
        video_fades.append(f"fade=t=in:s=0:n={count}:c={_hex(color)}")
        audio_fades.append(f"afade=t=in:ss=0:ns={_samples(count, fps)}")
    if effect["fade_out"]:
        count, color = effect["fade_out"]
        video_fades.append(f"fade=t=out:s={frames - count}:n={count}:c={_hex(color)}")
        fade = _samples(count, fps)
        audio_fades.append(f"afade=t=out:ss={length - fade}:ns={fade}")
    graph.append(f"{picture}{','.join(['null', *video_fades])}[v]")
    graph.append(f"{audio}aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                 f"apad,atrim=end_sample={length},asetpts=PTS-STARTPTS"
                 + "".join("," + f for f in audio_fades) + "[a]")
    command += [
        "-filter_complex", ";".join(graph), "-map", "[v]", "-map", "[a]",
        "-frames:v", str(frames),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
        "-pix_fmt", "yuv420p", "-r", str(fps),
        # PCM between cuts: independently encoded AAC clips introduce
        # encoder-delay gaps before the finishing pass.
        "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(destination),
    ]
    _run(command, cwd=scratch)
    return layout


def _assemble(plan: dict, clips: list[Path], effects: list[dict], destination: Path,
              scratch: Path) -> None:
    if not any(effect["handle"] for effect in effects):
        # Whitelisted generated paths, never values pasted from model output.
        concat = scratch / "concat.txt"
        concat.write_text("".join(f"file '{path.name}'\n" for path in clips), encoding="utf-8")
        _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
              "-i", str(concat), "-map", "0:v:0", "-map", "0:a:0", "-c", "copy", str(destination)])
        return
    fps = plan["output"]["fps"]
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    for clip in clips:
        command += ["-i", str(clip)]
    graph = [f"[{i}:v:0]settb=AVTB,setpts=PTS-STARTPTS[v{i}];[{i}:a:0]asetpts=PTS-STARTPTS[a{i}]"
             for i in range(len(clips))]
    video, audio = "[v0]", "[a0]"
    for i in range(1, len(clips)):
        previous = plan["segments"][i - 1]
        handle = effects[i - 1]["handle"]
        if handle:
            start = plan["segments"][i]["start_frame"]
            overlap = _samples(start + handle, fps) - _samples(start, fps)
            graph.append(f"{video}[v{i}]xfade=transition=fade:duration={handle / fps:.9f}:"
                         f"offset={previous['end_frame'] / fps:.9f}[xv{i}]")
            graph.append(f"{audio}[a{i}]acrossfade=ns={overlap}:c1=tri:c2=tri[xa{i}]")
        else:
            graph.append(f"{video}{audio}[v{i}][a{i}]concat=n=2:v=1:a=1[xv{i}][xa{i}]")
        video, audio = f"[xv{i}]", f"[xa{i}]"
    command += ["-filter_complex", ";".join(graph), "-map", video, "-map", audio,
                "-frames:v", str(plan["total_frames"]),
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p",
                "-r", str(fps), "-c:a", "pcm_s16le", str(destination)]
    _run(command, cwd=scratch)


# --------------------------------------------------------------------------
# Finishing: audio mix, captions, loudness


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


def _caption_filters(captions: dict, height: int, scratch: Path, font_option: str = "font=Sans") -> list[str]:
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
                f"drawtext=textfile='{filename.name}':expansion=none:{font_option}:"
                f"fontsize={size}:fontcolor=white:box=1:boxcolor=black@0.62:boxborderw={max(6, size // 3)}:"
                f"x=(w-text_w)/2:y={y}:enable='gte(n,{cue['start_frame']})*lt(n,{cue['end_frame']})'"
            )
    return filters


def _duck_expression(duck: dict, fps: int) -> str:
    """Gain curve that dips by depth_db inside each window, with linear ramps."""
    floor = 10 ** (-duck["depth_db"] / 20)
    ramp = max(duck["ramp_frames"], 1) / fps
    curves = [f"clip(min((t-{start / fps - ramp:.4f})/{ramp:.4f},({end / fps + ramp:.4f}-t)/{ramp:.4f}),0,1)"
              for start, end in duck["windows"]]
    combined = curves[0]
    for curve in curves[1:]:
        combined = f"max({combined},{curve})"
    return f"1-{1 - floor:.6f}*{combined}"


def _finish_timeline(plan: dict, assembled: Path, sources: list[Path], destination: Path,
                     scratch: Path, font_option: str = "font=Sans") -> None:
    timeline = plan.get("timeline") or DEFAULT_TIMELINE
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
        for duck in timeline.get("ducking", []):
            if duck["track"] == track["id"]:
                filters.append(f"volume=eval=frame:volume='{_duck_expression(duck, fps)}'")
        graph.append(f"[{index}:a:0]" + ",".join(filters) + f"[track{index}]")
        labels.append(f"[track{index}]")
    graph.append("".join(labels) + f"amix=inputs={len(labels)}:duration=first:normalize=0,"
                 f"alimiter=limit=0.95:level=false:latency=true,atrim=end_sample={total}[mix]")
    video_filters = [f"setpts=N/({fps}*TB)"]
    if "captions" in timeline:
        video_filters += _caption_filters(timeline["captions"], plan["output"]["height"], scratch, font_option)
    graph.append("[0:v:0]" + ",".join(video_filters) + "[picture]")
    command += ["-filter_complex", ";".join(graph), "-map", "[picture]", "-map", "[mix]",
                "-frames:v", str(plan["total_frames"]), "-t", f"{plan['total_frames'] / fps:.9f}",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                "-r", str(fps), "-ar", "48000", "-ac", "2"]
    if destination.suffix == ".mkv":
        command += ["-c:a", "pcm_s16le"]
    else:
        command += ["-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart"]
    _run([*command, str(destination)], cwd=scratch)


def _loudnorm_json(log: str) -> dict:
    found = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", log)
    if not found:
        raise ProductionError("Loudness analysis produced no measurement")
    return json.loads(found[-1])


def _master_loudness(plan: dict, mixed: Path, destination: Path) -> dict:
    """Two-pass EBU R128 normalisation; video is stream-copied, not re-encoded."""
    spec = plan["output"]["loudness"]
    target = f"I={spec['target_lufs']}:TP={spec['max_true_peak_dbtp']}:LRA=11"
    first = _loudnorm_json(_run([
        "ffmpeg", "-hide_banner", "-nostats", "-loglevel", "info", "-i", str(mixed),
        "-map", "0:a:0", "-af", f"loudnorm={target}:print_format=json", "-f", "null", "-",
    ]))
    copy = ["ffmpeg", "-hide_banner", "-nostats", "-loglevel", "info", "-y", "-i", str(mixed),
            "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy"]
    encode = ["-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart"]
    measured = float(first["input_i"]) if first["input_i"] not in ("-inf", "inf") else None
    if measured is None or measured <= qa.SILENT_PROGRAMME_LUFS:
        _run([*copy, *encode, str(destination)])
        return {"target": spec, "status": "skipped", "reason": "programme audio is silent"}
    loudnorm = (f"loudnorm={target}:measured_I={first['input_i']}:measured_TP={first['input_tp']}:"
                f"measured_LRA={first['input_lra']}:measured_thresh={first['input_thresh']}:"
                f"offset={first['target_offset']}:linear=true:print_format=json,aresample=48000")
    correction, attempts = 0.0, []
    for _ in range(4):
        chain = loudnorm + (f",volume={correction:.2f}dB" if correction else "")
        second = _loudnorm_json(_run([*copy, "-af", chain, *encode, str(destination)]))
        # Lossy encoding can push decoded peaks over the ceiling: measure the real file.
        peak = _decoded_true_peak(destination)
        attempts.append({"correction_db": round(correction, 2), "true_peak_dbtp": peak})
        if peak is None or peak <= spec["max_true_peak_dbtp"]:
            break
        correction -= peak - spec["max_true_peak_dbtp"] + 0.2
    return {"target": spec, "status": "applied",
            "normalization_type": second.get("normalization_type"),
            "input_lufs": float(first["input_i"]), "input_true_peak_dbtp": float(first["input_tp"]),
            "ceiling_passes": attempts}


def _decoded_true_peak(path: Path) -> float | None:
    log = _run(["ffmpeg", "-hide_banner", "-nostats", "-loglevel", "info", "-i", str(path),
                "-map", "0:a:0", "-af", "ebur128=peak=true", "-f", "null", "-"])
    found = re.findall(r"Peak:\s+(-?[\d.]+|-inf)\s+dBFS", log[log.rfind("Summary:"):])
    return None if not found or found[-1] == "-inf" else float(found[-1])


def _ffmpeg_version() -> str:
    completed = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, check=False)
    return completed.stdout.splitlines()[0] if completed.stdout else "unknown"


class FFmpegRenderer(Renderer):
    """Reference renderer: every IR feature through FFmpeg, verified by ffprobe."""

    summary = "FFmpeg reference renderer (cards, stills, clips, transitions, mix, captions, loudness)"
    SUPPORTED_KINDS = {"motion_graphics", "still_image", *VIDEO_KINDS}

    def check(self) -> list[tuple[str, str]]:
        missing = [tool for tool in ("ffmpeg", "ffprobe") if not shutil.which(tool)]
        return [("FAIL", f"missing {', '.join(missing)}")] if missing else [("OK", _ffmpeg_version())]

    def unsupported(self, plan: dict) -> list[str]:
        problems = [f"shot {s['shot_id']}: kind {s['kind']!r}" for s in plan["segments"]
                    if s["kind"] not in self.SUPPORTED_KINDS]
        problems += [f"transition {t['kind']!r}" for t in plan.get("picture", {}).get("transitions", [])
                     if t["kind"] not in ("crossfade", "dip")]
        return problems

    def check_copy(self, card: dict, output: dict, cards: list[dict]) -> list[tuple[str, str]]:
        """Set each card with the pinned font, exactly as render() will."""
        if not cards or not shutil.which("ffmpeg"):
            return []
        plan = {"title_card": card, "output": output}
        problems = []
        with tempfile.TemporaryDirectory(prefix="videogenome-copy-") as directory:
            scratch = Path(directory).resolve()
            font = _resolve_font(card, scratch)
            for entry in cards:
                try:
                    _card_layout(plan, entry, font, scratch)
                except ProductionError as exc:
                    problems.append((entry["shot_id"], str(exc)))
        return problems

    def render(self, plan: dict, job_directory: Path, output_path: Path) -> dict:
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            raise ProductionError("FFmpeg and ffprobe must be installed to render")
        if not plan["segments"]:
            raise ProductionError("No segments in render plan")
        if output_path.suffix.lower() != ".mp4":
            raise ProductionError("Output must be an .mp4 file")
        root = job_directory.resolve()
        output_path = output_path.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        audio_sources = _audio_sources(plan, root)
        effects = _segment_effects(plan)
        loudness = None

        with tempfile.TemporaryDirectory(prefix="videogenome-") as directory:
            scratch = Path(directory).resolve()
            has_cards = any(s["kind"] == "motion_graphics" for s in plan["segments"])
            has_captions = bool((plan.get("timeline") or {}).get("captions"))
            font = _resolve_font(plan["title_card"], scratch) if has_cards or has_captions else None
            font_option = font["option"] if font else "font=Sans"
            clips, layouts = [], []
            for index, (segment, effect) in enumerate(zip(plan["segments"], effects)):
                clip = scratch / f"clip_{index:04d}.mkv"
                layout = _render_segment(plan, segment, effect, root, clip, scratch, font)
                if layout:
                    layouts.append(layout)
                clips.append(clip)
            assembled = scratch / "assembled.mkv"
            _assemble(plan, clips, effects, assembled, scratch)
            finished = scratch / "finished.mp4"
            if "loudness" in plan["output"]:
                mixed = scratch / "mixed.mkv"
                _finish_timeline(plan, assembled, audio_sources, mixed, scratch, font_option)
                loudness = _master_loudness(plan, mixed, finished)
            else:
                _finish_timeline(plan, assembled, audio_sources, finished, scratch, font_option)
            shutil.copy2(finished, output_path)

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
        if font:
            font = {k: v for k, v in font.items() if k != "option"}
        return {
            "renderer": {"name": "videogenome-ffmpeg", "version": __version__,
                         "ffmpeg": _ffmpeg_version()},
            "frames_observed": actual_frames,
            "duration_expected_seconds": expected,
            "duration_observed_seconds": actual,
            "verified": ["output_exists", "container_readable", "resolution", "frame_count",
                         "duration_tolerance", "title_safe_width"],
            "loudness_normalization": loudness,
            "font": font,
            "title_layout": layouts,
        }


def render(plan: dict, job_directory: Path, output_path: Path, *,
           write_deliverables: bool = True, profile=None) -> dict:
    """Render with a pipeline profile (default: FFmpeg + measurements + sidecars)."""
    from videogenome.pipeline import run_render
    from videogenome.profile import Profile
    return run_render(plan, job_directory, output_path, profile or Profile.load(),
                      write_deliverables=write_deliverables)
