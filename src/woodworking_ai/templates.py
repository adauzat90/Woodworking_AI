"""Starter-project gallery (G3): ready-to-build specs for a cold start.

A first-time visitor shouldn't face an empty parameter form. This module curates
a small set of named, *guaranteed-valid* starter designs — one per common
home-shop project — that the web UI shows as a gallery: click a card and the
spec loads into the form and builds. Every starter is built from the real spec
dataclasses (so it can never advertise an invalid design) and serialised with
``to_dict`` for the same ``spec_from_dict`` path the rest of the app uses.

Pure data — no CAD dependency, no API key. Reused by the web ``/api/templates``
endpoint and covered by ``tests/test_templates.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

from .dsl import (
    CabinetSpec, CabinetType, TableSpec, WallShelfSpec, BoxSpec, BenchSpec,
    FrameSpec, BedSpec, CuttingBoardSpec, Drawer,
)


@dataclass(frozen=True)
class Template:
    """One starter design: an id, a label, a category, a blurb, and its spec."""
    id: str
    label: str
    category: str
    blurb: str
    spec: dict


# Categories order the gallery; keep them broad and few.
CAT_CABINETS = "Cabinets"
CAT_TABLES = "Tables & seating"
CAT_STORAGE = "Storage"
CAT_BEDROOM = "Bedroom"
CAT_DECOR = "Wall & decor"


def _templates() -> list[Template]:
    """Build the starter set fresh (specs validated by construction)."""
    items: list[Template] = [
        Template(
            "bookcase", "Bookcase", CAT_CABINETS,
            "Open shelving, four adjustable shelves — a great first cabinet.",
            CabinetSpec(name="Bookcase", cabinet_type=CabinetType.BOOKCASE,
                        width=800, height=1800, depth=300, shelves=4,
                        doors=0, species="birch").to_dict()),
        Template(
            "base_cabinet", "Base cabinet", CAT_CABINETS,
            "A shaker base cabinet: two doors, one shelf, soft-close.",
            CabinetSpec(name="Base cabinet", cabinet_type=CabinetType.BASE,
                        width=600, height=720, depth=560, doors=2, shelves=1,
                        door_style="shaker", species="maple").to_dict()),
        Template(
            "drawer_base", "Drawer base", CAT_CABINETS,
            "Three stacked drawers with real dovetailed boxes.",
            CabinetSpec(name="Drawer base", cabinet_type=CabinetType.BASE,
                        width=500, height=720, depth=560, doors=0,
                        drawers=[Drawer(180), Drawer(180), Drawer(220)],
                        species="maple").to_dict()),
        Template(
            "dining_table", "Dining table", CAT_TABLES,
            "A four-seat table — solid top, mortise-and-tenon aprons.",
            TableSpec(name="Dining table", width=1500, depth=850, height=740,
                      species="white_oak").to_dict()),
        Template(
            "dining_bench", "Dining bench", CAT_TABLES,
            "A bench to match the table — stretchers for a sitting load.",
            BenchSpec(name="Dining bench", width=1300, depth=350, height=450,
                      species="white_oak").to_dict()),
        Template(
            "stool", "Shop stool", CAT_TABLES,
            "A tall stool — the smallest legged project to cut your teeth on.",
            BenchSpec(name="Shop stool", width=400, depth=320, height=650,
                      species="maple").to_dict()),
        Template(
            "wall_shelf", "Floating shelf", CAT_DECOR,
            "A single oak shelf on a hidden French cleat.",
            WallShelfSpec(name="Floating shelf", length=900, depth=220,
                          thickness=32, species="red_oak").to_dict()),
        Template(
            "picture_frame", "Picture frame", CAT_DECOR,
            "A splined-miter frame with a rabbet for glass and a print.",
            FrameSpec(name="Picture frame", opening_w=400, opening_h=500,
                      molding_width=45, species="walnut").to_dict()),
        Template(
            "blanket_chest", "Blanket chest", CAT_STORAGE,
            "A dovetailed six-board chest with a hinged lid.",
            BoxSpec(name="Blanket chest", width=900, depth=450, height=500,
                    thickness=18, species="cherry").to_dict()),
        Template(
            "cutting_board", "Cutting board", CAT_TABLES,
            "A maple & walnut edge-grain board — a perfect weekend gift.",
            CuttingBoardSpec(name="Cutting board", length=450, width=300,
                             thickness=38, species="hard_maple",
                             species_b="walnut").to_dict()),
        Template(
            "queen_bed", "Queen bed", CAT_BEDROOM,
            "A knock-down platform bed — frame-and-panel head and footboard.",
            BedSpec(name="Queen bed", size="queen", species="walnut").to_dict()),
    ]
    return items


def templates() -> list[Template]:
    """The starter gallery, in display order."""
    return _templates()


def template(template_id: str) -> Template | None:
    """The starter with this id, or ``None``."""
    for t in _templates():
        if t.id == template_id:
            return t
    return None


def gallery() -> list[dict]:
    """The gallery as plain dicts for the ``/api/templates`` endpoint."""
    return [
        {"id": t.id, "label": t.label, "category": t.category,
         "blurb": t.blurb, "spec": t.spec}
        for t in templates()
    ]
