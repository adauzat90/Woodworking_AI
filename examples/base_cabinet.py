"""Build a cabinet straight from a DSL spec — no LLM, no API key needed.

    python examples/base_cabinet.py

Demonstrates the deterministic core: spec -> validate -> cut list. If build123d
is installed it will also export STEP/STL into ./out.
"""

from woodworking_ai import CabinetSpec, Material, ToeKick, Drawer, validate, generate_cutlist

spec = CabinetSpec(
    name="Sink Base 900",
    width=900, height=720, depth=560,
    material=Material(carcass=18, back=6, door=18, shelf=18),
    toe_kick=ToeKick(height=100, setback=50),
    shelves=1,
    doors=2,
    drawers=[Drawer(front_height=140)],
    reveal=3,
)

print(spec.to_json())

result = validate(spec)
print("\nValid:", result.ok)
for issue in result.issues:
    print(" ", issue)

cutlist = generate_cutlist(spec)
print("\n" + cutlist.to_csv())
print("\n" + cutlist.hardware_csv())
print("\n" + cutlist.summary())

# Optional: geometry export (only if build123d is available).
try:
    from pathlib import Path
    from woodworking_ai.builder import build_model, measure
    from woodworking_ai import exporters

    model = build_model(spec)
    print("\nGeometry:", measure(model))
    Path("out").mkdir(exist_ok=True)
    exporters.export_step(model, "out/sink_base.step")
    print("Wrote out/sink_base.step")
except RuntimeError as exc:
    print(f"\n(Skipping geometry export: {exc})")
