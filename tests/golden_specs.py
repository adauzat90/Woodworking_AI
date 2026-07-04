"""Representative specs for the golden-output safety net (no CAD/LLM needed).

A spread that exercises every dispatch branch the refactor touches: each cabinet
type, both constructions, mullion/drawers/false-fronts, a table, a blind corner,
a flat project, and a nested+reused assembly.
"""

from woodworking_ai import (
    CabinetSpec, CabinetType, Construction, ToeKick, Drawer, TableSpec,
    WallShelfSpec, BoxSpec, BenchSpec, PieceSpec, Component, Assembly, Project,
    spec_from_dict,
)


def golden_specs() -> dict:
    drawer_bank = Assembly(name="Drawer Bank", components=[
        Component(spec=CabinetSpec(name="3-Drawer", width=600,
                                   drawers=[Drawer(180), Drawer(180)]),
                  x=0, label="DB1"),
        Component(spec=CabinetSpec(name="3-Drawer", width=600), x=600, label="DB2"),
    ])
    kitchen = Project(name="Galley Kitchen", components=[
        Component(spec=drawer_bank, x=0, y=0, label="BANK"),
        Component(spec=CabinetSpec(name="Sink", width=900, doors=2),
                  x=1200, y=0, label="SINK"),
    ])
    reuse = spec_from_dict({
        "kind": "project", "name": "Wall of Cabinets", "units": "mm",
        "definitions": {"wall_pair": {
            "kind": "assembly", "name": "Wall Pair", "components": [
                {"spec": {"cabinet_type": "wall", "width": 600, "toe_kick": None}, "x": 0},
                {"spec": {"cabinet_type": "wall", "width": 600, "toe_kick": None}, "x": 600},
            ]}},
        "components": [
            {"ref": "wall_pair", "x": 0, "y": 0, "label": "Upper-L"},
            {"ref": "wall_pair", "x": 0, "y": 2000, "label": "Upper-R"},
        ],
    })

    return {
        "base_frameless": CabinetSpec(
            name="Base frameless", cabinet_type=CabinetType.BASE, width=600,
            height=720, depth=560, shelves=1, doors=2, drawers=[Drawer(140)]),
        "base_faceframe": CabinetSpec(
            name="Base face frame", cabinet_type=CabinetType.BASE,
            construction=Construction.FACE_FRAME, width=600, height=720,
            depth=560, shelves=1, doors=2, drawers=[Drawer(140)]),
        "base_mullion": CabinetSpec(
            name="Base mullion", width=900, height=720, depth=560, doors=2,
            center_mullion=True, shelves=2),
        "wall": CabinetSpec(
            name="Wall", cabinet_type=CabinetType.WALL, width=800, height=720,
            depth=330, toe_kick=None, shelves=2, doors=2),
        "tall": CabinetSpec(
            name="Tall pantry", cabinet_type=CabinetType.TALL, width=600,
            height=2100, depth=580, toe_kick=ToeKick(100, 50), shelves=5, doors=2),
        "bookcase": CabinetSpec(
            name="Bookcase", cabinet_type=CabinetType.BOOKCASE, width=800,
            height=1800, depth=300, toe_kick=ToeKick(80, 40), shelves=4, doors=0),
        "dresser": CabinetSpec(
            name="Dresser", cabinet_type=CabinetType.DRESSER, width=900,
            height=800, depth=500, toe_kick=ToeKick(80, 40), shelves=0, doors=0,
            drawers=[Drawer(180), Drawer(180), Drawer(180)]),
        "corner_blind": CabinetSpec(
            name="Blind corner", cabinet_type=CabinetType.CORNER_BLIND,
            width=900, height=720, depth=560, blind_width=300, doors=1, shelves=1),
        "false_front": CabinetSpec(
            name="False front", width=600, height=720, depth=560, doors=2,
            drawers=[Drawer(160), Drawer(160, false_front=True)]),
        "table": TableSpec(
            name="Dining table", width=1600, depth=900, height=740, leg=70,
            apron_height=100),
        "wall_shelf_cleat": WallShelfSpec(
            name="Oak shelf", length=800, depth=200, thickness=25,
            species="oak", fixing="french_cleat"),
        "wall_shelf_brackets": WallShelfSpec(
            name="Bracket shelf", length=900, depth=250, thickness=20,
            fixing="brackets", brackets=3),
        "box_chest": BoxSpec(
            name="Blanket chest", width=900, depth=450, height=450,
            thickness=18, corner_joint="dovetail", species="walnut"),
        "box_open": BoxSpec(
            name="Open box", width=400, depth=300, height=200, thickness=12,
            corner_joint="box", lid=False),
        "bench": BenchSpec(
            name="Dining bench", width=1200, depth=350, height=450, leg=45,
            species="ash"),
        "stool": BenchSpec(
            name="Shop stool", width=350, depth=350, height=650, leg=40,
            stretchers=True),
        "piece_shelving": PieceSpec(
            name="Garage Shelving", material_form="plywood", species="birch",
            parts=[
                {"name": "Leg", "at": [0, 0, 0], "size": [38, 400, 1000],
                 "grain": "z", "material_form": "solid", "species": "pine",
                 "repeat": {"count": 2, "step": [1162, 0, 0]}},
                {"name": "Shelf", "at": [38, 0, 200], "size": [1124, 400, 18],
                 "grain": "x", "repeat": {"count": 3, "step": [0, 0, 380]}},
            ],
            joints=[{"parts": ["Leg", "Shelf"], "joinery": "screw"}]),
        # A piece that composes shared components: a 2x4-SPF legged base + a
        # plywood top + a plywood lower shelf bank. Exercises the components-in-
        # piece expansion (namespaced parts/panels/joinery, merged physics) and
        # by-the-stick dimensional pricing end to end.
        "assembly_table_piece": PieceSpec(
            name="Workshop Assembly Table", material_form="solid", species="spf",
            parts=[
                {"name": "Top", "at": [0, 0, 882], "size": [1200, 600, 18],
                 "grain": "x", "material_form": "plywood", "species": "birch"},
            ],
            components=[
                {"component": "legged_base", "name": "Base", "at": [0, 0, 0],
                 "width": 1200, "depth": 600, "height": 900, "top_thickness": 18,
                 "leg": 89, "leg_depth": 38, "leg_inset": 40, "apron_height": 89,
                 "apron_thickness": 38, "joinery": "mortise_tenon"},
                {"component": "shelf_bank", "name": "Lower shelf",
                 "at": [150, 100, 0], "width": 900, "depth": 400, "height": 320,
                 "shelf_thickness": 18, "upright_thickness": 18, "shelves": 1,
                 "load_kg_per_m": 40, "species": "birch", "material_form": "plywood"},
            ]),
        "project_nested": kitchen,
        "project_reuse": reuse,
    }
