"""Genome library, number grounding, browser runtime (libraries, audio), MCP server and Studio."""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from tests.test_plugins import write
from videogenome.compiler import ProductionError
from videogenome.genomes import genome_errors, library
from videogenome.mcp_server import TOOLS, Server
from videogenome.profile import Profile
from videogenome.service import Service, Workspace, capture_page

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
HAS_BROWSER = bool(importlib.util.find_spec("playwright"))

CARD = {
    "schema_version": "0.5.0", "id": "test.card", "version": "1.0.0", "title": "Card", "category": "test",
    "description": "One title card for service tests",
    "inputs": {"title": {"type": "string", "required": True, "description": "Card text"},
               "year": {"type": "number", "required": False, "fill": "verbatim", "description": "A year"}},
    "style": {"mood": "plain", "palette": ["#101010", "#FFFFFF"], "typography": "sans", "pacing": "measured"},
    "output": {"width": 576, "height": 320, "fps": 24, "captions": False},
    "engines": ["ffmpeg"], "rules": {"allow_scene_reordering": False, "locked_elements": ["scenes"]},
    "scenes": [{"id": "s", "role": "card", "duration_frames": 24, "shots": [{
        "id": "card", "kind": "motion_graphics", "duration_frames": 24, "engine_hint": "ffmpeg",
        "direction": {"action": "Show the title", "text_template": "{{title}}"}}]}],
    "quality_gates": [{"id": "review", "mode": "human", "description": "Someone watches it"}],
}


def service(root: Path) -> Service:
    write(root / "templates" / "card" / "blueprint.json", CARD)
    return Service(Profile.load(), Workspace(root / "ws"), template_dirs=[root / "templates"])


class GenomeTests(unittest.TestCase):
    def test_levels_are_derived_from_what_exists(self) -> None:
        rows = {row["id"]: row for row in library()}
        self.assertEqual(rows["kinetic-type"]["level"], "template")
        self.assertEqual(rows["ambient-backdrop"]["level"], "code")
        self.assertEqual(rows["physics-sim"]["level"], "prompt")
        self.assertTrue(all(Path(row["prompt_path"]).is_file() for row in rows.values()))

    def test_invalid_genomes_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "demo"
            folder.mkdir()
            (folder / "prompt.md").write_text("too short")
            data = {"genome_schema": "0.1.0", "id": "other", "title": "Demo", "family": "data",
                    "summary": "A demo class used only in tests here.", "formats": ["16:9"], "prompt": "prompt.md",
                    "recipes": ["scene.missing"], "templates": ["nope.nope"]}
            errors = " ".join(genome_errors(data, folder))
            for expected in ("must match id", "too short", "unknown recipe", "unknown template"):
                self.assertIn(expected, errors)


class GroundingTests(unittest.TestCase):
    def test_numbers_in_the_brief(self) -> None:
        from videogenome.fill import numbers_in
        found = numbers_in("Revenue grew 42% to $1,250,000 in 2025; 3.5k users and twelve countries.")
        for value in (42, 1_250_000, 2025, 3.5, 3500, 12):
            self.assertIn(float(value), found)

    def test_verbatim_numbers_must_be_stated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            s = service(Path(directory))
            ok = s.check_inputs("test.card", {"title": "Founded", "year": 1998}, "Founded in 1998.")
            self.assertTrue(ok["ok"], ok)
            bad = s.check_inputs("test.card", {"title": "Founded", "year": 1999}, "Founded in 1998.")
            self.assertIn("not stated in the brief", bad["issues"][0]["problem"])
            unverified = s.check_inputs("test.card", {"title": "Founded", "year": 1999})
            self.assertTrue(unverified["ok"])
            self.assertEqual(unverified["verbatim_unverified"], ["year"])


@unittest.skipUnless(HAS_FFMPEG, "FFmpeg required")
class McpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.server = Server(service(Path(self.directory.name)))

    def tearDown(self) -> None:
        self.directory.cleanup()

    def rpc(self, method: str, params: dict | None = None) -> dict:
        return self.server.handle({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})

    def tool(self, tool_name: str, **arguments) -> tuple[dict, object]:
        result = self.rpc("tools/call", {"name": tool_name, "arguments": arguments})["result"]
        text = result["content"][0]["text"]
        return result, (text if result["isError"] else json.loads(text))

    def test_handshake_tools_and_prompts(self) -> None:
        init = self.rpc("initialize", {"protocolVersion": "2025-06-18"})["result"]
        self.assertEqual(init["serverInfo"]["name"], "videogenome")
        self.assertIn("VERBATIM", init["instructions"])
        self.assertIsNone(self.server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertEqual({t["name"] for t in self.rpc("tools/list")["result"]["tools"]}, {t["name"] for t in TOOLS})
        for tool in TOOLS:  # No tool lets an agent pick a pipeline, provider or command.
            self.assertFalse({"pipeline", "provider", "command", "endpoint"} & set(tool["inputSchema"]["properties"]))
        prompts = self.rpc("prompts/list")["result"]["prompts"]
        self.assertIn("author-physics-sim", {p["name"] for p in prompts})
        text = self.rpc("prompts/get", {"name": "author-physics-sim"})["result"]["messages"][0]["content"]["text"]
        self.assertIn("fixed-timestep", text)
        self.assertEqual(self.rpc("nope")["error"]["code"], -32601)

    def test_agent_writes_checks_and_renders(self) -> None:
        _, info = self.tool("template", id="test.card")
        self.assertIn("title", info["slots"])
        _, check = self.tool("check_inputs", template="test.card", inputs={"title": "x" * 400})
        self.assertFalse(check["ok"])
        result, summary = self.tool("render", template="test.card", inputs={"title": "Hello from an agent"},
                                    name="agent")
        self.assertFalse(result["isError"], summary)
        self.assertTrue(Path(summary["output"]).is_file())
        self.assertTrue(Path(summary["review_page"]).is_file())
        self.assertIn("image", [c["type"] for c in result["content"]])  # Contact sheet for vision agents.
        receipt = json.loads(Path(summary["receipt"]).read_text())
        self.assertEqual(receipt["fill"]["writer"]["name"], "agent (MCP)")
        failed, message = self.tool("render", template="test.card", inputs={"nope": "x"})
        self.assertTrue(failed["isError"])
        self.assertIn("not a text slot", message)
        _, runs = self.tool("runs")
        self.assertEqual(runs[0]["template"], "test.card")


@unittest.skipUnless(HAS_FFMPEG and HAS_BROWSER, "FFmpeg and playwright required")
class BrowserRuntimeTests(unittest.TestCase):
    def test_shared_libraries_modules_and_web_audio(self) -> None:
        page = """<!doctype html><html><body style="margin:0"><canvas id="c" width="64" height="64"></canvas>
<script type="module">
import * as vg from "/_lib/vg-scene/vg-scene.js";
import { colour } from "./part.mjs";
const c = document.getElementById("c").getContext("2d");
let ctx = null;
document.addEventListener("click", () => {
  ctx = new AudioContext();
  for (const at of [0.5, 1.0]) {
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.connect(g); g.connect(ctx.destination); g.gain.value = 0.4;
    o.start(ctx.currentTime + at); o.stop(ctx.currentTime + at + 0.1);
  }
});
vg.loop((t) => { c.fillStyle = colour; c.fillRect(0, 0, 64, 64); });
</script></body></html>"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write(root / "page.html", page)
            write(root / "part.mjs", 'export const colour = "#00FF00";')
            output = root / "out.mp4"
            info = capture_page(root / "page.html", output, size="64x64", fps=10, duration=1.5, click=True)
            self.assertEqual(info["frames"], 15)
            self.assertEqual(info["audio"], "recorded")
            log = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(output), "-af",
                                  "silencedetect=n=-40dB:d=0.2", "-f", "null", "-"],
                                 capture_output=True, text=True).stderr
            ends = [float(x.split("silence_end: ")[1].split()[0]) for x in log.splitlines() if "silence_end" in x]
            self.assertAlmostEqual(ends[0], 0.5, delta=0.02)   # The first beep lands on virtual time.
            self.assertAlmostEqual(ends[1], 1.0, delta=0.02)

    def test_pages_cannot_read_outside_their_folder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write(root / "secret.txt", "s3cret")
            write(root / "site" / "page.html", """<!doctype html><body style="margin:0"><canvas id="c" width="32" height="32"></canvas><script>
fetch("../secret.txt").then(r => r.ok ? r.text() : "blocked").catch(() => "blocked").then(t => {
  const c = document.getElementById("c").getContext("2d");
  c.fillStyle = t === "blocked" ? "#0000FF" : "#FF0000"; c.fillRect(0, 0, 32, 32); });
</script></body>""")
            output = root / "still.png"
            capture_page(root / "site" / "page.html", output, size="32x32", at=0.5, audio=False)
            pixel = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(output), "-f", "rawvideo",
                                    "-pix_fmt", "rgb24", "-"], capture_output=True).stdout[:3]
            self.assertGreater(pixel[2], 200)
            self.assertLess(pixel[0], 50)

    def test_recipe_scaffold_renders(self) -> None:
        from videogenome.authoring import scaffold_recipe
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "scene" / "demo"
            scaffold_recipe("scene.demo", folder)
            manifest = json.loads((folder / "recipe.json").read_text())
            self.assertEqual(manifest["timing"], "clock")
            output = Path(directory) / "demo.png"
            capture_page(folder / "index.html", output, size="320x180", at=1.0)
            self.assertGreater(output.stat().st_size, 1000)
            with self.assertRaises(ProductionError):
                scaffold_recipe("Bad Id", Path(directory) / "x")


class StudioTests(unittest.TestCase):
    def test_token_host_and_file_confinement(self) -> None:
        from http.server import ThreadingHTTPServer
        from videogenome.studio import Studio
        with tempfile.TemporaryDirectory() as directory:
            studio = Studio(service(Path(directory)), port=0)
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), studio.handler())
            studio.port = httpd.server_address[1]
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            base = f"http://127.0.0.1:{studio.port}"

            def get(path: str, headers: dict | None = None) -> tuple[int, bytes, dict]:
                request = urllib.request.Request(base + path, headers=headers or {})
                try:
                    with urllib.request.urlopen(request) as response:
                        return response.status, response.read(), dict(response.headers)
                except urllib.error.HTTPError as exc:
                    return exc.code, exc.read(), dict(exc.headers)
            try:
                self.assertEqual(get("/")[0], 403)
                self.assertEqual(get("/api/state")[0], 403)
                self.assertEqual(get(f"/?token={studio.token}", {"Host": "evil.example"})[0], 421)
                status, _, headers = get(f"/?token={studio.token}")
                self.assertEqual(status, 200)
                self.assertIn("HttpOnly", headers["Set-Cookie"])
                cookie = {"Cookie": headers["Set-Cookie"].split(";")[0]}
                status, body, _ = get("/api/state", cookie)
                self.assertEqual(json.loads(body)["pipeline"], "default")
                self.assertEqual(get("/files/../../etc/passwd", cookie)[0], 404)
                status, body, _ = get("/api/template/test.card", cookie)
                self.assertIn("title", json.loads(body)["slots"])
            finally:
                httpd.shutdown()
                httpd.server_close()


if __name__ == "__main__":
    unittest.main()
