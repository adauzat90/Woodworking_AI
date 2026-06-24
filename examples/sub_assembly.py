"""Define sub-assemblies and reuse them — no LLM, no API key needed.

    python examples/sub_assembly.py

Shows the two things the assembly layer adds on top of a flat run:

  1. NESTING — a `Component`'s spec can itself be an `Assembly` (a named group of
     placed pieces), so a "drawer bank" is designed once and dropped into a
     kitchen as one unit. Every stage (validate / cut list / estimate / drilling
     / geometry) recurses into it automatically.

  2. REUSE — declare a sub-assembly once under a project's `definitions` and
     place independent copies of it by `ref` (define-once, drop-in-many).

Both forms go through the *same* pipeline as a single cabinet, so a project of
groups yields one combined cut list and one quote.
"""

from woodworking_ai import (
    CabinetSpec, Component, Assembly, Project, spec_from_dict,
    validate, generate_cutlist, estimate,
)

# --- 1. Nesting: an Assembly placed inline as a component -------------------

drawer_bank = Assembly(name="Drawer Bank", components=[
    Component(spec=CabinetSpec(name="3-Drawer", width=600), x=0,   label="DB1"),
    Component(spec=CabinetSpec(name="3-Drawer", width=600), x=600, label="DB2"),
])

kitchen = Project(name="Galley Kitchen", components=[
    Component(spec=drawer_bank,                         x=0,    y=0, label="BANK"),
    Component(spec=CabinetSpec(name="Sink", width=900), x=1200, y=0, label="SINK"),
])

print("== Nested project ==")
print("valid:", validate(kitchen).ok)
print("combined cut-list parts:", len(generate_cutlist(kitchen).parts))
print("quote:", round(estimate(kitchen).total, 2), estimate(kitchen).currency)

# --- 2. Reuse: one definition, placed twice by reference --------------------

payload = {
    "kind": "project", "name": "Wall of Cabinets", "units": "mm",
    "definitions": {
        "wall_pair": {
            "kind": "assembly", "name": "Wall Pair",
            "components": [
                {"spec": {"cabinet_type": "wall", "width": 600,
                          "toe_kick": None}, "x": 0},
                {"spec": {"cabinet_type": "wall", "width": 600,
                          "toe_kick": None}, "x": 600},
            ],
        },
    },
    "components": [
        {"ref": "wall_pair", "x": 0, "y": 0,    "label": "Upper-L"},
        {"ref": "wall_pair", "x": 0, "y": 2000, "label": "Upper-R"},
    ],
}

wall = spec_from_dict(payload)
print("\n== Reuse via definitions + ref ==")
print("valid:", validate(wall).ok)
print("placements:", [c.ref for c in wall.components])
print("parts (two independent copies):", len(generate_cutlist(wall).parts))

# Optional: assemble the whole nested project into one 3D model.
try:
    from pathlib import Path
    from woodworking_ai.builder import build_model, measure
    from woodworking_ai import exporters

    model = build_model(kitchen)
    print("\nAssembled geometry:", measure(model))
    Path("out").mkdir(exist_ok=True)
    exporters.export_step(model, "out/kitchen.step")
    print("Wrote out/kitchen.step")
except RuntimeError as exc:
    print(f"\n(Skipping geometry export: {exc})")
