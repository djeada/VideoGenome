"""CLI: discover templates, fill them from briefs, produce media, render and measure."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from videogenome import __version__
from videogenome.catalog import discover, inspect_template, scaffold
from videogenome.compiler import ProductionError, compile_job, job_format, read_json, resolve_template
from videogenome.doctor import diagnose
from videogenome.formats import job_stem, label, output_path, resolve as resolve_formats
from videogenome.pipeline import run_render
from videogenome.plugins import CAPABILITIES, KINDS, available, load_type
from videogenome.produce import produce
from videogenome.profile import Profile, discover_pipelines

EXIT_GATE_FAILED = 3
EXIT_INCOMPLETE = 4


def _template_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--templates", type=Path, action="append", default=[], metavar="DIR",
        help="Trust an additional template directory (repeatable; also VIDEOGENOME_TEMPLATE_PATH)",
    )


def _format_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--format", action="append", default=[], metavar="ID",
                        help="Delivery format from the template's formats, e.g. 9x16 or 1:1; repeat, "
                             "comma-separate or use 'all'. Several formats write NAME.<format>.mp4 each")


def _job_formats(job: Path, requested: list[str], template_dirs: list[Path]) -> list[str]:
    """The formats to process: the requested ones, else the job's own (or the main) format."""
    data = read_json(job)
    template = data.get("template")
    if not isinstance(template, str):
        raise ProductionError(f"{job}: job has no template id")
    blueprint = read_json(resolve_template(template, job.resolve().parent, template_dirs))
    return resolve_formats(blueprint, requested) if requested else [job_format(data, blueprint)]


def _pipeline_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--pipeline", metavar="ID|PATH",
                        help="Pipeline profile (default: $VIDEOGENOME_PIPELINE or FFmpeg-only)")
    parser.add_argument("--pipelines", type=Path, action="append", default=[], metavar="DIR",
                        help="Extra directory of pipeline profiles (also VIDEOGENOME_PIPELINE_PATH)")


def _brief_options(parser: argparse.ArgumentParser) -> None:
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--brief", help="Plain-language brief: who it is for, what to say, facts to use")
    source.add_argument("--brief-file", type=Path, help="Read the brief from a UTF-8 text file")
    parser.add_argument("--set", action="append", default=[], metavar="INPUT=VALUE",
                        help="Fix a text input yourself; VALUE is parsed as JSON when possible (repeatable)")
    parser.add_argument("--max-attempts", type=int, default=3,
                        help="Writer replies to try before giving up (default 3)")


def _brief(args: argparse.Namespace) -> str:
    if args.brief_file:
        try:
            return args.brief_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ProductionError(f"Cannot read brief: {exc}") from exc
    return args.brief


def _pairs(items: list[str]) -> dict:
    values = {}
    for item in items:
        key, separator, raw = item.partition("=")
        if not separator or not key:
            raise ProductionError(f"Expected INPUT=VALUE, got {item!r}")
        try:
            values[key] = json.loads(raw)
        except json.JSONDecodeError:
            values[key] = raw
    return values


def _print_fill(result, job_path: Path, record: Path) -> None:
    for attempt in result.record["attempts"]:
        state = "ok" if not attempt["issues"] else f"{len(attempt['issues'])} problem(s)"
        print(f"Attempt:  {attempt['attempt']} ({attempt['seconds']:.1f}s) {state}")
        for issue in attempt["issues"][:8]:
            print(f"          - {', '.join(issue['slots']) + ': ' if issue['slots'] else ''}{issue['problem'][:160]}")
    for name in result.record["written_inputs"]:
        print(f"Input:    {name:<18} {json.dumps(result.job['inputs'][name], ensure_ascii=False)[:110]}")
    for entry in result.missing:
        print(f"Missing:  {entry['input']:<18} {entry['reason'][:110]}")
    print(f"Wrote {'job' if result.status == 'complete' else 'draft job'}: {job_path}")
    print(f"Wrote fill record: {record}")


def _fill_context(job: Path) -> dict | None:
    """Carry a `fill` record (``<job>.fill.json``) into the receipt and review page."""
    record = job.with_name(f"{job_stem(job)}.fill.json")
    if not record.is_file():
        return None
    try:
        data = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return {"fill": {"record": str(record), "status": data.get("status"), "writer": data.get("writer", {}),
                     "attempts": len(data.get("attempts", [])), "brief": data.get("brief", ""),
                     "written_inputs": data.get("written_inputs", []), "caveat": data.get("caveat", "")}}


def _print_production(report: list[dict], produced: Path) -> None:
    for entry in report:
        detail = entry.get("path") or entry.get("reason", "")
        via = " -> ".join(entry.get("providers", []))
        flag = "  [PLACEHOLDER]" if entry.get("placeholder") else ""
        print(f"Produce:  {entry['status']:<10} {entry['input']:<22} {entry['capability']:<12} "
              f"{via:<24} {detail}{flag}")
        for failure in entry.get("fallbacks", []):
            print(f"          fell back after {failure[:160]}")
    print(f"Wrote produced job: {produced}")


def _print_receipt_summary(receipt: dict) -> None:
    print(f"Rendered: {receipt['output_path']}")
    print(f"Duration: {receipt['duration_observed_seconds']:.3f}s "
          f"({receipt['frames_observed']} frames)")
    measured = receipt["measurements"]
    if "integrated_lufs" in measured.get("not_applicable", {}):
        print("Audio:    silent programme")
    elif isinstance(measured.get("integrated_lufs"), (int, float)):
        peak = measured.get("true_peak_dbtp")
        print(f"Audio:    {measured['integrated_lufs']:.1f} LUFS integrated"
              + (f", {peak:.1f} dBTP true peak" if isinstance(peak, (int, float)) else ""))
    if receipt.get("contains_placeholder_media"):
        print("WARNING:  contains placeholder media: animatic only, not for publication")
    font = receipt.get("font")
    if font and font.get("substituted"):
        print(f"WARNING:  font {font['requested_family']!r} unavailable; "
              f"rendered with {font['resolved_family']!r}")
    for gate in receipt["quality_gates"]:
        evidence = gate.get("evidence", {})
        detail = f" ({evidence['metric']} = {evidence.get('value')})" if "value" in evidence else ""
        print(f"Gate:     {gate['status']:<22} {gate['id']}{detail}")
    for kind, item in receipt["deliverables"].items():
        print(f"Sidecar:  {kind:<14} {item['path']}")


def _render_recipe(args: argparse.Namespace) -> int:
    """Preview one recipe through the same provider a pipeline would use."""
    import tempfile
    from videogenome.providers.procedural import ProceduralProvider
    suffix = args.output.suffix.lower()
    media = {".mp4": "video", ".png": "image", ".wav": "audio"}.get(suffix)
    if media is None:
        raise ProductionError("Output must end in .mp4, .png or .wav")
    params = {}
    for item in args.set:
        key, _, raw = item.partition("=")
        try:
            params[key] = json.loads(raw)
        except json.JSONDecodeError:
            params[key] = raw
    width, _, height = args.size.partition("x")
    request = {"recipe": args.recipe_id, "media": media, "width": int(width), "height": int(height),
               "fps": args.fps, "duration_seconds": args.duration, "seed": args.seed, "params": params}
    if args.preset:
        request["preset"] = args.preset
    provider = ProceduralProvider("procedural", {})
    with tempfile.TemporaryDirectory(prefix="videogenome-recipe-") as directory:
        result = provider.generate("procedural", request, Path(directory))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copyfile(result.path, args.output)
    print(f"Rendered {args.recipe_id} -> {args.output}")
    print(json.dumps(result.metadata["recipe"]["params"], indent=2))
    return 0


def _click(value: str) -> bool | list[float]:
    if value == "center":
        return True
    x, _, y = value.partition(",")
    try:
        return [float(x), float(y)]
    except ValueError as exc:
        raise ProductionError("--click takes X,Y in pixels, or nothing for the centre") from exc


def _capture(args: argparse.Namespace) -> int:
    """Render any self-contained HTML animation frame-exactly on a virtual clock."""
    from videogenome.service import capture_page
    info = capture_page(args.page, args.output, size=args.size, fps=args.fps, duration=args.duration,
                        seed=args.seed, click=_click(args.click) if args.click else None,
                        audio=not args.no_audio, params=_pairs(args.set), at=args.at, timing=args.timing)
    if info["media"] == "video":
        sound = {"recorded": "with recorded Web Audio", "silent": "page made no sound"}.get(info["audio"], "no audio")
        print(f"Captured {info['frames']} frames ({args.duration:g}s at {args.fps} fps, {args.size}, {sound}) "
              f"-> {args.output}")
    else:
        print(f"Captured still -> {args.output}")
    return 0


def _service(args: argparse.Namespace):
    from videogenome.service import Service, Workspace
    profile = Profile.load(args.pipeline, search=args.pipelines)
    return Service(profile, Workspace(args.workspace), template_dirs=args.templates)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="videogenome",
        description="Fill expert-authored video blueprints and render them with FFmpeg.",
    )
    parser.add_argument("--version", action="version", version=f"videogenome {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    helps = {"validate": "Validate a production job", "compile": "Compile a job to shot IR",
             "render": "Render a complete job", "produce": "Produce missing inputs with providers",
             "make": "Produce missing inputs, then render"}
    for name in ("validate", "compile", "render", "produce", "make"):
        command = commands.add_parser(name, help=helps[name])
        command.add_argument("job", type=Path, help="Production job JSON manifest")
        _template_option(command)
        _format_option(command)
        if name in ("render", "produce", "make"):
            _pipeline_option(command)
        if name in ("compile", "render", "make"):
            command.add_argument("-o", "--output", type=Path, required=True)
        if name in ("produce", "make"):
            command.add_argument("--force", action="store_true", help="Regenerate even if cached")
            command.add_argument("--only", action="append", default=[], metavar="INPUT",
                                 help="Produce only this input (repeatable)")
        if name in ("render", "make"):
            command.add_argument("--receipt", type=Path, help="Write QA/provenance receipt JSON")
            command.add_argument("--no-deliverables", action="store_true",
                                 help="Skip sidecar exporters")
    catalog = commands.add_parser("catalog", help="Discover approved blueprints as JSON")
    catalog.add_argument("--category")
    catalog.add_argument("--tag")
    catalog.add_argument("--orientation", choices=["landscape", "portrait", "square"])
    catalog.add_argument("--engine")
    catalog.add_argument("--shot-kind")
    catalog.add_argument("--self-contained", action="store_true",
                         help="Only templates that render from text inputs alone")
    catalog.add_argument("--table", action="store_true", help="Human-readable summary")
    _template_option(catalog)
    inspect = commands.add_parser("inspect", help="Describe one template's required inputs")
    inspect.add_argument("template_id")
    _template_option(inspect)
    skeleton = commands.add_parser("scaffold", help="Write an incomplete job manifest to fill")
    skeleton.add_argument("template_id")
    skeleton.add_argument("-o", "--output", type=Path, required=True)
    _template_option(skeleton)
    doctor = commands.add_parser("doctor", help="Check FFmpeg, filters, fonts and a pipeline's plugins")
    _template_option(doctor)
    _pipeline_option(doctor)
    commands.add_parser("plugins", help="List plugin types, capabilities and their sources")
    recipes = commands.add_parser("recipes", help="List procedural recipes, their params and presets")
    recipes.add_argument("--media", choices=["audio", "image", "video"])
    recipes.add_argument("--json", action="store_true", help="Full machine-readable descriptions")
    recipe = commands.add_parser("recipe", help="Render one procedural recipe to preview or tweak it")
    recipe.add_argument("recipe_id")
    recipe.add_argument("-o", "--output", type=Path, required=True, help=".mp4, .png or .wav")
    recipe.add_argument("--preset")
    recipe.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                        help="Override a param; VALUE is parsed as JSON when possible (repeatable)")
    recipe.add_argument("--duration", type=float, default=6.0)
    recipe.add_argument("--size", default="1280x720")
    recipe.add_argument("--fps", type=int, default=24)
    recipe.add_argument("--seed", type=int, default=1)
    capture = commands.add_parser("capture", help="Render a self-contained HTML animation frame-exactly to MP4")
    capture.add_argument("page", type=Path, help="HTML file; it may load files from its own directory only")
    capture.add_argument("-o", "--output", type=Path, required=True, help=".mp4, or .png/.jpg for one still")
    capture.add_argument("--size", default="1920x1080", help="WIDTHxHEIGHT (default 1920x1080)")
    capture.add_argument("--fps", type=int, default=30)
    capture.add_argument("--duration", type=float, default=10.0, help="Seconds (default 10)")
    capture.add_argument("--seed", type=int, default=1, help="Seed for Math.random")
    capture.add_argument("--at", type=float, help="Time of the still, in seconds (stills only)")
    capture.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                         help="Expose a value to the page as window.vgSpec.params (repeatable)")
    capture.add_argument("--click", nargs="?", const="center", metavar="X,Y",
                         help="Click once after loading (default: the centre), for click-to-play pages")
    capture.add_argument("--no-audio", action="store_true",
                         help="Do not record the page's Web Audio (default: record it in sync)")
    capture.add_argument("--timing", choices=["clock", "frame"], default="clock",
                         help="clock (default): ordinary rAF/CSS/timer code on a virtual clock; "
                              "frame: the page defines vgSetup/vgRender")
    fill = commands.add_parser("fill", help="Write a job's text inputs from a brief with the pipeline's writer")
    fill.add_argument("template", help="Template id, or an existing job .json whose text inputs to complete")
    _brief_options(fill)
    fill.add_argument("-o", "--output", type=Path, required=True, help="Job JSON to write")
    fill.add_argument("--id", help="Job id (default: derived from the template and brief)")
    fill.add_argument("--force", action="store_true", help="Overwrite an existing output file")
    _template_option(fill)
    _pipeline_option(fill)
    create = commands.add_parser("create", help="Brief to finished video: fill, produce, render")
    create.add_argument("template", help="Template id (see `videogenome catalog`)")
    _brief_options(create)
    create.add_argument("-o", "--output", type=Path, required=True, help="Programme .mp4 to write")
    create.add_argument("--workdir", type=Path, help="Job directory (default: <output>.job next to the output)")
    create.add_argument("--receipt", type=Path, help="Write QA/provenance receipt JSON")
    create.add_argument("--no-deliverables", action="store_true", help="Skip sidecar exporters")
    _template_option(create)
    _format_option(create)
    _pipeline_option(create)
    bench = commands.add_parser("bench", help="Measure how reliably the pipeline's writer fills templates")
    bench.add_argument("suite", type=Path, help="Brief suite JSON (see examples/briefs/smoke.json)")
    bench.add_argument("-o", "--output", type=Path, help="Write the full report JSON")
    bench.add_argument("--render", type=Path, metavar="DIR", help="Also produce, render and gate each video into DIR")
    bench.add_argument("--max-attempts", type=int, default=3)
    _template_option(bench)
    _pipeline_option(bench)
    lib = commands.add_parser("library", help="Every class of video, by readiness: template, code or prompt")
    lib.add_argument("--level", choices=["template", "code", "prompt"])
    lib.add_argument("--family")
    lib.add_argument("--json", action="store_true", help="Full machine-readable descriptions")
    genome = commands.add_parser("genome", help="Show one class: its templates, recipes and authoring prompt")
    genome.add_argument("genome_id")
    genome.add_argument("--prompt", action="store_true", help="Print only the authoring prompt")
    scaffold_recipe = commands.add_parser("recipe-new", help="Start a clock-timed scene recipe from the toolkit")
    scaffold_recipe.add_argument("recipe_id", help="area.name, e.g. scene.my-reveal")
    scaffold_recipe.add_argument("-o", "--output", type=Path, required=True, help="New recipe directory")
    scaffold_recipe.add_argument("--three", action="store_true", help="Include the vendored three.js")
    studio = commands.add_parser("studio", help="Local web UI: browse, fill, render, tune code, connect agents")
    studio.add_argument("--workspace", type=Path, default=Path("videogenome-workspace"),
                        help="Where runs are written (default ./videogenome-workspace)")
    studio.add_argument("--port", type=int, default=8765, help="Port on 127.0.0.1 (0 picks a free one)")
    studio.add_argument("--open", action="store_true", help="Open the browser")
    _template_option(studio)
    _pipeline_option(studio)
    previews = commands.add_parser("previews", help="Render each template's sample job for the Studio library")
    previews.add_argument("--workspace", type=Path, default=Path("videogenome-workspace"))
    previews.add_argument("--only", action="append", default=[], metavar="TEMPLATE")
    previews.add_argument("--force", action="store_true", help="Re-render previews that already exist")
    _template_option(previews)
    _pipeline_option(previews)
    mcp = commands.add_parser("mcp", help="MCP server on stdio, so agents can make videos")
    mcp.add_argument("--workspace", type=Path, default=Path("videogenome-workspace"),
                     help="Where runs are written (default ./videogenome-workspace)")
    _template_option(mcp)
    _pipeline_option(mcp)
    pipelines = commands.add_parser("pipelines", help="List available pipeline profiles")
    pipelines.add_argument("--pipelines", type=Path, action="append", default=[], metavar="DIR")
    args = parser.parse_args(argv)

    try:
        if args.command == "doctor":
            ok = True
            rows = diagnose(args.templates)
            if args.pipeline:
                rows += Profile.load(args.pipeline, search=args.pipelines).check()
            for status, name, detail in rows:
                ok &= status != "FAIL"
                print(f"{status:<5} {name:<28} {detail}")
            return 0 if ok else 1
        if args.command == "plugins":
            for kind in KINDS:
                print(f"{kind}s:")
                for name, source in available(kind).items():
                    try:
                        summary = load_type(kind, name).summary
                    except Exception as exc:  # noqa: BLE001 - report broken third-party plugins
                        summary = f"(cannot load: {exc})"
                    print(f"  {name:<20} {summary}\n  {'':<20} {source}")
            print("capabilities:")
            for name, spec in sorted(CAPABILITIES.items()):
                print(f"  {name:<20} {'/'.join(spec['media']):<12} {spec['description']}")
            return 0
        if args.command == "recipes":
            from videogenome.procedural import catalog as recipe_catalog
            entries = [r.describe() for r in recipe_catalog.discover().values()
                       if not args.media or args.media in r.data["media"]]
            if args.json:
                print(json.dumps(entries, indent=2))
                return 0
            for entry in entries:
                print(f"{entry['id']:<26} {'/'.join(entry['media']):<12} {entry['runtime']:<8} {entry['title']}")
                print(f"  presets: {', '.join(entry['presets']) or '-'}")
                print(f"  params:  {', '.join(entry['params'])}")
            return 0
        if args.command == "recipe":
            return _render_recipe(args)
        if args.command == "capture":
            return _capture(args)
        if args.command == "pipelines":
            for entry in discover_pipelines(args.pipelines):
                writer = f" writer: {entry['writer']}" if entry.get("writer") else ""
                print(f"{entry['id']:<28} routes: {', '.join(entry['routes']) or '-':<34}{writer} "
                      f"[{entry['verification']}]\n  {entry['description']}")
            return 0
        if args.command == "studio":
            from videogenome.studio import Studio
            app = Studio(_service(args), port=args.port)
            if args.open:
                import threading
                import webbrowser
                threading.Timer(0.8, lambda: webbrowser.open(app.url)).start()
            app.serve()
            return 0
        if args.command == "previews":
            service = _service(args)
            failed = 0
            for template_id in sorted(args.only or service.sample_jobs()):
                if (service.previews_dir / f"{template_id}.mp4").is_file() and not args.force:
                    print(f"cached   {template_id}")
                    continue
                try:
                    result = service.build_preview(template_id)
                    state = "gates failed" if result["automated_gates_failed"] else "ok"
                    print(f"{state:<8} {template_id:<38} {result['output']}")
                except ProductionError as exc:
                    failed += 1
                    print(f"skipped  {template_id:<38} {str(exc)[:120]}")
            return 1 if failed and args.only else 0
        if args.command == "mcp":
            from videogenome.mcp_server import Server
            Server(_service(args)).serve()
            return 0
        if args.command == "library":
            from videogenome.genomes import library
            rows = library(level=args.level, family=args.family)
            if args.json:
                print(json.dumps(rows, indent=2, ensure_ascii=False))
                return 0
            badge = {"template": "TEMPLATE", "code": "CODE", "prompt": "PROMPT"}
            for row in rows:
                links = ", ".join(row.get("templates") or row.get("recipes") or ["videogenome genome " + row["id"] + " --prompt"])
                print(f"{badge[row['level']]:<9} {row['family']:<12} {row['id']:<24} {row['title']}\n"
                      f"{'':<23}{'/'.join(row['formats']):<12} -> {links}")
            counts = {level: sum(r["level"] == level for r in rows) for level in badge}
            print(f"\n{counts['template']} ready to fill, {counts['code']} ready code, {counts['prompt']} prompt only")
            return 0
        if args.command == "genome":
            from videogenome.genomes import get
            entry = get(args.genome_id)
            if args.prompt:
                print(entry.prompt())
                return 0
            print(json.dumps(entry.describe(), indent=2, ensure_ascii=False))
            return 0
        if args.command == "recipe-new":
            from videogenome.authoring import scaffold_recipe
            for path in scaffold_recipe(args.recipe_id, args.output, three=args.three):
                print(f"Wrote {path}")
            print(f"Preview: videogenome capture {args.output / 'index.html'} -o preview.mp4 --duration 6")
            return 0
        if args.command == "bench":
            from videogenome.bench import run_bench
            profile = Profile.load(args.pipeline, search=args.pipelines)
            report = run_bench(args.suite, profile, template_dirs=args.templates, render_dir=args.render,
                               max_attempts=args.max_attempts)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print("Summary:  " + ", ".join(f"{k}={v}" for k, v in report["summary"].items()))
            return 0 if report["summary"]["as_expected"] == report["summary"]["briefs"] else 1
        if args.command == "fill":
            from videogenome.create import make_filler, save_fill
            if args.output.exists() and not args.force:
                raise ProductionError(f"Refusing to overwrite existing file: {args.output} (use --force)")
            profile = Profile.load(args.pipeline, search=args.pipelines)
            filler = make_filler(args.template, _brief(args), profile, template_dirs=args.templates,
                                 pinned=_pairs(args.set), max_attempts=args.max_attempts, job_id=args.id)
            result = filler.run()
            record = save_fill(result, args.output)
            _print_fill(result, args.output, record)
            if result.status == "incomplete":
                print("INCOMPLETE: the brief lacks what the inputs above need; add it to the brief "
                      "or set them with --set", file=sys.stderr)
                return EXIT_INCOMPLETE
            if result.status == "failed":
                print("ERROR: the writer's copy still breaks the template; see the problems above",
                      file=sys.stderr)
                return 1
            return 0
        if args.command == "create":
            from videogenome.create import FillIncomplete, create as create_video
            if args.output.suffix.lower() != ".mp4":
                raise ProductionError("Output must be an .mp4 file")
            profile = Profile.load(args.pipeline, search=args.pipelines)
            try:
                receipts, _, _ = create_video(
                    args.template, _brief(args), profile, args.output, template_dirs=args.templates,
                    pinned=_pairs(args.set), max_attempts=args.max_attempts, workdir=args.workdir,
                    write_deliverables=not args.no_deliverables, formats=args.format)
            except ProductionError as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return EXIT_INCOMPLETE if isinstance(exc, FillIncomplete) else 1
            failed = False
            for format_id, receipt in receipts.items():
                if len(receipts) > 1:
                    print(f"Format:   {label(format_id)}")
                if args.receipt:
                    path = output_path(args.receipt, format_id, len(receipts) > 1)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
                _print_receipt_summary(receipt)
                failed |= any(gate["status"] == "failed" for gate in receipt["quality_gates"])
            writer = receipt["fill"]["writer"]
            print(f"Copy:     written by {writer.get('model', {}).get('name') or writer['name']}"
                  " from the brief; review claims before publishing")
            if failed:
                print("ERROR: an automated quality gate failed; output kept for inspection", file=sys.stderr)
                return EXIT_GATE_FAILED
            return 0
        if args.command == "catalog":
            entries = discover(category=args.category, tag=args.tag,
                               orientation=args.orientation, engine=args.engine,
                               shot_kind=args.shot_kind,
                               self_contained=True if args.self_contained else None,
                               template_dirs=args.templates)
            if not args.table:
                print(json.dumps(entries, indent=2))
                return 0
            for entry in entries:
                media = "text only" if entry["self_contained"] else "needs media"
                ratios = "/".join(f["aspect_ratio"] for f in entry["formats"])
                print(f"{entry['id']:<40} {entry['version']:<7} "
                      f"{ratios:>14} {entry['duration_seconds']:>6.1f}s  "
                      f"{media:<11}  {entry['title']}")
            return 0
        if args.command == "inspect":
            print(json.dumps(inspect_template(args.template_id, args.templates), indent=2))
            return 0
        if args.command == "scaffold":
            if args.output.exists():
                raise ProductionError(f"Refusing to overwrite existing file: {args.output}")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            draft = scaffold(args.template_id, args.output, args.templates)
            args.output.write_text(json.dumps(draft, indent=2) + "\n", encoding="utf-8")
            optional = inspect_template(args.template_id, args.templates)["optional_inputs"]
            print(f"Wrote incomplete job skeleton (requires inputs/assets): {args.output}")
            if optional:
                print(f"Optional inputs you may add: {', '.join(sorted(optional))}")
            return 0
        formats = _job_formats(args.job, args.format, args.templates)
        several = len(formats) > 1
        profile = (Profile.load(args.pipeline, search=args.pipelines)
                   if args.command in ("produce", "make", "render") else None)
        failed = False
        for format_id in formats:
            job = args.job
            if several:
                print(f"Format:   {label(format_id)}")
            if args.command in ("produce", "make"):
                job, report = produce(args.job, profile, template_dirs=args.templates,
                                      force=args.force, only=args.only, format=format_id)
                _print_production(report, job)
                if args.command == "produce":
                    continue
            plan = compile_job(job, template_dirs=args.templates, allow_pending=args.command == "validate",
                               format=format_id)
            if args.command == "validate":
                pending = plan.get("pending_inputs", [])
                where = f" ({label(format_id)})" if several else ""
                print(f"PASS {args.job}{where}: {len(plan['segments'])} shots, {plan['total_frames']} frames"
                      + (f"; to produce before rendering: {', '.join(pending)}" if pending else ""))
            elif args.command == "compile":
                path = output_path(args.output, format_id, several)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
                print(f"Wrote immutable shot plan: {path}")
            else:
                receipt = run_render(plan, job.resolve().parent, output_path(args.output, format_id, several),
                                     profile, write_deliverables=not args.no_deliverables,
                                     context=_fill_context(args.job))
                if args.receipt:
                    path = output_path(args.receipt, format_id, several)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
                _print_receipt_summary(receipt)
                failed |= any(gate["status"] == "failed" for gate in receipt["quality_gates"])
        if failed:
            print("ERROR: an automated quality gate failed; output kept for inspection", file=sys.stderr)
            return EXIT_GATE_FAILED
        return 0
    except ProductionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
