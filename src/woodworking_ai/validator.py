"""Deterministic validation of a cabinet spec.

This is *not* an LLM. It applies type/range checks plus woodworking sanity
rules, catching the great majority of design errors before we ever attempt
geometry. It returns structured issues so the designer agent can self-repair.

No CAD dependency — runs anywhere, instantly.
"""

from __future__ import annotations

from dataclasses import dataclass

from .dsl import CabinetSpec, CabinetType


@dataclass
class Issue:
    severity: str   # "error" | "warning"
    field: str
    message: str

    def __str__(self) -> str:
        return f"[{self.severity}] {self.field}: {self.message}"


@dataclass
class ValidationResult:
    issues: list[Issue]

    @property
    def ok(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "warning"]

    def as_feedback(self) -> str:
        """Human/agent-readable summary used to prompt a repair."""
        if not self.issues:
            return "OK"
        return "\n".join(str(i) for i in self.issues)


def validate(spec: CabinetSpec) -> ValidationResult:
    issues: list[Issue] = []

    def err(fieldname: str, msg: str) -> None:
        issues.append(Issue("error", fieldname, msg))

    def warn(fieldname: str, msg: str) -> None:
        issues.append(Issue("warning", fieldname, msg))

    # --- basic positive dimensions ---------------------------------------
    for name in ("width", "height", "depth"):
        val = getattr(spec, name)
        if val is None or val <= 0:
            err(name, f"must be a positive number, got {val!r}")

    m = spec.material
    for name in ("carcass", "back", "door", "shelf"):
        val = getattr(m, name)
        if val is None or val <= 0:
            err(f"material.{name}", f"thickness must be positive, got {val!r}")

    # Stop here if fundamentals are broken — later checks would divide nonsense.
    if any(i.severity == "error" for i in issues):
        return ValidationResult(issues)

    # --- geometric consistency -------------------------------------------
    if spec.width < 2 * m.carcass + 50:
        err("width", "too narrow to hold two sides plus a usable opening")

    toe_h = spec.toe_kick.height if spec.toe_kick else 0.0
    if toe_h >= spec.height:
        err("toe_kick.height", "toe kick is taller than the whole cabinet")
    if spec.toe_kick and spec.toe_kick.setback >= spec.depth:
        err("toe_kick.setback", "toe kick setback exceeds cabinet depth")

    box_height = spec.height - toe_h
    if box_height <= m.carcass * 2:
        err("height", "carcass box height collapses after removing toe kick")

    # --- counts ----------------------------------------------------------
    if spec.doors not in (0, 1, 2):
        err("doors", f"prototype supports 0, 1 or 2 doors, got {spec.doors}")
    if spec.shelves < 0:
        err("shelves", "shelf count cannot be negative")
    if spec.reveal < 0:
        err("reveal", "reveal (gap) cannot be negative")

    # --- fronts must fit the opening height ------------------------------
    drawer_total = sum(d.front_height for d in spec.drawers)
    drawer_total += spec.reveal * max(len(spec.drawers), 0)
    if drawer_total >= box_height:
        err("drawers", "drawer fronts are taller than the available opening")

    # --- soft warnings (buildable, but worth flagging) -------------------
    if spec.doors == 1 and spec.width > 600:
        warn("doors", "a single door wider than 600mm tends to sag; consider two")
    if spec.shelves > 0 and spec.drawers:
        warn("shelves", "shelves above a drawer bank may be obstructed by the box")

    # --- per cabinet type ------------------------------------------------
    if spec.cabinet_type == CabinetType.WALL:
        if spec.toe_kick is not None:
            warn("toe_kick", "wall cabinets hang on the wall and have no toe kick")
        if spec.drawers:
            warn("drawers", "drawers are unusual in a wall cabinet")
        if spec.depth > 450:
            warn("depth", "wall cabinets are typically 300-400mm deep")
    elif spec.cabinet_type == CabinetType.TALL:
        if spec.toe_kick is None:
            warn("toe_kick", "tall/pantry cabinets usually sit on a toe kick")
        if spec.height < 1500:
            warn("height", "unusually short for a tall/pantry cabinet")
    else:  # BASE
        if spec.depth > 700:
            warn("depth", "unusually deep for a base cabinet")

    return ValidationResult(issues)
