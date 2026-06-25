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

from .dsl import spec_from_dict, ComponentGroup
from .validator import validate
from .cutlist import generate_cutlist
from . import exporters


def _emit_project(project: ComponentGroup, args) -> int:
    """Emit a whole group: aggregate validation, combined cut list, one quote."""
    unit = "imperial" if getattr(args, "imperial", False) else "metric"
    result = validate(project)
    print(project.to_json())
    print()
    if result.warnings:
        print("Warnings:")
        for w in result.warnings:
            print(f"  {w}")
    if not result.ok:
        print("Errors (project is not buildable):", file=sys.stderr)
        for e in result.errors:
            print(f"  {e}", file=sys.stderr)
        return 1

    # Critic: verify the assembled run — cabinets must not collide.
    from .agents.critic import critique
    crit = critique(project)
    r = crit.report
    print(f"\nAssembled run: {r.get('component_count', 0)} components, "
          f"{r.get('panel_count', 0)} panels, "
          f"{r.get('interference_count', 0)} interference(s)")
    if not crit.ok:
        print("\nCritic found assembly errors:", file=sys.stderr)
        for e in crit.errors:
            print(f"  {e}", file=sys.stderr)
        return 1

    cutlist = generate_cutlist(project)
    print("\nCombined cut list:")
    print(cutlist.to_csv(unit))
    print("\nHardware:")
    print(cutlist.hardware_csv())
    print("\n" + cutlist.summary(unit))

    if args.estimate:
        from .estimator import estimate
        print("\n" + estimate(project).report_text(unit))

    if args.drill:
        from .drilling import drilling_schedule
        print("\n" + drilling_schedule(project).report_text())

    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        exporters.write_cutlist_csv(cutlist, out / "cutlist.csv", unit)
        exporters.write_hardware_csv(cutlist, out / "hardware.csv")
        (out / "project.json").write_text(project.to_json() + "\n", encoding="utf-8")
        print(f"\nWrote project.json, cutlist.csv, hardware.csv to {out}/")
        if args.drill:
            from .drilling import drilling_schedule
            (out / "drilling.csv").write_text(
                drilling_schedule(project).to_csv() + "\n", encoding="utf-8")
            print("Wrote drilling.csv")
        if args.dxf:
            exporters.export_cutlayout_dxf(project, out / "cutlayout.dxf",
                                           cutlist=cutlist)
            print("Wrote cutlayout.dxf")
        if args.step or args.stl or args.glb:
            from .builder import build_project, measure
            model = build_project(project)
            print(f"Assembled geometry: {measure(model)}")
            if args.step:
                exporters.export_step(model, out / "project.step")
                print("Wrote project.step")
            if args.stl:
                exporters.export_stl(model, out / "project.stl")
                print("Wrote project.stl")
            if args.glb:
                exporters.export_glb(model, out / "project.glb")
                print("Wrote project.glb")
    return 0


def _emit(spec, args) -> int:
    if isinstance(spec, ComponentGroup):
        return _emit_project(spec, args)
    unit = "imperial" if getattr(args, "imperial", False) else "metric"
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
    print("\n" + crit.report_text(unit))
    if not crit.ok:
        print("\nCritic found geometry errors:", file=sys.stderr)
        for e in crit.errors:
            print(f"  {e}", file=sys.stderr)
        return 1

    # Render-based review: snapshot the model and optionally let Claude inspect it.
    if args.render or args.visual_review:
        render_path = (Path(args.out) / "render.png") if args.out else None
        if args.visual_review:
            from .agents.critic import visual_review
            vis = visual_review(spec, image_path=render_path)
            if "render_path" in vis.report:
                print(f"\nRendered snapshot: {vis.report['render_path']}")
            notes = vis.report.get("visual_notes")
            if notes:
                verdict = "looks correct" if vis.report.get("looks_correct") else "issues found"
                print(f"Visual review ({verdict}): {notes}")
            for v in vis.issues:
                print(f"  {v}")
        else:
            from .render import render_cabinet
            target = render_path or Path("render.png")
            render_cabinet(spec, target)
            print(f"\nRendered snapshot: {target}")

    cutlist = generate_cutlist(spec)
    print("\nCut list:")
    print(cutlist.to_csv(unit))
    print("\nHardware:")
    print(cutlist.hardware_csv())
    print("\n" + cutlist.summary(unit))

    if args.estimate:
        from .estimator import estimate
        print("\n" + estimate(spec, cutlist=cutlist).report_text(unit))

    if args.drill:
        from .drilling import drilling_schedule
        print("\n" + drilling_schedule(spec).report_text())

    if args.joinery:
        from .joinery import joinery_schedule
        print("\n" + joinery_schedule(spec).report_text())

    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        exporters.write_cutlist_csv(cutlist, out / "cutlist.csv", unit)
        exporters.write_hardware_csv(cutlist, out / "hardware.csv")
        (out / "spec.json").write_text(spec.to_json() + "\n", encoding="utf-8")
        print(f"\nWrote spec.json, cutlist.csv, hardware.csv to {out}/")
        if args.drill:
            from .drilling import drilling_schedule
            (out / "drilling.csv").write_text(
                drilling_schedule(spec).to_csv() + "\n", encoding="utf-8")
            print("Wrote drilling.csv")
        if args.dxf:
            exporters.export_cutlayout_dxf(spec, out / "cutlayout.dxf", cutlist=cutlist)
            print("Wrote cutlayout.dxf")

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
    common.add_argument("--dxf", action="store_true",
                        help="export a DXF cut-layout nest (no build123d needed)")
    common.add_argument("--render", action="store_true",
                        help="render PNG snapshots (needs matplotlib)")
    common.add_argument("--visual-review", action="store_true",
                        help="have Claude visually review the render (needs API key)")
    common.add_argument("--estimate", action="store_true",
                        help="estimate sheet count and cost")
    common.add_argument("--drill", action="store_true",
                        help="print the drilling schedule (32mm system, hinges)")
    common.add_argument("--joinery", action="store_true",
                        help="print the joinery setup sheet (dado/rabbet/etc.)")
    common.add_argument("--imperial", action="store_true",
                        help="show cut list and reports in fractional inches "
                             "(engine stays metric; the 32mm drilling schedule "
                             "remains in mm)")

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
        import json as _json
        data = _json.loads(Path(args.spec_file).read_text(encoding="utf-8"))
        return _emit(spec_from_dict(data), args)

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
