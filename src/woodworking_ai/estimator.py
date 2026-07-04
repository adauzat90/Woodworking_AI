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
from .dispatch import spec_kind, VOID, GROUP
from .cutlist import CutList, generate_cutlist
from .materials import (
    MAT_SHEET, MAT_BACK, MAT_DOOR_FRONT, MAT_DOOR_PANEL, MAT_DRAWER_BOX,
    MAT_FRAME, MAT_COUNTERTOP, MAT_MOLDING, MAT_TOP, MAT_LEG, MAT_APRON,
)
from .packing import pack
from . import stock as _stock
from . import species as _species

# One board foot is 144 in³ (mirrors cutlist.BOARD_FOOT_MM3); used to derive a
# fallback stick price from a $/board-foot when a size isn't in the price table.
_BOARD_FOOT_MM3 = 144.0 * (25.4 ** 3)
# Canonical species that are bought as construction lumber (priced by the stick)
# rather than hardwood-yard board feet, when their section is a stock dimension.
_CONSTRUCTION_SPECIES = frozenset({"spf", "douglas_fir", "pine"})


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
        MAT_SHEET: 70.0, MAT_BACK: 30.0, MAT_DOOR_FRONT: 95.0,
        MAT_DOOR_PANEL: 60.0, MAT_DRAWER_BOX: 55.0, MAT_FRAME: 40.0,
        MAT_COUNTERTOP: 180.0, MAT_MOLDING: 25.0,    # accessories
        MAT_TOP: 110.0, MAT_LEG: 35.0, MAT_APRON: 35.0,   # table stock
    })
    sheet_price_default: float = 70.0
    # Full-sheet price by physical *form* — used when a part declares its form
    # (e.g. an oak-plywood carcass). Falls back to `sheet_price` by usage label.
    form_sheet_price: dict[str, float] = field(default_factory=lambda: {
        "plywood": 70.0, "mdf": 45.0, "particleboard": 30.0,
        "melamine": 60.0, "hardboard": 22.0,
    })
    # Solid/dimensional lumber is bought by the board foot, not the sheet. Price
    # per board foot keyed by the cut list's `material` label.
    board_foot_price: dict[str, float] = field(default_factory=lambda: {
        "top": 9.0, "leg": 7.0, "apron": 6.0, "frame": 6.5,
    })
    board_foot_price_default: float = 7.0
    # Per-species board-foot OVERRIDE for solid lumber. The base $/bd-ft now comes
    # from the wood-species database (``species.price_per_bdft``) — the single
    # source — so this table only carries deliberate shop overrides, not a second
    # copy of every wood's price that could silently drift. ``oak`` is kept because
    # the species DB resolves bare "oak" to *red* oak ($8.5) while the shop prices
    # generic oak at $9.0; making that the one explicit exception stops the two
    # from disagreeing by accident.
    species_board_foot_price: dict[str, float] = field(
        default_factory=lambda: {"oak": 9.0})
    # Species cost multiplier applied to sheet goods (veneer premium) and to any
    # solid stock priced off a label rather than the per-species table above.
    species_multiplier: dict[str, float] = field(default_factory=lambda: {
        "pine": 0.7, "poplar": 0.8, "birch": 1.0, "beech": 1.1, "ash": 1.3,
        "maple": 1.4, "red_oak": 1.4, "oak": 1.5, "hickory": 1.6,
        "white_oak": 1.7, "cherry": 2.0, "mahogany": 2.4, "walnut": 2.8,
    })
    species_multiplier_default: float = 1.0
    # Milling/defect allowance billed on solid stock (rough lumber yields less).
    lumber_waste_factor: float = 1.15
    # Construction ("dimensional") lumber is bought by the STICK, not the board
    # foot, and is already S4S so it carries NO milling allowance. Price per
    # nominal name, per standard length label. Typical big-box prices; override
    # per shop. A (nominal, length) not listed falls back to the $/bd-ft below.
    stick_prices: dict[str, dict[str, float]] = field(default_factory=lambda: {
        "2x2": {"8ft": 2.60},
        "2x3": {"92-5/8in stud": 2.70, "8ft": 2.80},
        "2x4": {"92-5/8in stud": 3.30, "8ft": 3.50, "10ft": 4.80,
                "12ft": 6.20, "16ft": 9.80},
        "2x6": {"8ft": 5.50, "10ft": 7.20, "12ft": 9.20, "16ft": 13.50},
        "2x8": {"8ft": 8.90, "10ft": 11.50, "12ft": 14.50},
        "2x10": {"8ft": 12.50, "12ft": 18.50},
        "1x2": {"8ft": 1.60}, "1x3": {"8ft": 2.40}, "1x4": {"8ft": 3.20},
        "1x6": {"8ft": 5.00},
        "4x4": {"8ft": 12.00, "10ft": 16.50, "12ft": 22.00},
        "6x6": {"8ft": 33.00},
    })
    # Fallback $/board-foot for a dimensional size/length not in stick_prices.
    dimensional_price_per_bdft: float = 0.75
    # Per-unit hardware prices keyed by the hardware item name. Defaults you can
    # override; representative shop prices, not a live feed.
    hardware_price: dict[str, float] = field(default_factory=lambda: {
        "Concealed hinge": 4.0, "Door pull": 3.5, "Drawer pull": 3.5,
        "Drawer slide (pair)": 12.0, "Shelf pin": 0.15,
        # legged / table / bench / workbench
        "Drawer pull / knob": 3.5, "Tabletop fastener": 0.4,
        "Leg-to-apron bracket": 2.5, "Seat fastener": 0.4,
        "Bench vise": 120.0, "Bench dog": 8.0, "Cable grommet": 4.0,
        # bed (knock-down)
        "Bed bolt + cross-dowel nut": 2.5, "Bed-bolt cover cap": 0.5,
        # box / chest
        "Butt hinge (lid)": 4.0, "Lid-stay / chest support": 6.0,
        # picture / mirror frame
        "Corner spline / V-nail": 0.3, "Glazing (glass)": 12.0,
        "Frame backer board": 3.0, "Glazier point / turn button": 0.15,
        "D-ring strap hanger": 1.0, "Braided picture wire": 2.0,
        "French cleat (45° bevel pair)": 6.0, "Corner bracket": 1.5,
        "Wall anchor / lag screw": 0.5,
        # fasteners
        "Assembly screw 4×35": 0.1,
    })
    edge_banding_per_m: float = 1.5
    finish_per_m2_per_coat: float = 2.5   # finish material + labour per coat·m²
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
    form: str = ""            # physical form, when declared (plywood/mdf/...)
    species: str = ""         # wood species, when declared
    unit_price: float = 0.0   # per-sheet price actually charged (0 = derive it)


@dataclass
class BandingGroup:
    """Edge banding to order, per stock it must match."""
    stock: str
    metres: float


@dataclass
class LumberGroup:
    material: str
    thickness: float
    part_count: int
    board_feet: float         # net board feet (before the waste allowance)
    cost: float               # billed cost (includes the waste allowance)
    form: str = ""            # physical form, when declared ("solid")
    species: str = ""         # wood species, when declared


@dataclass
class StickGroup:
    """Construction lumber bought by the stick (a whole 2x4/4x4/… length).

    A group of same-nominal, same-species parts 1D-nested into whole sticks of one
    standard length — the buyable unit for cheap shop furniture, with no milling
    allowance (the stock is already S4S)."""
    nominal: str              # dimensional name, e.g. "2x4"
    length_label: str         # stick length bought, e.g. "8ft"
    length_mm: float
    species: str              # construction species (spf / douglas_fir / pine)
    sticks: int               # whole sticks to buy
    part_count: int           # pieces crosscut from them
    unit_price: float         # per-stick price charged
    cost: float               # sticks × unit_price


def _stick_length_label(length_mm: float) -> str:
    return _stock.DIMENSIONAL_LENGTH_LABELS.get(length_mm, f"{length_mm:.0f}mm")


def _stick_unit_price(prices: "PriceBook", nominal: str, length_mm: float,
                      label: str) -> float:
    """Per-stick price: the price book's (nominal, length) entry, else derived
    from the dimensional $/board-foot fallback and the stick's own volume."""
    table = prices.stick_prices.get(nominal, {})
    if label in table:
        return table[label]
    sec = _stock.DIMENSIONAL_LUMBER.get(nominal)
    if sec is None:
        return 0.0
    t, w = sec
    bd_ft = (t * w * length_mm) / _BOARD_FOOT_MM3
    return bd_ft * prices.dimensional_price_per_bdft


def _ffd_stick_count(lengths: list[float], capacity: float, kerf: float) -> int:
    """First-fit-decreasing stick count to cut *lengths* from sticks of usable
    run *capacity*. Each piece also consumes one saw kerf (the cut that frees it),
    so the effective demand is length + kerf. Deterministic (sorted descending)."""
    bins: list[float] = []            # remaining usable run in each open stick
    for L in sorted(lengths, reverse=True):
        need = L + kerf
        for i, rem in enumerate(bins):
            if rem + 1e-9 >= need:
                bins[i] = rem - need
                break
        else:
            bins.append(capacity - need)
    return len(bins)


def _stick_lengths_for(prices: "PriceBook", nominal: str) -> list[float]:
    """Standard lengths a nominal is sold in: exactly the lengths the price book
    stocks for it, or — when the nominal isn't in the table at all — every
    standard length (priced via the $/board-foot fallback). Keeping to stocked
    lengths stops the optimiser choosing a length it can only *derive* a (cheaper,
    inconsistent) fallback price for."""
    table = prices.stick_prices.get(nominal)
    if not table:
        return list(_stock.DIMENSIONAL_LENGTHS_MM)
    return [length_mm for length_mm in _stock.DIMENSIONAL_LENGTHS_MM
            if _stick_length_label(length_mm) in table]


def _nest_sticks(nominal: str, species: str, lengths: list[float],
                 prices: "PriceBook", kerf: float) -> "StickGroup | None":
    """Cheapest stocked stick length to cut *lengths* of one nominal from.

    Tries each stocked length that can hold the longest piece (plus a kerf),
    FFD-packs the pieces into it, and keeps the (length, count) with the lowest
    total cost. Returns None when no stocked stick is long enough for the longest
    piece (the caller then prices that group by the board foot)."""
    if not lengths:
        return None
    longest = max(lengths)
    best: StickGroup | None = None
    for length_mm in _stick_lengths_for(prices, nominal):
        if length_mm + 1e-6 < longest + kerf:
            continue
        label = _stick_length_label(length_mm)
        count = _ffd_stick_count(lengths, length_mm, kerf)
        unit = _stick_unit_price(prices, nominal, length_mm, label)
        cost = count * unit
        if best is None or cost < best.cost - 1e-9:
            best = StickGroup(
                nominal=nominal, length_label=label, length_mm=length_mm,
                species=species, sticks=count, part_count=len(lengths),
                unit_price=unit, cost=cost)
    return best


def _price_sticks(parts, prices: "PriceBook", kerf: float
                  ) -> tuple[list["StickGroup"], float, list]:
    """Split solid-lumber *parts* into stick-priced dimensional groups and the
    remaining board-foot parts.

    A part is stick-priced when its declared species is a construction softwood
    (spf / douglas_fir / pine) *and* its cross-section is an off-the-shelf
    dimensional section (a 2x4, 4x4, …). Such parts group by (nominal, species)
    and 1D-nest into whole sticks; everything else stays hardwood-yard board feet.
    Returns ``(stick_groups, stick_cost, board_parts)``.
    """
    buckets: dict[tuple[str, str, str], list] = {}
    board_parts: list = []
    for p in parts:
        if not p.is_solid_lumber:
            continue
        nominal = _stock.dimensional_match(p.thickness, p.width)
        canon = _species.normalize(p.species) if p.species else ""
        if nominal and canon in _CONSTRUCTION_SPECIES:
            buckets.setdefault((nominal, canon, p.species), []).append(p)
        else:
            board_parts.append(p)

    stick_groups: list[StickGroup] = []
    stick_cost = 0.0
    for (nominal, _canon, disp_species) in sorted(buckets, key=lambda k: k[:2]):
        bparts = buckets[(nominal, _canon, disp_species)]
        lengths = [p.length for p in bparts for _ in range(p.qty)]
        sg = _nest_sticks(nominal, disp_species, lengths, prices, kerf)
        if sg is None:
            board_parts.extend(bparts)   # too long for any stick — board-foot it
        else:
            stick_groups.append(sg)
            stick_cost += sg.cost
    return stick_groups, stick_cost, board_parts


def sheet_price(prices: "PriceBook", label: str, form: str,
                 species: str) -> float:
    """Full-sheet price for a group: form base (or label) × species premium."""
    if form and form in prices.form_sheet_price:
        base = prices.form_sheet_price[form]
    else:
        base = prices.sheet_price.get(label, prices.sheet_price_default)
    mult = prices.species_multiplier.get(
        species.strip().lower(), prices.species_multiplier_default)
    return base * mult


def _board_foot_price(prices: "PriceBook", label: str, species: str) -> float:
    """Board-foot price: the PriceBook's per-species table first (user override),
    then the wood-species database's $/bd-ft for a known wood, else the label
    price × species premium."""
    sp = species.strip().lower()
    if sp and sp in prices.species_board_foot_price:
        return prices.species_board_foot_price[sp]
    if sp:
        from . import species as _species
        db_price = _species.price_per_bdft(sp)
        if db_price is not None:
            return db_price
    base = prices.board_foot_price.get(label, prices.board_foot_price_default)
    return base * prices.species_multiplier.get(
        sp, prices.species_multiplier_default)


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
    banding_groups: list[BandingGroup] = field(default_factory=list)
    finish_cost: float = 0.0
    finish_m2: float = 0.0
    stick_groups: list[StickGroup] = field(default_factory=list)
    stick_cost: float = 0.0
    currency: str = "$"
    _rate: float = 65.0       # shop_rate_per_hour, echoed for report_text()

    @property
    def total(self) -> float:
        return (self.material_cost + self.lumber_cost + self.stick_cost
                + self.hardware_cost + self.edge_banding_cost + self.labour_cost
                + self.finish_cost)

    @property
    def total_sheets(self) -> int:
        return sum(g.sheets for g in self.groups)

    @property
    def total_board_feet(self) -> float:
        return sum(g.board_feet for g in self.lumber_groups)

    @property
    def total_sticks(self) -> int:
        return sum(g.sticks for g in self.stick_groups)

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
        if self.stick_groups:
            lines.append("  dimensional lumber (sticks):")
            for sg in self.stick_groups:
                lines.append(
                    f"    {sg.species:<10} {sg.nominal:<5} {sg.length_label:<12} "
                    f"{sg.part_count:>2} parts -> {sg.sticks} stick(s) "
                    f"({c}{sg.cost:.2f})"
                )
        banding = format_run_mm(self.edge_banding_m * 1000.0, unit)
        lines += [
            f"  material:        {c}{self.material_cost:8.2f} "
            f"({self.total_sheets} sheets)",
            f"  lumber:          {c}{self.lumber_cost:8.2f} "
            f"({self.total_board_feet:.1f} bd ft)",
        ]
        if self.stick_cost:
            lines.append(
                f"  dimensional:     {c}{self.stick_cost:8.2f} "
                f"({self.total_sticks} sticks)")
        lines += [
            f"  hardware:        {c}{self.hardware_cost:8.2f}",
            f"  edge banding:    {c}{self.edge_banding_cost:8.2f} "
            f"({banding})",
        ]
        for bg in self.banding_groups:
            lines.append(
                f"    {bg.stock:<22} {format_run_mm(bg.metres * 1000.0, unit)}")
        lines += [
            f"  labour:          {c}{self.labour_cost:8.2f} "
            f"({self.labour_hours:.1f} h @ {c}{self._rate:.0f}/h)",
        ]
        if self.finish_cost:
            lines.append(
                f"  finishing:       {c}{self.finish_cost:8.2f} "
                f"({self.finish_m2:.1f} m²)")
        lines += [
            f"  {'-'*30}",
            f"  TOTAL:           {c}{self.total:8.2f}",
        ]
        return "\n".join(lines)


def pack_sheets(rects: list[tuple], sheet: SheetSize
                ) -> tuple[int, float, int]:
    """Shelf-pack *rects* and report (sheets_used, utilization, oversize_count).

    Thin wrapper over :func:`woodworking_ai.packing.pack`, which the DXF
    cut-layout export shares, so the quote and the nest diagram always agree.
    Each rect is ``(length, width)`` and may carry ``grain`` and a sequence
    token: ``(length, width[, grain[, seq]])``.
    """
    items = []
    for r in rects:
        grain = r[2] if len(r) > 2 else "none"
        seq = r[3] if len(r) > 3 else ""
        items.append((r[0], r[1], "", grain, seq))
    placed, oversize = pack(items, sheet)
    if not placed:
        return (0, 0.0, len(oversize))
    packed_area = sum(l * w for shelf in placed for (_, _, l, w, _) in shelf)
    utilization = packed_area / (len(placed) * sheet.length * sheet.width)
    return (len(placed), utilization, len(oversize))


def _edge_banding_metres(spec: CabinetSpec) -> float:
    """Rough banding run (fallback when no per-edge data is available)."""
    if not getattr(spec, "edge_banding", False):
        return 0.0
    return (2 * spec.box_height + spec.interior_width) / 1000.0


def pack_sheet_groups(parts, prices: PriceBook, sheet: SheetSize,
                       combine_sheet_stock: bool) -> tuple[list[SheetGroup], float]:
    """Pack sheet-good *parts* onto sheets; return (groups, material_cost).

    Default keys each buyable product (usage label / declared form+species) to
    its own sheets. ``combine_sheet_stock`` groups by thickness alone, so one
    grade of sheet covers the whole build — priced at the dearest contributing
    grade so the quote never under-counts. Solid lumber is excluded.
    """
    groups: dict[tuple[str, str, str, float], list] = {}
    contributors: dict[tuple[str, str, str, float], set] = {}
    for p in parts:
        if p.is_solid_lumber:
            continue
        key = (("", "", "", p.thickness) if combine_sheet_stock else p.stock_key)
        groups.setdefault(key, [])
        contributors.setdefault(key, set()).add((p.stock_label, p.form, p.species))
        # Door/drawer fronts cut from one sheet in sequence for a grain/colour
        # match; grain locks each part's orientation on the sheet.
        seq = "front" if p.material == MAT_DOOR_FRONT else ""
        groups[key].extend([(p.length, p.width, p.grain, seq)] * p.qty)

    sheet_groups: list[SheetGroup] = []
    material_cost = 0.0
    for (label, form, species, thickness), rects in sorted(groups.items()):
        sheets, util, oversize = pack_sheets(rects, sheet)
        if combine_sheet_stock:
            price = max(sheet_price(prices, lbl, frm, sp)
                        for (lbl, frm, sp) in contributors[(label, form, species, thickness)])
            disp = "sheet goods"
        else:
            price = sheet_price(prices, label, form, species)
            disp = label
        material_cost += sheets * price
        sheet_groups.append(SheetGroup(
            material=disp, thickness=thickness, part_count=len(rects),
            sheets=sheets, utilization=util, oversize=oversize,
            form=form, species=species, unit_price=price))
    return sheet_groups, material_cost


def _estimate_project(project: ComponentGroup, prices: PriceBook,
                      sheet: SheetSize,
                      combine_sheet_stock: bool = False) -> Estimate:
    """Sum component estimates into one quote.

    By default sheets are counted per component (each cabinet is cut from its own
    sheets, which is how a shop buying distinct products actually orders), then
    like sheet groups are merged for the report. With ``combine_sheet_stock`` the
    whole run is one buy: every cabinet's sheet parts of the same thickness nest
    together across the project, so a kitchen run packs far fewer, fuller sheets.
    Hardware, banding, labour and solid lumber always add straight up.
    """
    groups: dict[tuple[str, float], SheetGroup] = {}
    lumber: dict[tuple[str, float], LumberGroup] = {}
    sticks: dict[tuple[str, str, str], StickGroup] = {}
    banding: dict[str, float] = {}
    material_cost = hardware_cost = banding_cost = banding_m = 0.0
    labour_hours = labour_cost = lumber_cost = stick_cost = 0.0
    finish_cost = finish_m2 = 0.0
    for comp in project.components:
        e = estimate(comp.spec, prices=prices, sheet=sheet,
                     combine_sheet_stock=combine_sheet_stock)
        material_cost += e.material_cost
        hardware_cost += e.hardware_cost
        banding_cost += e.edge_banding_cost
        banding_m += e.edge_banding_m
        for bg in e.banding_groups:
            banding[bg.stock] = banding.get(bg.stock, 0.0) + bg.metres
        labour_hours += e.labour_hours
        labour_cost += e.labour_cost
        lumber_cost += e.lumber_cost
        stick_cost += e.stick_cost
        finish_cost += e.finish_cost
        finish_m2 += e.finish_m2
        for sg in e.stick_groups:
            key = (sg.nominal, sg.length_label, sg.species)
            if key in sticks:
                acc = sticks[key]
                acc.sticks += sg.sticks
                acc.part_count += sg.part_count
                acc.cost += sg.cost
            else:
                sticks[key] = StickGroup(
                    sg.nominal, sg.length_label, sg.length_mm, sg.species,
                    sg.sticks, sg.part_count, sg.unit_price, sg.cost)
        for g in e.groups:
            key = (g.material, g.form, g.species, g.thickness)
            if key in groups:
                acc = groups[key]
                acc.part_count += g.part_count
                acc.sheets += g.sheets
                acc.oversize += g.oversize
                acc.utilization = max(acc.utilization, g.utilization)
            else:
                groups[key] = SheetGroup(g.material, g.thickness, g.part_count,
                                         g.sheets, g.utilization, g.oversize,
                                         form=g.form, species=g.species)
        for g in e.lumber_groups:
            key = (g.material, g.form, g.species, g.thickness)
            if key in lumber:
                acc = lumber[key]
                acc.part_count += g.part_count
                acc.board_feet += g.board_feet
                acc.cost += g.cost
            else:
                lumber[key] = LumberGroup(g.material, g.thickness, g.part_count,
                                          g.board_feet, g.cost,
                                          form=g.form, species=g.species)

    # When combining, re-pack every component's sheet parts as one run-wide buy
    # (and re-price it) instead of the per-component sum — so the quote matches
    # the run-wide nesting diagram and captures the cross-cabinet savings.
    if combine_sheet_stock:
        sheet_groups, material_cost = pack_sheet_groups(
            generate_cutlist(project).parts, prices, sheet, True)
    else:
        sheet_groups = sorted(groups.values(),
                              key=lambda g: (g.material, g.thickness))

    est = Estimate(
        spec_name=project.name, groups=sheet_groups,
        material_cost=material_cost, hardware_cost=hardware_cost,
        edge_banding_cost=banding_cost, edge_banding_m=banding_m,
        labour_hours=labour_hours, labour_cost=labour_cost,
        lumber_groups=sorted(lumber.values(),
                             key=lambda g: (g.material, g.thickness)),
        lumber_cost=lumber_cost,
        banding_groups=[BandingGroup(k, banding[k]) for k in sorted(banding)],
        finish_cost=finish_cost, finish_m2=finish_m2,
        stick_groups=sorted(sticks.values(),
                            key=lambda g: (g.nominal, g.length_label, g.species)),
        stick_cost=stick_cost,
    )
    est._rate = prices.shop_rate_per_hour
    return est


def estimate(spec, *, cutlist: CutList | None = None,
             prices: PriceBook | None = None,
             sheet: SheetSize | None = None,
             combine_sheet_stock: bool = False) -> Estimate:
    """Produce a cost estimate for a cabinet, table, or group.

    ``combine_sheet_stock`` nests all sheet parts of the same thickness onto
    shared sheets (one grade of stock for the whole build) instead of keeping
    each usage product on its own sheets — fewer, fuller sheets.
    """
    prices = prices or PriceBook()
    sheet = sheet or SheetSize()
    kind = spec_kind(spec)
    if kind == VOID:
        # A reserved gap buys nothing and builds nothing.
        est = Estimate(
            spec_name=spec.name, groups=[], material_cost=0.0,
            hardware_cost=0.0, edge_banding_cost=0.0, edge_banding_m=0.0,
            labour_hours=0.0, labour_cost=0.0)
        est._rate = prices.shop_rate_per_hour
        return est
    if kind == GROUP:
        return _estimate_project(spec, prices, sheet,
                                 combine_sheet_stock=combine_sheet_stock)
    cl = cutlist or generate_cutlist(spec)

    # Pack the sheet goods (see :func:`pack_sheet_groups`): each buyable product
    # on its own sheets by default, or all same-thickness parts nested together
    # when ``combine_sheet_stock`` is set.
    sheet_groups, material_cost = pack_sheet_groups(
        cl.parts, prices, sheet, combine_sheet_stock)

    # Solid lumber. Construction-softwood parts whose cross-section is an
    # off-the-shelf dimensional section (a 2x4, 4x4, …) are bought as STICKS and
    # 1D-nested — no 15% milling allowance, since S4S stock is already surfaced.
    # Everything else is hardwood-yard stock priced by the board foot WITH the
    # milling allowance. Stick parts are removed from the board-foot breakdown so
    # the two never double-count.
    stick_groups, stick_cost, board_parts = _price_sticks(
        cl.parts, prices, sheet.kerf)
    board_cl = CutList(spec_name="", parts=board_parts)
    lumber_groups: list[LumberGroup] = []
    lumber_cost = 0.0
    for g in board_cl.lumber_breakdown():
        price = _board_foot_price(prices, g["material"], g.get("species", ""))
        cost = g["board_feet"] * prices.lumber_waste_factor * price
        lumber_cost += cost
        lumber_groups.append(LumberGroup(
            material=g["material"], thickness=g["thickness"],
            part_count=g["parts"], board_feet=g["board_feet"], cost=cost,
            form=g.get("form", ""), species=g.get("species", ""),
        ))

    # Hardware.
    hardware_cost = sum(
        prices.hardware_price.get(h.name, 0.0) * h.qty for h in cl.hardware
    )

    # Edge banding. Prefer the actual banded-edge run from the cut list (per
    # material), so the quote bands exactly the edges the build rules show; fall
    # back to the rough whole-cabinet estimate for legacy parts with no per-edge
    # data.
    banding_groups = [BandingGroup(g["stock"], g["metres"])
                      for g in cl.banding_breakdown()]
    if banding_groups:
        banding_m = cl.total_banding_m
    else:
        banding_m = _edge_banding_metres(spec)
    banding_cost = banding_m * prices.edge_banding_per_m

    # Labour. ``drawers`` is a list on a cabinet but a plain count on the legged
    # types (nightstand/desk); accept either so per-drawer labour is billed.
    _drawers = getattr(spec, "drawers", [])
    n_drawers = _drawers if isinstance(_drawers, int) else len(_drawers)
    hours = (prices.labour_base_h
             + prices.labour_per_part_h * sum(p.qty for p in cl.parts)
             + prices.labour_per_door_h * getattr(spec, "doors", 0)
             + prices.labour_per_drawer_h * n_drawers)
    labour_cost = hours * prices.shop_rate_per_hour

    # Finishing (sand + coat the shown faces), when a finish is specified.
    fin_cost = fin_m2 = 0.0
    if str(getattr(spec, "finish", "none")).lower() != "none":
        from .finishing import finish_cost as _finish_cost
        fin_cost, fin_m2 = _finish_cost(spec, prices.finish_per_m2_per_coat)

    est = Estimate(
        spec_name=spec.name, groups=sheet_groups,
        material_cost=material_cost, hardware_cost=hardware_cost,
        edge_banding_cost=banding_cost, edge_banding_m=banding_m,
        labour_hours=hours, labour_cost=labour_cost,
        lumber_groups=lumber_groups, lumber_cost=lumber_cost,
        banding_groups=banding_groups,
        finish_cost=fin_cost, finish_m2=fin_m2,
        stick_groups=stick_groups, stick_cost=stick_cost,
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
    "species_multiplier_default", "dimensional_price_per_bdft",
)
# Per-label price maps (material/form/species/hardware -> price/multiplier).
_PRICE_MAPS = ("sheet_price", "form_sheet_price", "board_foot_price",
               "species_board_foot_price", "species_multiplier", "hardware_price")


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
    # stick_prices is a NESTED {nominal: {length_label: price}} map; merge it a
    # level deeper than the flat price maps above.
    sp = data.get("stick_prices")
    if isinstance(sp, dict):
        for nominal, lengths in sp.items():
            if isinstance(lengths, dict):
                dst = pb.stick_prices.setdefault(str(nominal), {})
                for lab, v in lengths.items():
                    x = _num(v, lo=0.0)
                    if x is not None:
                        dst[str(lab)] = x
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
