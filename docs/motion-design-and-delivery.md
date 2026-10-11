# Motion design, transitions, mastering and executed QA (schema 0.3.0)

Schema **0.3.0** is a superset of 0.2.0. It adds five optional, renderer-neutral
contracts, all owned by the template author and locked against job overrides:

| Contract | Where | What the FFmpeg adapter does |
|---|---|---|
| Title-card typography | `style.title_card`, `direction.kicker_template` | Pins one font file, fits copy with measured glyphs, draws kicker + lines + accent rule with staggered entrances |
| Picture transitions | `timeline.transitions`, `timeline.fade_in_frames`, `timeline.fade_out_frames` | Frame-exact crossfades (with source handles) and dips through a colour |
| Loudness delivery | `output.loudness` | Two-pass EBU R128 normalisation; video is stream-copied in the second pass |
| Machine-checked gates | `quality_gates[].check` | Measures the output and marks the gate `passed`, `failed` or `not_applicable` |
| Review sidecars | `output.poster_frame` (optional) | Writes SRT/WebVTT, a poster frame and a per-shot contact sheet |

Using any of these fields with `schema_version` 0.1.0 or 0.2.0 is a validation
error, so older compilers never silently ignore them. Existing 0.1/0.2
templates render as before, except that over-long title copy now wraps (or is
rejected) instead of running off the frame.

## Title cards

~~~json
"title_card": {
  "font_family": "Inter", "font_weight": "bold", "align": "left",
  "font_size": 104, "min_font_size": 64, "max_lines": 5, "line_spacing": 1.08,
  "safe_margin_x": 96, "safe_margin_top": 288, "safe_margin_bottom": 480,
  "background": "#0E0F13", "text_color": "#F5F5F0", "accent_color": "#FF5A36",
  "accent_bar": true, "kicker_font_size": 48, "entrance": "rise", "entrance_frames": 12
}
~~~

* Colours must be members of `style.palette`; the validator rejects off-brand values.
* `font_family` is restricted to letters, digits and spaces and resolved through
  fontconfig to **one file**, which is copied into the render sandbox, hashed and
  recorded in the receipt. If the family is not installed the receipt marks
  `"substituted": true` and the CLI prints a warning. `videogenome doctor` checks
  every catalog font in advance.
* Copy fitting happens twice. The **compiler** estimates glyph advance, picks the
  largest size between `font_size` and `min_font_size` that fits `max_lines` and
  the safe area, and balances line breaks to avoid orphans. Copy that cannot fit
  is rejected with an actionable message, so a small model gets feedback before
  any media work. The **renderer** then measures every line by decoding an actual
  drawtext frame, and may only shrink (never re-wrap) until the ink fits. Planned
  and executed sizes and measured widths are recorded under `title_layout`.
* `kicker_template` (motion-graphics shots only) is a small accent-coloured line
  above the headline, such as `"01 / 03"`. It accepts `{{slot}}` text inputs.
* Text is placed on a fixed baseline grid (`y_align=baseline`, FFmpeg 6.1+), so
  line positions do not depend on which letters a line contains.
* Entrances are `none`, `fade` or `rise`, eased and staggered per line. The accent
  rule fades in with the copy.

## Transitions and programme fades

~~~json
"timeline": {
  "fade_in_frames": 8, "fade_out_frames": 16,
  "transitions": [
    {"after_shot": "headline_card", "kind": "dip", "duration_frames": 12, "color": "#14202E"},
    {"after_shot": "live_clip", "kind": "crossfade", "duration_frames": 8}
  ]
}
~~~

Transitions never change the programme length or any shot's start frame:

* **dip**: the outgoing shot fades to `color` over its last ⌈d/2⌉ frames and the
  incoming shot fades up over its first ⌊d/2⌋. Embedded audio fades with it.
  For type-only sequences, dipping through the background colour reads as
  "text out, text in" and avoids two layers of copy overlapping.
* **crossfade**: the incoming shot's first *d* frames are blended over a *handle*
  of *d* extra frames rendered past the outgoing shot's end. Cards and stills
  get handles for free; for video the source must contain them, otherwise the
  render fails with "needs … including any crossfade handle". Embedded audio
  crossfades sample-exactly.
* The validator rejects transitions after unknown or final shots, duplicates, and
  any combination of fades that leaves a shot without a clean frame.

## Loudness mastering

~~~json
"output": {"loudness": {"target_lufs": -14, "max_true_peak_dbtp": -1.0}}
~~~

After mixing, the adapter runs FFmpeg `loudnorm` analysis, then a second, linear
pass using the measured values. The receipt records the input loudness and
whether FFmpeg could stay linear (`normalization_type`). A silent programme
(at or below -70 LUFS) is not normalised and is reported as `skipped`. Common targets: -14 LUFS
for social platforms, -16 for podcasts and web, -23 (EBU R128) or -24 (ATSC
A/85) for broadcast.

## Executed measurements and machine-checked gates

Every render measures the finished file with fixed, documented detectors:

| Measurement | Detector |
|---|---|
| `integrated_lufs`, `loudness_range_lu`, `true_peak_dbtp` | `ebur128=peak=true` |
| `black_seconds` | `blackdetect=d=0.1:pix_th=0.10:pic_th=0.98` |
| `blank_seconds`, `longest_blank_seconds` | frames whose luma range is ≤ 12 (nothing visible, any background colour) |
| `longest_silence_seconds` | `silencedetect=n=-50dB:d=0.25` |

`blackdetect` counts a frame as black when 98% of its pixels are near black. A
dark-background card whose text covers less than 2% of the frame therefore
counts as "black". To detect dead picture, use `longest_blank_seconds` instead.

An automated gate becomes executable by naming one of these metrics:

~~~json
{"id": "programme_loudness", "mode": "automated",
 "description": "Integrated loudness within 1 LU of -14 LUFS.",
 "check": {"metric": "integrated_lufs", "min": -15, "max": -13}}
~~~

Gate statuses in the receipt:

| Status | Meaning |
|---|---|
| `passed` / `failed` | The metric was measured on the output; `evidence` holds the value and bounds |
| `not_applicable` | A loudness metric on a silent programme |
| `not_evaluated` | No machine check exists, e.g. aesthetic or storytelling judgement |
| `self_attested_approved` | A human gate listed in the job's `approved_gates` (self-attested, not verified) |

`videogenome render` exits with status **3** when any automated gate fails. It keeps the
output and receipt for inspection. Checks only allow `min` and `max` on these
metrics; nothing in a blueprint is executed as code.

## Review sidecars

Unless `--no-deliverables` is passed, the renderer writes next to `OUTPUT.mp4`:

* `OUTPUT.srt` and `OUTPUT.vtt`: the compiled caption cues with the same line
  breaks as the burned-in captions and millisecond timestamps derived from frames
  (only when the blueprint has captions),
* `OUTPUT.poster.jpg`: `output.poster_frame`, or two-thirds into the first shot,
* `OUTPUT.contact.jpg`: one tile per shot, sampled after entrances complete.

Each sidecar is hashed in the receipt. Sidecars are decoded from the verified output,
never rendered separately, and may not overwrite a source asset.

## Limits

* Glyph estimates assume Latin-script, mixed-case copy. Capitals and wide
  scripts are caught by measurement and shrink the type, but complex-script
  shaping and right-to-left layout are not reviewed.
* Only `fade`-style crossfades are offered. Wipes, pushes, motion blur and
  beat-synced cuts remain planned.
* Loudness and blank-picture checks are technical signals, not proof of a good
  mix or a good edit. Human gates remain necessary.
