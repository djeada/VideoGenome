"""Scaffold new scene recipes that already follow every recipe rule.

``videogenome recipe-new scene.my-reveal -o recipes/scene/my-reveal`` writes a
working clock-timed page on the vg-scene toolkit (measured text fitting,
contrast-safe colour, grain) and a manifest whose parameters are bounded and
documented. Preview it with ``videogenome capture``, then replace the drawing
code with the scene you want.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from videogenome.compiler import ProductionError

RECIPE_ID = re.compile(r"^[a-z][a-z0-9]*\.[a-z0-9][a-z0-9.-]*$")

PAGE = """<!doctype html>
<!--
  {title}: describe what the viewer sees here, beat by beat.

  Timing: clock. Animate with requestAnimationFrame, performance.now, timers or
  CSS/WAAPI animations; VideoGenome's virtual clock makes every frame exact.
  Parameters arrive in window.vgSpec.params. Draw copy with fillText, fit it
  with vg.fit (it throws when copy cannot fit), never use innerHTML for copy.
-->
<html>
<head>
<meta charset="utf-8">
{importmap}</head>
<body>
<script type="module">
{imports}import * as vg from "../../_lib/vg-scene/vg-scene.js";

const {{ P, W, H, D, unit, portrait }} = vg.setup({{
  title: "Your title here", palette: ["#0E1116", "#F2F4F7", "#3DDC97"], grain: 0.03,
}});
const [BG, INK, ACCENT] = P.palette;
{body}
</script>
</body>
</html>
"""

CANVAS_BODY = """const ctx = vg.canvas2d();
const title = vg.fit(ctx, P.title, {
  maxSize: unit * (portrait ? 0.11 : 0.12), minSize: unit * 0.04, weight: 800,
  maxWidth: W * 0.8, maxLines: 3, label: "title",
});
const ink = vg.readable(BG, [INK, "#FFFFFF", "#000000"]);

vg.loop((t) => {
  ctx.fillStyle = BG; ctx.fillRect(0, 0, W, H);
  vg.dotGrid(ctx, t, INK);
  const rise = vg.tween(t, 0.2, 0.9, vg.ease.outExpo);
  const top = (H - title.height) / 2 + (1 - rise) * title.size * 0.6;
  vg.drawLines(ctx, title, W / 2, top, { color: ink, align: "center", alpha: rise });
  const rule = vg.tween(t, 0.6, 0.8, vg.ease.outExpo);
  ctx.fillStyle = ACCENT;
  ctx.fillRect(W / 2 - title.width * 0.25 * rule, top + title.height + title.size * 0.3,
               title.width * 0.5 * rule, Math.max(4, title.size * 0.06));
  vg.grain(ctx, t, P.grain);
});
"""

THREE_IMPORTMAP = """<script type="importmap">
{"imports": {"three": "../../_lib/three/three.module.min.js", "three/addons/": "../../_lib/three/addons/"}}
</script>
<style>html, body { margin: 0; overflow: hidden; background: #000; }</style>
"""

THREE_IMPORTS = """import * as THREE from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
"""

THREE_BODY = """const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
renderer.setSize(W, H);
renderer.toneMapping = THREE.ACESFilmicToneMapping;
document.body.appendChild(renderer.domElement);
const scene = new THREE.Scene();
scene.background = new THREE.Color(BG);
scene.environment = new THREE.PMREMGenerator(renderer).fromScene(new RoomEnvironment(), 0.04).texture;
const camera = new THREE.PerspectiveCamera(35, W / H, 0.1, 100);
const hero = new THREE.Mesh(new THREE.TorusKnotGeometry(0.8, 0.28, 220, 32),
  new THREE.MeshPhysicalMaterial({ color: ACCENT, roughness: 0.3, metalness: 0.1, clearcoat: 1 }));
scene.add(hero);

vg.loop((t) => {
  const orbit = t * 0.35;
  camera.position.set(Math.sin(orbit) * 5, 1.2, Math.cos(orbit) * 5);
  camera.lookAt(0, 0, 0);
  hero.rotation.y = t * 0.6;
  renderer.render(scene, camera);
});
"""


def recipe_manifest(recipe_id: str, three: bool) -> dict:
    title = recipe_id.split(".", 1)[1].replace("-", " ").capitalize()
    return {
        "recipe_schema": "0.1.0", "id": recipe_id, "version": "0.1.0",
        "title": f"{title} (scaffold)",
        "description": "Describe the shot: what appears, how it moves, and what the parameters control.",
        "media": ["video", "image"], "runtime": "browser", "entry": "index.html", "timing": "clock",
        "libraries": ["vg-scene", *(["three"] if three else [])],
        "params": {"type": "object", "additionalProperties": False, "properties": {
            "title": {"type": "string", "minLength": 1, "maxLength": 48, "default": "Your title here",
                      "description": "On-screen title"},
            "palette": {"type": "array", "minItems": 3, "maxItems": 3,
                        "items": {"type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"},
                        "default": ["#0E1116", "#F2F4F7", "#3DDC97"], "description": "Ground, ink and accent"},
            "grain": {"type": "number", "minimum": 0, "maximum": 0.12, "default": 0.03,
                      "description": "Film grain amount"}}},
        "presets": {"default": {}},
        "tags": ["scene", "scaffold"], "license": "MIT", "authors": ["Your name"],
        "notes": ["Scaffolded by `videogenome recipe-new`; replace the drawing code and this description."],
        "cost": {"seconds_per_output_second": 2.0},
    }


def scaffold_recipe(recipe_id: str, directory: Path, *, three: bool = False) -> list[Path]:
    if not RECIPE_ID.match(recipe_id):
        raise ProductionError("Recipe ids look like area.name, e.g. scene.my-reveal")
    if directory.exists() and any(directory.iterdir()):
        raise ProductionError(f"Refusing to write into non-empty directory {directory}")
    directory.mkdir(parents=True, exist_ok=True)
    title = recipe_id.split(".", 1)[1].replace("-", " ").capitalize()
    page = PAGE.format(title=title, importmap=THREE_IMPORTMAP if three else "",
                       imports=THREE_IMPORTS if three else "", body=THREE_BODY if three else CANVAS_BODY)
    written = [directory / "index.html", directory / "recipe.json"]
    written[0].write_text(page, encoding="utf-8")
    written[1].write_text(json.dumps(recipe_manifest(recipe_id, three), indent=2) + "\n", encoding="utf-8")
    return written
