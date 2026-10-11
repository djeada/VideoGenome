"""CLI: validate, compile and render content-only production jobs."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from videogenome.compiler import ProductionError, compile_job
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
    args = parser.parse_args()

    try:
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
