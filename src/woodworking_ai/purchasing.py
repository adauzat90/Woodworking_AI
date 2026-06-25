"""Purchase order: the orderable buy-list, grouped by supplier.

The estimate (see :mod:`woodworking_ai.estimator`) answers "what will this cost?".
A purchase order answers the next question a shop asks: "what do I actually buy,
and from whom?". This module turns the same spec + price book into the document a
buyer acts on — every line carries a supplier, an item, a spec/SKU, a quantity
with its unit, a unit price and a line total — grouped by the supplier/brand the
shop raises the order against:

* **sheet goods** by species/grade/nominal size (from the estimate's sheet groups),
* **solid lumber** by the board foot (from the cut list's lumber breakdown),
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

from .cutlist import CutList, generate_cutlist
from .dsl import ComponentGroup
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


@dataclass
class PurchaseOrder:
    """A purchase order for a spec, grouped by supplier."""
    name: str
    lines: list[POLine] = field(default_factory=list)
    currency: str = "$"

    @property
    def grand_total(self) -> float:
        return sum(line.line_total for line in self.lines)

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
        return "\n".join(out)


def _sheet_lines(est: Estimate, prices: PriceBook) -> list[POLine]:
    """Sheet-goods lines, one per buyable stock, priced exactly as the quote."""
    lines: list[POLine] = []
    for g in est.groups:
        if g.sheets <= 0:
            continue
        price = sheet_price(prices, g.material, g.form, g.species)
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


def purchase_order(spec, *, prices: PriceBook | None = None,
                   sheet: SheetSize | None = None,
                   cutlist: CutList | None = None) -> PurchaseOrder:
    """Build a supplier-grouped purchase order for *spec*.

    Works on a cabinet, a table, or a whole :class:`ComponentGroup`/project — a
    project aggregates into one PO (its merged sheet/lumber/banding groups and
    the union of every component's hardware). For a given *prices* the returned
    order's :pyattr:`PurchaseOrder.grand_total` equals ``estimate(spec,
    prices=prices).total`` to the penny: every line is billed off the same
    numbers the quote uses.
    """
    prices = prices or PriceBook()
    sheet = sheet or SheetSize()
    est = estimate(spec, cutlist=cutlist, prices=prices, sheet=sheet)

    if is_group(spec):
        cl = _project_cutlist(spec)
    else:
        cl = cutlist or generate_cutlist(spec)

    lines: list[POLine] = []
    lines += _sheet_lines(est, prices)
    lines += _lumber_lines(est)
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

    return PurchaseOrder(name=est.spec_name, lines=lines, currency=est.currency)


def _project_cutlist(project: ComponentGroup) -> CutList:
    """Merge every component's hardware into one cut list for the PO.

    Like hardware (same name+brand+sku) sums its quantity, so a run's drawer
    pulls land on a single order line. Parts aren't needed here (sheet/lumber/
    banding come from the aggregated estimate), so the merged list carries
    hardware only.
    """
    merged: dict[tuple, "object"] = {}
    from .cutlist import Hardware
    for comp in project.components:
        for h in generate_cutlist(comp.spec).hardware:
            key = (h.name, h.brand, h.sku, h.category, h.notes)
            if key in merged:
                merged[key].qty += h.qty
            else:
                merged[key] = Hardware(
                    h.name, h.qty, h.notes, sku=h.sku, brand=h.brand,
                    category=h.category)
    return CutList(spec_name=project.name, parts=[],
                   hardware=list(merged.values()))
