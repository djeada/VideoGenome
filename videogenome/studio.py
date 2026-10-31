"""VideoGenome Studio: a local web UI for people who do not live in a terminal.

    videogenome studio --pipeline procedural-writer --workspace ~/videogenome-runs

See what can be generated (the library, by readiness), fill a template from a
brief or by hand with live checks, render with the operator's pipeline, play
with recipe parameters, run your own HTML animation unchanged, and connect an
agent over MCP. It binds to 127.0.0.1 only, requires a per-session token on
every API call, refuses unexpected Host headers (DNS rebinding) and serves
files from the workspace alone.
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import secrets
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from videogenome import __version__
from videogenome.compiler import ProductionError, read_json
from videogenome.service import Service, contact_sheet
from videogenome.requests import (
    BRIEF, CAPTURE_PROPERTIES, COPY_PROPERTIES, FORMATS, IDENTIFIER, NAME, PREVIEW_PROPERTIES,
    object_schema, parse_request, validate_request,
)

STATIC = Path(__file__).resolve().parent / "studio_static"
MAX_BODY = 4 * 1024 * 1024
POST_SCHEMAS = {
    "check": object_schema({**COPY_PROPERTIES, "brief": {**BRIEF, "type": ["string", "null"]},
                            "layout": {"type": "boolean"}},
                           ("template", "inputs")),
    "render": object_schema({**COPY_PROPERTIES, "brief": {**BRIEF, "type": ["string", "null"]},
                             "author": NAME, "name": NAME, "formats": FORMATS}, ("template",)),
    "fill": object_schema({"template": IDENTIFIER, "brief": {**BRIEF, "minLength": 1}}, ("template", "brief")),
    "create": object_schema({"template": IDENTIFIER, "brief": {**BRIEF, "minLength": 1}, "name": NAME,
                             "formats": FORMATS},
                            ("template", "brief")),
    "preview-recipe": object_schema(PREVIEW_PROPERTIES, ("recipe",)),
    "capture": object_schema(CAPTURE_PROPERTIES, ("html",)),
    "preview-template": object_schema({}),
}


class Jobs:
    """Background work with a log, so the UI can show progress and results."""

    def __init__(self, workers: int = 2) -> None:
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="vg-studio")
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()

    def submit(self, label: str, work) -> str:
        job_id = uuid.uuid4().hex[:12]
        record = {"id": job_id, "label": label, "status": "queued", "log": [], "result": None, "error": None,
                  "started": time.time(), "finished": None}
        with self.lock:
            self.jobs[job_id] = record

        def log(line: str) -> None:
            record["log"].append(f"{time.time() - record['started']:6.1f}s  {line}")

        def run() -> None:
            record["status"] = "running"
            log(f"started: {label}")
            try:
                record["result"] = work(log)
                record["status"] = "done"
                log("done")
            except ProductionError as exc:
                record["status"], record["error"] = "failed", str(exc)
                log(f"failed: {exc}")
            except Exception as exc:  # noqa: BLE001 - surface to the UI
                record["status"], record["error"] = "failed", f"{type(exc).__name__}: {exc}"
                log(traceback.format_exc(limit=4))
            record["finished"] = time.time()

        self.pool.submit(run)
        return job_id

    def get(self, job_id: str) -> dict | None:
        return self.jobs.get(job_id)


class Studio:
    def __init__(self, service: Service, *, host: str = "127.0.0.1", port: int = 8765) -> None:
        self.service = service
        self.token = secrets.token_urlsafe(24)
        self.jobs = Jobs()
        self.host, self.port = host, port
        self.previews = service.previews_dir

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/?token={self.token}"

    # ---- API --------------------------------------------------------------------
    def state(self) -> dict:
        writer = None
        if "writer" in self.service.profile.data:
            spec = self.service.profile.data["writer"]
            writer = (spec.get("config", {}).get("model") or {}).get("name") or spec["type"]
        return {"version": __version__, "pipeline": self.service.profile.id,
                "pipeline_description": self.service.profile.data.get("description"),
                "writer": writer, "workspace": str(self.service.workspace.root),
                "samples": sorted(self.service.sample_jobs())}

    def preview_paths(self, template_id: str) -> dict:
        video, poster = self.previews / f"{template_id}.mp4", self.previews / f"{template_id}.jpg"
        return {"video": self.file_url(video) if video.is_file() else None,
                "poster": self.file_url(poster) if poster.is_file() else None}

    def file_url(self, path: str | Path | None) -> str | None:
        if not path:
            return None
        path = Path(path).resolve()
        if not self.service.workspace.contains(path):
            return None
        return "/files/" + quote(path.relative_to(self.service.workspace.root).as_posix(), safe="/")

    def with_urls(self, result: dict) -> dict:
        out = dict(result)
        for key in ("output", "review_page", "contact_sheet", "poster", "receipt"):
            if result.get(key):
                out[f"{key}_url"] = self.file_url(result[key])
        if isinstance(result.get("formats"), list):  # One row per delivery format.
            out["formats"] = [self.with_urls(row) if isinstance(row, dict) else row for row in result["formats"]]
        return out

    def render_preview(self, template_id: str, log) -> dict:
        return self.with_urls(self.service.build_preview(template_id, log))

    def api(self, method: str, path: str, body: dict) -> tuple[int, object]:
        s = self.service
        parts = [unquote(p) for p in path.strip("/").split("/")][1:]  # after "api"
        head = parts[0] if parts else ""
        if method == "GET":
            if head == "state":
                return 200, self.state()
            if head == "library":
                rows = s.library()
                for row in rows:
                    row["previews"] = {t: self.preview_paths(t) for t in row.get("templates", [])}
                return 200, rows
            if head == "genome" and len(parts) == 2:
                return 200, s.genome(parts[1])
            if head == "templates":
                return 200, [t | {"preview": self.preview_paths(t["id"])} for t in s.templates()]
            if head == "template" and len(parts) == 2:
                info = s.template(parts[1])
                sample = self.service.sample_jobs().get(parts[1])
                info["sample_inputs"] = read_json(sample)["inputs"] if sample else None
                info["preview"] = self.preview_paths(parts[1])
                return 200, info
            if head == "recipes":
                return 200, s.recipes()
            if head == "runs":
                return 200, [self.with_urls(r) for r in s.workspace.runs()]
            if head == "run" and len(parts) == 2:
                return 200, s.edit_run(parts[1])
            if head == "jobs" and len(parts) == 2:
                job = self.jobs.get(parts[1])
                if job is None:
                    return 404, {"error": "unknown job"}
                return 200, {**job, "result": self.with_urls(job["result"]) if isinstance(job["result"], dict)
                             and "output" in job["result"] else job["result"]}
            return 404, {"error": "not found"}
        if method == "POST":
            if head in POST_SCHEMAS:
                validate_request(body, POST_SCHEMAS[head])
            if head == "check":
                return 200, s.check_inputs(body["template"], body.get("inputs", {}), body.get("brief") or None,
                                           formats=body.get("formats"), layout=body.get("layout", False))
            if head == "fill":
                return 202, {"job": self.jobs.submit(f"write copy for {body['template']}",
                                                     lambda log: s.fill(body["template"], body["brief"]))}
            if head == "render":
                return 202, {"job": self.jobs.submit(
                    f"render {body['template']}",
                    lambda log: s.render(body["template"], body.get("inputs", {}), brief=body.get("brief") or None,
                                         author=body.get("author", "person"), name=body.get("name"),
                                         formats=body.get("formats"), log=log))}
            if head == "create":
                return 202, {"job": self.jobs.submit(
                    f"brief to video: {body['template']}",
                    lambda log: s.create(body["template"], body["brief"], name=body.get("name"),
                                         formats=body.get("formats"), log=log))}
            if head == "preview-recipe":
                return 202, {"job": self.jobs.submit(
                    f"preview {body['recipe']}",
                    lambda log: s.preview_recipe(body["recipe"], preset=body.get("preset") or None,
                                                 params=body.get("params") or {}, size=body.get("size", "1280x720"),
                                                 duration=body.get("duration", 6), fps=body.get("fps", 30),
                                                 seed=body.get("seed", 1)))}
            if head == "capture":
                return 202, {"job": self.jobs.submit(
                    "run your HTML",
                    lambda log: s.capture(html=body["html"], size=body.get("size", "1920x1080"),
                                          fps=body.get("fps", 30), duration=body.get("duration", 8),
                                          seed=body.get("seed", 1), params=body.get("params"),
                                          click=body.get("click"), audio=body.get("audio", True),
                                          name=body.get("name", "my-html")))}
            if head == "preview-template" and len(parts) == 2:
                return 202, {"job": self.jobs.submit(f"sample render of {parts[1]}",
                                                     lambda log: self.render_preview(parts[1], log))}
            return 404, {"error": "not found"}
        return 405, {"error": "method not allowed"}

    # ---- HTTP ------------------------------------------------------------------------
    def handler(self):
        studio = self

        class Handler(BaseHTTPRequestHandler):
            server_version = f"VideoGenomeStudio/{__version__}"

            def log_message(self, *args) -> None:
                pass

            def _host_ok(self) -> bool:
                host = (self.headers.get("Host") or "").lower()
                return host in (f"127.0.0.1:{studio.port}", f"localhost:{studio.port}")

            def _headers(self, status: int, length: int, content_type: str, extra: dict | None = None) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(length))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                for key, value in (extra or {}).items():
                    self.send_header(key, value)
                self.end_headers()

            def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None) -> None:
                self._headers(status, len(body), content_type, extra)
                if self.command != "HEAD":
                    try:
                        self.wfile.write(body)
                    except (BrokenPipeError, ConnectionResetError):
                        pass  # A navigation can cancel an in-flight API response.

            def _json(self, status: int, data: object) -> None:
                self._send(status, json.dumps(data, ensure_ascii=True, default=str).encode(), "application/json")

            def _authorised(self) -> bool:
                cookie = self.headers.get("Cookie") or ""
                tokens = {part.strip().partition("=")[2] for part in cookie.split(";") if part.strip().startswith("vg_token=")}
                return self._matches_token(self.headers.get("X-VG-Token", "")) or any(
                    self._matches_token(t) for t in tokens)

            def _matches_token(self, token: str) -> bool:
                return secrets.compare_digest(token.encode("utf-8"), studio.token.encode("ascii"))

            def do_GET(self) -> None:  # noqa: N802
                self.route("GET")

            def do_HEAD(self) -> None:  # noqa: N802
                self.route("GET")

            def do_POST(self) -> None:  # noqa: N802
                self.route("POST")

            def route(self, method: str) -> None:
                if not self._host_ok():
                    self._send(421, b"Misdirected request", "text/plain")
                    return
                url = urlparse(self.path)
                if url.path in ("/", "/index.html"):
                    token = parse_qs(url.query).get("token", [""])[0]
                    if not self._matches_token(token) and not self._authorised():
                        self._send(403, b"Open the Studio with the URL printed in the terminal (it carries a token).",
                                   "text/plain")
                        return
                    page = (STATIC / "index.html").read_bytes()
                    self._send(200, page, "text/html; charset=utf-8", {
                        "Set-Cookie": f"vg_token={studio.token}; Path=/; HttpOnly; SameSite=Strict",
                        "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; media-src 'self'; "
                                                   "style-src 'self'; script-src 'self'; frame-src 'self'; "
                                                   "connect-src 'self'"})
                    return
                if url.path.startswith("/static/"):
                    name = url.path.removeprefix("/static/")
                    path = (STATIC / name).resolve()
                    if not path.is_file() or not path.is_relative_to(STATIC):
                        self._send(404, b"not found", "text/plain")
                        return
                    kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                    self._send(200, path.read_bytes(), kind)
                    return
                if not self._authorised():
                    self._send(403, b"missing session token", "text/plain")
                    return
                if url.path.startswith("/files/"):
                    if method != "GET":
                        self._json(405, {"error": "method not allowed"})
                        return
                    self.serve_file(unquote(url.path.removeprefix("/files/")))
                    return
                if url.path.startswith("/api/"):
                    body = {}
                    if method == "POST":
                        lengths = self.headers.get_all("Content-Length", [])
                        raw = lengths[0] if len(lengths) == 1 else "0" if not lengths else ""
                        if self.headers.get("Transfer-Encoding") or not re.fullmatch(r"[0-9]+", raw):
                            self._json(400, {"error": "invalid Content-Length or unsupported Transfer-Encoding"})
                            return
                        # Avoid converting an arbitrarily long integer header.
                        length = int(raw) if len(raw) <= 10 else MAX_BODY + 1
                        if length > MAX_BODY:
                            self._json(413, {"error": "request too large"})
                            return
                        try:
                            body = parse_request(self.rfile.read(length) or b"{}")
                        except (ValueError, UnicodeDecodeError, RecursionError):
                            self._json(400, {"error": "invalid JSON"})
                            return
                    try:
                        status, data = studio.api(method, url.path, body)
                    except (ProductionError, KeyError, ValueError, TypeError) as exc:
                        status, data = 400, {"error": f"{exc}"}
                    self._json(status, data)
                    return
                self._send(404, b"not found", "text/plain")

            def serve_file(self, relative: str) -> None:
                root = studio.service.workspace.root
                path = (root / relative).resolve()
                if not path.is_file() or not path.is_relative_to(root):
                    self._send(404, b"not found", "text/plain")
                    return
                kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                extra = {"Accept-Ranges": "bytes", "Cache-Control": "no-store"}
                # Apply this to every workspace response, including SVG and .htm.
                # Review pages retain local images, styles and video playback.
                extra["Content-Security-Policy"] = (
                    "sandbox allow-same-origin; default-src 'self'; script-src 'none'; "
                    "style-src 'unsafe-inline'; object-src 'none'; base-uri 'none'; form-action 'none'")
                with path.open("rb") as handle:
                    size = os.fstat(handle.fileno()).st_size
                    start, length, status = 0, size, 200
                    spec = self.headers.get("Range") if self.command == "GET" else None
                    # Multi-range requests are deliberately served in full (RFC 9110).
                    if spec and spec.startswith("bytes=") and "," not in spec:
                        try:
                            match = re.fullmatch(r"bytes=([0-9]*)-([0-9]*)", spec)
                            if not match or not any(match.groups()) or size == 0:
                                raise ValueError
                            first, last = match.groups()
                            if first:
                                start = int(first)
                                end = min(int(last), size - 1) if last else size - 1
                            else:
                                suffix = int(last)
                                if suffix == 0:
                                    raise ValueError
                                start, end = max(0, size - suffix), size - 1
                            if start >= size or end < start:
                                raise ValueError
                        except ValueError:
                            self._send(416, b"", kind, {**extra, "Content-Range": f"bytes */{size}"})
                            return
                        length, status = end - start + 1, 206
                        extra["Content-Range"] = f"bytes {start}-{end}/{size}"
                    self._headers(status, length, kind, extra)
                    if self.command == "HEAD":
                        return
                    handle.seek(start)
                    try:
                        while length:
                            chunk = handle.read(min(length, 64 * 1024))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            length -= len(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        pass  # Browsers cancel an in-flight request when seeking.

        return Handler

    def serve(self) -> None:
        httpd = ThreadingHTTPServer((self.host, self.port), self.handler())
        self.port = httpd.server_address[1]
        print(f"VideoGenome Studio {__version__}: {self.url}", flush=True)
        print(f"Pipeline: {self.service.profile.id}   Workspace: {self.service.workspace.root}", flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            httpd.server_close()


__all__ = ["Studio", "contact_sheet"]
