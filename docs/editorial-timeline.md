# Audio and captions on a locked timeline

Blueprint schema **0.2.0** adds an optional `timeline` for overlapping audio and
burned-in captions over the existing sequential picture track. The job still
uses schema **0.1.0**: fillers supply declared copy and cleared audio/image/video
assets through `inputs`, `assets` and `shot_assets`. They cannot change timing,
gains, fades, caption limits or the source-audio policy.

Existing 0.1.0 blueprints and jobs continue to compile and render. They keep IR
0.1.0; blueprints with a timeline produce IR 0.2.0. Older compilers reject the
new blueprint version rather than silently discarding its editorial decisions.
The older `output.captions` flag alone remains descriptive; 0.2.0 requires actual
caption cues when that flag is true. No jobs or old templates are migrated.

## Run the complete example

With the development requirements, FFmpeg and ffprobe installed:

```bash
python -m videogenome inspect educational.captioned-explainer
python -m tools.create_editorial_demo -o /tmp/vg-editorial
python -m videogenome compile /tmp/vg-editorial/job.json -o /tmp/vg-editorial/plan.json
python -m videogenome render /tmp/vg-editorial/job.json \
  -o /tmp/vg-editorial/demo.mp4 --receipt /tmp/vg-editorial/receipt.json

# A contrasting brief uses the exact same locked template.
python -m tools.create_editorial_demo --brief learning -o /tmp/vg-learning
python -m videogenome render /tmp/vg-learning/job.json \
  -o /tmp/vg-learning/demo.mp4 --receipt /tmp/vg-learning/receipt.json
```

Both outputs are 640×360 at 24 FPS, eight seconds long. The generator creates an
original geometric image and two calibration tones, with no downloads or API
calls. The tones demonstrate music/narration placement; **they are not speech or
finished music**. The 220 Hz source has a one-second silent lead-in that the
template trims. A 660 Hz source enters at two seconds, overlaps the music and
ends at six seconds. Real productions can fill these same slots with approved
recordings without changing renderer code.

The generated source files have accurate, self-attested provenance referring to
the repository's MIT-licensed generator. Human gates are left unevaluated. Do not
reuse these provenance records when substituting your own recordings.

CI renders both briefs and uploads `videogenome-editorial-examples` containing
the MP4s, compiled plans and receipts for human review.

## Audio tracks

An expert blueprint can declare:

```json
{
  "timeline": {
    "source_audio": "preserve",
    "source_audio_gain_db": 0,
    "audio_tracks": [
      {
        "id": "music_bed",
        "input_ref": "music",
        "start_frame": 0,
        "duration_frames": 192,
        "in_frame": 24,
        "gain_db": -18,
        "fade_in_frames": 12,
        "fade_out_frames": 24
      }
    ]
  }
}
```

`music` must be a declared input of type `audio`. The job binds it to an asset
ID such as `"inputs": {"music": "approved_music"}`; the asset has the same
local-path, origin and rights requirements as picture media.

| Field | Meaning |
| --- | --- |
| `start_frame` | Inclusive position on the global picture timeline |
| `duration_frames` | Positive length; the track cannot extend past the picture |
| `in_frame` | Source trim offset, measured at the **output** FPS; defaults to 0 |
| `gain_db` | Fixed gain from −60 to +12 dB; defaults to 0 |
| `fade_in_frames` / `fade_out_frames` | Linear amplitude fades inside the track; default 0; their sum cannot exceed its length |
| `source_audio` | Preserve embedded clip sound (default) or mute it |
| `source_audio_gain_db` | Fixed gain on preserved clip sound; defaults to 0 |

Up to 32 additional tracks may overlap or cross picture cuts. IDs must be
unique. Tracks reference actual, sufficiently long audio; there is no implicit
looping or silent replacement for missing media. Sources are checked for an
audio stream, duration and matching compilation hash before picture rendering.

The adapter resamples to stereo 48 kHz, maps frame positions to the nearest
sample (ties round up), applies trims/gain/fades, delays each track, then mixes
without automatic volume normalization. A 0.95-peak limiter with compensated
latency protects the PCM mix from overload; AAC encoding can alter peaks.
This is not loudness mastering or automatic dialogue ducking. Set sensible
gains and listen to the entire result.

Timeline intermediates use PCM audio to avoid per-shot AAC encoder-delay gaps.
The finished video is encoded as H.264/AAC. Exact output bytes can vary with
FFmpeg and font versions; timing and media hashes are explicit.

## Caption cues

Captions belong to the blueprint timeline, not to arbitrary job overrides:

```json
{
  "captions": {
    "style": {
      "font_size": 20,
      "margin_x": 24,
      "margin_bottom": 24,
      "max_chars_per_line": 28,
      "max_lines": 2,
      "max_chars_per_second": 20
    },
    "cues": [
      {"id": "intro", "start_frame": 12, "duration_frames": 60,
       "text_template": "{{caption_intro}}"}
    ]
  }
}
```

This object goes inside `timeline`, and `output.captions` must be true. Cues use
global frame positions with an exclusive end, so a cue may continue across a
picture cut. Overlapping cues and cues outside the picture are rejected.

The compiler resolves declared text slots, collapses whitespace and wraps at
word boundaries. It rejects empty copy, oversized words, too many lines and
copy exceeding the blueprint's characters-per-second limit (including spaces).
The author must provide a conservative horizontal safe area using a full-em
width per character plus caption-box padding. The maximum caption block must
fit vertically. These are layout constraints, not certification of readable
translation, font coverage, caption accuracy or accessibility.

The adapter draws centered white sans-serif text on translucent black boxes,
with a six-pixel line gap. Text is read from generated files with drawtext
expansion disabled. Percent signs and FFmpeg-looking expressions remain
literal. There is no automatic transcription, alignment, karaoke timing,
language detection or sidecar subtitle export.

## Evidence and remaining limits

Receipts include the executed timeline, original source hashes and provenance,
planned/observed frame counts, output hash and container duration. Production
checks enforce frame count, resolution and duration; template quality gates
retain their existing self-attested or unevaluated status.

Integration tests decode the real output to verify overlapping tone levels,
trim/start/end timing, fades, preserved/muted source sound, caption frame
boundaries across a cut and caption placement. They also check missing,
incompatible, uncleared, changed and short audio inputs. These fixture checks
do not automatically certify arbitrary production media.

Picture remains a single sequential track. Transitions, overlays other than
captions, speech synthesis, provider generation, automatic mixing and formal
human approval workflows remain outside this implementation.
