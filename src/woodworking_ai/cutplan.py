"""Cut from the lumber you already own.

The estimator nests parts into *standard sheets* to compute **what to buy**.
Hobbyists usually start the other way round: from a pile of boards they already
have, and want a plan that assigns their parts to those boards — with a yield
figure, the offcuts left over, and a **shortfall** list of parts that did not
fit (so they know what still to buy).

This module is pure arithmetic — no CAD dependency, no API key — so it runs and
unit-tests anywhere. It builds on:

* :mod:`woodworking_ai.packing` — the generalised guillotine packer
  (:func:`~woodworking_ai.packing.pack_into_bin`) nests rectangles into one
  owned board, honouring the same grain/orientation rules the sheet nest uses.
* :func:`woodworking_ai.cutlist.generate_cutlist` — the parts to place, with
  their grain, thickness, form and species already resolved.

Grouping mirrors the estimator's: parts merge by ``(thickness, form, species)``
so a part can only be cut from a board of the matching make-up. Grain is honoured
exactly as in nesting — a grained part's length runs along the board length and
is never rotated across the grain. Cutting is kerf-aware: each placement reserves
a saw-blade width between parts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .cutlist import CutList, generate_cutlist, Part
from .materials import MAT_DOOR_FRONT
from .dispatch import spec_kind, VOID
from .packing import pack_into_bin

# A small tolerance (mm) when matching a part thickness to a board thickness, so
# an 18.0mm part lands on an 18.0mm (or 18.3mm nominal) board.
THICKNESS_TOL = 1.0
DEFAULT_KERF = 3.0   # saw blade width lost per cut (mm), matches SheetSize


@dataclass
class StockBoard:
    """A board the shop already owns.

    All lengths in mm. ``form`` (plywood/solid/mdf/...) and ``species`` are
    optional; when given they restrict which parts the board can hold (a part is
    only assigned to a board of the same make-up). ``qty`` is how many identical
    boards are on hand.
    """

    length: float
    width: float
    thickness: float
    species: str = ""
    form: str = ""
    qty: int = 1
    id: str = ""          # optional label, e.g. "walnut 8/4 #1"

    @property
    def area_m2(self) -> float:
        return (self.length / 1000.0) * (self.width / 1000.0)

    def to_dict(self) -> dict:
        return {
            "length": self.length, "width": self.width,
            "thickness": self.thickness, "species": self.species,
            "form": self.form, "qty": self.qty, "id": self.id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StockBoard":
        """A board from a (possibly partial) dict; dimensions kept positive.

        Tolerant of missing keys and string numbers so a hand-written
        ``boards.json`` loads without ceremony.
        """
        def num(key, default=0.0, lo=None):
            try:
                x = float(data.get(key, default))
            except (TypeError, ValueError):
                x = float(default)
            if not math.isfinite(x):
                x = float(default)
            if lo is not None and x < lo:
                x = lo
            return x

        qty = data.get("qty", 1)
        try:
            qty = int(qty)
        except (TypeError, ValueError):
            qty = 1
        return cls(
            length=num("length", 0.0, lo=0.0),
            width=num("width", 0.0, lo=0.0),
            thickness=num("thickness", 0.0, lo=0.0),
            species=str(data.get("species", "") or ""),
            form=str(data.get("form", "") or ""),
            qty=max(qty, 0),
            id=str(data.get("id", "") or ""),
        )


def boards_from_dicts(items) -> list[StockBoard]:
    """Load a list of :class:`StockBoard` from a list of dicts (or a wrapper).

    Accepts either a bare list ``[{...}, ...]`` or ``{"boards": [...]}`` so a
    ``boards.json`` can be either shape.
    """
    if isinstance(items, dict):
        items = items.get("boards", [])
    return [StockBoard.from_dict(d) for d in (items or [])]


def boards_to_dicts(boards: list[StockBoard]) -> list[dict]:
    return [b.to_dict() for b in boards]


@dataclass
class PlacedPart:
    """One part placed on a board: position + size on the board (mm)."""
    x: float
    y: float
    length: float
    width: float
    label: str
    part_id: str = ""


@dataclass
class BoardPlan:
    """The cut layout for one physical board instance."""
    board: StockBoard
    instance: int                       # 1-based, when a board's qty > 1
    placements: list[PlacedPart] = field(default_factory=list)

    @property
    def used_area_m2(self) -> float:
        return sum((p.length / 1000.0) * (p.width / 1000.0)
                   for p in self.placements)

    @property
    def yield_pct(self) -> float:
        """Packed area as a fraction (0..1) of this board's area."""
        a = self.board.area_m2
        return (self.used_area_m2 / a) if a > 0 else 0.0

    @property
    def offcut_area_m2(self) -> float:
        return max(self.board.area_m2 - self.used_area_m2, 0.0)

    @property
    def part_count(self) -> int:
        return len(self.placements)


@dataclass
class Shortfall:
    """A part (one instance) that no owned board could hold."""
    label: str
    length: float
    width: float
    thickness: float
    form: str = ""
    species: str = ""
    part_id: str = ""
    reason: str = ""        # "no matching board" | "too big for every board"


@dataclass
class CutPlan:
    spec_name: str
    boards: list[BoardPlan] = field(default_factory=list)
    shortfall: list[Shortfall] = field(default_factory=list)
    kerf: float = DEFAULT_KERF

    @property
    def placed_count(self) -> int:
        return sum(b.part_count for b in self.boards)

    @property
    def boards_used(self) -> int:
        """Boards that actually hold at least one part."""
        return sum(1 for b in self.boards if b.placements)

    @property
    def total_board_area_m2(self) -> float:
        return sum(b.board.area_m2 for b in self.boards if b.placements)

    @property
    def used_area_m2(self) -> float:
        return sum(b.used_area_m2 for b in self.boards)

    @property
    def offcut_area_m2(self) -> float:
        return sum(b.offcut_area_m2 for b in self.boards if b.placements)

    @property
    def yield_pct(self) -> float:
        """Overall yield: packed area / area of the boards actually used."""
        a = self.total_board_area_m2
        return (self.used_area_m2 / a) if a > 0 else 0.0

    @property
    def complete(self) -> bool:
        """True when every part was assigned to an owned board."""
        return not self.shortfall

    def report_text(self, unit: str = "metric") -> str:
        from .units import format_length, format_area
        lines = [f"Cut plan from stock — {self.spec_name}"]
        if not self.boards:
            lines.append("  (no boards supplied)")
        for bp in self.boards:
            if not bp.placements:
                continue
            b = bp.board
            tag = b.id or _board_label(b)
            inst = f" #{bp.instance}" if b.qty > 1 else ""
            dims = (f"{format_length(b.length, unit, mark=False)} x "
                    f"{format_length(b.width, unit, mark=False)} x "
                    f"{format_length(b.thickness, unit, mark=False)}")
            lines.append(
                f"  {tag}{inst}  {dims}  -> {bp.part_count} part(s), "
                f"{bp.yield_pct * 100:4.0f}% yield, "
                f"{format_area(bp.offcut_area_m2, unit)} offcut")
            for p in bp.placements:
                lines.append(
                    f"      {p.label:<26} "
                    f"{format_length(p.length, unit, mark=False)} x "
                    f"{format_length(p.width, unit, mark=False)}")
        lines.append(
            f"  placed {self.placed_count} part(s) on {self.boards_used} "
            f"board(s), overall {self.yield_pct * 100:.0f}% yield")
        if self.shortfall:
            lines.append(f"  SHORTFALL — {len(self.shortfall)} part(s) still "
                         "to buy:")
            for s in self.shortfall:
                lines.append(
                    f"      {s.label:<26} "
                    f"{format_length(s.length, unit, mark=False)} x "
                    f"{format_length(s.width, unit, mark=False)} x "
                    f"{format_length(s.thickness, unit, mark=False)}  "
                    f"({s.reason})")
        else:
            lines.append("  no shortfall — every part fits your stock")
        return "\n".join(lines)

    def to_csv(self, unit: str = "metric") -> str:
        """Per-placement CSV: one row per placed part, then shortfall rows."""
        from .units import format_length, length_unit_label
        lbl = length_unit_label(unit)

        def f(v: float) -> str:
            return format_length(v, unit, mark=False)

        lines = [f"board,instance,part_id,part,x_{lbl},y_{lbl},"
                 f"length_{lbl},width_{lbl},thickness_{lbl},status"]
        for bp in self.boards:
            b = bp.board
            board = b.id or _board_label(b)
            for p in bp.placements:
                lines.append(
                    f"{board},{bp.instance},{p.part_id},{p.label},"
                    f"{f(p.x)},{f(p.y)},{f(p.length)},{f(p.width)},"
                    f"{f(b.thickness)},placed")
        for s in self.shortfall:
            lines.append(
                f",,{s.part_id},{s.label},,,{f(s.length)},{f(s.width)},"
                f"{f(s.thickness)},shortfall")
        return "\n".join(lines)


def cutplan_dxf(plan: CutPlan) -> str:
    """A DXF (R12) cut-layout for every used board in *plan*, as a string.

    Reuses the same low-level rectangle/text primitives the sheet nest DXF uses
    (so a board layout reads identically to a sheet layout in a CAM viewer).
    Boards are tiled left-to-right; each placed part is a labelled rectangle in
    the board's own frame. Pure text — no CAD dependency.
    """
    from .dxf import rect, text, layer_table
    gap = 200.0
    out: list[str] = layer_table()
    out += ["0", "SECTION", "2", "ENTITIES"]
    ox = 0.0
    for bp in plan.boards:
        if not bp.placements:
            continue
        b = bp.board
        out += rect(ox, 0, b.length, b.width, layer="SHEET")
        tag = b.id or _board_label(b)
        inst = f" #{bp.instance}" if b.qty > 1 else ""
        out += text(ox + 5, b.width + 30, 40, f"{tag}{inst}", layer="SHEET")
        for p in bp.placements:
            out += rect(ox + p.x, p.y, p.length, p.width)
            out += text(ox + p.x + 8, p.y + p.width / 2 - 8, 16,
                         f"{p.label} {p.length:.0f}x{p.width:.0f}")
        ox += b.length + gap
    if plan.shortfall:
        labels = ", ".join(s.label for s in plan.shortfall)
        out += text(0, -60, 24, f"SHORTFALL (buy): {labels}", "WARN")
    out += ["0", "ENDSEC", "0", "EOF"]
    return "\n".join(out) + "\n"


def _board_label(b: StockBoard) -> str:
    """A short human label for a board with no explicit id."""
    bits = [b.species, b.form]
    name = " ".join(x for x in bits if x).strip()
    return name or "board"


def _group_key(p: Part) -> tuple[float, str, str]:
    """Merge key for a part: ``(thickness, form, species)`` (lowercased)."""
    return (round(p.thickness, 1), (p.form or "").strip().lower(),
            (p.species or "").strip().lower())


def _board_key(b: StockBoard) -> tuple[float, str, str]:
    return (round(b.thickness, 1), (b.form or "").strip().lower(),
            (b.species or "").strip().lower())


def _board_matches(part_key, board: StockBoard) -> bool:
    """True when *board* can hold a part of *part_key*.

    Thickness must match within tolerance. Form/species act as filters only when
    BOTH sides declare them: an undeclared (blank) form/species on either side is
    treated as a wildcard, so a generic board takes generic parts and a part with
    no declared species can be cut from any board of the right thickness. This
    mirrors the estimator's tolerance for legacy parts that never declared a make.
    """
    pt, pform, pspecies = part_key
    if abs(pt - board.thickness) > THICKNESS_TOL:
        return False
    bform = (board.form or "").strip().lower()
    bspecies = (board.species or "").strip().lower()
    if pform and bform and pform != bform:
        return False
    if pspecies and bspecies and pspecies != bspecies:
        return False
    return True


def _explode(parts: list[Part]) -> list[tuple]:
    """One nesting item per physical piece: ``(part, instance, item_tuple)``.

    A qty-N part becomes N items. Each item is the packer tuple
    ``(length, width, label, grain, seq)``; door/drawer fronts carry the
    ``"front"`` sequence token so they stay contiguous, exactly like the sheet
    nest.
    """
    items = []
    for p in parts:
        code = f"{p.id} " if p.id else ""
        seq = "front" if p.material == MAT_DOOR_FRONT else ""
        for i in range(p.qty):
            label = (f"{code}{p.name}" if p.qty == 1
                     else f"{code}{p.name} {i + 1}")
            items.append((p, label,
                          (p.length, p.width, label, p.grain, seq)))
    return items


def cut_plan(spec, boards: list[StockBoard], *,
             cutlist: CutList | None = None,
             kerf: float = DEFAULT_KERF) -> CutPlan:
    """Assign a spec's (or cut list's) parts to owned *boards*.

    *spec* may be a spec object (a cut list is generated from it) or an already
    built :class:`~woodworking_ai.cutlist.CutList`; pass a CutList directly via
    *cutlist* to override. Parts are grouped by ``(thickness, form, species)``
    and each group is nested onto its matching boards with the generalised
    guillotine packer — grain-aware (a grained part's length runs along the
    board length) and kerf-aware.

    Returns a :class:`CutPlan` with per-board placements + offcuts + yield, and
    a **shortfall** list of parts that did not fit any owned board (what to buy).
    Parts not yet placed when a board fills up roll over to the next matching
    board; a part that matches no board, or is too big for every matching board,
    becomes a shortfall.
    """
    if cutlist is not None:
        cl = cutlist
        name = cl.spec_name
    elif isinstance(spec, CutList):
        cl = spec
        name = cl.spec_name
    else:
        if spec_kind(spec) == VOID:
            return CutPlan(spec_name=getattr(spec, "name", "design"), kerf=kerf)
        cl = generate_cutlist(spec)
        name = cl.spec_name

    plan = CutPlan(spec_name=name, kerf=kerf)

    # Expand every board's qty into individual instances we can fill one by one.
    board_plans: list[BoardPlan] = []
    for b in boards:
        for inst in range(1, max(int(b.qty), 0) + 1):
            board_plans.append(BoardPlan(board=b, instance=inst))
    plan.boards = board_plans

    items = _explode(cl.parts)

    # Group items by stock key; assign each group to its matching boards.
    groups: dict[tuple, list[tuple]] = {}
    for (part, label, item) in items:
        groups.setdefault(_group_key(part), []).append((part, label, item))

    # Index of the part behind each label, for shortfall metadata.
    part_by_label = {label: part for (part, label, _it) in items}

    for key, group_items in groups.items():
        matching = [bp for bp in board_plans if _board_matches(key, bp.board)]
        pending = list(group_items)   # (part, label, item) still to place

        for bp in matching:
            if not pending:
                break
            # Pack the pending parts onto the strip of this board still free
            # below whatever an earlier group already placed (see the helpers
            # below). Anything that does not fit rolls to the next board.
            placed, leftover, oversize = pack_into_bin(
                [it for (_p, _l, it) in pending],
                _remaining_length(bp), _remaining_width(bp), kerf)
            # The strip starts below whatever an earlier group already placed;
            # capture that offset ONCE (it must not grow as we append below).
            y_offset = _used_height(bp)
            placed_labels = set()
            for (x, y, l, w, lbl) in placed:
                part = part_by_label.get(lbl)
                bp.placements.append(PlacedPart(
                    x=x, y=y + y_offset, length=l, width=w, label=lbl,
                    part_id=part.id if part else ""))
                placed_labels.add(lbl)
            # Anything that did not fit THIS board (leftover/oversize) stays
            # pending for the next matching board.
            pending = [(p, lbl, it) for (p, lbl, it) in pending
                       if lbl not in placed_labels]

        # Whatever is still pending matched no remaining capacity on any board.
        for (part, label, _it) in pending:
            reason = ("no matching board" if not matching
                      else "too big for every board")
            plan.shortfall.append(Shortfall(
                label=label, length=part.length, width=part.width,
                thickness=part.thickness, form=part.form, species=part.species,
                part_id=part.id, reason=reason))

    return plan


# --- helpers for incremental board filling ----------------------------------
# A board is filled in one or more passes (one per matching group). Each pass
# packs onto the strip of width still free below the parts already placed, so a
# later group lands under an earlier one rather than overlapping it. This keeps
# the simple shelf model while letting heterogeneous groups share a board.

def _used_height(bp: BoardPlan) -> float:
    """Lowest free y on the board (max bottom edge of placed parts)."""
    return max((p.y + p.width for p in bp.placements), default=0.0)


def _remaining_width(bp: BoardPlan) -> float:
    used = _used_height(bp)
    return max(bp.board.width - used, 0.0)


def _remaining_length(bp: BoardPlan) -> float:
    return bp.board.length
