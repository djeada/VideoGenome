# Delivery formats: one job, several aspect ratios (schema 0.6.0)

A video usually ships to more than one place: a 16:9 cut for YouTube or a
website, a 9:16 cut for Reels, Shorts and TikTok, a 1:1 cut for feeds. In
VideoGenome these are **formats of one template**, rendered from **one job**
with the same copy, timing, sound and gates. Nothing is cropped from a master:
each format is laid out again by its renderer at its own frame size.

## In a blueprint

The blueprint's `output` is its main format. `output.formats` lists the other
aspect ratios the template is authored and reviewed for, keyed by aspect id:

~~~json
"output": {
  "width": 1080, "height": 1920, "fps": 30, "captions": false,
  "loudness": {"target_lufs": -14, "max_true_peak_dbtp": -1.0},
  "formats": {
    "16x9": {"width": 1920, "height": 1080},
    "1x1":  {"width": 1080, "height": 1080}
  }
}
~~~

* The key must equal the reduced ratio of the size (`16x9`, `9x16`, `1x1`,
  `4x5`), must not repeat the main format, and sizes must be even.
* A format may restate the **pixel-valued typography** that cannot scale on
  its own: `title_card` (font sizes, line count, safe margins) and
  `caption_style` (font size, margins, characters per line, lines). Everything
  else (palette, story, timing, audio, loudness, poster frame, gates) is
  shared, because a format is the same video, not a different one.
* Every format is validated on its own: `python -m tools.validate` re-checks
  caption safe areas, title-card margins and every `copy_examples` entry at
  each format's size and reports problems as `format 9:16: ...`.
* Copy contracts are the tightest across formats, so copy that passes
  `check_inputs` or a writer's fill renders in every format.

List a format only after looking at it. Code-rendered scenes lay themselves
out for any frame, but "renders" is not "looks right": render the sample job
in every format and review the frames (see [checks](#checks)).

## In a job

Jobs need nothing new. Pick formats when you render:

~~~bash
videogenome make job.json --pipeline procedural --format all -o promo.mp4
# promo.9x16.mp4  promo.16x9.mp4  promo.1x1.mp4, each with its own receipt,
# gates, poster, contact sheet and review page

videogenome make job.json --pipeline procedural --format 1:1 -o square.mp4
# one format: written exactly to -o
~~~

`--format` repeats, takes comma lists, `9:16` or `9x16`, and `all`; the default
is the job's own `format` field, else the main format. `validate`, `compile`,
`render`, `produce` and `create` take it too.

Produced media is made per format: the main format's media goes to
`generated/`, another format's to `generated/<format>/`, and the produced job
(`job.9x16.produced.json`) records `"format": "9x16"`. Media that does not
depend on the frame (music, sound effects, narration) is produced once and
reused by every format. A job holding produced media renders only in the format
it was produced for; ask `make` for another format instead of re-rendering it.

Receipts carry `"format"`, and an automated gate that fails in any format
fails the run (exit status 3) and is reported per format.

## Layout checks for code-rendered scenes

Scene recipes measure their copy with real glyphs and throw when it cannot fit
the frame. The **layout check** loads each scene a job would produce, with the
exact params and frame size a render would use, steps its clock through the
programme without capturing frames, and reports what the page threw, for every
format, in a few seconds:

* `check_inputs` with `layout: true` (always on for MCP agents, on the Studio's
  *Check my copy* button, and before every Studio or MCP render).
* Writers filling a template (`fill`, `create`, Studio *Write my copy*) get
  layout problems back as revision requests, naming the slot and format:
  `in the 1:1 format: scene (scene.stat-reveal): label 1 "..." does not fit`.
* It runs only when the operator's pipeline renders recipes with the
  procedural provider; otherwise the result says it was not checked.
  It needs Playwright and Chromium, like any browser recipe.

## Cockpits

* **CLI:** `--format` as above; `videogenome catalog --table` lists every
  template's formats, and `--orientation portrait` matches any template that
  renders a portrait format.
* **Studio:** templates with several formats show a *Deliver in* picker; one
  render produces each chosen format and the result lets you switch between them.
* **MCP:** `template` returns `formats`; `render` and `check_inputs` accept
  `formats` (e.g. `["all"]`); the render result lists every format and returns
  one contact sheet per format.

## Checks

Before adding a format to a template:

~~~bash
python -m tools.validate                                   # every format validates
videogenome make examples/my-template/job.json --pipeline procedural --format all -o out/scene.mp4
python -m unittest tests.test_formats                      # samples and copy examples fit every format
~~~

Then look at each format's frames. When a format fails or looks wrong, fix
the recipe's layout for that frame shape (a square is not a short portrait: it
needs neither the 9:16 platform-UI reserve nor a three-column layout) or leave
the format out. `educational.chart-story` offers 16:9 and 9:16 only, because its
title, subtitle and takeaway leave no room for a chart in a square.

## Limits

* Footage and stills follow each shot's `fit` (`cover` crops the centre,
  `contain` letterboxes). There is no subject-aware reframing yet, so templates
  built on filmed media should list extra formats only with a human framing gate.
* Loudness targets are shared across formats; platforms normalise playback.
* The layout check catches copy that a scene refuses to set; it does not judge
  composition. Review the frames.
