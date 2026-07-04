"""Purchase order: the orderable buy-list, grouped by supplier.

The estimate (see :mod:`woodworking_ai.estimator`) answers "what will this cost?".
A purchase order answers the next question a shop asks: "what do I actually buy,
and from whom?". This module turns the same spec + price book into the document a
buyer acts on — every line carries a supplier, an item, a spec/SKU, a quantity
with its unit, a unit price and a line total — grouped by the supplier/brand the
shop raises the order against:

* **sheet goods** by species/grade/nominal size (from the estimate's sheet groups),
* **solid lumber** by the board foot (from the cut list's lumber breakdown),
* **construction lumber** by the stick (a whole 2x4/4x4/… length) for cheap
  dimensional stock — priced per piece, not the board foot,
* **hardware** by SKU + brand (resolved from :mod:`woodworking_ai.hardware`),
* **edge banding** by the metre (from the cut list's banding breakdown),
* **finish** by the litre (from :mod:`woodworking_ai.finishing`),
* **shop labour** as an in-house line, so the order's grand total reconciles
  with the quote.

The grand total is built from the *same* numbers the estimator bills, so for a
given :class:`PriceBook` the PO grand total equals ``estimate(...).total`` to the
penny. Pure arithmetic — no CAD dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .cutlist import CutList, generate_cutlist, project_hardware
from .dispatch import is_group
from .estimator import (
    Estimate, PriceBook, SheetSize, sheet_price, estimate,
)
from .materials import stock_name, product_hint
from .stock import stock_label, stock_product

# Suppliers for the non-hardware trades. Hardware lines use the brand as the
# supplier (a shop raises one order per brand), so they are named at build time.
SUPPLIER_SHEET = "Sheet goods supplier"
SUPPLIER_LUMBER = "Lumber yard"
SUPPLIER_BANDING = "Edge-banding supplier"
SUPPLIER_FINISH = "Finish supplier"
SUPPLIER_LABOUR = "Shop labour (in-house)"


@dataclass
class POLine:
    """One orderable line of a purchase order."""
    supplier: str
    category: str          # sheet | lumber | hardware | banding | finish | labour
    item: str              # human description of what to buy
    spec: str = ""         # nominal size / stock spec / SKU
    qty: float = 0.0
    unit: str = ""         # ea | sheet | bd ft | m | L | h
    unit_price: float = 0.0
    line_total: float = 0.0
    brand: str = ""        # hardware brand, when applicable
    sku: str = ""          # orderable part number, when applicable
    source: str = ""       # where to buy it (retailer); advisory, never priced
    url: str = ""          # an optional search/buy link for the source
    alt: str = ""          # a home-center equivalent (for pro/Euro hardware)


@dataclass
class PurchaseOrder:
    """A purchase order for a spec, grouped by supplier.

    ``lines`` are the billable materials + labour and reconcile to the quote
    (:pyattr:`grand_total` == ``estimate(...).total``). ``consumables`` are the
    shop sundries a build also needs — glue, abrasives, clamps, finishing kit —
    kept **separate** so they never disturb that reconciliation; they carry their
    own :pyattr:`consumables_total`.
    """
    name: str
    lines: list[POLine] = field(default_factory=list)
    currency: str = "$"
    consumables: list[POLine] = field(default_factory=list)

    @property
    def grand_total(self) -> float:
        return sum(line.line_total for line in self.lines)

    @property
    def consumables_total(self) -> float:
        return sum(line.line_total for line in self.consumables)

    @property
    def suppliers(self) -> list[str]:
        """Distinct suppliers in line order (stable, de-duplicated)."""
        out: list[str] = []
        for line in self.lines:
            if line.supplier not in out:
                out.append(line.supplier)
        return out

    def lines_by_supplier(self) -> dict[str, list[POLine]]:
        """Lines grouped by supplier, preserving first-seen supplier order."""
        groups: dict[str, list[POLine]] = {}
        for line in self.lines:
            groups.setdefault(line.supplier, []).append(line)
        return groups

    def supplier_total(self, supplier: str) -> float:
        return sum(line.line_total for line in self.lines
                   if line.supplier == supplier)

    def to_csv(self) -> str:
        """The PO as CSV: one row per line, then a grand-total row."""
        def esc(v) -> str:
            s = str(v)
            return f'"{s}"' if ("," in s or '"' in s) else s

        rows = ["supplier,category,item,spec_or_sku,qty,unit,"
                "unit_price,line_total"]
        for ln in self.lines:
            rows.append(",".join(esc(v) for v in (
                ln.supplier, ln.category, ln.item, ln.spec or ln.sku,
                round(ln.qty, 3), ln.unit, round(ln.unit_price, 4),
                round(ln.line_total, 2))))
        rows.append(",".join(("", "", "GRAND TOTAL", "", "", "", "",
                              str(round(self.grand_total, 2)))))
        if self.consumables:
            rows.append("")
            rows.append(",".join(esc(v) for v in (
                SUPPLIER_CONSUMABLES, "note", CONSUMABLES_NOTE, "",
                "", "", "", "")))
            for ln in self.consumables:
                rows.append(",".join(esc(v) for v in (
                    ln.supplier, ln.category, ln.item, ln.spec or ln.sku,
                    round(ln.qty, 3), ln.unit, round(ln.unit_price, 4),
                    round(ln.line_total, 2))))
            rows.append(",".join(esc(v) for v in (
                "", "", "consumables subtotal (not in grand total)", "",
                "", "", "", round(self.consumables_total, 2))))
        return "\n".join(rows)

    def report_text(self) -> str:
        c = self.currency
        out = [f"Purchase order — {self.name}"]
        for supplier, lines in self.lines_by_supplier().items():
            out.append(f"  {supplier}:")
            for ln in lines:
                sku = f" [{ln.sku}]" if ln.sku else ""
                out.append(
                    f"    {ln.item:<28}{sku} {ln.qty:>8.2f} {ln.unit:<6} "
                    f"@ {c}{ln.unit_price:>7.2f} = {c}{ln.line_total:>9.2f}")
            out.append(f"    {'-' * 30}")
            out.append(f"    subtotal: {c}{self.supplier_total(supplier):.2f}")
        out.append(f"  {'=' * 30}")
        out.append(f"  GRAND TOTAL: {c}{self.grand_total:.2f}")
        if self.consumables:
            out.append("")
            out.append("  Shop consumables:")
            out.append(f"    ({CONSUMABLES_NOTE})")
            for ln in self.consumables:
                alt = f"  [or: {ln.alt}]" if ln.alt else ""
                out.append(
                    f"    {ln.item:<28}{' ':>9} {ln.qty:>8.2f} {ln.unit:<6} "
                    f"@ {c}{ln.unit_price:>7.2f} = {c}{ln.line_total:>9.2f}{alt}")
            out.append(f"    consumables subtotal: {c}{self.consumables_total:.2f}")
        return "\n".join(out)


def _sheet_lines(est: Estimate, prices: PriceBook) -> list[POLine]:
    """Sheet-goods lines, one per buyable stock, priced exactly as the quote."""
    lines: list[POLine] = []
    for g in est.groups:
        if g.sheets <= 0:
            continue
        # Use the exact per-sheet price the estimate charged (set when stock is
        # combined / re-priced for offcuts); fall back to deriving it.
        price = g.unit_price or sheet_price(prices, g.material, g.form, g.species)
        name = stock_name(g.form, g.species, fallback=stock_label(g.material))
        product = product_hint(g.form, stock_product(g.material))
        spec = f"{product} {g.thickness:.0f}mm".strip()
        lines.append(POLine(
            supplier=SUPPLIER_SHEET, category="sheet", item=name, spec=spec,
            qty=g.sheets, unit="sheet", unit_price=price,
            line_total=g.sheets * price))
    return lines


def _lumber_lines(est: Estimate) -> list[POLine]:
    """Solid-lumber lines by the board foot; line total is the billed cost
    (which already carries the milling-waste allowance), so it reconciles."""
    lines: list[POLine] = []
    for g in est.lumber_groups:
        if g.board_feet <= 0:
            continue
        name = stock_name(g.form, g.species, solid=True,
                          fallback=stock_label(g.material))
        unit_price = g.cost / g.board_feet if g.board_feet else 0.0
        lines.append(POLine(
            supplier=SUPPLIER_LUMBER, category="lumber", item=name,
            spec=f"{g.thickness:.0f}mm S4S", qty=round(g.board_feet, 2),
            unit="bd ft", unit_price=unit_price, line_total=g.cost))
    return lines


def _species_display(sp: str) -> str:
    """Buyer-facing species label for a dimensional-lumber line ("SPF", "Pine")."""
    s = str(sp or "").strip()
    if s.lower() == "spf":
        return "SPF"
    return s.replace("_", " ").title() if s else "Construction"


def _stick_lines(est: Estimate) -> list[POLine]:
    """Dimensional-lumber lines by the stick (piece), priced exactly as the quote.

    e.g. item "SPF 2x4", spec "8ft stick", qty 7, unit "ea" — so the buyer orders
    whole sticks, and the line totals reconcile with the quote's ``stick_cost``.
    """
    lines: list[POLine] = []
    for g in est.stick_groups:
        if g.sticks <= 0:
            continue
        lines.append(POLine(
            supplier=SUPPLIER_LUMBER, category="lumber",
            item=f"{_species_display(g.species)} {g.nominal}".strip(),
            spec=f"{g.length_label} stick", qty=g.sticks, unit="ea",
            unit_price=g.unit_price, line_total=g.cost))
    return lines


def _hardware_lines(cl: CutList, prices: PriceBook) -> list[POLine]:
    """Hardware lines, grouped under each item's brand as the supplier.

    Priced with the same name→price lookup the estimator uses, so the hardware
    subtotal across all brands equals ``est.hardware_cost``. Brand-less catalogue
    items (generic line, assembly fasteners) fall under a generic supplier.
    """
    lines: list[POLine] = []
    for h in cl.hardware:
        brand = (h.brand or "generic").strip()
        supplier = f"{brand.title()} (hardware)"
        unit_price = prices.hardware_price.get(h.name, 0.0)
        lines.append(POLine(
            supplier=supplier, category="hardware", item=h.name,
            spec=h.sku or h.notes, qty=h.qty, unit="ea",
            unit_price=unit_price, line_total=unit_price * h.qty,
            brand=brand, sku=h.sku))
    return lines


def _banding_lines(est: Estimate, prices: PriceBook) -> list[POLine]:
    """Edge-banding lines by the metre, per stock it must match."""
    lines: list[POLine] = []
    groups = est.banding_groups
    if groups:
        for bg in groups:
            lines.append(POLine(
                supplier=SUPPLIER_BANDING, category="banding",
                item=f"Edge banding — {bg.stock}", spec="pre-glued roll",
                qty=round(bg.metres, 2), unit="m",
                unit_price=prices.edge_banding_per_m,
                line_total=bg.metres * prices.edge_banding_per_m))
    elif est.edge_banding_m > 0:
        # Legacy parts with no per-edge data: one undifferentiated run.
        lines.append(POLine(
            supplier=SUPPLIER_BANDING, category="banding", item="Edge banding",
            spec="pre-glued roll", qty=round(est.edge_banding_m, 2), unit="m",
            unit_price=prices.edge_banding_per_m,
            line_total=est.edge_banding_m * prices.edge_banding_per_m))
    return lines


def _finish_lines(spec, est: Estimate) -> list[POLine]:
    """Finish line by the litre. The line total is the quote's finish cost; the
    per-litre price is derived from it so the readable buy-quantity (litres)
    still reconciles."""
    if est.finish_cost <= 0:
        return []
    from .finishing import finishing_schedule
    fin = finishing_schedule(spec)
    litres = fin.get("litres", 0.0) or 0.0
    unit_price = est.finish_cost / litres if litres else 0.0
    item = f"Finish — {fin.get('type', 'finish')}"
    return [POLine(
        supplier=SUPPLIER_FINISH, category="finish", item=item,
        spec=f"{fin.get('coats', 0)} coats over {est.finish_m2:.1f} m²",
        qty=round(litres, 2), unit="L", unit_price=unit_price,
        line_total=est.finish_cost)]


def _labour_line(est: Estimate, prices: PriceBook) -> list[POLine]:
    """Shop labour as an in-house line, so the grand total matches the quote."""
    if est.labour_cost <= 0:
        return []
    return [POLine(
        supplier=SUPPLIER_LABOUR, category="labour", item="Shop labour",
        spec="cut, process, assemble, finish", qty=round(est.labour_hours, 2),
        unit="h", unit_price=prices.shop_rate_per_hour,
        line_total=est.labour_cost)]


# --- shop consumables (G4a) --------------------------------------------------
# A build also needs sundries the quote doesn't itemise: glue, abrasives, clamps,
# finishing kit. These are kept OFF the reconciled `lines` (so the PO still ties
# to the quote) and surfaced as their own section with indicative prices. Prices
# are typical retail and overridable by editing this table.
SUPPLIER_CONSUMABLES = "Shop consumables"
# Shown wherever the consumables block appears, so no one mistakes the sundry
# prices for the firm material quote.
CONSUMABLES_NOTE = ("Estimates — typical retail; adjust to your shop. "
                    "Not in the grand total, and clamps/brushes you may already own.")
_GLUE_BOTTLE_PRICE = 8.0       # ~250ml PVA
_SANDPAPER_SHEET_PRICE = 0.9   # per sheet
_CLAMP_PRICE = 16.0            # one parallel/bar clamp (a kept tool, not per-build)
_CLAMP_SPACING_MM = 200.0      # ~one clamp per this span of a glued panel
_CLAMP_MIN = 2                 # never suggest fewer than a pair
_CLAMP_MAX = 12                # cap the suggestion for a very wide panel
_BRUSH_PRICE = 4.0
_CONDITIONER_PRICE = 12.0      # pre-stain wood conditioner


def _largest_part_mm(cl: CutList) -> float:
    return max((getattr(p, "length", 0.0) or 0.0 for p in cl.parts), default=0.0)


def _consumable_lines(spec, est: Estimate, cl: CutList) -> list[POLine]:
    """Indicative shop-consumables lines (glue, abrasives, clamps, finishing kit).

    Derived from the same data the rest of the pipeline uses — the glue-up count,
    the finishing schedule's grits + area, and the largest glued panel — so the
    list scales with the actual build. Each line is best-effort and skipped when
    its quantity rounds to zero.
    """
    import math
    from .planning import glue_up_count
    from .finishing import finishing_schedule
    from . import species as species_mod

    lines: list[POLine] = []

    # Glue — ~one 250ml bottle per two glue-ups, at least one for any glued build.
    glue_ups = max(glue_up_count(spec), 0)
    bottles = max(1, math.ceil(glue_ups / 2)) if glue_ups else 0
    if bottles:
        lines.append(POLine(
            supplier=SUPPLIER_CONSUMABLES, category="consumable",
            item="Wood glue (PVA)", spec="~250ml bottle", qty=bottles, unit="ea",
            unit_price=_GLUE_BOTTLE_PRICE, line_total=bottles * _GLUE_BOTTLE_PRICE))

    # Abrasives — the finish's grit sequence (or a default 3-grit sand for a bare
    # piece) over the finishable area, ~0.5 m² of useful life per sheet.
    fin = finishing_schedule(spec)
    grits = fin.get("grits") or [120, 150, 180]
    area = max(float(fin.get("area_m2", 0.0)) or 0.0, 1.0)
    sheets = len(grits) * max(2, math.ceil(area / 0.5))
    if sheets:
        lines.append(POLine(
            supplier=SUPPLIER_CONSUMABLES, category="abrasive",
            item="Sandpaper (assorted grits)",
            spec=f"{'/'.join(str(g) for g in grits)} grit", qty=sheets,
            unit="sheet", unit_price=_SANDPAPER_SHEET_PRICE,
            line_total=round(sheets * _SANDPAPER_SHEET_PRICE, 2)))

    # Clamps — enough to span the largest glued panel at ~1 per 200mm (a kept
    # tool: priced for shoppers who don't own them, flagged as such).
    span = _largest_part_mm(cl)
    n_clamps = (min(max(int(span // _CLAMP_SPACING_MM) + 1, _CLAMP_MIN), _CLAMP_MAX)
                if span > 0 else 0)
    if n_clamps:
        lines.append(POLine(
            supplier=SUPPLIER_CONSUMABLES, category="clamp",
            item="Bar / parallel clamps", spec="own these? skip — ~1 per 200mm",
            qty=n_clamps, unit="ea", unit_price=_CLAMP_PRICE,
            line_total=n_clamps * _CLAMP_PRICE))

    # Finishing sundries — applicators, and a conditioner for blotch-prone woods.
    if fin.get("coats", 0):
        lines.append(POLine(
            supplier=SUPPLIER_CONSUMABLES, category="finish",
            item="Brushes / applicators & rags", spec="for the finish coats",
            qty=2, unit="ea", unit_price=_BRUSH_PRICE,
            line_total=2 * _BRUSH_PRICE))
        if species_mod.finishing_category(getattr(spec, "species", "")) == \
                species_mod.FINISH_BLOTCH and "stain" in str(fin.get("type", "")):
            lines.append(POLine(
                supplier=SUPPLIER_CONSUMABLES, category="finish",
                item="Pre-stain wood conditioner",
                spec="blotch-prone species — condition before stain", qty=1,
                unit="ea", unit_price=_CONDITIONER_PRICE,
                line_total=_CONDITIONER_PRICE))
    return lines


def _apply_sources(lines: list[POLine]) -> None:
    """Stamp each line with where to buy it (retailer / link / big-box alt)."""
    from .sources import source_for
    for ln in lines:
        retailer, url, alt = source_for(
            ln.category, brand=ln.brand, item=ln.item, sku=ln.sku)
        ln.source, ln.url, ln.alt = retailer, url, alt


def purchase_order(spec, *, prices: PriceBook | None = None,
                   sheet: SheetSize | None = None,
                   cutlist: CutList | None = None,
                   est: Estimate | None = None) -> PurchaseOrder:
    """Build a supplier-grouped purchase order for *spec*.

    Works on a cabinet, a table, or a whole :class:`ComponentGroup`/project — a
    project aggregates into one PO (its merged sheet/lumber/banding groups and
    the union of every component's hardware). For a given *prices* the returned
    order's :pyattr:`PurchaseOrder.grand_total` equals ``estimate(spec,
    prices=prices).total`` to the penny: every line is billed off the same
    numbers the quote uses.

    Pass ``est`` to bill off an already-computed estimate (e.g. one that nests
    combined stock, or that has been reduced for owned offcuts) so the buy-list
    matches the quote the user is looking at instead of re-pricing everything new.
    """
    prices = prices or PriceBook()
    sheet = sheet or SheetSize()
    est = est or estimate(spec, cutlist=cutlist, prices=prices, sheet=sheet)

    if is_group(spec):
        # A group's PO needs only merged hardware here; sheet/lumber/banding
        # come from the aggregated estimate above.
        cl = CutList(spec_name=spec.name, hardware=project_hardware(spec))
    else:
        cl = cutlist or generate_cutlist(spec)

    lines: list[POLine] = []
    lines += _sheet_lines(est, prices)
    lines += _lumber_lines(est)
    lines += _stick_lines(est)
    lines += _hardware_lines(cl, prices)
    lines += _banding_lines(est, prices)
    lines += _finish_lines(spec, est)
    lines += _labour_line(est, prices)

    # Group by supplier for a clean, raise-one-order-per-supplier layout while
    # keeping the within-supplier line order stable.
    order: dict[str, int] = {}
    for ln in lines:
        order.setdefault(ln.supplier, len(order))
    lines.sort(key=lambda ln: order[ln.supplier])

    consumables = _consumable_lines(spec, est, cl)

    # Stamp sourcing onto every line (billable + consumable); advisory only.
    _apply_sources(lines)
    _apply_sources(consumables)

    return PurchaseOrder(name=est.spec_name, lines=lines, currency=est.currency,
                         consumables=consumables)


