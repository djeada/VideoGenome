"""CLI: discover templates, validate, compile and render content-only production jobs."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from videogenome import __version__
from videogenome.catalog import discover, inspect_template, scaffold
from videogenome.compiler import ProductionError, compile_job
from videogenome.doctor import diagnose
from videogenome.pipeline import run_render
from videogenome.plugins import CAPABILITIES, KINDS, available, load_type
from videogenome.produce import produce
from videogenome.profile import Profile, discover_pipelines

EXIT_GATE_FAILED = 3


def _template_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--templates", type=Path, action="append", default=[], metavar="DIR",
        help="Trust an additional template directory (repeatable; also VIDEOGENOME_TEMPLATE_PATH)",
    )


def _pipeline_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--pipeline", metavar="ID|PATH",
                        help="Pipeline profile (default: $VIDEOGENOME_PIPELINE or FFmpeg-only)")
    parser.add_argument("--pipelines", type=Path, action="append", default=[], metavar="DIR",
                        help="Extra directory of pipeline profiles (also VIDEOGENOME_PIPELINE_PATH)")


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
        if args.command == "pipelines":
            for entry in discover_pipelines(args.pipelines):
                print(f"{entry['id']:<28} routes: {', '.join(entry['routes']) or '-':<34} "
                      f"[{entry['verification']}]\n  {entry['description']}")
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
                print(f"{entry['id']:<40} {entry['version']:<7} "
                      f"{entry['output']['aspect_ratio']:>5} {entry['duration_seconds']:>6.1f}s  "
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
        if args.command in ("produce", "make"):
            profile = Profile.load(args.pipeline, search=args.pipelines)
            produced, report = produce(args.job, profile, template_dirs=args.templates,
                                       force=args.force, only=args.only)
            _print_production(report, produced)
            if args.command == "produce":
                return 0
            args.job = produced
        plan = compile_job(args.job, template_dirs=args.templates)
        if args.command == "validate":
            print(f"PASS {args.job}: {len(plan['segments'])} shots, {plan['total_frames']} frames")
        elif args.command == "compile":
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
            print(f"Wrote immutable shot plan: {args.output}")
        else:
            if args.command == "render":
                profile = Profile.load(args.pipeline, search=args.pipelines)
            receipt = run_render(plan, args.job.resolve().parent, args.output, profile,
                                 write_deliverables=not args.no_deliverables)
            if args.receipt:
                args.receipt.parent.mkdir(parents=True, exist_ok=True)
                args.receipt.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            _print_receipt_summary(receipt)
            if any(gate["status"] == "failed" for gate in receipt["quality_gates"]):
                print("ERROR: an automated quality gate failed; output kept for inspection",
                      file=sys.stderr)
                return EXIT_GATE_FAILED
        return 0
    except ProductionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
