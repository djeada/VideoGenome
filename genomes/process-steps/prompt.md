# Authoring prompt: step-by-step explainer

Build a process explainer for 3-6 ordered steps. A title states the outcome;
each step lands in turn (node pops with a spring, label slides in, a one-line
note fades in), the active step is clearly highlighted while finished ones dim
and show a check, and the last beat brings everything back as a recap. Lay out
as a vertical list in 9:16 and a two-column title/list composition in 16:9.
Expose `title`, `steps`, `notes`, a four-colour `palette` and a recap switch;
fit all labels at one shared size so the list reads calmly.

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
