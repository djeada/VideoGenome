# Authoring prompt: narrated illustrated slides

Build a narrated slide explainer: title, 3-5 slides each with an image, one or
two narrated sentences and a caption that matches the narration, and a closing
line. Images move gently (push-in or pan), captions stay in a safe band, music
ducks under the voice, and each slide's length is set by the narration budget.
Expose scripts and image descriptions as slots; images and voices are produced
by the pipeline or supplied.

**House rules.** `"timing": "clock"` with the `vg-scene` toolkit (`videogenome recipe-new`);
every on-screen string is a bounded param drawn with `fillText` and fitted with
`vg.fit` (throw when it cannot fit); ink chosen with `vg.readable`; layout from
`W`, `H` and `unit` so 16:9, 9:16 and 1:1 work, with copy kept out of the top 12%
and bottom 22% in 9:16; seeded randomness only; no network; at least three
finished presets. Facts a writer could invent (names, numbers, dates, quotes)
become `fill: "verbatim"` template slots.

**Checks.** Render each preset at 1080x1920 and 1920x1080, build contact sheets
every 1-1.5 s and look at them; wire a template with sound cued to the beats;
confirm the loudness, true-peak and no-dead-picture gates pass; fill it from two
briefs with a small local writer.
