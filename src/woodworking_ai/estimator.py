"""Estimator: sheet-goods nesting and cost.

Takes a :class:`CabinetSpec` (and its cut list) and produces a buildable-cost
estimate: how many sheets of each material are needed (via a simple guillotine
shelf-nesting), plus material, hardware, edge-banding and labour costs.

Pure arithmetic — no CAD dependency. The nesting is a deterministic
next-fit-decreasing-height packer: good enough for a quote and a sheet count,
and easy to reason about. (A true optimal 2D bin-pack is NP-hard; shops use
heuristics like this too.)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .dsl import CabinetSpec
from .cutlist import CutList, generate_cutlist


@dataclass
class SheetSize:
    length: float = 2440.0   # standard 8x4 sheet, mm
    width: float = 1220.0
    kerf: float = 3.0        # saw blade width lost per cut


@dataclass
class PriceBook:
    """All prices are defaults you can override; currency-agnostic."""
    # Full-sheet price keyed by the cut list's `material` label.
    sheet_price: dict[str, float] = field(default_factory=lambda: {
        "sheet": 70.0, "back panel": 30.0, "door/front": 95.0,
        "drawer box": 55.0, "frame": 40.0,
        "top": 110.0, "leg": 35.0, "apron": 35.0,   # table stock
    })
    sheet_price_default: float = 70.0
    # Per-unit hardware prices keyed by the hardware item name.
    hardware_price: dict[str, float] = field(default_factory=lambda: {
        "Concealed hinge": 4.0, "Door pull": 3.5, "Drawer pull": 3.5,
        "Drawer slide (pair)": 12.0, "Shelf pin": 0.15,
    })
    edge_banding_per_m: float = 1.5
    shop_rate_per_hour: float = 65.0
    # Simple labour model (hours).
    labour_base_h: float = 0.5
    labour_per_part_h: float = 0.05
    labour_per_door_h: float = 0.25
    labour_per_drawer_h: float = 0.30


@dataclass
class SheetGroup:
    material: str
    thickness: float
    part_count: int
    sheets: int
    utilization: float        # 0..1, packed area / sheet area used
    oversize: int = 0         # parts too big for one sheet


@dataclass
class Estimate:
    spec_name: str
    groups: list[SheetGroup]
    material_cost: float
    hardware_cost: float
    edge_banding_cost: float
    edge_banding_m: float
    labour_hours: float
    labour_cost: float
    currency: str = "$"

    @property
    def total(self) -> float:
        return (self.material_cost + self.hardware_cost
                + self.edge_banding_cost + self.labour_cost)

    @property
    def total_sheets(self) -> int:
        return sum(g.sheets for g in self.groups)

    def report_text(self) -> str:
        c = self.currency
        lines = [f"Cost estimate — {self.spec_name}", "  sheet goods:"]
        for g in self.groups:
            note = f"  ({g.oversize} oversize!)" if g.oversize else ""
            lines.append(
                f"    {g.material:<12} {g.thickness:>4.0f}mm  "
                f"{g.part_count:>2} parts -> {g.sheets} sheet(s), "
                f"{g.utilization*100:4.0f}% used{note}"
            )
        lines += [
            f"  material:        {c}{self.material_cost:8.2f} "
            f"({self.total_sheets} sheets)",
            f"  hardware:        {c}{self.hardware_cost:8.2f}",
            f"  edge banding:    {c}{self.edge_banding_cost:8.2f} "
            f"({self.edge_banding_m:.1f} m)",
            f"  labour:          {c}{self.labour_cost:8.2f} "
            f"({self.labour_hours:.1f} h @ {c}{self._rate:.0f}/h)",
            f"  {'-'*30}",
            f"  TOTAL:           {c}{self.total:8.2f}",
        ]
        return "\n".join(lines)

    _rate: float = 65.0


def _orient(length: float, width: float) -> tuple[float, float]:
    """Longest side along the sheet length."""
    return (max(length, width), min(length, width))


def pack_sheets(rects: list[tuple[float, float]], sheet: SheetSize
                ) -> tuple[int, float, int]:
    """Next-fit-decreasing-height shelf packing.

    Returns (sheets_used, utilization, oversize_count). Each rect is (l, w) and
    is auto-oriented longest-side-along-length.
    """
    oriented = [_orient(l, w) for (l, w) in rects]
    oversize = sum(1 for (l, w) in oriented
                   if l > sheet.length or w > sheet.width)
    fit = [(l, w) for (l, w) in oriented
           if l <= sheet.length and w <= sheet.width]
    if not fit:
        return (0, 0.0, oversize)

    # Tallest shelves first packs cleaner.
    fit.sort(key=lambda r: r[1], reverse=True)

    sheets = 1
    shelf_y = 0.0           # bottom of the current shelf
    shelf_h = 0.0           # height of the current shelf
    cursor_x = 0.0          # next free x on the current shelf
    packed_area = 0.0

    for (l, w) in fit:
        if cursor_x + l <= sheet.length:           # fits on current shelf
            pass
        else:                                      # new shelf
            shelf_y += shelf_h + sheet.kerf
            shelf_h = 0.0
            cursor_x = 0.0
            if shelf_y + w > sheet.width:          # new sheet
                sheets += 1
                shelf_y = 0.0
        cursor_x += l + sheet.kerf
        shelf_h = max(shelf_h, w)
        packed_area += l * w

    sheet_area = sheet.length * sheet.width
    utilization = packed_area / (sheets * sheet_area)
    return (sheets, utilization, oversize)


def _edge_banding_metres(spec: CabinetSpec) -> float:
    if not getattr(spec, "edge_banding", False):
        return 0.0
    m = spec.material
    toe_h = spec.toe_kick.height if spec.toe_kick else 0.0
    box_h = spec.height - toe_h
    interior_w = spec.width - 2 * m.carcass
    return (2 * box_h + interior_w) / 1000.0


def estimate(spec: CabinetSpec, *, cutlist: CutList | None = None,
             prices: PriceBook | None = None,
             sheet: SheetSize | None = None) -> Estimate:
    """Produce a cost estimate for *spec*."""
    cl = cutlist or generate_cutlist(spec)
    prices = prices or PriceBook()
    sheet = sheet or SheetSize()

    # Group panels by (material, thickness) and nest each group.
    groups: dict[tuple[str, float], list] = {}
    for p in cl.parts:
        key = (p.material, p.thickness)
        groups.setdefault(key, [])
        groups[key].extend([(p.length, p.width)] * p.qty)

    sheet_groups: list[SheetGroup] = []
    material_cost = 0.0
    for (material, thickness), rects in sorted(groups.items()):
        sheets, util, oversize = pack_sheets(rects, sheet)
        price = prices.sheet_price.get(material, prices.sheet_price_default)
        material_cost += sheets * price
        sheet_groups.append(SheetGroup(
            material=material, thickness=thickness, part_count=len(rects),
            sheets=sheets, utilization=util, oversize=oversize,
        ))

    # Hardware.
    hardware_cost = sum(
        prices.hardware_price.get(h.name, 0.0) * h.qty for h in cl.hardware
    )

    # Edge banding.
    banding_m = _edge_banding_metres(spec)
    banding_cost = banding_m * prices.edge_banding_per_m

    # Labour.
    hours = (prices.labour_base_h
             + prices.labour_per_part_h * sum(p.qty for p in cl.parts)
             + prices.labour_per_door_h * getattr(spec, "doors", 0)
             + prices.labour_per_drawer_h * len(getattr(spec, "drawers", [])))
    labour_cost = hours * prices.shop_rate_per_hour

    est = Estimate(
        spec_name=spec.name, groups=sheet_groups,
        material_cost=material_cost, hardware_cost=hardware_cost,
        edge_banding_cost=banding_cost, edge_banding_m=banding_m,
        labour_hours=hours, labour_cost=labour_cost,
    )
    est._rate = prices.shop_rate_per_hour
    return est
