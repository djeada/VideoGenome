# Authoring prompt: brand title sting

Build a brand title sting: a name (1-22 characters) and an optional tagline.
The name should *arrive*: letters converge from depth, assemble from strokes, or
unfold from a shape; a single impact moment (flash ring, particles, camera punch)
marks the landing at about 25% of the duration, then a light sweep or gloss pass
and a quiet hold for the tagline. Expose `name`, `tagline`, a three-colour
`palette`, a `finish` enum (chrome, flat, glow), `tempo` and particle count.
Document the landing time so templates can lock a riser and an impact to it.

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
