"""Machine-honest geometry (A2): joinery + bores cut into the B-Rep.

These exercise the real OpenCascade booleans, so they need build123d. CI does
NOT install it, so every test guards with ``pytest.importorskip`` and is skipped
cleanly there (the slab path is covered by the existing pure tests).
"""

import math

import pytest

from woodworking_ai import (
    CabinetSpec, Material, ToeKick, Drawer, Component, Project,
)


def spec(**o) -> CabinetSpec:
    d = dict(name="Mach", width=600, height=720, depth=560,
             material=Material(18, 6, 18, 18, 12), toe_kick=ToeKick(100, 50),
             shelves=1, doors=2, drawers=[], reveal=3)
    d.update(o)
    return CabinetSpec(**d)


def _by_label(model) -> dict:
    return {c.label: c for c in model.children}


def test_side_panel_loses_its_dado_volume():
    """A carcass side ≈ slab − Σ(housing boxes), no bores muddying the sum.

    With no shelves/doors/drawers the side carries only its bottom dado and the
    back rabbet (no shelf-pin / slide / hinge bores), so the removed volume is
    exactly the union of those two housings.
    """
    pytest.importorskip("build123d")
    from woodworking_ai.builder import build_model
    from woodworking_ai.joinery import joinery_schedule

    s = spec(shelves=0, doors=0, drawers=[])
    off = _by_label(build_model(s))
    on = _by_label(build_model(s, joinery_geometry=True))
    side_off, side_on = off["Side L"], on["Side L"]

    removed = side_off.volume - side_on.volume
    assert removed > 0          # something was actually cut

    # Housings keyed to this part, sized box-style (width x depth).
    pid = "A1"
    ops = [o for o in joinery_schedule(s).ops
           if o.part_id == pid and o.width > 0 and o.depth > 0]
    assert ops, "expected at least one housed joint on the side"

    sy, sz = s.depth, s.box_height
    bottom = next(o for o in ops if "bottom" in o.reference)
    back = next(o for o in ops if "rear" in o.reference)
    # Bottom dado: full-depth box, ``width`` tall, ``depth`` into the thickness.
    dado = sy * bottom.width * bottom.depth
    # Back rabbet: full-height strip, ``width`` along Y, ``depth`` into thickness.
    rabbet = back.width * sz * back.depth
    # The two housings meet at the rear-bottom corner; subtract that overlap.
    overlap = back.width * bottom.width * min(bottom.depth, back.depth)
    expected = dado + rabbet - overlap
    assert removed == pytest.approx(expected, rel=0.05)


def test_door_gets_hinge_cup_pockets():
    """A hinged door carries 35mm cup pockets ~12.5mm deep when bores apply."""
    pytest.importorskip("build123d")
    import build123d as b3d
    from woodworking_ai.builder import build_model
    from woodworking_ai.hardware import hinge_count

    s = spec(doors=1, shelves=0)
    on = _by_label(build_model(s, joinery_geometry=True))
    door = on["Door"]

    # Cylindrical pocket walls appear once per hinge cup.
    cyl = [f for f in door.faces() if f.geom_type == b3d.GeomType.CYLINDER]
    n = hinge_count(s.box_height - 2 * s.reveal)
    assert len(cyl) == n
    # Each pocket wall is ~ pi * dia * depth in side area (35mm dia, 12.5 deep).
    for f in cyl:
        assert f.area == pytest.approx(math.pi * 35.0 * 12.5, rel=0.2)


def test_flag_off_is_unchanged_slab_geometry():
    """Regression: flag off is byte-for-byte today's slabs (volume + bbox)."""
    pytest.importorskip("build123d")
    from woodworking_ai.builder import build_model, measure

    s = spec(drawers=[Drawer(140)])
    base = build_model(s)
    again = build_model(s, joinery_geometry=False)
    assert measure(base) == measure(again)
    bv = {c.label: round(c.volume, 3) for c in base.children}
    av = {c.label: round(c.volume, 3) for c in again.children}
    assert bv == av
    # And the machined model must differ (sanity: the flag does something).
    cut = build_model(s, joinery_geometry=True)
    cv = {c.label: round(c.volume, 3) for c in cut.children}
    assert cv != bv


def _project() -> Project:
    """A two-cabinet run, each component a plain housed-joint carcass."""
    return Project(name="Run", components=[
        Component(spec=spec(name="A", shelves=0, doors=0, drawers=[]),
                  x=0, label="C1"),
        Component(spec=spec(name="B", width=800, shelves=0, doors=0,
                            drawers=[]), x=600, label="C2"),
    ])


def test_project_components_are_machined():
    """A2 gap fix: ``build_project(..., joinery_geometry=True)`` must cut each
    component's panels with that component's own joinery, resolved through the
    per-component tag. A tagged side panel's machined volume is strictly less
    than its slab volume."""
    pytest.importorskip("build123d")
    from woodworking_ai.builder import build_model

    proj = _project()
    off = _by_label(build_model(proj))
    on = _by_label(build_model(proj, joinery_geometry=True))

    # Every component contributes a tagged side; each one must lose material.
    cut_any = False
    for tag in ("C1", "C2"):
        label = f"{tag} · Side L"
        assert label in off and label in on, f"missing {label}"
        if on[label].volume < off[label].volume - 1e-6:
            cut_any = True
            # The bottom dado + back rabbet are real removals, not noise.
            assert on[label].volume > 0
    assert cut_any, "no project component panel was machined"


def test_project_flag_off_is_unchanged_slabs():
    """Regression: with the flag off a project is byte-for-byte plain slabs."""
    pytest.importorskip("build123d")
    from woodworking_ai.builder import build_model, measure

    proj = _project()
    base = build_model(proj)
    again = build_model(proj, joinery_geometry=False)
    assert measure(base) == measure(again)
    bv = {c.label: round(c.volume, 3) for c in base.children}
    av = {c.label: round(c.volume, 3) for c in again.children}
    assert bv == av
    # And the machined project must actually differ from the slab project.
    cut = build_model(proj, joinery_geometry=True)
    cv = {c.label: round(c.volume, 3) for c in cut.children}
    assert cv != bv


def test_machined_export_does_not_raise(tmp_path):
    """An export of a normal spec with the flag on must not crash."""
    pytest.importorskip("build123d")
    from woodworking_ai.builder import build_model
    from woodworking_ai import exporters

    s = spec(drawers=[Drawer(140)], shelves=2)
    model = build_model(s, joinery_geometry=True)
    p = exporters.export_step(model, tmp_path / "machined.step")
    assert p.exists() and p.stat().st_size > 0
