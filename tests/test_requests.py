"""Regression tests for malformed client requests, run history and HTTP media delivery."""
from __future__ import annotations

import io
import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

from tests.test_cockpits import CARD, service
from tests.test_plugins import write
from videogenome.compiler import ProductionError, _check_input
from videogenome.mcp_server import Server
from videogenome.service import capture_page
from videogenome.studio import MAX_BODY, Studio


class McpRequestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = Mock()
        self.out = io.StringIO()
        self.server = Server(self.service, self.out)

    def rpc(self, method: str, params: object = None) -> dict:
        return self.server.handle({"jsonrpc": "2.0", "id": 7, "method": method,
                                   "params": {} if params is None else params})

    def test_malformed_envelopes_do_not_end_the_session(self) -> None:
        for message in (None, [], 3, "ping", {}, {"id": 1, "method": "ping"},
                        {"jsonrpc": "1.0", "id": 1, "method": "ping"},
                        {"jsonrpc": "2.0", "id": {}, "method": "ping"},
                        {"jsonrpc": "2.0", "id": True, "method": "ping"},
                        {"jsonrpc": "2.0", "id": 1, "method": []}):
            with self.subTest(message=message):
                self.assertEqual(self.server.handle(message)["error"]["code"], -32600)
                self.assertEqual(self.rpc("ping")["result"], {})

    def test_bad_params_and_unknown_methods_are_protocol_errors(self) -> None:
        for params in ([], "wrong", 0, False):
            with self.subTest(params=params):
                self.assertEqual(self.rpc("tools/call", params)["error"]["code"], -32602)
        for params in ({}, {"name": []}, {"name": "runs", "arguments": []},
                       {"name": "runs", "arguments": None}):
            self.assertEqual(self.rpc("tools/call", params)["error"]["code"], -32602)
        self.assertEqual(self.rpc("missing")["error"]["code"], -32601)
        self.assertEqual(self.rpc("prompts/get", {"name": 42})["error"]["code"], -32602)

    def test_tool_contracts_are_enforced_before_dispatch(self) -> None:
        invalid = [
            ("render", {"template": "test.card", "inputs": []}),
            ("render", {"template": "test.card", "inputs": {}, "pipeline": "untrusted"}),
            ("check_inputs", {"template": "test.card"}),
            ("capture_html", {"html": "<body/>", "fps": 1.5}),
            ("capture_html", {"html": "<body/>", "fps": True}),
            ("capture_html", {"html": "<body/>", "duration": float("nan")}),
            ("capture_html", {"html": "<body/>", "duration": 601}),
            ("capture_html", {"html": "<body/>", "audio": "false"}),
            ("capture_html", {"html": "<body/>", "params": {"x": float("inf")}}),
            ("capture_html", {"html": "\ud800"}),
            ("check_inputs", {"template": "test.card", "inputs": {"\ud800": "x"}}),
            ("preview_recipe", {"recipe": "visual.aurora", "fps": 0}),
            ("preview_recipe", {"recipe": "visual.aurora", "seed": -1}),
            ("runs", {"limit": -1}), ("runs", {"limit": 1001}),
        ]
        for name, args in invalid:
            with self.subTest(name=name, args=args):
                reply = self.rpc("tools/call", {"name": name, "arguments": args})
                if "error" in reply:
                    self.assertEqual(reply["error"]["code"], -32602)
                else:
                    self.assertTrue(reply["result"]["isError"], reply)
        self.assertEqual(self.service.mock_calls, [])

    def test_valid_capture_preserves_options_without_coercion(self) -> None:
        self.service.capture.return_value = {"output": "video.mp4"}
        result = self.rpc("tools/call", {"name": "capture_html", "arguments": {
            "html": "<body/>", "fps": 24, "duration": 0.25, "audio": False, "seed": 17}})["result"]
        self.assertFalse(result["isError"])
        args = self.service.capture.call_args.kwargs
        self.assertEqual((args["fps"], args["duration"], args["seed"], args["audio"]), (24, 0.25, 17, False))

    def test_notifications_never_start_work_and_null_ids_receive_a_reply(self) -> None:
        self.assertIsNone(self.server.handle({"jsonrpc": "2.0", "method": "tools/call", "params": {
            "name": "render", "arguments": {"template": "test.card", "inputs": {}}}}))
        self.assertEqual(self.service.mock_calls, [])
        response = self.server.handle({"jsonrpc": "2.0", "id": None, "method": "ping"})
        self.assertIsNone(response["id"])
        self.assertEqual(response["result"], {})

    def test_stdio_recovers_after_invalid_json_and_invalid_requests(self) -> None:
        self.server.serve(io.StringIO('\n{broken\n[]\n{"jsonrpc":"2.0","id":1,"method":"ping","params":{"n":NaN}}\n'
                                    '{"jsonrpc":"2.0","id":2,"method":"ping"}\n'))
        replies = [json.loads(line) for line in self.out.getvalue().splitlines()]
        self.assertEqual([r["error"]["code"] for r in replies[:-1]], [-32700, -32600, -32700])
        self.assertEqual(replies[-1], {"jsonrpc": "2.0", "id": 2, "result": {}})

    def test_deeply_nested_inputs_return_errors_without_ending_the_session(self) -> None:
        nested: object = "leaf"
        for _ in range(100):
            nested = [nested]
        reply = self.rpc("tools/call", {"name": "capture_html", "arguments": {"html": "x", "params": {"n": nested}}})
        self.assertEqual(reply["error"]["code"], -32602)
        self.assertEqual(self.rpc("ping")["result"], {})


class SharedServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.service = service(self.root)

    def test_optional_null_and_empty_values_cannot_bypass_type_checks(self) -> None:
        for value in (None, "", []):
            with self.subTest(value=value):
                checked = self.service.check_inputs("test.card", {"title": "Hello", "year": value})
                self.assertFalse(checked["ok"], checked)
                self.assertIn("finite number", str(checked["issues"]))

    def test_required_blueprint_defaults_are_available_to_check(self) -> None:
        card = json.loads(json.dumps(CARD))
        card["inputs"]["title"]["default"] = "Hello"
        write(self.root / "templates/card/blueprint.json", card)
        self.assertTrue(self.service.check_inputs("test.card", {})["ok"])

    def test_invalid_capture_and_preview_options_allocate_no_runs(self) -> None:
        for options in ({"fps": 1.5}, {"fps": True}, {"duration": float("inf")}, {"seed": -1},
                        {"params": []}, {"size": "15x16"}, {"size": "8192x8192"}):
            for action in (lambda: self.service.capture(html="<body/>", **options),
                           lambda: self.service.preview_recipe("visual.aurora", **options)):
                with self.subTest(options=options), self.assertRaises(ProductionError):
                    action()
        self.assertEqual(list((self.service.workspace.root / "runs").iterdir()), [])

    def test_capture_rejects_unbounded_still_times_before_launching_browser(self) -> None:
        page = self.root / "page.html"
        page.write_text("<body/>")
        with patch("videogenome.service.subprocess.run") as run:
            for at in (-1, float("nan"), float("inf"), 601):
                with self.subTest(at=at), self.assertRaises(ProductionError):
                    capture_page(page, self.root / "still.png", at=at)
            run.assert_not_called()

    def test_compiler_rejects_non_finite_numbers(self) -> None:
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value), self.assertRaisesRegex(ProductionError, "finite number"):
                _check_input("year", {"type": "number"}, value, {})

    def test_history_limits_completed_runs_and_skips_untrusted_or_corrupt_summaries(self) -> None:
        runs = self.service.workspace.root / "runs"
        write(runs / "001-success/summary.json", {"run": "old"})
        (runs / "002-incomplete").mkdir()
        (runs / "003-bad").mkdir()
        (runs / "003-bad/summary.json").write_text("[]")
        (runs / "004-invalid-encoding").mkdir()
        (runs / "004-invalid-encoding/summary.json").write_bytes(b"\xff")
        write(self.root / "private/summary.json", {"run": "outside"})
        (runs / "005-symlink").symlink_to(self.root / "private", target_is_directory=True)
        (runs / "006-summary-symlink").mkdir()
        (runs / "006-summary-symlink/summary.json").symlink_to(self.root / "private/summary.json")
        self.assertEqual(self.service.workspace.runs(1), [{"run": "old"}])
        with self.assertRaises(ProductionError):
            self.service.workspace.runs(-1)


class StudioHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.studio = Studio(service(self.root), port=0)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), self.studio.handler())
        self.studio.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)
        self.file = self.studio.service.workspace.root / "clip.mp4"
        self.file.write_bytes(b"0123456789")

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()
        self.studio.jobs.pool.shutdown(wait=True)

    def request(self, path: str, *, method: str = "GET", body: bytes | None = None,
                headers: dict | None = None) -> tuple[int, bytes, dict]:
        connection = HTTPConnection("127.0.0.1", self.studio.port, timeout=5)
        try:
            connection.request(method, path, body, {"X-VG-Token": self.studio.token, **(headers or {})})
            response = connection.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            connection.close()

    def test_byte_ranges_support_browser_seeking(self) -> None:
        for spec, expected, content_range in (
            ("bytes=2-5", b"2345", "bytes 2-5/10"),
            ("bytes=7-", b"789", "bytes 7-9/10"),
            ("bytes=-3", b"789", "bytes 7-9/10"),
            ("bytes=-20", b"0123456789", "bytes 0-9/10"),
            ("bytes=8-100", b"89", "bytes 8-9/10"),
        ):
            with self.subTest(spec=spec):
                status, body, headers = self.request("/files/clip.mp4", headers={"Range": spec})
                self.assertEqual((status, body), (206, expected))
                self.assertEqual(headers["Content-Range"], content_range)
                self.assertEqual(int(headers["Content-Length"]), len(expected))

    def test_malformed_and_unsatisfiable_ranges_return_416(self) -> None:
        for spec in ("bytes=10-", "bytes=7-2", "bytes=-0", "bytes=-", "bytes=x-y", "bytes=-1-3"):
            with self.subTest(spec=spec):
                status, body, headers = self.request("/files/clip.mp4", headers={"Range": spec})
                self.assertEqual((status, body, headers["Content-Range"]), (416, b"", "bytes */10"))
        self.file.write_bytes(b"")
        self.assertEqual(self.request("/files/clip.mp4", headers={"Range": "bytes=0-"})[0], 416)

    def test_multiple_or_unknown_ranges_are_ignored(self) -> None:
        for spec in ("bytes=0-1,4-5", "items=0-2"):
            self.assertEqual(self.request("/files/clip.mp4", headers={"Range": spec})[:2], (200, b"0123456789"))

    def test_head_and_streaming_do_not_read_the_entire_file_into_memory(self) -> None:
        with patch.object(Path, "read_bytes", side_effect=AssertionError("whole-file read")):
            status, body, headers = self.request("/files/clip.mp4", method="HEAD", headers={"Range": "bytes=0-2"})
            self.assertEqual((status, body, headers["Content-Length"]), (200, b"", "10"))
            self.assertEqual(self.request("/files/clip.mp4")[:2], (200, b"0123456789"))

    def test_workspace_markup_cannot_run_scripts_and_urls_are_encoded(self) -> None:
        for name in ("review.html", "capture.htm", "image.svg"):
            path = self.file.with_name(name)
            path.write_text("<script>alert(1)</script>")
            status, _, headers = self.request(self.studio.file_url(path))
            self.assertEqual(status, 200)
            self.assertIn("script-src 'none'", headers["Content-Security-Policy"])
            self.assertIn("sandbox", headers["Content-Security-Policy"])
        path = self.file.with_name("take #1% + ü.mp4")
        path.write_bytes(b"special")
        url = self.studio.file_url(path)
        self.assertIn("%23", url)
        self.assertEqual(self.request(url)[:2], (200, b"special"))

    def test_invalid_request_bodies_return_400_without_queuing_work(self) -> None:
        for body in (b"[]", b"null", b"true", b"{broken", b"\xff", b'{"template":"test.card","inputs":[]}'):
            with self.subTest(body=body):
                self.assertEqual(self.request("/api/render", method="POST", body=body)[0], 400)
        for body in (b'{"html":"x","fps":1.5}', b'{"html":"x","audio":"false"}',
                     b'{"html":"x","duration":NaN}', b'{"html":"x","params":{"x":1e400}}',
                     b'{"html":"\\ud800"}',
                     b'{"html":"x","pipeline":"untrusted"}'):
            self.assertEqual(self.request("/api/capture", method="POST", body=body)[0], 400)
        self.assertEqual(self.studio.jobs.jobs, {})

    def test_invalid_content_lengths_are_rejected_before_reading(self) -> None:
        for length in ("-1", "nope", "9" * 100):
            with self.subTest(length=length):
                status, body, _ = self.request("/api/check", method="POST", headers={"Content-Length": length})
                self.assertEqual(status, 413 if length.startswith("9") else 400, body)
        self.assertEqual(self.request("/api/check", method="POST",
                                      headers={"Content-Length": str(MAX_BODY + 1)})[0], 413)

    def test_invalid_unicode_session_token_is_denied_without_crashing(self) -> None:
        status, _, _ = self.request("/?token=%C3%BC", headers={"X-VG-Token": "wrong"})
        self.assertEqual(status, 403)
        self.assertEqual(self.request("/api/state")[0], 200)

    def test_valid_check_and_capture_keep_existing_ui_contracts(self) -> None:
        status, body, _ = self.request("/api/check", method="POST", body=json.dumps({
            "template": "test.card", "inputs": {"title": "Hello"}, "brief": None}).encode())
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])
        with patch.object(self.studio.jobs, "submit", return_value="capture-job") as submit:
            self.assertEqual(self.studio.api("POST", "/api/capture", {
                "html": "<body/>", "audio": False, "seed": 8, "params": {"title": "Hello"}}),
                (202, {"job": "capture-job"}))
            with patch.object(self.studio.service, "capture", return_value={}) as capture:
                submit.call_args.args[1](lambda _: None)
                self.assertEqual(capture.call_args.kwargs["params"], {"title": "Hello"})
                self.assertEqual(capture.call_args.kwargs["seed"], 8)
                self.assertIs(capture.call_args.kwargs["audio"], False)


if __name__ == "__main__":
    unittest.main()
