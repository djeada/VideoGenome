"""CLI: validate, compile and render content-only production jobs."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from videogenome.compiler import ProductionError, compile_job
from videogenome.catalog import discover, inspect_template, scaffold
from videogenome.render import render


def main() -> int:
    parser = argparse.ArgumentParser(prog="videogenome")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "compile", "render"):
        command = commands.add_parser(name)
        command.add_argument("job", type=Path, help="Production job JSON manifest")
        if name in ("compile", "render"):
            command.add_argument("-o", "--output", type=Path, required=True)
        if name == "render":
            command.add_argument("--receipt", type=Path, help="Write QA/provenance receipt JSON")
    catalog = commands.add_parser("catalog", help="Discover approved blueprints as JSON")
    catalog.add_argument("--category")
    catalog.add_argument("--tag")
    catalog.add_argument("--orientation", choices=["landscape", "portrait", "square"])
    catalog.add_argument("--engine")
    catalog.add_argument("--shot-kind")
    inspect = commands.add_parser("inspect", help="Describe one template's required inputs")
    inspect.add_argument("template_id")
    skeleton = commands.add_parser("scaffold", help="Write an incomplete job manifest to fill")
    skeleton.add_argument("template_id")
    skeleton.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        if args.command == "catalog":
            print(json.dumps(discover(category=args.category, tag=args.tag,
                                      orientation=args.orientation, engine=args.engine,
                                      shot_kind=args.shot_kind), indent=2))
            return 0
        if args.command == "inspect":
            print(json.dumps(inspect_template(args.template_id), indent=2))
            return 0
        if args.command == "scaffold":
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(scaffold(args.template_id, args.output), indent=2) + "\n",
                encoding="utf-8"
            )
            print(f"Wrote incomplete job skeleton (requires inputs/assets): {args.output}")
            return 0
        plan = compile_job(args.job)
        if args.command == "validate":
            print(f"PASS {args.job}: {len(plan['segments'])} shots, {plan['total_frames']} frames")
        elif args.command == "compile":
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
            print(f"Wrote immutable shot plan: {args.output}")
        else:
            receipt = render(plan, args.job.resolve().parent, args.output)
            if args.receipt:
                args.receipt.parent.mkdir(parents=True, exist_ok=True)
                args.receipt.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            print(f"Rendered: {args.output}")
            print(f"Duration: {receipt['duration_observed_seconds']:.3f}s")
        return 0
    except ProductionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
