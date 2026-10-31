# Authoring a video class: genome, scene recipe, template

This guide turns one class of video (a data story, a 3D product hero, a
countdown) into something anyone can generate from a brief. Read
[procedural recipes](procedural-recipes.md) and [briefs and writers](briefs-and-writers.md) first.

## What goes where

| Artifact | Path | What it is | Who changes it at job time |
|---|---|---|---|
| **Genome** | `genomes/<id>/genome.json` + `prompt.md` | The class: what viewers see, formats, links to its code and templates, and an authoring prompt for building new variations | Nobody |
| **Recipe** (ready code) | `recipes/scene/<name>/` | A clock-timed HTML scene with typed, bounded params and presets | Params only, within the schema |
| **Template** (ready to fill) | `templates/<category>/<name>/blueprint.json` | Locks the recipe's look, timing, sound cues and gates; opens typed slots | Slot values only |
| **Sample job** | `examples/<name>/job.json` | A filled job that renders with `--pipeline procedural` | — |
| **Bench briefs** | `examples/briefs/<genome>.json` | Realistic briefs (including one that lacks a required fact) | — |

A genome's level is derived from what exists: `template` > `code` > `prompt`.

## Recipe rules (ready code)

Start from the scaffold: `videogenome recipe-new scene.my-scene -o recipes/scene/my-scene`
(add `--three` for WebGL 3D). It is a working page on the `vg-scene` toolkit
(`recipes/_lib/vg-scene/vg-scene.js`): `setup`, `canvas2d`, `loop`, `fit`,
`drawLines`, `readable`, `tween`, `ease`, `spring`, `rng`, `grain`,
`vignette`, `dotGrid`, `roundRect`, `beats`, `formatNumber`. Three.js 0.169 is
vendored at `_lib/three` with bloom, glTF loading and a room environment.

1. **Timing.** `"timing": "clock"`. Animate with `requestAnimationFrame`,
   `performance.now`, timers or CSS/WAAPI; never measure real time any other
   way. Derive every beat from `D = spec.duration_seconds` (use `vg.beats`) so
   the scene fits any template length, and document the beat times so
   templates can cue sound to them.
2. **Any aspect ratio.** Lay out from `W`, `H` and `unit = min(W, H)`. Check
   16:9, 9:16 and 1:1. In 9:16 keep copy out of the top 12% and bottom 22%,
   where platform UI sits. A square is its own shape, not a short portrait or a
   narrow landscape: it needs neither that reserve nor side columns a third of
   the frame wide. Every param value the schema allows must fit every shape, or
   the page must throw.
3. **Copy.** Every on-screen string is a param with `maxLength`. Draw it with
   `fillText` (never `innerHTML`) and fit it with `vg.fit`, which balances
   lines and **throws** when copy cannot fit. Never shrink text below
   legibility (about `unit * 0.03`). Hold every line long enough to read (at
   least 1.5 s, and about 15 characters per second).
4. **Colour.** A `palette` param, with ink chosen by `vg.readable` (4.5:1
   against its ground) so no preset produces unreadable text.
5. **Determinism.** Randomness only from `vg.rng(spec.seed + k)` or the seeded
   `Math.random`. The same spec must render the same frames.
6. **Offline.** No network, CDN or web fonts. Load data the page needs as a sibling ES module
   (`import { land } from "./land.js"`) or `await` it before drawing: the clock starts when the
   page has loaded, and a `fetch()` still in flight then is not waited for. Inter comes from the system;
   ship any other asset inside the recipe directory.
7. **Params.** Every property has a type, bounds, a default and a description.
   Ship at least three named presets that each look finished, and data params
   (numbers, labels) as arrays with `minItems`/`maxItems`.
8. **Performance.** Aim for at most 4 s of render per output second at
   1080×1920 in 2D, and 8 s in 3D (software WebGL). Keep geometry modest,
   precompute what you can, and avoid per-frame allocation.
9. **Craft.** Motion should read as designed: eased entrances with overlap
   and stagger, anticipation and settle, one focal point per beat, a clear
   rhythm. Avoid the AI giveaways people complain about: text and frames
   jammed into corners, generic purple gradients, everything moving at once,
   and unreadable flashes.

## Template rules (ready to fill)

* Schema `0.6.0`, `kind: "animation"`, `engine_hint: "browser"`, `fit: "cover"`.
  List every aspect ratio you have rendered and reviewed in `output.formats`
  ([delivery formats](delivery-formats.md)); one job then renders them all.
  The scene is a producible `video` input whose `produce.request` names the
  recipe, its preset (`"{{look}}"` from an enum input) and params mapped from
  slots (`"{{headline}}"`, or arrays such as `["{{stat_1}}", "{{stat_2}}"]`;
  a whole-value `"{{n}}"` keeps numbers numeric).
* Every fact a writer could invent is `fill: "verbatim"`: names, quotes,
  numbers, dates, prices, places. Creative copy stays `write`.
* Add one to three `copy_examples` on a different topic from the sample job.
  `python -m tools.validate` checks them like a writer's reply.
* Sound comes from audio recipes on the timeline, cued to the scene's beats
  (`audio.pulse`, `audio.lofi-beat`, `audio.ambient-pad`, `audio.transition`
  presets `whoosh`, `riser`, `impact`, `swell`, `soft-click`...). Master social
  9:16 to -14 LUFS and everything else to -16, with `programme_loudness` and
  `true_peak_headroom` gates. Use `no_dead_picture` unless the class has a
  deliberate hold on a flat ground. Add human gates for what only people can
  judge (accuracy of data, brand approval, claims).
* `rules.notes` say what is locked, how copy is fitted, and where the sound cues sit.

## Genome

`genome.json` (schema `schemas/genome.schema.json`) names the family, formats,
typical durations, recipes, templates, what a user must bring, and honest
limits. `prompt.md` is the authoring prompt for this class, at least 120 words.
A frontier model (or a person) should be able to follow it to build a *new*
recipe in the class: the look, motion grammar, beat structure, params to
expose, the rules above, and the checks to run. It must not paste
someone else's published prompt.

## Checks before you call it done

~~~bash
python -m tools.validate                                     # blueprints, copy examples, recipes, genomes
videogenome recipe scene.my-scene --preset P --size 1080x1920 --duration 10 -o p.mp4   # every preset
videogenome recipe scene.my-scene --size 1920x1080 --duration 10 -o l.mp4
ffmpeg -i p.mp4 -vf "select='not(mod(n\,45))',scale=360:-2,tile=6x1" -frames:v 1 sheet.jpg
videogenome make examples/my-template/job.json --pipeline procedural --format all -o out.mp4   # every format, all gates pass
python -m unittest tests.test_formats                        # samples and copy examples fit every format
videogenome fill my.template --pipeline procedural-writer --brief "..." -o job.json # a local writer can fill it
~~~

Look at the contact sheets yourself. Measurements prove timing and loudness,
not taste.
