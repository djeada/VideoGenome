"""Writers, brief filling, create, review pages, virtual-clock capture and scene recipes."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from tests.test_plugins import FAKE_TTS, RIGHTS, _Server, write
from videogenome import plugins
from videogenome.blueprint import validate_blueprint
from videogenome.compiler import ProductionError, find_template, read_json
from videogenome.create import FillIncomplete, create
from videogenome.fill import Filler, check_values, parse_reply, response_schema, slot_contracts
from videogenome.plugins import PluginError, Writer, Written
from videogenome.produce import CopyTooLong, produce
from videogenome.profile import Profile
from videogenome.review import review_html
from videogenome.writers import CommandWriter, OpenAIChatWriter, transcript

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
HAS_BROWSER = bool(importlib.util.find_spec("playwright"))


class ScriptedWriter(Writer):
    """Replies from a queue; records what it was asked."""

    summary = "test writer"
    queue: list[str] = []
    seen: list[list[dict]] = []

    def write(self, system: str, messages: list[dict], schema: dict) -> Written:
        type(self).seen.append([dict(m) for m in messages])
        if not type(self).queue:
            raise PluginError("scripted writer ran out of replies")
        return Written(type(self).queue.pop(0), {"model_id": "scripted"})


def reply(inputs: dict, missing: list | None = None) -> str:
    return json.dumps({"inputs": inputs, "missing": missing or []})


def blueprint(template_id: str) -> tuple[dict, Path]:
    path = find_template(template_id)
    return read_json(path), path


def filler(template_id: str, brief: str, replies: list[str], **options) -> Filler:
    ScriptedWriter.queue = list(replies)
    ScriptedWriter.seen = []
    data, path = blueprint(template_id)
    return Filler(data, path, ScriptedWriter("scripted", {}), brief=brief, **options)


TIPS_BRIEF = ("Reel for runners: warm up for five minutes, increase weekly distance by at most ten percent, "
              "and rest one day a week. End by asking viewers to save it.")
GOOD_TIPS = {"hook": "Run longer without injury", "tip_1": "Warm up for five minutes before every run.",
             "tip_2": "Add at most ten percent distance per week.", "tip_3": "Take one full rest day each week.",
             "cta": "Save this for your next run"}


class SlotContractTests(unittest.TestCase):
    def test_budgets_come_from_the_locked_blueprint(self) -> None:
        slides = slot_contracts(blueprint("educational.narrated-slides")[0])
        # 5.5 s narration slot at 2.5 words/s, and a caption reading-speed limit.
        self.assertEqual(slides["slide_1_script"]["max_words"], 13)
        self.assertTrue(any("caption" in use for use in slides["slide_1_script"]["uses"]))
        self.assertNotIn("slide_1_image", slides)  # Media is never written.
        kinetic = slot_contracts(blueprint("social.kinetic-promo")[0])
        self.assertEqual(kinetic["hook"]["max_chars"], 48)  # From the recipe's param schema.
        self.assertTrue(kinetic["hook"]["on_screen"])
        self.assertEqual(kinetic["look"]["enum"], ["swiss", "neon", "ink", "calm"])
        sting = slot_contracts(blueprint("commercial.title-sting")[0])
        self.assertEqual(sting["name"]["mode"], "verbatim")
        schema = response_schema(sting)
        # Every required slot must be present; a verbatim one may be null when the brief lacks it.
        self.assertEqual(schema["properties"]["inputs"]["required"], ["name", "tagline"])
        self.assertEqual(schema["properties"]["inputs"]["properties"]["name"]["type"], ["string", "null"])

    def test_shipped_copy_examples_pass_the_writer_checks(self) -> None:
        for template_id in ("social.vertical-tips", "social.kinetic-promo", "educational.steps-explainer",
                            "commercial.title-sting", "social.ugc-testimonial"):
            data, _ = blueprint(template_id)
            self.assertTrue(data["copy_examples"], template_id)
            self.assertEqual(validate_blueprint(data), [], template_id)

    def test_bad_examples_are_rejected(self) -> None:
        data, _ = blueprint("commercial.title-sting")
        data["copy_examples"][0]["inputs"]["name"] = "Day Shift"
        data["copy_examples"][0]["inputs"]["tagline"] = "Fast 🚀"
        errors = " ".join(validate_blueprint(data))
        self.assertIn("VERBATIM", errors)
        self.assertIn("cannot draw", errors)
        data, _ = blueprint("social.vertical-tips")
        data["schema_version"] = "0.4.0"
        self.assertTrue(any("0.5.0" in e for e in validate_blueprint(data)))

    def test_short_verbatim_values_match_whole_words_only(self) -> None:
        from videogenome.fill import _appears_in
        self.assertTrue(_appears_in("M", "Revenue reached $860M last year."))
        self.assertFalse(_appears_in("M", "Meet the team in March."))
        self.assertFalse(_appears_in("vol", "Our volunteers sort food."))

    def test_grounded_values_must_sit_next_to_their_label(self) -> None:
        data = json.loads(json.dumps(blueprint("social.vertical-tips")[0]))
        data["inputs"]["share"] = {"type": "number", "required": False, "fill": "verbatim",
                                   "grounded_with": "mode", "description": "A share"}
        data["inputs"]["mode"] = {"type": "string", "required": False, "fill": "verbatim", "description": "A mode"}
        brief = ("Commute survey of 2025: bus 34 percent of trips. " + "Filler words go here. " * 8
                 + "Lakeside station opened.")
        contracts = slot_contracts(data)
        ok = check_values(data, contracts, {"share": 34, "mode": "bus"}, brief)
        self.assertFalse([i for i in ok if "share" in i["slots"]], ok)
        bad = check_values(data, contracts, {"share": 2025, "mode": "Lakeside"}, brief)
        self.assertTrue(any("not next to" in i["problem"] for i in bad))

    def test_reply_parsing_tolerates_fences_and_prose(self) -> None:
        self.assertEqual(parse_reply('```json\n{"inputs": {}}\n```'), {"inputs": {}})
        self.assertEqual(parse_reply('Sure! {"inputs": {"a": 1}} done'), {"inputs": {"a": 1}})
        with self.assertRaises(ValueError):
            parse_reply("no json here")


class FillerTests(unittest.TestCase):
    def test_complete_on_first_reply(self) -> None:
        result = filler("social.vertical-tips", TIPS_BRIEF, [reply({**GOOD_TIPS, "energy": "upbeat"})]).run()
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.job["inputs"]["tip_2"], GOOD_TIPS["tip_2"])
        self.assertEqual(result.job["template_version"], "0.2.0")
        self.assertEqual(result.job["assets"], {})
        self.assertEqual(result.job["approved_gates"], [])  # A writer never approves anything.
        record = result.record
        self.assertEqual(record["status"], "complete")
        self.assertEqual(len(record["attempts"]), 1)
        self.assertEqual(record["brief_sha256"], hashlib.sha256(TIPS_BRIEF.encode()).hexdigest())

    def test_the_prompt_carries_contracts_examples_and_the_brief_as_data(self) -> None:
        f = filler("social.vertical-tips", TIPS_BRIEF, [reply(GOOD_TIPS)])
        f.run()
        prompt = ScriptedWriter.seen[0][0]["content"]
        self.assertIn("used as: headline of title card tip_1_card", prompt)
        self.assertIn("EXAMPLE BY THE TEMPLATE'S AUTHOR", prompt)
        self.assertIn("Stop burning your garlic", prompt)
        self.assertIn("<<<BRIEF\n" + TIPS_BRIEF + "\nBRIEF>>>", prompt)

    def test_overlong_copy_is_sent_back_with_the_problem(self) -> None:
        long_tip = "Warm up for five minutes before every single run " * 4
        f = filler("social.vertical-tips", TIPS_BRIEF, [reply({**GOOD_TIPS, "tip_1": long_tip}), reply(GOOD_TIPS)])
        result = f.run()
        self.assertEqual(result.status, "complete")
        self.assertEqual(len(result.record["attempts"]), 2)
        feedback = ScriptedWriter.seen[1][-1]["content"]
        self.assertIn("tip_1", feedback)
        self.assertIn("you wrote", feedback)

    def test_emoji_and_unknown_keys(self) -> None:
        f = filler("social.vertical-tips", TIPS_BRIEF,
                   [reply({**GOOD_TIPS, "cta": "Save this 🔥", "music": "x.wav"}), reply(GOOD_TIPS)])
        result = f.run()
        first = result.record["attempts"][0]
        self.assertEqual(first["ignored_keys"], ["music"])
        self.assertTrue(any("cannot draw" in i["problem"] for i in first["issues"]))
        self.assertEqual(result.status, "complete")
        self.assertNotIn("music", result.job["inputs"])

    def test_verbatim_slots_cannot_be_invented(self) -> None:
        brief = "Reveal for the Larkspur Lamp. Tagline: Light that follows the sun."
        f = filler("commercial.title-sting", brief,
                   [reply({"name": "Larkspur Lumina", "tagline": "Light that follows the sun"}),
                    reply({"name": "Larkspur Lamp", "tagline": "Light that follows the sun"})])
        result = f.run()
        self.assertIn("VERBATIM", result.record["attempts"][0]["issues"][0]["problem"])
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.job["inputs"]["name"], "Larkspur Lamp")

    def test_missing_facts_are_reported_not_guessed(self) -> None:
        brief = "Testimonial video for our accounting app. We have no transcript yet."
        f = filler("social.ugc-testimonial", brief,
                   [reply({}, [{"input": "hook_line", "reason": "no transcript"},
                               {"input": "testimonial_line", "reason": "no transcript"},
                               {"input": "cta", "reason": "no approved call to action"}])])
        result = f.run()
        self.assertEqual(result.status, "incomplete")
        self.assertEqual({m["input"] for m in result.missing}, {"hook_line", "testimonial_line", "cta"})
        self.assertEqual(len(result.record["attempts"]), 1)  # No retry that could invite fabrication.

    def test_writer_must_write_creative_slots_before_calling_them_missing(self) -> None:
        tips = {k: v for k, v in GOOD_TIPS.items() if k != "cta"}
        f = filler("social.vertical-tips", TIPS_BRIEF,
                   [reply(tips, [{"input": "cta", "reason": "brief has no CTA"}]), reply(GOOD_TIPS)])
        result = f.run()
        self.assertEqual(result.status, "complete")
        self.assertIn("yours to write", ScriptedWriter.seen[1][-1]["content"])

    def test_invalid_json_and_exhausted_attempts_fail(self) -> None:
        f = filler("social.vertical-tips", TIPS_BRIEF, ["not json", "still not json"], max_attempts=2)
        result = f.run()
        self.assertEqual(result.status, "failed")
        self.assertIn("not valid JSON", result.issues[0]["problem"])

    def test_pinned_inputs_are_kept_and_validated(self) -> None:
        f = filler("social.vertical-tips", TIPS_BRIEF, [reply(GOOD_TIPS)], pinned={"energy": "calm-tech"})
        self.assertNotIn("energy", f.contracts)
        self.assertEqual(f.run().job["inputs"]["energy"], "calm-tech")
        for bad in ({"energy": "loud"}, {"music": "track"}, {"nope": "x"}):
            with self.subTest(bad=bad), self.assertRaises(ProductionError):
                filler("social.vertical-tips", TIPS_BRIEF, [], pinned=bad)

    def test_check_values_uses_the_compiler_copy_fitting(self) -> None:
        data, _ = blueprint("educational.narrated-slides")
        contracts = slot_contracts(data)
        script = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen"
        issues = check_values(data, contracts, {"slide_1_script": script}, "brief")
        self.assertTrue(any("narration slot" in i["problem"] for i in issues))


class WriterAdapterTests(unittest.TestCase):
    def test_openai_chat_writer_sends_schema_and_reads_content(self) -> None:
        received = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                received.append((self.path, body))
                answer = {"model": "m", "choices": [{"finish_reason": "stop", "message": {
                    "content": "<think>plan</think>" + reply({"hook": "Hi"})}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
                data = json.dumps(answer).encode()
                self.send_response(200); self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

            def log_message(self, *args) -> None:
                pass

        server = _Server(Handler)
        try:
            writer = OpenAIChatWriter("w", {"base_url": server.url + "/v1", "model_id": "m"})
            written = writer.write("SYS", [{"role": "user", "content": "brief"}], {"type": "object"})
        finally:
            server.close()
        path, body = received[0]
        self.assertEqual(path, "/v1/chat/completions")
        self.assertEqual(body["messages"][0], {"role": "system", "content": "SYS"})
        self.assertEqual(body["response_format"]["type"], "json_schema")
        self.assertEqual(json.loads(written.text)["inputs"]["hook"], "Hi")  # Thinking stripped.
        self.assertEqual(written.metadata["completion_tokens"], 5)

    def test_command_writer_pipes_the_prompt_on_stdin_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            script = write(Path(directory) / "echo.py",
                           "import sys, json\ntext = sys.stdin.read()\n"
                           "print(json.dumps({'inputs': {'hook': str('BRIEF>>>' in text)}, 'missing': []}))\n")
            writer = CommandWriter("w", {"argv": ["{python}", str(script)]})
            written = writer.write("SYS", [{"role": "user", "content": "<<<BRIEF\nx\nBRIEF>>>"}], {})
            self.assertEqual(json.loads(written.text)["inputs"]["hook"], "True")
            with self.assertRaisesRegex(PluginError, "no placeholders"):
                CommandWriter("w", {"argv": ["tool", "{prompt}"]}).write("S", [], {})
        self.assertIn("### ASSISTANT", transcript("S", [{"role": "user", "content": "u"}], {}))

    def test_profiles_declare_and_inherit_a_writer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = write(Path(directory) / "p.json", {
                "pipeline_schema": "0.1.0", "id": "with-writer", "description": "procedural plus a writer",
                "verification": "unit test", "extends": "procedural",
                "writer": {"type": "openai-chat", "config": {"base_url": "http://127.0.0.1:9/v1", "model_id": "m"}}})
            profile = Profile.load(path)
            self.assertIsInstance(profile.writer(), OpenAIChatWriter)
            self.assertEqual(profile.describe()["writer"], "openai-chat")
            self.assertIn("procedural", profile.data["routes"])
            self.assertTrue(any(row[1] == "writer" for row in profile.check()))
        with self.assertRaisesRegex(PluginError, "has no writer"):
            Profile.load().writer()


NARRATED_CARD = {
    "schema_version": "0.5.0", "id": "test.narrated-card", "version": "1.0.0",
    "title": "Narrated card", "category": "test", "description": "A card with a two-second narration slot",
    "inputs": {
        "title": {"type": "string", "required": True, "description": "Card text"},
        "line": {"type": "string", "required": True, "description": "Spoken line"},
        "voice": {"type": "audio", "required": True, "description": "Narration",
                  "produce": {"capability": "speech", "request": {"text": "{{line}}"}}}},
    "style": {"mood": "plain", "palette": ["#101010", "#FFFFFF"], "typography": "sans", "pacing": "measured"},
    "output": {"width": 576, "height": 320, "fps": 30, "captions": False},
    "engines": ["ffmpeg"],
    "rules": {"allow_scene_reordering": False, "locked_elements": ["scenes"]},
    "scenes": [{"id": "s", "role": "card", "duration_frames": 60, "shots": [{
        "id": "card", "kind": "motion_graphics", "duration_frames": 60, "engine_hint": "ffmpeg",
        "direction": {"action": "Show the title", "text_template": "{{title}}"}}]}],
    "timeline": {"audio_tracks": [{"id": "vo", "input_ref": "voice", "start_frame": 0, "duration_frames": 60}]},
    "quality_gates": [{"id": "review", "mode": "human", "description": "Someone watches it"}],
}


@unittest.skipUnless(HAS_FFMPEG, "FFmpeg required")
class CreateTests(unittest.TestCase):
    def setUp(self) -> None:
        plugins.register("writer", "scripted", ScriptedWriter)
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.templates = self.root / "templates"
        write(self.templates / "card" / "blueprint.json", NARRATED_CARD)
        write(self.root / "tts.py", FAKE_TTS)  # 0.3 s of tone per word.
        self.profile_path = write(self.root / "profile.json", {
            "pipeline_schema": "0.1.0", "id": "test-create", "description": "fake TTS and a scripted writer",
            "verification": "unit test",
            "providers": {"tts": {"type": "command", "config": {
                "capabilities": ["speech"], "argv": ["{python}", "{profile_dir}/tts.py", "--out", "{output}"],
                "stdin": "{text}", "extension": ".wav", "output_rights": RIGHTS}}},
            "routes": {"speech": "tts"}, "writer": {"type": "scripted"}})

    def tearDown(self) -> None:
        plugins.unregister("writer", "scripted")
        self.directory.cleanup()

    def test_word_budget_then_measured_speech(self) -> None:
        self.assertEqual(validate_blueprint(NARRATED_CARD), [])
        # A 2 s slot allows 5 words; 8 words are refused before any speech is made.
        ScriptedWriter.queue = [reply({"title": "Hello", "line": "one two three four five six seven eight"}),
                                reply({"title": "Hello", "line": "one two three four five"})]
        ScriptedWriter.seen = []
        receipt, result, job_path = create("test.narrated-card", "Say hello in five words.",
                                           Profile.load(self.profile_path), self.root / "out" / "card.mp4",
                                           template_dirs=[self.templates], log=lambda _: None)
        self.assertEqual(result.job["inputs"]["line"], "one two three four five")
        self.assertIn("narration slot", ScriptedWriter.seen[1][-1]["content"])
        self.assertEqual(receipt["fill"]["status"], "complete")
        self.assertTrue((job_path.parent / "job.fill.json").is_file())
        self.assertTrue(Path(receipt["deliverables"]["review_page"]["path"]).is_file())
        # Produce measures the real speech: 8 words at 0.3 s each overrun the 2 s slot.
        job = read_json(job_path)
        job["inputs"]["line"] = "a b c d e f g h"
        write(job_path, job)
        with self.assertRaises(CopyTooLong) as caught:
            produce(job_path, Profile.load(self.profile_path), template_dirs=[self.templates], force=True)
        self.assertEqual(caught.exception.input, "voice")
        self.assertGreater(caught.exception.seconds, caught.exception.need)

    def test_create_revises_copy_after_measured_overrun(self) -> None:
        slow = json.loads(json.dumps(NARRATED_CARD))
        slow["id"] = "test.narrated-card-slow"
        for item in (slow["scenes"][0], slow["scenes"][0]["shots"][0], slow["timeline"]["audio_tracks"][0]):
            item["duration_frames"] = 90  # 3 s slot: a 7-word budget
        write(self.templates / "slow" / "blueprint.json", slow)
        # A slow voice (0.5 s per word): 7 words pass the budget but speak for 3.5 s.
        tts = self.root / "tts.py"
        tts.write_text(tts.read_text().replace("0.3 * 22050", "0.5 * 22050"))
        ScriptedWriter.queue = [reply({"title": "Hi", "line": "a b c d e f g"}),
                                reply({"title": "Hi", "line": "a b c d e"})]
        ScriptedWriter.seen = []
        logs: list[str] = []
        receipt, result, _ = create("test.narrated-card-slow", "Say hi.", Profile.load(self.profile_path),
                                    self.root / "slow.mp4", template_dirs=[self.templates], log=logs.append)
        self.assertTrue(any(line.startswith("Revise:") for line in logs))
        self.assertIn("rewrite it in at most", ScriptedWriter.seen[-1][-1]["content"])
        self.assertEqual(result.job["inputs"]["line"], "a b c d e")
        self.assertEqual(receipt["frames_observed"], 90)

    def test_incomplete_brief_stops_before_any_media(self) -> None:
        ScriptedWriter.queue = [reply({}, [{"input": "title", "reason": "x"}, {"input": "line", "reason": "y"}]),
                                reply({}, [{"input": "title", "reason": "x"}, {"input": "line", "reason": "y"}])]
        with self.assertRaises(FillIncomplete):
            create("test.narrated-card", "Nothing useful.", Profile.load(self.profile_path),
                   self.root / "x.mp4", template_dirs=[self.templates], log=lambda _: None)
        self.assertFalse((self.root / "x.job" / "generated").exists())


class ReviewPageTests(unittest.TestCase):
    def test_page_escapes_job_text_and_lists_pending_gates(self) -> None:
        receipt = {
            "job_id": "j<script>", "template_id": "t", "template_version": "1", "output_path": "/x/out.mp4",
            "duration_observed_seconds": 1.0, "frames_observed": 30, "frames_planned": 30,
            "measurements": {"integrated_lufs": -14.0}, "deliverables": {},
            "quality_gates": [{"id": "claims", "mode": "human", "status": "not_evaluated",
                               "description": "<img src=x onerror=alert(1)>"},
                              {"id": "loud", "mode": "automated", "status": "failed", "description": "d",
                               "evidence": {"metric": "integrated_lufs", "value": -20}}],
            "fill": {"brief": "</pre><script>alert(1)</script>", "writer": {"name": "w"}, "attempts": 1},
            "assets": {}, "caveats": ["c"],
        }
        page = review_html(receipt, Path("/x/out.review.html"))
        self.assertNotIn("<script>alert", page)
        self.assertNotIn("<img src=x", page)
        self.assertIn("Automated gate failed: loud", page)
        self.assertIn('src="out.mp4"', page)
        self.assertIn("Waiting for a human decision", page)


CLOCK_PAGE = """<!doctype html><html><body style="margin:0"><canvas id="c" width="64" height="64"></canvas>
<script>
const c = document.getElementById('c').getContext('2d');
const start = performance.now();
let late = false;
setTimeout(() => { late = true; }, 500);
function loop(now) {
  c.fillStyle = (now - start) < 250 ? '#FF0000' : late ? '#0000FF' : '#00FF00';
  c.fillRect(0, 0, 64, 64);
  requestAnimationFrame(loop);
}
requestAnimationFrame(loop);
</script></body></html>"""


@unittest.skipUnless(HAS_FFMPEG and HAS_BROWSER, "FFmpeg and playwright required")
class CaptureTests(unittest.TestCase):
    def capture(self, page: Path, output: Path) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "videogenome", "capture", str(page), "-o", str(output),
             "--size", "64x64", "--fps", "10", "--duration", "1"], capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def pixel(self, video: Path, frame: int) -> tuple[int, int, int]:
        raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(video), "-vf",
                              f"select=eq(n\\,{frame})", "-fps_mode", "passthrough", "-frames:v", "1",
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        middle = (32 * 64 + 32) * 3
        return tuple(raw[middle:middle + 3])

    def test_virtual_clock_drives_raf_timers_and_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            page = write(root / "page.html", CLOCK_PAGE)
            self.capture(page, root / "a.mp4")
            self.capture(page, root / "b.mp4")
            self.assertEqual((root / "a.mp4").read_bytes(), (root / "b.mp4").read_bytes())
            red, green, blue = self.pixel(root / "a.mp4", 1), self.pixel(root / "a.mp4", 3), self.pixel(root / "a.mp4", 8)
            self.assertGreater(red[0], 200)      # 0.1 s
            self.assertGreater(green[1], 200)    # 0.3 s: after 250 ms, before the 500 ms timer
            self.assertGreater(blue[2], 200)     # 0.8 s: the timer fired on virtual time

    def test_scene_recipes_render_without_page_errors(self) -> None:
        from videogenome.providers.procedural import ProceduralProvider
        provider = ProceduralProvider("procedural", {})
        for recipe in ("scene.kinetic-type", "scene.steps", "scene.title-sting"):
            with self.subTest(recipe=recipe), tempfile.TemporaryDirectory() as directory:
                result = provider.generate("procedural", {
                    "recipe": recipe, "media": "image", "width": 360, "height": 640, "fps": 24,
                    "duration_seconds": 4.0, "seed": 3}, Path(directory))
                self.assertGreater(result.path.stat().st_size, 1000)

    def test_text_that_cannot_fit_is_refused(self) -> None:
        from videogenome.providers.procedural import ProceduralProvider
        provider = ProceduralProvider("procedural", {})
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(PluginError, "too long"):
            provider.generate("procedural", {
                "recipe": "scene.kinetic-type", "media": "image", "width": 320, "height": 320, "fps": 24,
                "duration_seconds": 4.0, "params": {"phrases": ["W" * 48]}}, Path(directory))


if __name__ == "__main__":
    unittest.main()
