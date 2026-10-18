# Authoring prompt: kinetic typography reel

Build a VideoGenome scene recipe (`recipes/scene/<name>/`, `"timing": "clock"`,
library `vg-scene`) for a kinetic typography reel of 2-6 short phrases.

**What the viewer sees.** One phrase per beat, set large in a heavy sans. Words
enter one after another (rise through a line mask, slide, or scale from a
baseline), holding long enough to read: at least 1.5 seconds per phrase and
about 15 characters per second. A single graphic element runs through the
whole piece and carries the cuts, for example a dot that lands as the full
stop and then expands to become the next ground, a bar that wipes, or a shape
that morphs. Keep one focal point per beat. No text in the corners, no
generic gradients, no everything-moves-at-once.

**Beat structure.** Split `spec.duration_seconds` into equal beats with
`vg.beats`; entrance in the first 25% of a beat, transition in the last 15-20%.
Document the transition times, because templates cue whooshes to them.

**Parameters to expose.** `phrases` (array of 1-6 strings, `maxLength` 48),
`palette` (ground, ink, accent), `align`, `weight`, `tempo` (0.6-1.8),
`grain`, and a switch for emphasising the final word. Ship at least four
presets (for example light Swiss, dark neon, ink, calm).

**Rules.** Draw copy with `fillText` and fit each phrase with `vg.fit`
(balanced lines, throw when it cannot fit). Choose ink with `vg.readable` so
every ground keeps 4.5:1 contrast, and switch the emphasis colour when it
would not. Treat a trailing period as the dot itself, and do not draw a dot
after `?` or `!`. Lay out from `W`, `H` and `unit` so 9:16, 16:9 and 1:1 all
work, keeping copy out of the top 12% and bottom 22% in 9:16. Use only seeded
randomness and no network.

**Checks.** Render every preset at 1080x1920 and 1920x1080 for 9-10 s, build
contact sheets every 1.5 s, and look at them: entrances, holds, the cut
frames, the final frame. Then wire it into a template with a pulse bed and
whooshes on the cuts, and confirm loudness, true-peak and no-dead-picture
gates pass.
