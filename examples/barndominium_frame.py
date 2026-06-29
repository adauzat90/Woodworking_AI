"""Auto-place the structural frame of a barndominium — no LLM, no API key.

    python examples/barndominium_frame.py

You give the building envelope (length x width x wall height) and the beam/post
make-up; the engine AUTOMATICALLY places the main carrying beams and the support
posts under them, spacing the posts so no beam clear-spans further than it can
safely carry the load. Then it flows through the same pipeline as any furniture
piece: validate -> cut list. If build123d is installed it also exports a STEP.
"""

from woodworking_ai import BuildingFrameSpec, validate, generate_cutlist
from woodworking_ai.building import frame_plan

# A 40 ft x 30 ft barndominium, 12 ft walls. Built-up 3-ply 2x12 girders on
# treated 6x6 posts (the defaults). Leave beam/post spacing at 0 to auto-place.
spec = BuildingFrameSpec(
    name="40x30 Barndominium frame",
    length=12192,      # 40 ft
    width=9144,        # 30 ft
    wall_height=3658,  # 12 ft
    design_load=245,   # ~50 psf supported area load (a loft floor)
)

print(spec.to_json())

plan = frame_plan(spec)
print(
    f"\nAuto-placed: {plan.n_beams} carrying beams on {plan.n_posts} posts\n"
    f"  {plan.n_lines} beam lines @ {plan.line_spacing / 1000:.1f} m on-centre\n"
    f"  {plan.posts_per_beam} posts per beam: {plan.n_bays} bays of "
    f"{plan.clear_span / 1000:.1f} m (safe span ~{plan.max_span / 1000:.1f} m)"
)

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
    exporters.export_step(model, "out/barndominium_frame.step")
    print("Wrote out/barndominium_frame.step")
except RuntimeError as exc:
    print(f"\n(Skipping geometry export: {exc})")
