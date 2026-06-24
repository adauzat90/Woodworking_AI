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

from dataclasses import dataclass, field
from typing import Any

from ..dsl import CabinetSpec
from ..geometry import PanelBox, panel_layout
from ..cutlist import generate_cutlist

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

    def report_text(self) -> str:
        r = self.report
        lines = [
            "Critic report",
            f"  overall (mm):    {r.get('width', 0):.0f} W x "
            f"{r.get('height', 0):.0f} H x {r.get('depth', 0):.0f} D (carcass)",
            f"  with fronts:     {r.get('depth_with_fronts', 0):.0f} mm deep",
            f"  clear opening:   {r.get('opening_width', 0):.0f} x "
            f"{r.get('opening_height', 0):.0f} mm",
            f"  panels:          {r.get('panel_count', 0)}",
            f"  front coverage:  {r.get('front_coverage_pct', 0):.0f}% of the face",
            f"  sheet goods:     ~{r.get('sheet_area_m2', 0):.2f} m²",
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
    """Pairs of panels that share positive volume (real collisions)."""
    hits: list[tuple[str, str, float]] = []
    for i in range(len(panels)):
        for j in range(i + 1, len(panels)):
            ox, oy, oz = _overlap(panels[i], panels[j])
            if ox > TOUCH_EPS and oy > TOUCH_EPS and oz > TOUCH_EPS:
                hits.append((panels[i].label, panels[j].label, ox * oy * oz))
    return hits


def critique(spec: CabinetSpec, *, use_cad: bool = False,
             model: Any = None) -> CritiqueResult:
    """Verify the geometry implied by *spec*.

    Set ``use_cad=True`` (or pass a pre-built ``model``) to additionally measure
    the real build123d B-Rep and cross-check it.
    """
    panels = panel_layout(spec)
    result = CritiqueResult()

    def err(kind, msg):
        result.issues.append(CritiqueIssue("error", kind, msg))

    def warn(kind, msg):
        result.issues.append(CritiqueIssue("warning", kind, msg))

    # --- overall envelope ------------------------------------------------
    # Measure the structural shell (sides/bottom/stretchers + toe kick). The
    # back and fronts are excluded: an applied back protrudes behind and fronts
    # sit proud, neither of which should distort the carcass dimensions.
    shell = [p for p in panels if p.category in ("carcass", "toe")]
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

    # --- clear opening + front coverage ----------------------------------
    m = spec.material
    toe_h = spec.toe_kick.height if spec.toe_kick else 0.0
    opening_w = spec.width - 2 * m.carcass
    opening_h = (spec.height - toe_h) - 2 * m.carcass
    result.report.update(opening_width=opening_w, opening_height=opening_h)

    if fronts:
        front_area = sum(p.size[0] * p.size[2] for p in fronts)
        face_area = spec.width * (spec.height - toe_h)
        coverage = 100.0 * front_area / face_area if face_area else 0.0
        result.report["front_coverage_pct"] = coverage
        # Fronts must stay within the carcass width (no overhang past the sides).
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

    # --- sheet goods (from the cut list) ---------------------------------
    result.report["sheet_area_m2"] = generate_cutlist(spec).sheet_area_m2

    # --- optional geometric cross-check ----------------------------------
    if use_cad or model is not None:
        try:
            from ..builder import build_model, measure
            if model is None:
                model = build_model(spec)
            dims = measure(model)
            result.report["measured"] = dims
            # The real B-Rep includes fronts, so compare against full depth.
            for label, got, want in (
                ("width", dims["width"], env_w),
                ("height", dims["height"], env_h),
                ("depth", dims["depth"], full_depth),
            ):
                if abs(got - want) > DIM_TOL:
                    err("geometry",
                        f"built {label} {got:.1f}mm != expected {want:.1f}mm")
        except RuntimeError as exc:
            warn("geometry", f"could not build B-Rep for cross-check: {exc}")

    return result
