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

import dataclasses
import math
from dataclasses import dataclass, field

from .dsl import CabinetSpec, ComponentGroup
from .cutlist import CutList, generate_cutlist, SOLID_LUMBER_MATERIALS
from .packing import pack


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
    # Solid/dimensional lumber is bought by the board foot, not the sheet. Price
    # per board foot keyed by the cut list's `material` label.
    board_foot_price: dict[str, float] = field(default_factory=lambda: {
        "top": 9.0, "leg": 7.0, "apron": 6.0, "frame": 6.5,
    })
    board_foot_price_default: float = 7.0
    # Milling/defect allowance billed on solid stock (rough lumber yields less).
    lumber_waste_factor: float = 1.15
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
class LumberGroup:
    material: str
    thickness: float
    part_count: int
    board_feet: float         # net board feet (before the waste allowance)
    cost: float               # billed cost (includes the waste allowance)


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
    lumber_groups: list[LumberGroup] = field(default_factory=list)
    lumber_cost: float = 0.0
    currency: str = "$"
    _rate: float = 65.0       # shop_rate_per_hour, echoed for report_text()

    @property
    def total(self) -> float:
        return (self.material_cost + self.lumber_cost + self.hardware_cost
                + self.edge_banding_cost + self.labour_cost)

    @property
    def total_sheets(self) -> int:
        return sum(g.sheets for g in self.groups)

    @property
    def total_board_feet(self) -> float:
        return sum(g.board_feet for g in self.lumber_groups)

    def report_text(self, unit: str = "metric") -> str:
        from .units import format_length, format_run_mm
        c = self.currency
        lines = [f"Cost estimate — {self.spec_name}", "  sheet goods:"]
        for g in self.groups:
            note = f"  ({g.oversize} oversize!)" if g.oversize else ""
            thk = format_length(g.thickness, unit)
            lines.append(
                f"    {g.material:<12} {thk:>8}  "
                f"{g.part_count:>2} parts -> {g.sheets} sheet(s), "
                f"{g.utilization*100:4.0f}% used{note}"
            )
        if self.lumber_groups:
            lines.append("  solid lumber:")
            for g in self.lumber_groups:
                thk = format_length(g.thickness, unit)
                lines.append(
                    f"    {g.material:<12} {thk:>8}  "
                    f"{g.part_count:>2} parts -> {g.board_feet:6.2f} bd ft "
                    f"({c}{g.cost:.2f})"
                )
        banding = format_run_mm(self.edge_banding_m * 1000.0, unit)
        lines += [
            f"  material:        {c}{self.material_cost:8.2f} "
            f"({self.total_sheets} sheets)",
            f"  lumber:          {c}{self.lumber_cost:8.2f} "
            f"({self.total_board_feet:.1f} bd ft)",
            f"  hardware:        {c}{self.hardware_cost:8.2f}",
            f"  edge banding:    {c}{self.edge_banding_cost:8.2f} "
            f"({banding})",
            f"  labour:          {c}{self.labour_cost:8.2f} "
            f"({self.labour_hours:.1f} h @ {c}{self._rate:.0f}/h)",
            f"  {'-'*30}",
            f"  TOTAL:           {c}{self.total:8.2f}",
        ]
        return "\n".join(lines)


def pack_sheets(rects: list[tuple[float, float]], sheet: SheetSize
                ) -> tuple[int, float, int]:
    """Shelf-pack *rects* and report (sheets_used, utilization, oversize_count).

    Thin wrapper over :func:`woodworking_ai.packing.pack`, which the DXF
    cut-layout export shares, so the quote and the nest diagram always agree.
    """
    placed, oversize = pack([(l, w, "") for (l, w) in rects], sheet)
    if not placed:
        return (0, 0.0, len(oversize))
    packed_area = sum(l * w for shelf in placed for (_, _, l, w, _) in shelf)
    utilization = packed_area / (len(placed) * sheet.length * sheet.width)
    return (len(placed), utilization, len(oversize))


def _edge_banding_metres(spec: CabinetSpec) -> float:
    if not getattr(spec, "edge_banding", False):
        return 0.0
    return (2 * spec.box_height + spec.interior_width) / 1000.0


def _estimate_project(project: ComponentGroup, prices: PriceBook,
                      sheet: SheetSize) -> Estimate:
    """Sum component estimates into one quote.

    Sheets are counted per component (each cabinet is cut from its own sheets,
    which is how a shop actually buys material), then like sheet groups are
    merged for the report. Hardware, banding and labour add straight up.
    """
    groups: dict[tuple[str, float], SheetGroup] = {}
    lumber: dict[tuple[str, float], LumberGroup] = {}
    material_cost = hardware_cost = banding_cost = banding_m = 0.0
    labour_hours = labour_cost = lumber_cost = 0.0
    for comp in project.components:
        e = estimate(comp.spec, prices=prices, sheet=sheet)
        material_cost += e.material_cost
        hardware_cost += e.hardware_cost
        banding_cost += e.edge_banding_cost
        banding_m += e.edge_banding_m
        labour_hours += e.labour_hours
        labour_cost += e.labour_cost
        lumber_cost += e.lumber_cost
        for g in e.groups:
            key = (g.material, g.thickness)
            if key in groups:
                acc = groups[key]
                acc.part_count += g.part_count
                acc.sheets += g.sheets
                acc.oversize += g.oversize
                acc.utilization = max(acc.utilization, g.utilization)
            else:
                groups[key] = SheetGroup(g.material, g.thickness, g.part_count,
                                         g.sheets, g.utilization, g.oversize)
        for g in e.lumber_groups:
            key = (g.material, g.thickness)
            if key in lumber:
                acc = lumber[key]
                acc.part_count += g.part_count
                acc.board_feet += g.board_feet
                acc.cost += g.cost
            else:
                lumber[key] = LumberGroup(g.material, g.thickness, g.part_count,
                                          g.board_feet, g.cost)
    est = Estimate(
        spec_name=project.name, groups=sorted(
            groups.values(), key=lambda g: (g.material, g.thickness)),
        material_cost=material_cost, hardware_cost=hardware_cost,
        edge_banding_cost=banding_cost, edge_banding_m=banding_m,
        labour_hours=labour_hours, labour_cost=labour_cost,
        lumber_groups=sorted(lumber.values(),
                             key=lambda g: (g.material, g.thickness)),
        lumber_cost=lumber_cost,
    )
    est._rate = prices.shop_rate_per_hour
    return est


def estimate(spec, *, cutlist: CutList | None = None,
             prices: PriceBook | None = None,
             sheet: SheetSize | None = None) -> Estimate:
    """Produce a cost estimate for a cabinet, table, or group."""
    prices = prices or PriceBook()
    sheet = sheet or SheetSize()
    if isinstance(spec, ComponentGroup):
        return _estimate_project(spec, prices, sheet)
    cl = cutlist or generate_cutlist(spec)

    # Group panels by (material, thickness) and nest each group. Solid lumber is
    # priced by the board foot below, so it is left out of the sheet packing.
    groups: dict[tuple[str, float], list] = {}
    for p in cl.parts:
        if p.material in SOLID_LUMBER_MATERIALS:
            continue
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

    # Solid lumber, priced by the board foot (with a milling-waste allowance).
    lumber_groups: list[LumberGroup] = []
    lumber_cost = 0.0
    for g in cl.lumber_breakdown():
        price = prices.board_foot_price.get(
            g["material"], prices.board_foot_price_default)
        cost = g["board_feet"] * prices.lumber_waste_factor * price
        lumber_cost += cost
        lumber_groups.append(LumberGroup(
            material=g["material"], thickness=g["thickness"],
            part_count=g["parts"], board_feet=g["board_feet"], cost=cost,
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
        lumber_groups=lumber_groups, lumber_cost=lumber_cost,
    )
    est._rate = prices.shop_rate_per_hour
    return est


# --- price book / sheet size (de)serialisation -------------------------------
# Let a front end read the shop's default rates and post tuned overrides. The
# from_dict helpers merge a (possibly partial) override onto the defaults and
# coerce every value to a sane, finite, non-negative number.

# Scalar (single-value) PriceBook fields, exposed for editing.
_PRICE_SCALARS = (
    "sheet_price_default", "board_foot_price_default", "lumber_waste_factor",
    "edge_banding_per_m", "shop_rate_per_hour", "labour_base_h",
    "labour_per_part_h", "labour_per_door_h", "labour_per_drawer_h",
)
# Per-label price maps (material/hardware -> price).
_PRICE_MAPS = ("sheet_price", "board_foot_price", "hardware_price")


def _num(value, default=None, lo=None):
    """Coerce *value* to a finite float, clamped to >= *lo*; else *default*."""
    try:
        x = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(x):
        return default
    if lo is not None and x < lo:
        x = lo
    return x


def pricebook_to_dict(prices: PriceBook) -> dict:
    """The full price book as a plain JSON-friendly dict."""
    return dataclasses.asdict(prices)


def pricebook_from_dict(data) -> PriceBook:
    """A PriceBook with any overrides in *data* merged onto the defaults."""
    pb = PriceBook()
    if not isinstance(data, dict):
        return pb
    for f in _PRICE_SCALARS:
        if f in data:
            x = _num(data[f], lo=0.0)
            if x is not None:
                setattr(pb, f, x)
    for f in _PRICE_MAPS:
        sub = data.get(f)
        if isinstance(sub, dict):
            for k, v in sub.items():
                x = _num(v, lo=0.0)
                if x is not None:
                    getattr(pb, f)[str(k)] = x
    return pb


def sheetsize_to_dict(sheet: SheetSize) -> dict:
    return {"length": sheet.length, "width": sheet.width, "kerf": sheet.kerf}


def sheetsize_from_dict(data) -> SheetSize:
    """A SheetSize with overrides merged on; dimensions kept strictly positive."""
    s = SheetSize()
    if not isinstance(data, dict):
        return s
    s.length = _num(data.get("length"), s.length, lo=1.0)
    s.width = _num(data.get("width"), s.width, lo=1.0)
    s.kerf = _num(data.get("kerf"), s.kerf, lo=0.0)
    return s
