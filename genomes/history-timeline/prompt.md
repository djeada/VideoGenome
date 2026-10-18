# Authoring prompt: history timeline with a travelling camera

Build a VideoGenome scene recipe (`recipes/scene/<name>/`, `"timing": "clock"`,
library `vg-scene`) for a history piece of 3-7 dated events.

**What the viewer sees.** A kicker and title rise in, then slide into a
header while a long horizontal axis draws itself. The world is wider than
the frame: events sit at positions along the axis and the camera glides from
one to the next (ease in-out, with a slow drift during each hold so the frame
never freezes). As it moves, tick marks and year labels stream past, the
travelled part of the axis turns to the accent colour, and a large, faint
odometer-style year counter rolls through the years in between. When the
camera arrives, a pin drops onto the axis with a ripple, a stem grows and a
card lands: the date exactly as given (large, accent), a headline, and an
optional one-line note. The previous card dims and slides out of view. A small
progress track with one dot per event fills underneath. At the end the camera
zooms the axis out until every event fits, the cards give way to the pins and
their dates, every pin lights in a wave, and a summary line lands.

**Beat structure.** Intro about 12% of the duration, outro about 18%, equal
beats per event; the move into an event takes about 30% of its beat and ends
as the card lands. Document landing times, move midpoints and the zoom-out so
templates cue clicks, whooshes and a swell.

**Dates.** Draw them verbatim. Parse a year from each (the first 3-6 digit
run, negative for BC/BCE) only to place ticks and drive the counter; if any
date has no year or the years go backwards, fall back to plain ticks and no
counter. Choose tick intervals per segment from a "nice" list so ticks stay
readable whether a segment spans 2 or 2,000 years.

**Parameters.** `title`, `kicker`, `dates` (maxLength 18), `labels`
(maxLength 34), `notes` (maxLength 52), `summary`, `spacing` (even or
proportional with a minimum gap), a five-colour `palette` (ground, ink,
accent, paper, muted), `grid`, `grain`. Ship four presets (archive sepia,
museum ivory, space midnight, civic teal).

**Rules.** One size for all dates, one for all headlines, one for all notes,
fitted with `vg.fit`; throw if a card would not fit between the header and
the axis. Pick ink with `vg.readable` against the card tint. In 9:16 keep copy
between 12% and 78% of the height. Bake the ground once, seeded randomness only,
no network. Templates must mark every date `fill: "verbatim"`.

**Checks.** Render each preset at 1080x1920 and 1920x1080 with 3 and 7
events, long labels and notes, BC dates, and dates with no year; build contact
sheets every second and look at the landings, the moves and the final
overview. Then confirm loudness, true-peak and no-dead-picture gates pass.
