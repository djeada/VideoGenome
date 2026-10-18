# Authoring prompt: physics simulation loop

Build a physics simulation scene that is satisfying to watch and repeatable:
step a fixed-timestep solver (Verlet or impulse-based) from frame time only,
never from wall-clock deltas, so frame N always shows the same state; derive
the initial layout from the seed. Choose one clear setup (balls into a
container that spells a word, a chain catenary, a Newton's cradle, a marble
run), give it a camera and lighting that make contact moments readable, and
add an optional title and caption. Expose body count, gravity, restitution,
palette and the title. Precompute the simulation once and index frames into it
so any frame renders without re-simulating.

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
