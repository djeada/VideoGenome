# Authoring prompt: code snippet reveal

Build a VideoGenome scene recipe (`recipes/scene/<name>/`, `"timing": "clock"`,
library `vg-scene`) that reveals a short program in a self-contained editor.

**What the viewer sees.** A title, then an editor window (title bar, file tab,
line-number gutter) that scales in. The code types itself with a believable
rhythm: the editor auto-indents, characters inside a word come faster than
after punctuation, each Enter is followed by a short pause to think, and closing
brackets and quotes arrive quickly. A cursor is solid while typing and blinks
when idle. Tokens are coloured as they appear by a small tokenizer you write
(keywords, builtins, strings, numbers, comments, calls, types, operators; Rust
macros, Bash variables and flags). Then the key lines light up with a band and
an accent bar while the rest dims; a dark terminal panel slides up, the run
command types, the supplied output lands line by line; finally the title gives
way to a one-line takeaway. The code is drawn as text and never executed.

**Beat structure.** Intro 1 s; typing fills the window up to D minus the tail;
highlight, terminal and takeaway beats follow at fixed offsets (shrink them in
proportion only when D is short). Generate the typing schedule as relative
delays from a seeded RNG, then scale it to the window so any code length lands
on the same beats. Document the beat times for sound cues.

**Parameters to expose.** `title`, `filename`, `language` (enum), `code` and
`output` as multi-line strings (bounded by a pattern, checked line by line in
the page), `highlight` line numbers and `highlight_text` snippets (fail when a
snippet is not in the code), `command`, `takeaway`, a five-colour `palette`, a
seven-colour `syntax` palette, `pace` and `grain`. Ship dark, light (with a dark
terminal), phosphor and warm presets.

**Rules.** Measure the monospace advance once and fit the font to the longest
line and the available height; never go below about 2.6% of the short side,
throw instead. Lay out from `W`, `H`, `unit`: portrait stacks title, editor and
terminal; landscape sets the title beside the editor and lets the terminal
overlap its lower corner. Keep copy out of the top 12% and bottom 22% in 9:16.
Seeded randomness only; no network.

**Checks.** Render every preset in both aspects with a short and a 14-line
snippet in each language; look at the typing frames, the highlight, the
terminal and the takeaway. Run the sample code yourself and paste its real
output. Then make the sample jobs and pass the automated gates.
