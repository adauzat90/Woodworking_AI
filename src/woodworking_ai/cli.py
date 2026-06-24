"""Command-line entry point.

Examples
--------
    # Natural language -> spec -> cut list (needs ANTHROPIC_API_KEY):
    woodai design "36 inch sink base, two doors, shaker, soft-close"

    # Same but also export 3D geometry (needs build123d):
    woodai design "tall pantry 600 wide" --out ./out --step --stl

    # Skip the LLM and build straight from a spec JSON file:
    woodai build my_cabinet.json --out ./out --step
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .dsl import CabinetSpec
from .validator import validate
from .cutlist import generate_cutlist
from . import exporters


def _emit(spec: CabinetSpec, args) -> int:
    result = validate(spec)
    print(spec.to_json())
    print()
    if result.warnings:
        print("Warnings:")
        for w in result.warnings:
            print(f"  {w}")
    if not result.ok:
        print("Errors (design is not buildable):", file=sys.stderr)
        for e in result.errors:
            print(f"  {e}", file=sys.stderr)
        return 1

    # Critic: verify the geometry the spec produces (analytical, no CAD needed).
    from .agents.critic import critique
    crit = critique(spec)
    print("\n" + crit.report_text())
    if not crit.ok:
        print("\nCritic found geometry errors:", file=sys.stderr)
        for e in crit.errors:
            print(f"  {e}", file=sys.stderr)
        return 1

    cutlist = generate_cutlist(spec)
    print("\nCut list:")
    print(cutlist.to_csv())
    print("\nHardware:")
    print(cutlist.hardware_csv())
    print("\n" + cutlist.summary())

    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        exporters.write_cutlist_csv(cutlist, out / "cutlist.csv")
        exporters.write_hardware_csv(cutlist, out / "hardware.csv")
        (out / "spec.json").write_text(spec.to_json() + "\n", encoding="utf-8")
        print(f"\nWrote spec.json, cutlist.csv, hardware.csv to {out}/")

        if args.step or args.stl or args.glb:
            from .builder import build_model, measure
            model = build_model(spec)
            dims = measure(model)
            print(f"Geometry built: {dims}")
            if args.step:
                exporters.export_step(model, out / "cabinet.step")
                print("Wrote cabinet.step")
            if args.stl:
                exporters.export_stl(model, out / "cabinet.stl")
                print("Wrote cabinet.stl")
            if args.glb:
                exporters.export_glb(model, out / "cabinet.glb")
                print("Wrote cabinet.glb")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="woodai", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--out", help="output directory for files")
    common.add_argument("--step", action="store_true", help="export STEP (needs build123d)")
    common.add_argument("--stl", action="store_true", help="export STL (needs build123d)")
    common.add_argument("--glb", action="store_true", help="export GLB (needs build123d)")

    p_design = sub.add_parser("design", parents=[common],
                              help="natural language -> design (uses Claude)")
    p_design.add_argument("prompt", help="what to build, in plain language")
    p_design.add_argument("--model", help="override the Claude model id")
    p_design.add_argument("--attempts", type=int, default=3)

    p_build = sub.add_parser("build", parents=[common],
                             help="build from an existing spec JSON file")
    p_build.add_argument("spec_file", help="path to a spec .json file")

    args = parser.parse_args(argv)

    if args.cmd == "design":
        from .agents import design_from_prompt
        print(f"Designing: {args.prompt!r}\n")
        res = design_from_prompt(args.prompt, max_attempts=args.attempts, model=args.model)
        print(f"(agent converged in {res.attempts} attempt(s))\n")
        return _emit(res.spec, args)

    if args.cmd == "build":
        spec = CabinetSpec.from_json(Path(args.spec_file).read_text(encoding="utf-8"))
        return _emit(spec, args)

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
