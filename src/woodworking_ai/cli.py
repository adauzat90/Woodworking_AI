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
import os
import sys
from pathlib import Path


def _default_unit() -> str:
    """The shop's default display unit (G6b: imperial-first for US shops).

    An imperial-first shop sets ``WOODAI_UNITS=in`` (or ``imperial``) once and
    every report opens in fractional inches without passing ``--imperial`` each
    run. Anything else (or unset) keeps the millimetre-native default. The engine
    stays mm-native regardless — this only chooses the display layer.
    """
    val = os.environ.get("WOODAI_UNITS", "").strip().lower()
    if val in ("in", "inch", "inches", "imperial"):
        return "imperial"
    return "metric"

from .dsl import spec_from_dict, ComponentGroup
from . import service


def _tooling_from_args(args):
    """A :class:`ShopTooling` from ``--shop``/``--tools``, or ``None``.

    ``--shop`` picks a preset; ``--tools`` is an explicit comma-list of owned
    capabilities (turning everything else off). ``--tools`` wins when both are
    given. ``None`` (neither flag) leaves the design unconstrained.
    """
    from .tooling import PRESETS, ShopTooling
    tools = getattr(args, "tools", None)
    shop = getattr(args, "shop", None)
    if tools:
        names = [t for t in tools.replace(",", " ").split() if t]
        return ShopTooling.from_names(names)
    if shop:
        return PRESETS.get(shop)
    return None


def _emit(spec, args, tooling=None) -> int:
    """Validate, critique, and report a spec (cabinet/table or whole project).

    Runs the design pipeline exactly once through :func:`service.assemble` and
    writes every requested export through :func:`service.export_bytes`; this
    function only does presentation (stdout text/CSV and choosing filenames).
    A :class:`ComponentGroup` is reported as one aggregated run; the few places
    the two paths read differently are gated on ``is_group``. ``tooling`` (a
    :class:`~tooling.ShopTooling`) constrains validation to makeable joinery.
    """
    is_group = isinstance(spec, ComponentGroup)
    noun = "project" if is_group else "design"
    # --imperial forces inches; otherwise fall back to the shop default
    # (WOODAI_UNITS), which is "metric" unless an imperial-first shop set it.
    unit = "imperial" if getattr(args, "imperial", False) else _default_unit()

    asm = service.assemble(spec, tooling=tooling)

    print(spec.to_json())
    print()
    result = asm.validation
    if result.warnings:
        print("Warnings:")
        for w in result.warnings:
            print(f"  {w}")
    if not result.ok:
        print(f"Errors ({noun} is not buildable):", file=sys.stderr)
        for e in result.errors:
            print(f"  {e}", file=sys.stderr)
        return 1

    # Critic: verify the geometry the spec produces (analytical, no CAD needed).
    crit = asm.critique
    if is_group:
        r = crit.report
        print(f"\nAssembled run: {r.get('component_count', 0)} components, "
              f"{r.get('panel_count', 0)} panels, "
              f"{r.get('interference_count', 0)} interference(s)")
    else:
        print("\n" + crit.report_text(unit))
    if not crit.ok:
        label = "assembly errors" if is_group else "geometry errors"
        print(f"\nCritic found {label}:", file=sys.stderr)
        for e in crit.errors:
            print(f"  {e}", file=sys.stderr)
        return 1

    # Render-based review: snapshot the model and optionally let Claude inspect
    # it (single specs only — a whole run is reviewed analytically above).
    if not is_group and (args.render or args.visual_review):
        render_path = (Path(args.out) / "render.png") if args.out else None
        if args.visual_review:
            from .agents.critic import visual_review
            vis = visual_review(spec, image_path=render_path)
            if "render_path" in vis.report:
                print(f"\nRendered snapshot: {vis.report['render_path']}")
            notes = vis.report.get("visual_notes")
            if notes:
                verdict = ("looks correct" if vis.report.get("looks_correct")
                           else "issues found")
                print(f"Visual review ({verdict}): {notes}")
            for v in vis.issues:
                print(f"  {v}")
        else:
            from .render import render_cabinet
            target = render_path or Path("render.png")
            render_cabinet(spec, target)
            print(f"\nRendered snapshot: {target}")

    cutlist = asm.cutlist
    print("\nCombined cut list:" if is_group else "\nCut list:")
    print(cutlist.to_csv(unit))
    print("\nHardware:")
    print(cutlist.hardware_csv())
    print("\n" + cutlist.summary(unit))

    if args.estimate:
        print("\n" + asm.estimate.report_text(unit))

    if args.drill:
        print("\n" + asm.drilling.report_text())

    if not is_group and args.joinery:
        print("\n" + asm.joinery.report_text())

    if not is_group and args.assembly:
        print("\n" + asm.assembly.report_text())

    # Build plan: skill rating + method-aware phase time breakdown. The time
    # model reflects the supplied tooling (hand vs. jig vs. machine); with no
    # --shop/--tools it uses a stable well-equipped default.
    _print_plan(asm.plan)

    if getattr(args, "from_stock", None):
        import json as _json
        from .cutplan import boards_from_dicts, cut_plan
        data = _json.loads(Path(args.from_stock).read_text(encoding="utf-8"))
        boards = boards_from_dicts(data)
        plan = cut_plan(spec, boards, cutlist=cutlist)
        print("\n" + plan.report_text(unit))

    if tooling is not None or getattr(args, "tools_list", False):
        from .tooling import tools_needed
        print("\nTools needed:")
        for t in tools_needed(spec, tooling):
            mark = "" if t.owned is None else ("  ✓ have" if t.owned
                                               else "  ✗ MISSING")
            print(f"  {t.operation:<26} {t.tool}{mark}")

    if args.out:
        _write_outputs(spec, asm, args, unit, is_group=is_group)
    return 0


def _print_plan(plan: dict) -> None:
    """Print the skill rating and the method-aware phase time breakdown."""
    skill = plan.get("skill", {})
    time = plan.get("time", {})
    print("\nBuild plan:")
    print(f"  skill level: {skill.get('level', '?')}")
    for d in skill.get("drivers", []):
        print(f"    - {d}")
    phases = time.get("hours_by_phase", {})
    print(f"  estimated time: {time.get('total', 0):.1f} h")
    for phase in ("mill", "joinery", "assembly", "finish", "hardware"):
        hrs = phases.get(phase, 0.0)
        if hrs:
            print(f"    {phase:<10} {hrs:5.2f} h")
    for d in time.get("drivers", []):
        print(f"    · {d}")


def _write_outputs(spec, asm, args, unit: str, *, is_group: bool) -> None:
    """Write the requested export files via the service export layer."""
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    def write(fmt: str, filename: str) -> None:
        data, _mime, _name = service.export_bytes(spec, fmt, units=unit)
        (out / filename).write_bytes(data)

    write("cutlist", "cutlist.csv")
    write("hardware", "hardware.csv")
    spec_file = "project.json" if is_group else "spec.json"
    (out / spec_file).write_text(spec.to_json() + "\n", encoding="utf-8")
    print(f"\nWrote {spec_file}, cutlist.csv, hardware.csv to {out}/")

    if args.drill:
        write("drilling", "drilling.csv")
        print("Wrote drilling.csv")
    if args.dxf:
        write("dxf", "cutlayout.dxf")
        print("Wrote cutlayout.dxf")
    if not is_group and args.drawings:
        write("drawings", "drawings.svg")
        print("Wrote drawings.svg")
    if getattr(args, "from_stock", None):
        import json as _json
        from .cutplan import boards_from_dicts, cut_plan
        data = _json.loads(Path(args.from_stock).read_text(encoding="utf-8"))
        plan = cut_plan(spec, boards_from_dicts(data), cutlist=asm.cutlist)
        (out / "cutplan.csv").write_text(plan.to_csv(unit) + "\n",
                                         encoding="utf-8")
        print("Wrote cutplan.csv")
    if not is_group and getattr(args, "package", False):
        write("package", "build_package.pdf")
        print("Wrote build_package.pdf")

    if args.step or args.stl or args.glb or getattr(args, "dae", False):
        from .builder import build_model, measure
        joinery_geometry = getattr(args, "joinery_geometry", False)
        model = build_model(spec, joinery_geometry=joinery_geometry)
        verb = "Assembled geometry" if is_group else "Geometry built"
        print(f"{verb}: {measure(model)}")
        base = "project" if is_group else "cabinet"
        from . import exporters
        if args.step:
            exporters.export_step(model, out / f"{base}.step")
            print(f"Wrote {base}.step")
        if args.stl:
            exporters.export_stl(model, out / f"{base}.stl")
            print(f"Wrote {base}.stl")
        if args.glb:
            exporters.export_glb(model, out / f"{base}.glb")
            print(f"Wrote {base}.glb")
        if getattr(args, "dae", False):
            exporters.export_dae(model, out / f"{base}.dae")
            print(f"Wrote {base}.dae")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="woodai", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--out", help="output directory for files")
    common.add_argument("--step", action="store_true", help="export STEP (needs build123d)")
    common.add_argument("--stl", action="store_true", help="export STL (needs build123d)")
    common.add_argument("--glb", action="store_true", help="export GLB (needs build123d)")
    common.add_argument("--dae", action="store_true",
                        help="export Collada DAE for SketchUp (needs build123d + trimesh)")
    common.add_argument("--dxf", action="store_true",
                        help="export a DXF cut-layout nest (no build123d needed)")
    common.add_argument("--drawings", action="store_true",
                        help="export dimensioned 2D shop drawings (SVG)")
    common.add_argument("--package", action="store_true",
                        help="export the printable build-package PDF (needs reportlab)")
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
    common.add_argument("--joinery-geometry", action="store_true",
                        dest="joinery_geometry",
                        help="cut joinery + bores into the exported STEP/STL/GLB "
                             "B-Rep (machine honest; needs build123d)")
    common.add_argument("--assembly", action="store_true",
                        help="print the step-by-step assembly sequence")
    common.add_argument("--imperial", action="store_true",
                        help="show cut list and reports in fractional inches "
                             "(engine stays metric; the 32mm drilling schedule "
                             "remains in mm). An imperial-first shop can set "
                             "WOODAI_UNITS=in to make this the default")
    common.add_argument("--shop", choices=["full", "hobbyist", "hand"],
                        help="design against a preset tool inventory: 'hand' "
                             "(hand tools + drill), 'hobbyist' (table saw, "
                             "router, jigs — no Domino/dovetail jig), or 'full'")
    common.add_argument("--tools",
                        help="comma-list of tools you own, e.g. "
                             "'table_saw,router,pocket_jig,dovetail_jig'; only "
                             "joinery these can make is allowed (overrides --shop)")
    common.add_argument("--tools-list", action="store_true", dest="tools_list",
                        help="print the tool/jig checklist the design requires")
    common.add_argument("--from-stock", dest="from_stock", metavar="BOARDS.JSON",
                        help="assign parts to boards you already own (a JSON "
                             "list of {length,width,thickness,species,form,qty}) "
                             "and print the cut plan + what's still to buy")

    p_design = sub.add_parser("design", parents=[common],
                              help="natural language -> design (uses Claude)")
    p_design.add_argument("prompt", help="what to build, in plain language")
    p_design.add_argument("--model", help="override the Claude model id")
    p_design.add_argument("--attempts", type=int, default=3)

    p_build = sub.add_parser("build", parents=[common],
                             help="build from an existing spec JSON file")
    p_build.add_argument("spec_file", help="path to a spec .json file")

    args = parser.parse_args(argv)

    tooling = _tooling_from_args(args)

    if args.cmd == "design":
        from .agents import design_from_prompt
        print(f"Designing: {args.prompt!r}\n")
        res = design_from_prompt(args.prompt, max_attempts=args.attempts,
                                 model=args.model, tooling=tooling)
        print(f"(agent converged in {res.attempts} attempt(s))\n")
        return _emit(res.spec, args, tooling=tooling)

    if args.cmd == "build":
        import json as _json
        data = _json.loads(Path(args.spec_file).read_text(encoding="utf-8"))
        return _emit(spec_from_dict(data), args, tooling=tooling)

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
