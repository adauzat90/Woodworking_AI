"""Wall shelf (H1) — a board + a French cleat or brackets.

Proves the new leaf type flows through the whole pipeline (dispatch, panels,
cut list, hardware, validate, joinery, assembly, estimate) and round-trips
through the DSL, with no edit to any generic stage.
"""

import math

import pytest

from woodworking_ai import (
    WallShelfSpec, ShelfFixing, Project, Component,
    validate, generate_cutlist, estimate, spec_from_dict,
)
from woodworking_ai.dsl import MM_PER_IN
from woodworking_ai.dispatch import spec_kind, WALL_SHELF
from woodworking_ai.geometry import panel_layout
from woodworking_ai.joinery import joinery_schedule
from woodworking_ai.assembly_steps import assembly_plan
from woodworking_ai import furniture


def _shelf(**kw) -> WallShelfSpec:
    base = dict(name="Oak Shelf", length=800, depth=200, thickness=25,
                species="oak")
    base.update(kw)
    return WallShelfSpec(**base)


def test_dispatch_kind_and_registry():
    assert spec_kind(_shelf()) == WALL_SHELF
    assert furniture.is_registered(WALL_SHELF)


def test_spec_from_dict_routes_to_wall_shelf():
    spec = spec_from_dict({"kind": "wall_shelf", "name": "S", "length": 900})
    assert isinstance(spec, WallShelfSpec)
    assert spec.length == 900


def test_roundtrip_to_from_dict():
    spec = _shelf(fixing="brackets", brackets=3)
    again = WallShelfSpec.from_dict(spec.to_dict())
    assert again == spec
    assert again.fixing == ShelfFixing.BRACKETS


def test_imperial_on_load_converts_to_mm():
    spec = WallShelfSpec.from_dict(
        {"units": "in", "length": 36, "depth": 8, "thickness": 1,
         "mount_height": 55})
    assert spec.units == "mm"
    assert spec.length == pytest.approx(36 * MM_PER_IN)
    assert spec.depth == pytest.approx(8 * MM_PER_IN)
    assert spec.mount_height == pytest.approx(55 * MM_PER_IN)


def test_built_height_is_board_plus_fixing_not_mount_height():
    # ``height`` is the built artifact's Z-extent (board + cleat), distinct from
    # the install ``mount_height`` — so the Critic measures the real object.
    spec = _shelf()
    assert spec.height == pytest.approx(spec.thickness + spec.cleat_height)
    assert spec.height != spec.mount_height


def test_panels_board_plus_cleat():
    panels = panel_layout(_shelf())
    labels = [p.label for p in panels]
    assert "Shelf" in labels
    assert any(l.startswith("Cleat") for l in labels)
    shelf = next(p for p in panels if p.label == "Shelf")
    # Board top sits at the mounting height.
    assert shelf.center[2] + shelf.size[2] / 2 == pytest.approx(_shelf().mount_height)


def test_panels_brackets_count():
    panels = panel_layout(_shelf(fixing="brackets", brackets=3))
    brackets = [p for p in panels if p.label.startswith("Bracket")]
    assert len(brackets) == 3


def test_cutlist_has_board_and_cleat_parts():
    cl = generate_cutlist(_shelf())
    names = [p.name for p in cl.parts]
    assert "Shelf board" in names
    assert "Cleat" in names
    assert all(p.id for p in cl.parts)            # IDs assigned
    cleat = next(p for p in cl.parts if p.name == "Cleat")
    assert cleat.qty == 2                          # one to wall, one to shelf


def test_cleat_hardware_entry():
    cl = generate_cutlist(_shelf())
    hw = [h.name for h in cl.hardware]
    assert any("French cleat" in h for h in hw)
    assert any("anchor" in h.lower() or "lag" in h.lower() for h in hw)


def test_bracket_hardware_entry():
    cl = generate_cutlist(_shelf(fixing="brackets", brackets=2))
    hw = [h.name for h in cl.hardware]
    assert any("bracket" in h.lower() for h in hw)


def test_validate_sane_shelf_passes():
    assert validate(_shelf()).ok


def test_validate_rejects_nonpositive_dims():
    res = validate(_shelf(length=0))
    assert not res.ok


def test_validate_brackets_need_two():
    res = validate(_shelf(fixing="brackets", brackets=1))
    assert not res.ok
    assert any("bracket" in i.field for i in res.errors)


def test_validate_flags_excessive_sag():
    # A long, thin, heavily-loaded pine shelf must trip the deflection check.
    res = validate(_shelf(length=1600, depth=200, thickness=15,
                          species="pine", load_kg_per_m=40))
    msgs = " ".join(i.message for i in res.issues).lower()
    assert ("sag" in msgs) or ("deflect" in msgs)


def test_joinery_has_cleat_bevel():
    ops = joinery_schedule(_shelf()).ops
    assert any("bevel" in o.operation for o in ops)


def test_assembly_plan_nonempty():
    plan = assembly_plan(_shelf())
    assert plan.subassemblies
    assert plan.flat_steps()


def test_estimate_prices_the_board():
    assert estimate(_shelf()).total > 0


def test_wall_shelf_inside_a_project():
    proj = Project(name="Shelving", components=[
        Component(spec=_shelf(name="A", length=600), x=0, label="A"),
        Component(spec=_shelf(name="B", length=600), x=1000, label="B"),
    ])
    assert validate(proj).ok
    cl = generate_cutlist(proj)
    assert len(cl.parts) >= 4                       # two boards + two cleats
    assert estimate(proj).total > 0
    assert len(panel_layout(proj)) > 0
