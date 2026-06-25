"""The Critic agent: verify the *built geometry* against the spec.

This is the second half of the execute-and-verify loop (the first being the
:mod:`validator`, which checks the spec before geometry exists). Where the
validator asks "is the spec sane?", the Critic asks "did the panels we placed
actually produce the cabinet we asked for, with nothing intersecting?".

Like Zoo's Zookeeper — which inspects models with computational tools (mass,
volume, bounding box) rather than eyeballing them — the Critic is deterministic
and computational. Its findings are returned as structured issues so the
Designer LLM can repair its own output.

Two layers:

* **Analytical** (default, no CAD dependency): reconstructs every panel's
  axis-aligned box from :func:`panel_layout` and checks the overall envelope,
  part interferences, and front coverage with plain arithmetic.
* **Geometric** (opt-in, needs build123d): measures the real B-Rep model and
  cross-checks it against the analytical envelope, catching compiler/library
  bugs the math alone cannot.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..dsl import CabinetSpec, ComponentGroup, Construction, Joinery
from ..geometry import (
    PanelBox, panel_layout, project_layout, footprints_overlap, component_tag,
)
from ..cutlist import generate_cutlist
from ..constants import FRAME_WIDTH
from ..tooling import DEFAULT_TOOLS
from . import llm

# Tolerances in mm. Panels that merely touch (shared faces) overlap by ~0; only
# overlaps beyond this count as interference.
TOUCH_EPS = 0.01
DIM_TOL = 0.5


@dataclass
class CritiqueIssue:
    severity: str        # "error" | "warning"
    kind: str            # "envelope" | "interference" | "coverage" | "geometry"
    message: str

    def __str__(self) -> str:
        return f"[{self.severity}] {self.kind}: {self.message}"


@dataclass
class CritiqueResult:
    issues: list[CritiqueIssue] = field(default_factory=list)
    report: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    @property
    def errors(self) -> list[CritiqueIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[CritiqueIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    def as_feedback(self) -> str:
        """Repair note fed back to the Designer agent."""
        if not self.issues:
            return "Geometry verified: overall dimensions match and no parts collide."
        return "\n".join(str(i) for i in self.issues)

    def report_text(self, unit: str = "metric") -> str:
        from ..units import format_length as _fl, format_area as _fa
        r = self.report

        def L(key: str) -> str:
            return _fl(r.get(key, 0), unit)

        lines = [
            "Critic report",
            f"  overall:         {L('width')} W x {L('height')} H x "
            f"{L('depth')} D (carcass)",
            f"  with fronts:     {L('depth_with_fronts')} deep",
            f"  clear opening:   {L('opening_width')} x {L('opening_height')}",
            f"  panels:          {r.get('panel_count', 0)}",
            f"  front coverage:  {r.get('front_coverage_pct', 0):.0f}% of the face",
            f"  sheet goods:     ~{_fa(r.get('sheet_area_m2', 0), unit)}",
            f"  interferences:   {r.get('interference_count', 0)}",
        ]
        if self.issues:
            lines.append("  findings:")
            lines += [f"    {i}" for i in self.issues]
        else:
            lines.append("  findings:        none — geometry verified ✓")
        return "\n".join(lines)


def _overlap(a: PanelBox, b: PanelBox) -> tuple[float, float, float]:
    """Per-axis interpenetration depth of two boxes (negative => a gap)."""
    ab, bb = a.bounds(), b.bounds()
    return tuple(
        min(ab[ax][1], bb[ax][1]) - max(ab[ax][0], bb[ax][0]) for ax in range(3)
    )


def _interferences(panels: list[PanelBox]) -> list[tuple[str, str, float]]:
    """Pairs of panels that share positive volume (real collisions).

    Rotated panels are skipped: their AABB over-approximates the true footprint,
    so an axis-aligned test would report false collisions. The opt-in B-Rep
    check (``brep=True``) verifies those exactly.
    """
    checked = [p for p in panels if not getattr(p, "is_rotated", False)
               and not getattr(p, "oversized", False)]
    hits: list[tuple[str, str, float]] = []
    for i in range(len(checked)):
        for j in range(i + 1, len(checked)):
            ox, oy, oz = _overlap(checked[i], checked[j])
            if ox > TOUCH_EPS and oy > TOUCH_EPS and oz > TOUCH_EPS:
                hits.append((checked[i].label, checked[j].label, ox * oy * oz))
    return hits


def _brep_interferences(model: Any, eps_volume: float = 1.0,
                        skip: set[str] | None = None
                        ) -> list[tuple[str, str, float]]:
    """True solid-boolean interferences between a model's panels (mm³).

    Unlike the analytical AABB check, this is exact for *any* geometry —
    rotated, mitred or otherwise non-axis-aligned parts a future construction
    style might introduce. O(n²) boolean intersections, so it is opt-in.
    ``skip`` names panels excluded from the check (e.g. trim-to-fit blanks).
    """
    skip = skip or set()
    children = [c for c in getattr(model, "children", [])
                if getattr(c, "label", None) not in skip]
    hits: list[tuple[str, str, float]] = []
    for i in range(len(children)):
        for j in range(i + 1, len(children)):
            a, b = children[i], children[j]
            try:
                vol = (a & b).volume
            except Exception:
                vol = 0.0  # disjoint solids can raise instead of empty
            if vol > eps_volume:
                hits.append((getattr(a, "label", f"#{i}"),
                             getattr(b, "label", f"#{j}"), vol))
    return hits


def _span(group: list[PanelBox], axis: int) -> float:
    if not group:
        return 0.0
    lo = min(p.bounds()[axis][0] for p in group)
    hi = max(p.bounds()[axis][1] for p in group)
    return hi - lo


def _buildability_issues(spec: CabinetSpec, tools=DEFAULT_TOOLS
                         ) -> list[CritiqueIssue]:
    """Shop-floor checks the envelope/interference math misses.

    Catches the problems that bite at the machine or on install: a housing the
    tooling can't cut in one pass, a box too deep to line-bore by hand, twin
    doors whose pulls clash, and a face-frame drawer whose slides need build-out
    blocks to reach the box.
    """
    out: list[CritiqueIssue] = []
    m = spec.material

    def warn(kind, msg):
        out.append(CritiqueIssue("warning", kind, msg))

    # --- machinability ---------------------------------------------------
    if spec.joinery in (Joinery.DADO, Joinery.RABBET):
        w = m.carcass
        if (w > tools.dado_max or w < tools.dado_min) and \
                not any(abs(w - b) < 0.6 for b in tools.router_bits):
            warn("machinability",
                 f"a {w:.0f}mm housing is outside the dado stack "
                 f"({tools.dado_min:.0f}-{tools.dado_max:.0f}mm) and matches no "
                 "router bit on hand — it needs multiple passes or a wider stack")
    if spec.shelves > 0 and spec.depth > tools.max_handdrill_reach:
        warn("machinability",
             f"a {spec.depth:.0f}mm-deep box is past comfortable hand-drill reach "
             f"(~{tools.max_handdrill_reach:.0f}mm); line-bore the shelf-pin rows "
             "with a jig or CNC")

    # --- door-swing / handle clash ---------------------------------------
    # Inset (face-frame) twin doors with no centre stile have nothing to close
    # against and their edges/pulls clash; overlay doors overlap the opening and
    # are fine, so this is gated to inset construction.
    if (spec.construction == Construction.FACE_FRAME and spec.doors == 2
            and not spec.center_mullion and not spec.is_corner):
        warn("clearance",
             "inset twin doors meet with no centre stile — nothing to close "
             "against and the pulls clash; add a centre mullion or a door stop")

    # --- face-frame drawer slide stack-up --------------------------------
    boxed = [d for d in spec.drawers
             if not d.false_front and str(d.slide_type).lower() == "side_mount"]
    if spec.construction == Construction.FACE_FRAME and boxed:
        lip = FRAME_WIDTH - m.carcass    # frame overhang past the carcass side
        if lip > 3.0:
            warn("clearance",
                 f"face-frame drawers: the frame overhangs the carcass side by "
                 f"{lip:.0f}mm, so side-mount slides won't reach the box — add "
                 "slide build-out blocks (or use undermount)")
    return out


def _critique_project(project: ComponentGroup, *, use_cad: bool = False,
                      brep: bool = False, model: Any = None) -> CritiqueResult:
    """Verify an assembled group: envelope, and component-to-component collisions.

    The decisive check is interference *between* cabinets — a class of error
    that only exists once components are placed in one frame.
    """
    panels = project_layout(project)
    result = CritiqueResult()
    shell = [p for p in panels if p.category in ("carcass", "toe")]
    full_w, full_h, full_d = (_span(panels, 0), _span(panels, 2), _span(panels, 1))
    result.report.update(
        width=_span(shell, 0), height=_span(shell, 2), depth=_span(shell, 1),
        depth_with_fronts=full_d, panel_count=len(panels),
        component_count=len(project.components),
        sheet_area_m2=generate_cutlist(project).sheet_area_m2,
    )

    # Component-to-component collision via oriented 2D footprints. (The panel
    # AABB test skips rotated panels, so it can't see perpendicular runs; the
    # footprint check is exact for any rotation. brep=True adds solid-level.)
    comps = project.components
    collisions = 0
    for i in range(len(comps)):
        for j in range(i + 1, len(comps)):
            if footprints_overlap(comps[i], comps[j]):
                collisions += 1
                result.issues.append(CritiqueIssue(
                    "error", "interference",
                    f"'{component_tag(comps[i], i + 1)}' and "
                    f"'{component_tag(comps[j], j + 1)}' overlap in plan — "
                    "components collide"))
    result.report["interference_count"] = collisions

    if use_cad or brep or model is not None:
        try:
            from ..builder import build_model, measure
            if model is None:
                model = build_model(project)
            dims = measure(model)
            result.report["measured"] = dims
            for label, got, want in (("width", dims["width"], full_w),
                                     ("height", dims["height"], full_h),
                                     ("depth", dims["depth"], full_d)):
                if abs(got - want) > DIM_TOL:
                    result.issues.append(CritiqueIssue(
                        "error", "geometry",
                        f"built {label} {got:.1f}mm != expected {want:.1f}mm"))
            if brep:
                skip = {p.label for p in panels if getattr(p, "oversized", False)}
                for a, b, vol in _brep_interferences(model, skip=skip):
                    result.issues.append(CritiqueIssue(
                        "error", "interference",
                        f"B-Rep: '{a}' and '{b}' intersect (~{vol/1000:.1f} cm³)"))
        except RuntimeError as exc:
            result.issues.append(CritiqueIssue(
                "warning", "geometry", f"could not build B-Rep for cross-check: {exc}"))
    return result


def critique(spec, *, use_cad: bool = False,
             brep: bool = False, model: Any = None) -> CritiqueResult:
    """Verify the geometry implied by *spec* (cabinet, table, or group).

    Set ``use_cad=True`` (or pass a pre-built ``model``) to additionally measure
    the real build123d B-Rep and cross-check it. Set ``brep=True`` to also run
    exact solid-boolean interference (needs build123d).
    """
    if isinstance(spec, ComponentGroup):
        return _critique_project(spec, use_cad=use_cad, brep=brep, model=model)
    panels = panel_layout(spec)
    result = CritiqueResult()
    is_cabinet = isinstance(spec, CabinetSpec)

    def err(kind, msg):
        result.issues.append(CritiqueIssue("error", kind, msg))

    def warn(kind, msg):
        result.issues.append(CritiqueIssue("warning", kind, msg))

    # --- overall envelope ------------------------------------------------
    # For a cabinet, measure the structural shell (sides/bottom/stretchers + toe
    # kick) — the back and fronts protrude/sit proud and shouldn't distort the
    # carcass dimensions. For other furniture (e.g. a table) every panel counts.
    if is_cabinet:
        shell = [p for p in panels if p.category in ("carcass", "toe")]
    else:
        shell = panels
    fronts = [p for p in panels if p.is_front]

    def span(group, axis):
        if not group:
            return 0.0
        lo = min(p.bounds()[axis][0] for p in group)
        hi = max(p.bounds()[axis][1] for p in group)
        return hi - lo

    env_w = span(shell, 0)
    env_h = span(shell, 2)
    env_d = span(shell, 1)
    full_width = span(panels, 0)
    full_height = span(panels, 2)
    full_depth = span(panels, 1)

    result.report.update(
        width=env_w, height=env_h, depth=env_d,
        depth_with_fronts=full_depth, panel_count=len(panels),
    )

    for label, got, want in (
        ("width", env_w, spec.width),
        ("height", env_h, spec.height),
        ("depth", env_d, spec.depth),
    ):
        if abs(got - want) > DIM_TOL:
            err("envelope",
                f"{label} is {got:.1f}mm but the spec calls for {want:.1f}mm")

    # --- interferences ---------------------------------------------------
    hits = _interferences(panels)
    result.report["interference_count"] = len(hits)
    for a, b, vol in hits:
        err("interference",
            f"'{a}' and '{b}' overlap (~{vol/1000:.1f} cm³) — they would not fit")

    # --- clear opening + front coverage (cabinets only) ------------------
    if is_cabinet:
        m = spec.material
        result.report.update(
            opening_width=spec.interior_width,
            opening_height=spec.box_height - 2 * m.carcass,
        )
        if fronts:
            front_area = sum(p.size[0] * p.size[2] for p in fronts)
            face_area = spec.width * spec.box_height
            coverage = 100.0 * front_area / face_area if face_area else 0.0
            result.report["front_coverage_pct"] = coverage
            max_x = max(p.bounds()[0][1] for p in fronts)
            min_x = min(p.bounds()[0][0] for p in fronts)
            if max_x - min_x > spec.width + DIM_TOL:
                err("coverage", "door/drawer fronts overhang the cabinet width")
            if coverage < 60:
                warn("coverage",
                     f"fronts cover only {coverage:.0f}% of the face — large gaps")
        else:
            result.report["front_coverage_pct"] = 0.0
            if spec.doors == 0 and not spec.drawers:
                warn("coverage", "open cabinet: no doors or drawers specified")

    # --- buildability: machinability + clearances (cabinets only) --------
    if is_cabinet:
        result.issues.extend(_buildability_issues(spec))

    # --- sheet goods (from the cut list) ---------------------------------
    result.report["sheet_area_m2"] = generate_cutlist(spec).sheet_area_m2

    # --- optional geometric cross-check ----------------------------------
    if use_cad or brep or model is not None:
        try:
            from ..builder import build_model, measure
            if model is None:
                model = build_model(spec)
            dims = measure(model)
            result.report["measured"] = dims
            # The real B-Rep spans every panel (proud fronts, angled doors),
            # so compare against the full panel span, not the carcass shell.
            for label, got, want in (
                ("width", dims["width"], full_width),
                ("height", dims["height"], full_height),
                ("depth", dims["depth"], full_depth),
            ):
                if abs(got - want) > DIM_TOL:
                    err("geometry",
                        f"built {label} {got:.1f}mm != expected {want:.1f}mm")
            if brep:
                skip = {p.label for p in panels
                        if getattr(p, "oversized", False)}
                brep_hits = _brep_interferences(model, skip=skip)
                result.report["brep_interference_count"] = len(brep_hits)
                for a, b, vol in brep_hits:
                    err("interference",
                        f"B-Rep: '{a}' and '{b}' intersect (~{vol/1000:.1f} cm³)")
        except RuntimeError as exc:
            warn("geometry", f"could not build B-Rep for cross-check: {exc}")

    return result


# ---------------------------------------------------------------------------
# Render-based review: render the model and let a vision model inspect it.
# ---------------------------------------------------------------------------

VISION_SYSTEM = """You are a master cabinetmaker reviewing a rendered cabinet \
design before it goes to the shop. You are shown a front elevation, a side \
elevation, and an isometric view of the SAME cabinet, rendered from its \
parametric spec.

Judge only what the render shows. Look for visual problems a measurement check \
would miss, such as: doors or drawers that look missing, lopsided, or unevenly \
sized; gaps that look too large or uneven; panels that stick out or float; a \
toe kick that is missing or wrong; proportions that look off for the stated use.

Respond with ONE JSON object and nothing else:
{"looks_correct": true|false,
 "issues": ["short description", ...],   // empty if it looks right
 "notes": "one-sentence overall impression"}"""


# The Designer and Critic share one tolerant JSON extractor (see agents.llm).
_extract_json = llm.extract_json


def visual_review(spec: CabinetSpec, *, image_path: str | Path | None = None,
                  model: str | None = None) -> CritiqueResult:
    """Render *spec* and have a vision model inspect the snapshot.

    Findings come back as ``kind="visual"`` issues. If matplotlib or the
    Anthropic SDK / API key are unavailable, the review is skipped gracefully
    with a single warning rather than raising.
    """
    from ..render import render_cabinet  # lazy: matplotlib optional

    result = CritiqueResult()

    # 1) Render the snapshot (or reuse one provided by the caller).
    try:
        if image_path is None:
            import tempfile
            image_path = Path(tempfile.mkdtemp()) / f"{spec.name or 'cabinet'}.png"
            render_cabinet(spec, image_path)
        else:
            image_path = Path(image_path)
            if not image_path.exists():
                render_cabinet(spec, image_path)
    except RuntimeError as exc:
        result.issues.append(CritiqueIssue("warning", "visual",
                                           f"render skipped: {exc}"))
        return result
    result.report["render_path"] = str(image_path)

    # 2) Ask the vision model to inspect it.
    summary = (
        f"{spec.name}: {spec.width:.0f} x {spec.height:.0f} x {spec.depth:.0f} mm, "
        f"{spec.construction.value}, {spec.doors} door(s), "
        f"{len(spec.drawers)} drawer(s), {spec.shelves} shelf(s)."
    )
    try:
        text = llm.complete_with_image(
            VISION_SYSTEM,
            f"Cabinet spec: {summary}\nReview the three views.",
            image_path.read_bytes(), model=model,
        )
    except llm.LLMError as exc:
        result.issues.append(CritiqueIssue("warning", "visual",
                                           f"vision review skipped: {exc}"))
        return result

    # 3) Parse the verdict.
    try:
        verdict = _extract_json(text)
    except (ValueError, json.JSONDecodeError) as exc:
        result.issues.append(CritiqueIssue("warning", "visual",
                                           f"could not parse vision verdict: {exc}"))
        return result

    result.report["visual_notes"] = verdict.get("notes", "")
    result.report["looks_correct"] = bool(verdict.get("looks_correct", True))
    for issue in verdict.get("issues", []):
        # Visual findings are warnings: a second opinion, not a hard gate.
        result.issues.append(CritiqueIssue("warning", "visual", str(issue)))
    return result


def render_review(spec: CabinetSpec, *, image_path: str | Path | None = None,
                  use_llm: bool = True, model: str | None = None) -> CritiqueResult:
    """Full review: computational :func:`critique` + optional visual review.

    The two result sets are merged so callers get one report and one issue list.
    """
    result = critique(spec)
    if use_llm:
        visual = visual_review(spec, image_path=image_path, model=model)
        result.issues.extend(visual.issues)
        result.report.update(visual.report)
    elif image_path is not None:
        # Just produce the render without calling the model.
        from ..render import render_cabinet
        try:
            render_cabinet(spec, image_path)
            result.report["render_path"] = str(image_path)
        except RuntimeError as exc:
            result.issues.append(CritiqueIssue("warning", "visual",
                                               f"render skipped: {exc}"))
    return result
