"""Plugin architecture: registry, entry points, adapters, profiles and production."""
from __future__ import annotations

import base64
import json
import os
import shutil
import sys
import tempfile
import textwrap
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from tools.create_editorial_demo import write_tone
from videogenome import plugins
from videogenome.blueprint import validate_blueprint
from videogenome.compiler import ROOT, ProductionError, compile_job
from videogenome.pipeline import run_render
from videogenome.plugins import (
    Analyzer, PluginError, Renderer, available, check_request, load_type,
)
from videogenome.produce import produce
from videogenome.profile import Profile, discover_pipelines
from videogenome.providers.command import CommandProvider
from videogenome.providers.comfyui import ComfyUIProvider
from videogenome.providers.mcp import MCPProvider
from videogenome.providers.openai_compatible import OpenAICompatibleProvider

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
SLIDES_JOB = ROOT / "examples/narrated-slides/job.json"
RIGHTS = {"license": "MIT", "evidence": "synthetic test tool"}

# A fake TTS CLI: reads text on stdin, writes 0.3 s of tone per word.
FAKE_TTS = textwrap.dedent('''
    import math, struct, sys, wave
    out = sys.argv[sys.argv.index("--out") + 1]
    words = len(sys.stdin.read().split())
    if "--fail" in sys.argv:
        sys.exit("synthetic failure")
    with wave.open(out, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050)
        w.writeframes(b"".join(struct.pack("<h", int(6000 * math.sin(i / 7)))
                               for i in range(int(words * 0.3 * 22050))))
    print("args", sys.argv[1:])
''')

# A fake voice converter: copies --source to --out and records the voice it was given.
FAKE_VC = textwrap.dedent('''
    import shutil, sys
    args = sys.argv[1:]
    shutil.copyfile(args[args.index("--source") + 1], args[args.index("--out") + 1])
    open(args[args.index("--out") + 1] + ".voice", "w").write(args[args.index("--voice") + 1])
''')

# A minimal stdio MCP server with one tool that writes a tone file.
FAKE_MCP = textwrap.dedent('''
    import json, math, struct, sys, wave
    def send(message):
        sys.stdout.write(json.dumps(message) + "\\n"); sys.stdout.flush()
    print("server log line that is not JSON", flush=True)
    for line in sys.stdin:
        message = json.loads(line)
        method = message.get("method")
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": message["id"], "result": {"protocolVersion": "2025-06-18",
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "fake", "version": "1"}}})
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": message["id"], "result": {"tools": [{"name": "render_sound"}]}})
        elif method == "tools/call":
            args = message["params"]["arguments"]
            if args.get("fail"):
                send({"jsonrpc": "2.0", "id": message["id"],
                      "result": {"isError": True, "content": [{"type": "text", "text": "boom"}]}})
                continue
            with wave.open(args["path"], "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(48000)
                w.writeframes(b"".join(struct.pack("<h", int(5000 * math.sin(i / 9)))
                                       for i in range(int(float(args["seconds"]) * 48000))))
            send({"jsonrpc": "2.0", "id": message["id"],
                  "result": {"content": [{"type": "text", "text": "wrote " + args["label"]}]}})
''')


def write(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return path


class _Server:
    """Run a BaseHTTPRequestHandler subclass on an ephemeral localhost port."""

    def __init__(self, handler: type[BaseHTTPRequestHandler]) -> None:
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


class RegistryTests(unittest.TestCase):
    def test_builtins_cover_every_extension_point(self) -> None:
        self.assertTrue({"command", "openai-compatible", "comfyui", "mcp", "placeholder"}
                        <= set(available("provider")))
        self.assertIn("ffmpeg", available("renderer"))
        self.assertIn("ffmpeg", available("analyzer"))
        self.assertTrue({"subtitles", "poster", "contact_sheet"} <= set(available("exporter")))
        with self.assertRaisesRegex(PluginError, "No provider plugin type"):
            load_type("provider", "does-not-exist")

    def test_third_party_entry_points_are_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write(root / "vg_fake_plugin.py", textwrap.dedent('''
                from videogenome.plugins import Generated, Provider
                class EchoProvider(Provider):
                    summary = "test provider from an entry point"
                    capabilities = frozenset({"jingle"})
                    capability_specs = {"jingle": {"media": ["audio"], "description": "A short jingle",
                                                    "required": ["prompt"], "fields": {"prompt": "string"}}}
                    def generate(self, capability, request, workdir):
                        raise NotImplementedError
            '''))
            info = root / "vg_fake_plugin-1.0.dist-info"
            write(info / "METADATA", "Metadata-Version: 2.1\nName: vg-fake-plugin\nVersion: 1.0\n")
            write(info / "entry_points.txt", "[videogenome.providers]\necho = vg_fake_plugin:EchoProvider\n")
            sys.path.insert(0, directory)
            try:
                self.assertIn("entry point", available("provider")["echo"])
                cls = load_type("provider", "echo")
                self.assertEqual(cls.summary, "test provider from an entry point")
                # Loading the type registered its new capability contract.
                self.assertIn("jingle", plugins.CAPABILITIES)
                check_request("jingle", {"prompt": "upbeat", "media": "audio"})
            finally:
                sys.path.remove(directory)
                plugins.CAPABILITIES.pop("jingle", None)
                sys.modules.pop("vg_fake_plugin", None)

    def test_capability_requests_are_typed(self) -> None:
        check_request("speech", {"text": "Hello", "voice": "a", "media": "audio"})
        for request, message in (({"voice": "a"}, "requires 'text'"),
                                 ({"text": "x", "colour": "red"}, "unknown fields"),
                                 ({"text": "x", "speed": "fast"}, "must be number"),
                                 ({"text": "x\x00"}, "NUL"),
                                 ({"text": "x", "media": "video"}, "cannot produce video")):
            with self.subTest(request=request), self.assertRaisesRegex(PluginError, message):
                check_request("speech", request)
        with self.assertRaisesRegex(PluginError, "Unknown capability"):
            check_request("teleport", {})

    def test_register_rejects_wrong_interface(self) -> None:
        class NotAProvider(Analyzer):
            def measure(self, output, plan):
                return {}
        with self.assertRaisesRegex(PluginError, "does not implement Provider"):
            plugins.register("provider", "bad", NotAProvider)  # type: ignore[arg-type]


class CommandProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        write(self.root / "tts.py", FAKE_TTS)

    def provider(self, **config) -> CommandProvider:
        base = {"capabilities": ["speech"], "argv": ["{python}", "{profile_dir}/tts.py", "--out", "{output}"],
                "stdin": "{text}", "extension": ".wav", "output_rights": RIGHTS}
        return CommandProvider("tts", {**base, **config}, base_dir=self.root)

    def test_runs_without_a_shell_and_passes_text_on_stdin(self) -> None:
        work = self.root / "work"
        work.mkdir()
        result = self.provider().generate("speech", {"text": "one two three; rm -rf /"}, work)
        self.assertTrue(result.path.is_file())
        self.assertGreater(result.path.stat().st_size, 1000)

    def test_free_text_may_not_be_a_bare_positional(self) -> None:
        for argv in (["tool", "{text}"], ["tool", "--x", "{voice}", "{prompt}"], ["tool", "say:{text}"]):
            with self.subTest(argv=argv), self.assertRaisesRegex(PluginError, "option value"):
                CommandProvider("x", {"capabilities": ["speech"], "argv": argv, "extension": ".wav"})
        for argv in (["tool", "--text", "{text}"], ["tool", "--prompt={prompt}"], ["tool", "-f", "{text_file}"]):
            with self.subTest(argv=argv):
                CommandProvider("x", {"capabilities": ["speech"], "argv": argv, "extension": ".wav"})

    def test_executable_must_be_fixed(self) -> None:
        with self.assertRaisesRegex(PluginError, "executable must be fixed"):
            CommandProvider("x", {"capabilities": ["speech"], "argv": ["{voice}"], "extension": ".wav"})

    def test_optional_arguments_drop_with_their_flag(self) -> None:
        work = self.root / "work"
        work.mkdir()
        provider = self.provider(argv=["{python}", "{profile_dir}/tts.py", "--out", "{output}",
                                       "--model", "{references.model?}", "--voice", "{voice?}"])
        result = provider.generate("speech", {"text": "hi", "voice": "alto"}, work)
        self.assertEqual(result.metadata["executable"], "{python}")

    def test_failures_and_missing_output_are_explicit(self) -> None:
        work = self.root / "work"
        work.mkdir()
        failing = self.provider(argv=["{python}", "{profile_dir}/tts.py", "--out", "{output}", "--fail"])
        with self.assertRaisesRegex(PluginError, "synthetic failure"):
            failing.generate("speech", {"text": "x"}, work)
        silent = self.provider(argv=["{python}", "-c", "print('nothing written')"])
        with self.assertRaisesRegex(PluginError, "did not write"):
            silent.generate("speech", {"text": "x"}, work)


class HTTPProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_openai_compatible_speech_and_images(self) -> None:
        write_tone(self.root / "tone.wav", 300, 0.5)
        tone = (self.root / "tone.wav").read_bytes()
        png = base64.b64encode(b"\x89PNG\r\n\x1a\nnot-really").decode()
        seen = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:
                pass

            def do_POST(self) -> None:  # noqa: N802 - http.server API
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                seen.append((self.path, body, self.headers.get("Authorization")))
                payload = tone if self.path.endswith("/audio/speech") else json.dumps(
                    {"data": [{"b64_json": png}]}).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(payload)

        server = _Server(Handler)
        self.addCleanup(server.close)
        with mock.patch.dict(os.environ, {"TEST_KEY": "secret"}):
            provider = OpenAICompatibleProvider("kokoro", {
                "base_url": server.url + "/v1", "model_id": "kokoro", "api_key_env": "TEST_KEY"})
            speech = provider.generate("speech", {"text": "Hello there", "voice": "af_heart"}, self.root)
            image = provider.generate("image", {"prompt": "a lighthouse", "width": 640, "height": 360,
                                                "seed": 7}, self.root)
        self.assertEqual(speech.path.read_bytes(), tone)
        self.assertTrue(image.path.read_bytes().startswith(b"\x89PNG"))
        path, body, auth = seen[0]
        self.assertEqual((path, body["input"], body["voice"], body["model"], auth),
                         ("/v1/audio/speech", "Hello there", "af_heart", "kokoro", "Bearer secret"))
        self.assertEqual(seen[1][1]["size"], "640x360")
        with self.assertRaisesRegex(PluginError, "cannot serve"):
            provider.generate("video", {"prompt": "x"}, self.root)

    def test_endpoint_errors_are_reported(self) -> None:
        provider = OpenAICompatibleProvider("down", {"base_url": "http://127.0.0.1:9/v1", "model_id": "m"})
        with self.assertRaisesRegex(PluginError, "failed"):
            provider.generate("speech", {"text": "x"}, self.root)
        with self.assertRaises(PluginError):
            OpenAICompatibleProvider("bad", {"base_url": "file:///etc/passwd", "model_id": "m"})

    def test_comfyui_binds_inputs_queues_polls_and_downloads(self) -> None:
        workflow = {"3": {"class_type": "KSampler", "inputs": {"seed": 1}},
                    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "default"}},
                    "12": {"class_type": "WanVideo", "inputs": {"length": 1}},
                    "9": {"class_type": "SaveImage", "inputs": {}}}
        write(self.root / "wf.json", workflow)
        queued, polls = [], []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:
                pass

            def _json(self, data) -> None:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps(data).encode())

            def do_POST(self) -> None:  # noqa: N802
                queued.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self._json({"prompt_id": "p1", "number": 0, "node_errors": {}})

            def do_GET(self) -> None:  # noqa: N802
                if self.path.startswith("/history/p1"):
                    polls.append(1)
                    if len(polls) < 2:
                        return self._json({})
                    return self._json({"p1": {"status": {"status_str": "success", "completed": True},
                                              "outputs": {"9": {"videos": [{"filename": "clip.mp4",
                                                                            "subfolder": "", "type": "output"}]}}}})
                if self.path.startswith("/view?filename=clip.mp4"):
                    self.send_response(200)
                    self.end_headers()
                    return self.wfile.write(b"fake-mp4-bytes")
                self.send_response(404)
                self.end_headers()

        server = _Server(Handler)
        self.addCleanup(server.close)
        provider = ComfyUIProvider("comfy", {"base_url": server.url, "poll_seconds": 0.01, "workflows": {
            "video": {"file": "wf.json", "output_node": "9", "bindings": {
                "prompt": [{"node": "6", "input": "text"}], "seed": [{"node": "3", "input": "seed"}],
                "duration_seconds": [{"node": "12", "input": "length", "transform": "frames",
                                      "frame_multiple": 4, "frame_offset": 1}]}}}}, base_dir=self.root)
        self.assertEqual(provider.serves(), frozenset({"video"}))
        result = provider.generate("video", {"prompt": "waves at dusk", "seed": 99, "width": 832,
                                             "height": 480, "fps": 16, "duration_seconds": 3.0}, self.root)
        self.assertEqual(result.path.read_bytes(), b"fake-mp4-bytes")
        sent = queued[0]["prompt"]
        self.assertEqual(sent["6"]["inputs"]["text"], "waves at dusk")
        self.assertEqual(sent["3"]["inputs"]["seed"], 99)
        self.assertEqual(sent["12"]["inputs"]["length"], 49)  # 48 frames -> 4n+1
        self.assertEqual(workflow["6"]["inputs"]["text"], "default")  # Template untouched.


class MCPProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        write(self.root / "server.py", FAKE_MCP)

    def provider(self, arguments: dict) -> MCPProvider:
        return MCPProvider("fake", {
            "capabilities": ["sound"], "server": {"argv": ["{python}", "{profile_dir}/server.py"]},
            "steps": [{"tool": "render_sound", "arguments": arguments}], "extension": ".wav",
            "timeout_seconds": 30, "output_rights": RIGHTS}, base_dir=self.root)

    def test_calls_tools_and_collects_output(self) -> None:
        provider = self.provider({"path": "{output}", "seconds": "{duration_seconds}", "label": "{prompt}"})
        self.assertEqual(provider.check()[0][0], "OK")
        result = provider.generate("sound", {"prompt": "door creak", "duration_seconds": 0.5}, self.root)
        self.assertTrue(result.path.is_file())
        self.assertEqual(result.metadata["steps"][0]["result"], "wrote door creak")

    def test_tool_errors_surface(self) -> None:
        provider = self.provider({"path": "{output}", "seconds": 1, "label": "x", "fail": True})
        with self.assertRaisesRegex(PluginError, "boom"):
            provider.generate("sound", {"prompt": "x", "duration_seconds": 1.0}, self.root)

    def test_free_text_cannot_fill_code_arguments(self) -> None:
        with self.assertRaisesRegex(PluginError, "code arguments"):
            self.provider({"code": "print({prompt!r})".replace("!r", ""), "path": "{output}"})
        with self.assertRaisesRegex(PluginError, "code arguments"):
            self.provider({"args": {"script": "{text}"}})


class ProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_shipped_profiles_validate_and_load(self) -> None:
        found = {entry["id"]: entry for entry in discover_pipelines()}
        self.assertTrue({"animatic", "open-source-local", "blender-mcp", "kokoro-fastapi", "comfyui",
                         "stable-diffusion-cpp", "espeak-ng", "localai"} <= set(found))
        env = {name: "/opt/x" for name in ("PIPER_BIN", "PIPER_VOICES", "TYPE_SIMULATOR_DIR",
                                           "TYPE_SIMULATOR_PYTHON", "BLENDER_BIN", "BLENDER_MCP_SERVER",
                                           "SD_CPP_BIN", "SD_CPP_MODEL", "LOCALAI_TTS_MODEL",
                                           "LOCALAI_IMAGE_MODEL", "KOKORO_PYTHON")}
        with mock.patch.dict(os.environ, env):
            for pipeline_id in found:
                with self.subTest(pipeline=pipeline_id):
                    profile = Profile.load(pipeline_id)
                    for name in profile.data.get("providers", {}):
                        profile.provider(name)  # Config validates against the type's schema.
                    for capability in profile.data.get("routes", {}):
                        self.assertTrue(profile.routes_for(capability))
        self.assertTrue(all(entry["verification"] for entry in found.values()))

    def test_extends_merges_and_env_is_expanded_lazily(self) -> None:
        child = write(self.root / "child.json", {
            "pipeline_schema": "0.1.0", "id": "test.child", "extends": "animatic",
            "description": "A child profile for tests", "verification": "unit test",
            "providers": {"tts": {"type": "command", "config": {
                "capabilities": ["speech"], "argv": ["${VG_TEST_TTS}", "--out", "{output}"],
                "stdin": "{text}", "extension": ".wav"}}},
            "routes": {"speech": "tts"}, "voices": {"narrator": "${VG_TEST_VOICE}"}})
        profile = Profile.load(str(child))
        self.assertEqual(profile.routes_for("speech"), [[("tts", "speech")]])
        self.assertEqual(profile.routes_for("image"), [[("placeholder", "image")]])  # Inherited.
        with self.assertRaisesRegex(PluginError, "VG_TEST_TTS is not set"):
            profile.provider("tts")
        with mock.patch.dict(os.environ, {"VG_TEST_TTS": "/usr/bin/tts", "VG_TEST_VOICE": "alto"}):
            self.assertEqual(profile.provider("tts").config["argv"][0], "/usr/bin/tts")
            self.assertEqual(profile.role("voices", "narrator"), "alto")
        self.assertEqual(len(profile.describe()["sources"]), 2)

    def test_invalid_unknown_and_cyclic_profiles(self) -> None:
        with self.assertRaisesRegex(PluginError, "Unknown pipeline"):
            Profile.load("no-such-pipeline")
        bad = write(self.root / "bad.json", {"pipeline_schema": "0.1.0", "id": "bad"})
        with self.assertRaisesRegex(PluginError, "Invalid pipeline profile"):
            Profile.load(str(bad))
        for name, parent in (("a", "b"), ("b", "a")):
            write(self.root / "cycle" / f"{name}.json", {
                "pipeline_schema": "0.1.0", "id": f"cycle-{name}", "extends": f"cycle-{parent}",
                "description": "cyclic test profile", "verification": "unit test"})
        with self.assertRaisesRegex(PluginError, "cycle"):
            Profile.load("cycle-a", search=[self.root / "cycle"])


@unittest.skipUnless(HAS_FFMPEG, "FFmpeg required")
class ProduceTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        write(self.root / "tools" / "tts.py", FAKE_TTS)
        write(self.root / "tools" / "vc.py", FAKE_VC)
        self.job = self.root / "job" / "job.json"
        write(self.job, json.loads(SLIDES_JOB.read_text(encoding="utf-8")))

    def profile(self, providers: dict, routes: dict, **extra) -> Profile:
        path = write(self.root / "tools" / "profile.json", {
            "pipeline_schema": "0.1.0", "id": "test.profile", "extends": "animatic",
            "description": "Test composition profile", "verification": "unit test",
            "providers": providers, "routes": routes, **extra})
        return Profile.load(str(path))

    def tts(self, *flags: str, rights: bool = True) -> dict:
        config = {"capabilities": ["speech"], "stdin": "{text}", "extension": ".wav",
                  "argv": ["{python}", "{profile_dir}/tts.py", "--out", "{output}", *flags]}
        if rights:
            config["output_rights"] = RIGHTS
        return {"type": "command", "config": config}

    def test_animatic_produces_everything_and_render_flags_placeholders(self) -> None:
        produced, report = produce(self.job, Profile.load("animatic"))
        self.assertEqual({e["status"] for e in report}, {"generated"})
        self.assertEqual(len(report), 8)  # 3 images, 3 voices, music, backdrop
        plan = compile_job(produced)
        # Still shots were bound automatically from their single image input.
        self.assertEqual(plan["segments"][1]["asset_id"], "slide_1_image")
        receipt = run_render(plan, produced.parent, self.root / "anim.mp4", Profile.load("animatic"),
                             write_deliverables=False)
        self.assertTrue(receipt["contains_placeholder_media"])
        self.assertIn("placeholder", receipt["caveats"][0].lower())
        self.assertEqual(receipt["pipeline"]["id"], "animatic")
        again, report = produce(self.job, Profile.load("animatic"))
        self.assertEqual({e["status"] for e in report}, {"cached"})

    def test_supplied_inputs_win_and_compile_hints_production(self) -> None:
        job = json.loads(self.job.read_text())
        with self.assertRaisesRegex(ProductionError, "producible via 'image'"):
            compile_job(self.job)
        write_tone(self.job.parent / "voice.wav", 200, 3)
        job["assets"] = {"recorded": {"kind": "audio", "path": "voice.wav",
                                      "origin": {"type": "filmed", "description": "studio take"},
                                      "rights": {"cleared": True, "license": "owned", "evidence": "talent release"}}}
        job["inputs"]["slide_1_voice"] = "recorded"
        write(self.job, job)
        _, report = produce(self.job, Profile.load("animatic"))
        self.assertNotIn("slide_1_voice", {e["input"] for e in report})

    def test_real_command_speech_is_conformed_to_the_locked_slot(self) -> None:
        profile = self.profile({"tts": self.tts()}, {"speech": "tts"})
        produced, report = produce(self.job, profile, only=["slide_1_voice"])
        entry = report[0]
        self.assertEqual((entry["status"], entry["providers"]), ("generated", ["tts"]))
        self.assertEqual(entry["conformed_to_seconds"], 5.5)
        asset = json.loads(produced.read_text())["assets"]["slide_1_voice"]
        self.assertEqual(asset["origin"]["type"], "generated")
        self.assertEqual(asset["rights"]["license"], "MIT")
        self.assertFalse(asset["generation"]["placeholder"])
        manifest = json.loads((self.job.parent / "generated/manifest.json").read_text())
        self.assertIn("Every video starts", manifest["slide_1_voice"]["request"]["text"])

    def test_overlong_speech_asks_for_a_shorter_script(self) -> None:
        job = json.loads(self.job.read_text())
        job["inputs"]["slide_1_script"] = " ".join(["word"] * 30)
        write(self.job, job)
        profile = self.profile({"tts": self.tts()}, {"speech": "tts"})
        with self.assertRaisesRegex(ProductionError, "shorten the text"):
            produce(self.job, profile, only=["slide_1_voice"])

    def test_provider_without_declared_rights_is_refused(self) -> None:
        profile = self.profile({"tts": self.tts(rights=False)}, {"speech": "tts"})
        with self.assertRaisesRegex(ProductionError, "declares no output_rights"):
            produce(self.job, profile, only=["slide_1_voice"])

    def test_fallback_and_chain_routes(self) -> None:
        vc = {"type": "command", "config": {
            "capabilities": ["voice_conversion"], "extension": ".wav", "output_rights": RIGHTS,
            "argv": ["{python}", "{profile_dir}/vc.py", "--source", "{references.source}",
                     "--voice", "{voice}", "--out", "{output}"]}}
        profile = self.profile(
            {"broken": self.tts("--fail"), "tts": self.tts(), "vc": vc},
            {"speech": {"chain": [{"provider": "tts"}, {"provider": "vc", "capability": "voice_conversion"}]},
             "image": {"fallback": ["broken_image", "placeholder"]}},
            voices={"narrator": "character_ref.wav"})
        profile.data["providers"]["broken_image"] = {"type": "command", "config": {
            "capabilities": ["image"], "extension": ".png", "output_rights": RIGHTS,
            "argv": ["{python}", "-c", "import sys; sys.exit('gpu out of memory')"]}}
        _, report = produce(self.job, profile, only=["slide_1_voice", "slide_1_image"])
        by_input = {entry["input"]: entry for entry in report}
        self.assertEqual(by_input["slide_1_voice"]["providers"], ["tts", "vc"])
        self.assertEqual(by_input["slide_1_image"]["providers"], ["placeholder"])
        manifest = json.loads((self.job.parent / "generated/manifest.json").read_text())
        steps = manifest["slide_1_voice"]["steps"]
        self.assertEqual([s["capability"] for s in steps], ["speech", "voice_conversion"])

    def test_required_input_without_route_is_an_error_optional_is_skipped(self) -> None:
        path = write(self.root / "tools" / "empty.json", {
            "pipeline_schema": "0.1.0", "id": "test.empty", "description": "No providers at all",
            "verification": "unit test"})
        with self.assertRaisesRegex(ProductionError, "routes no 'image' provider"):
            produce(self.job, Profile.load(str(path)))
        _, report = produce(self.job, Profile.load(str(path)), only=["music"])
        self.assertEqual(report[0]["status"], "skipped")


@unittest.skipUnless(HAS_FFMPEG, "FFmpeg required")
class PipelineCompositionTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        job = json.loads((ROOT / "examples/three-card-explainer/job.json").read_text())
        self.plan = compile_job(write(self.root / "job.json", job))

    def tearDown(self) -> None:
        for kind, name in (("analyzer", "test-wer"), ("renderer", "test-limited")):
            plugins.unregister(kind, name)

    def test_custom_analyzer_metric_drives_a_gate(self) -> None:
        class FakeWER(Analyzer):
            metrics = frozenset({"word_error_rate"})

            def measure(self, output, plan):
                return {"metrics": {"word_error_rate": 0.04}, "details": {"model": "fake"}}

        plugins.register("analyzer", "test-wer", FakeWER)
        self.plan["quality_gates"].append({"id": "speech_accuracy", "mode": "automated",
                                           "description": "WER below 10%", "status": "not_evaluated",
                                           "check": {"metric": "word_error_rate", "max": 0.1}})
        path = write(self.root / "p.json", {"pipeline_schema": "0.1.0", "id": "test.wer",
                                            "description": "Adds a WER analyzer", "verification": "unit test",
                                            "analyzers": [{"type": "ffmpeg"}, {"type": "test-wer"}],
                                            "exporters": []})
        receipt = run_render(self.plan, self.root, self.root / "out.mp4", Profile.load(str(path)))
        gate = {g["id"]: g for g in receipt["quality_gates"]}["speech_accuracy"]
        self.assertEqual((gate["status"], gate["evidence"]["source"]), ("passed", "FakeWER"))
        self.assertEqual(receipt["deliverables"], {})
        self.assertIn("integrated_lufs", receipt["measurements"]["not_applicable"])

    def test_renderer_must_refuse_unsupported_features(self) -> None:
        class NoCards(Renderer):
            def unsupported(self, plan):
                return ["motion_graphics shots"]

            def render(self, plan, job_directory, output):
                raise AssertionError("must not be called")

        plugins.register("renderer", "test-limited", NoCards)
        path = write(self.root / "p.json", {"pipeline_schema": "0.1.0", "id": "test.limited",
                                            "description": "A limited renderer", "verification": "unit test",
                                            "renderer": {"type": "test-limited"}})
        with self.assertRaisesRegex(PluginError, "cannot honour: motion_graphics"):
            run_render(self.plan, self.root, self.root / "out.mp4", Profile.load(str(path)))


class ProducibleBlueprintTests(unittest.TestCase):
    def test_shipped_producible_templates_validate(self) -> None:
        for name in ("educational/narrated-slides", "educational/code-typing-reel",
                     "commercial/product-turntable"):
            with self.subTest(template=name):
                data = json.loads((ROOT / "templates" / name / "blueprint.json").read_text())
                self.assertEqual(validate_blueprint(data), [])

    def test_produce_spec_is_checked_against_the_capability(self) -> None:
        data = json.loads((ROOT / "templates/educational/narrated-slides/blueprint.json").read_text())
        data["inputs"]["slide_1_voice"]["produce"]["capability"] = "image"
        data["inputs"]["slide_1_image"]["produce"]["references"] = ["slide_1_image"]
        data["inputs"]["closing"]["produce"] = {"capability": "speech"}
        errors = validate_blueprint(data)
        self.assertTrue(any("cannot produce audio" in e for e in errors))
        self.assertTrue(any("must be another media input" in e for e in errors))
        self.assertTrue(any("only audio, image or video" in e for e in errors))
        data = json.loads((ROOT / "templates/educational/narrated-slides/blueprint.json").read_text())
        data["schema_version"] = "0.3.0"
        self.assertTrue(any("requires schema_version 0.4.0" in e for e in validate_blueprint(data)))


@unittest.skipUnless(HAS_FFMPEG, "FFmpeg required")
class PlaceholderProviderTests(unittest.TestCase):
    def test_every_media_kind_is_labelled_and_timed(self) -> None:
        from videogenome.providers.placeholder import PlaceholderProvider
        from videogenome.render import probe
        provider = PlaceholderProvider("placeholder", {})
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            for capability, request, kind in (
                ("speech", {"text": "one two three four five", "max_seconds": 5.0}, "audio"),
                ("music", {"prompt": "x", "duration_seconds": 2.0}, "audio"),
                ("image", {"prompt": "x", "width": 320, "height": 180}, "video"),
                ("typing", {"text": "print(1)", "width": 320, "height": 568, "fps": 24,
                            "duration_seconds": 1.5, "media": "video"}, "video"),
            ):
                with self.subTest(capability=capability):
                    step = work / capability
                    step.mkdir()
                    result = provider.generate(capability, request, step)
                    self.assertTrue(result.metadata["placeholder"])
                    streams = probe(result.path)["streams"]
                    self.assertEqual(streams[0]["codec_type"], kind)


if __name__ == "__main__":
    unittest.main()
