# Authoring prompt: route map journey

Build a VideoGenome scene recipe (`recipes/scene/<name>/`, `"timing": "clock"`,
library `vg-scene`) that tells a journey of 2-5 stops on a map.

**What the viewer sees.** A map that settles on the whole route while the title
rises and the stops pop in. For each leg the camera eases (inOutCubic, zoom
interpolated in log space) to frame the leg, a marker travels along it with an
eased start and stop, and the travelled part of the route is drawn solid over a
quiet dashed preview of what is ahead. On arrival a ripple fires and a stop card
(index chip, name, optional one-line note) springs in next to the stop, then
folds into a small label. Counters for distance and duration run while the
marker moves and land exactly on the stated totals. The outro pulls back to the
whole route with every stop labelled. One focal point per beat: the moving
marker, then the card.

**Geography, honestly.** Ship real coastlines only from public-domain data
inside the recipe directory (Natural Earth is public domain), simplified by a
script you also ship, with source, version, hash and licence in the manifest
notes. Load it as a sibling ES module so it is ready before the first frame.
Never zoom past what the data can show. If you cannot ship real data, draw an
abstract map and say so. Never compute or claim a road distance: show the
numbers the brief states.

**Beat structure.** Intro about 10% of D, outro about 20%, legs share the rest;
departure at 10% of a leg, arrival at 60%. Document these times, because a
template cues whooshes and clicks to the ones that do not depend on the stop
count.

**Parameters to expose.** `title`, `stops`, `notes`, `lat`, `lon` (arrays,
2-5), `distance`, `duration` with unit enums, counter `labels`, `path`
(arc, straight), `marker` (dot, plane), `land` (fill, dots, none), `borders`,
a six-colour `palette` and `grain`. Ship four presets: a light atlas, a dark
dot-matrix, a dark transit look and a sea-and-sand voyage.

**Rules.** Copy with `fillText`, fitted by `vg.fit` (throw when it cannot fit).
Choose ink with `vg.readable`. Place cards and labels against the safe area, each
other, the marker and the drawn route; skip a label rather than overlap it. In
9:16 keep copy out of the top 12% and bottom 22%. Unwrap longitudes so a leg
crosses the Pacific the short way. Seeded randomness only; no network.

**Checks.** Render every preset at 1080x1920 and 1920x1080 with short (2 stops),
long (5 stops across an ocean) and island routes; look at contact sheets and
single frames at the arrivals; confirm stops sit on land and counters end on the
stated totals; then make the sample job and pass loudness, true-peak and
no-dead-picture gates.
