"""5-piece doors and accessories appear in the geometry (panel_layout)."""

from woodworking_ai.dsl import CabinetSpec
from woodworking_ai.geometry import panel_layout
from woodworking_ai.agents.critic import critique
from woodworking_ai.drilling import drilling_schedule


def _cab(**kw):
    base = dict(width=900, height=720, depth=560, doors=2, shelves=1)
    base.update(kw)
    return CabinetSpec(**base)


def _labels(spec):
    return [p.label for p in panel_layout(spec)]


def test_slab_door_is_one_panel_per_leaf():
    panels = [p for p in panel_layout(_cab(door_style="slab"))
              if p.label.startswith("Door")]
    assert len(panels) == 2   # two slab leaves


def test_shaker_door_emits_frame_and_recessed_panel():
    panels = panel_layout(_cab(door_style="shaker"))
    labels = [p.label for p in panels]
    # Each leaf: hinge stile (Door L/R) + latch stile + 2 rails + centre panel.
    assert "Door L" in labels and "Door R" in labels
    assert "Stile L latch" in labels and "Rail L top" in labels
    assert "Panel L" in labels and "Panel R" in labels
    # The centre panel is the recessed, thinner door_panel stock.
    panel = next(p for p in panels if p.label == "Panel L")
    spec = _cab(door_style="shaker")
    assert panel.size[1] == spec.material.door_panel
    assert panel.size[1] < spec.material.door


def test_shaker_door_still_bores_one_hinge_cup_op_per_leaf():
    sched = drilling_schedule(_cab(door_style="shaker"))
    cups = [op for op in sched.ops if "hinge cup" in op.operation]
    assert len(cups) == 2   # the hinge-side stile keeps the Door label


def test_shaker_geometry_passes_the_critic():
    crit = critique(_cab(door_style="shaker"))
    assert crit.ok
    assert crit.report["interference_count"] == 0


def test_accessories_appear_as_panels():
    spec = _cab(accessories=[
        {"kind": "countertop", "depth": 620, "overhang": 30},
        {"kind": "filler", "width": 50, "side": "left"},
        {"kind": "end_panel", "side": "right"},
        {"kind": "molding", "type": "crown", "height": 90}])
    labels = _labels(spec)
    assert "Countertop" in labels and "Filler" in labels
    assert "End panel" in labels and "Crown molding" in labels


def test_countertop_sits_above_the_carcass_without_interfering():
    spec = _cab(accessories=[{"kind": "countertop", "depth": 620, "overhang": 30}])
    panels = panel_layout(spec)
    counter = next(p for p in panels if p.label == "Countertop")
    box_top = spec.toe_kick_height + spec.box_height
    # Its bottom sits on the carcass top (touch, not overlap).
    assert counter.bounds()[2][0] >= box_top - 0.01
    assert critique(spec).ok


def test_accessories_do_not_distort_the_carcass_envelope():
    plain = critique(_cab())
    withacc = critique(_cab(accessories=[
        {"kind": "filler", "width": 50, "side": "left"},
        {"kind": "countertop", "depth": 620}]))
    # The measured carcass shell (width/height/depth) is unchanged by trim.
    for k in ("width", "height", "depth"):
        assert plain.report[k] == withacc.report[k]
