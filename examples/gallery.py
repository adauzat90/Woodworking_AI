"""Build one of each cabinet type/construction and print a cost estimate.

    python examples/gallery.py

No LLM or API key needed. Renders PNGs into ./out if matplotlib is installed.
"""

from woodworking_ai import (
    CabinetSpec, CabinetType, Construction, Material, ToeKick, Drawer,
    validate, generate_cutlist, estimate,
)

SPECS = [
    CabinetSpec(name="Base — frameless", cabinet_type=CabinetType.BASE,
                width=600, height=720, depth=560, shelves=1, doors=2,
                drawers=[Drawer(140)]),
    CabinetSpec(name="Base — face frame", cabinet_type=CabinetType.BASE,
                construction=Construction.FACE_FRAME, width=600, height=720,
                depth=560, shelves=1, doors=2, drawers=[Drawer(140)]),
    CabinetSpec(name="Wall", cabinet_type=CabinetType.WALL, width=800,
                height=720, depth=330, toe_kick=None, shelves=2, doors=2),
    CabinetSpec(name="Tall pantry", cabinet_type=CabinetType.TALL, width=600,
                height=2100, depth=580, toe_kick=ToeKick(100, 50), shelves=5,
                doors=2),
]

for spec in SPECS:
    print("=" * 60)
    print(spec.name)
    result = validate(spec)
    print(f"  valid: {result.ok}  ({len(result.warnings)} warning(s))")
    print("  " + generate_cutlist(spec).summary())
    est = estimate(spec)
    print(f"  estimate: {est.currency}{est.total:.2f} "
          f"({est.total_sheets} sheets, {est.labour_hours:.1f} h)")
    try:
        from pathlib import Path
        from woodworking_ai.render import render_cabinet
        Path("out").mkdir(exist_ok=True)
        fname = "out/" + spec.name.lower().replace(" — ", "_").replace(" ", "_") + ".png"
        render_cabinet(spec, fname)
        print(f"  rendered: {fname}")
    except RuntimeError:
        pass
