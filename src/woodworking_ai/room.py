"""Room-aware planning: fit a run to a real wall, size fillers, flag scribe.

A :class:`~dsl.Project` places cabinets at abstract ``x``/``y``. A real install
starts from a wall: *this* wall is 3658 mm long, the ceiling is 2440 mm, the
floor drops 8 mm left-to-right, the corner is 6 mm out of square, and there's a
window. This module turns those measurements into a buildable plan: it checks
the run fits the wall, sizes the **filler** that closes the leftover gap, and
emits **scribe** allowances for out-of-square walls and out-of-level floors.

Pure data — no CAD. Lengths in mm.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# How much filler to leave at a run end even when a run fits exactly, so a
# cabinet never has to be scribed hard against a wall with no material to remove.
MIN_SCRIBE_FILLER = 12.0
MAX_REASONABLE_FILLER = 150.0   # wider than this, add a cabinet or a panel


@dataclass
class Obstacle:
    kind: str = "window"          # window | door | outlet | column
    start: float = 0.0            # mm from the wall's left end
    width: float = 0.0
    sill: float = 0.0             # height to the bottom (window)
    height: float = 0.0


@dataclass
class Wall:
    length: float = 3000.0
    height: float = 2440.0
    obstacles: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"length": self.length, "height": self.height,
                "obstacles": [vars(o) if isinstance(o, Obstacle) else dict(o)
                              for o in self.obstacles]}

    @classmethod
    def from_dict(cls, d: dict) -> "Wall":
        obs = [Obstacle(**{k: v for k, v in o.items()
                           if k in Obstacle.__dataclass_fields__})
               for o in d.get("obstacles", []) if isinstance(o, dict)]
        return cls(length=float(d.get("length", 3000.0)),
                   height=float(d.get("height", 2440.0)), obstacles=obs)


@dataclass
class Room:
    name: str = "Room"
    ceiling_height: float = 2440.0
    floor_drop: float = 0.0       # out-of-level over the run (mm)
    out_of_square: float = 0.0    # corner out-of-square (mm over the wall)
    walls: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"name": self.name, "ceiling_height": self.ceiling_height,
                "floor_drop": self.floor_drop, "out_of_square": self.out_of_square,
                "walls": [w.to_dict() if isinstance(w, Wall) else dict(w)
                          for w in self.walls]}

    @classmethod
    def from_dict(cls, d: dict) -> "Room":
        return cls(
            name=str(d.get("name", "Room")),
            ceiling_height=float(d.get("ceiling_height", 2440.0)),
            floor_drop=float(d.get("floor_drop", 0.0)),
            out_of_square=float(d.get("out_of_square", 0.0)),
            walls=[Wall.from_dict(w) for w in d.get("walls", [])
                   if isinstance(w, dict)])


def run_widths(project) -> list[float]:
    """Each component's run width along the wall, cabinets *and* appliance gaps.

    A reserved :class:`~dsl.ApplianceVoid` is a SPACE that still consumes run
    width, so it is included — :func:`fit_run` then totals the real wall the run
    needs. Components with no ``width`` (e.g. a nested sub-assembly) contribute 0.
    """
    return [float(getattr(c.spec, "width", 0.0) or 0.0)
            for c in getattr(project, "components", []) or []]


def fit_run(widths: list[float], wall_length: float) -> dict:
    """Fit cabinet *widths* to a wall: totals, the gap, and the filler needed.

    *widths* may include appliance-gap widths (see :func:`run_widths`); a gap
    consumes wall length just like a cabinet, so the total reflects the real run.
    """
    total = sum(float(w) for w in widths)
    gap = wall_length - total
    return {
        "total": round(total, 1),
        "wall_length": round(wall_length, 1),
        "gap": round(gap, 1),
        "fits": gap >= -0.5,
        "overrun": round(max(0.0, -gap), 1),
        "filler_width": round(gap, 1) if gap > 0.5 else 0.0,
    }


def scribe_plan(room: Room) -> dict:
    """Scribe/shim allowances for an out-of-square, out-of-level room."""
    notes: list[str] = []
    if room.out_of_square > 1.0:
        notes.append(
            f"corner is ~{room.out_of_square:.0f}mm out of square; leave a filler "
            "or scribe stile to plane to the wall")
    if room.floor_drop > 1.0:
        notes.append(
            f"floor drops ~{room.floor_drop:.0f}mm across the run; level the "
            "cabinets and scribe/extend the toe kick to the low end")
    if room.ceiling_height and room.ceiling_height < 2400:
        notes.append(
            f"low ceiling ({room.ceiling_height:.0f}mm); check tall cabinets and "
            "crown fit")
    return {"out_of_square_mm": room.out_of_square, "floor_drop_mm": room.floor_drop,
            "notes": notes}


def plan_wall(widths: list[float], wall: Wall, room: Room | None = None) -> dict:
    """Plan a run against one wall: fit, filler sizing, scribe, and issues.

    Returns a dict with ``fit`` (see :func:`fit_run`), a recommended
    ``filler`` accessory list to drop on the run, ``scribe`` notes, and a list
    of ``(severity, field, message)`` issues.
    """
    fit = fit_run(widths, wall.length)
    issues: list = []
    fillers: list = []

    if not fit["fits"]:
        issues.append((
            "error", "run",
            f"run is {fit['total']:.0f}mm but the wall is only "
            f"{wall.length:.0f}mm — over by {fit['overrun']:.0f}mm; drop a "
            "cabinet or narrow the run"))
    else:
        gap = fit["filler_width"]
        if gap <= 0.5:
            issues.append((
                "warning", "filler",
                "run fills the wall exactly; leave a small filler so a cabinet "
                "isn't scribed hard to the wall with nothing to remove"))
        elif gap > MAX_REASONABLE_FILLER:
            issues.append((
                "warning", "filler",
                f"a {gap:.0f}mm gap is wide for a single filler; add a cabinet, "
                "a wider end panel, or split fillers at both ends"))
        if gap > 0.5:
            fillers.append({"kind": "filler", "width": gap, "side": "right"})

    return {"fit": fit, "fillers": fillers,
            "scribe": scribe_plan(room) if room else None, "issues": issues}
