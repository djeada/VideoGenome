# Authoring prompt: game attract mode

Build a game in attract mode: the game plays itself with a seeded AI or a scripted
input track, so the same seed always produces the same run. Show the title,
the score rising, a few satisfying moments (combo, near-miss, power-up) and a
game-over or win card. Use juice: easing, screen shake on hits, particles,
pixel-perfect scaling for pixel art. Expose the title, palette, difficulty and
seed. The page must never wait for real input; a click-to-start page can be
captured with `videogenome capture --click`.

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
