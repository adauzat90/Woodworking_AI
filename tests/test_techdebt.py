"""Regression tests for the shared helpers introduced in the tech-debt pass.

These lock in the de-duplications so the consolidated code paths cannot quietly
drift apart again: spec dimension properties, the single shelf-nester shared by
the estimator and the DXF export, the shared JSON extractor, and the expanded
designer schema hint.
"""

import pytest

from woodworking_ai import (
    CabinetSpec, CabinetType, Material, ToeKick, Drawer, SheetSize, pack_sheets,
    Construction, generate_cutlist,
)
from woodworking_ai.dsl import DSL_SCHEMA_HINT
from woodworking_ai.geometry import front_plan, panel_layout
from woodworking_ai.packing import pack
from woodworking_ai.dxf import _pack_positions
from woodworking_ai.agents import llm


def _spec(**o) -> CabinetSpec:
    d = dict(name="T", width=600, height=720, depth=560,
             material=Material(18, 6, 18, 18, 12), toe_kick=ToeKick(100, 50),
             shelves=1, doors=2, drawers=[], reveal=3)
    d.update(o)
    return CabinetSpec(**d)


# --- spec dimension properties -------------------------------------------

def test_dimension_properties():
    s = _spec()
    assert s.toe_kick_height == 100
    assert s.box_height == 620            # 720 - 100
    assert s.interior_width == 564        # 600 - 2*18
    assert s.interior_depth == 554        # 560 - 6


def test_toe_kick_height_none():
    s = _spec(toe_kick=None)
    assert s.toe_kick_height == 0.0
    assert s.box_height == s.height


# --- one shared shelf-nester ---------------------------------------------

def test_pack_sheets_delegates_to_packing():
    rects = [(600, 400), (800, 500), (1200, 600)]
    items = [(l, w, f"p{i}") for i, (l, w) in enumerate(rects)]
    sheet = SheetSize()

    placed, oversize = pack(items, sheet)
    n_sheets, util, n_oversize = pack_sheets(rects, sheet)

    assert n_sheets == len(placed)
    assert n_oversize == len(oversize)
    assert 0 < util <= 1


def test_dxf_pack_is_the_shared_packer():
    # _pack_positions is now an alias for packing.pack — same object, same result.
    assert _pack_positions is pack


def test_estimator_and_dxf_both_nest_via_shared_packer(tmp_path):
    # The estimator nests per material group; the DXF nests every part mixed on
    # shared sheets. Different groupings, but one packer underneath — both must
    # produce a sane, non-zero sheet count for the same spec.
    from woodworking_ai.dxf import export_cutlayout_dxf
    from woodworking_ai.estimator import estimate
    spec = _spec(cabinet_type=CabinetType.TALL, height=2100, shelves=6,
                 doors=2, drawers=[Drawer(150), Drawer(150)])
    text = export_cutlayout_dxf(spec, tmp_path / "n.dxf").read_text()
    assert text.count("Sheet ") >= 1
    assert estimate(spec).total_sheets >= 1


# --- one shared JSON extractor -------------------------------------------

def test_extract_json_plain_and_fenced():
    assert llm.extract_json('{"a": 1}') == {"a": 1}
    fenced = "Here you go:\n```json\n{\"a\": 2}\n```\nThanks"
    assert llm.extract_json(fenced) == {"a": 2}


def test_designer_and_critic_share_extractor():
    from woodworking_ai.agents import designer, critic
    # designer calls llm.extract_json directly; critic re-exports it by name.
    assert critic._extract_json is llm.extract_json
    assert "extract_json" in designer.llm.__dict__ or hasattr(designer.llm, "extract_json")


# --- designer schema hint covers every cabinet type ----------------------

def test_schema_hint_documents_all_cabinet_types():
    for ct in CabinetType:
        assert ct.value in DSL_SCHEMA_HINT, f"{ct.value} missing from schema hint"


# --- one shared front layout (geometry panels == cut-list parts) ---------

# A spread of front configurations: overlay/inset, single/double doors,
# mullion, drawer banks, false fronts, and a blind corner.
_FRONT_CASES = [
    dict(doors=2, drawers=[]),
    dict(doors=1, width=450, drawers=[]),
    dict(doors=2, center_mullion=True),
    dict(doors=2, construction=Construction.FACE_FRAME),
    dict(doors=2, center_mullion=True, construction=Construction.FACE_FRAME),
    dict(doors=0, drawers=[Drawer(140), Drawer(180), Drawer(180)]),
    dict(doors=2, drawers=[Drawer(160), Drawer(160, false_front=True)]),
    dict(cabinet_type=CabinetType.CORNER_BLIND, blind_width=300, doors=1,
         width=900),
]


@pytest.mark.parametrize("opts", _FRONT_CASES)
def test_front_panels_and_parts_share_dimensions(opts):
    spec = _spec(**opts)
    plan = front_plan(spec)
    panels = {p.label: p for p in panel_layout(spec)}
    parts = {p.name: p for p in generate_cutlist(spec).parts}

    # Every drawer front: same width (X) and height (Z) in panel and part.
    for dr in plan.drawers:
        panel = panels[f"Drawer front {dr.index}"]
        part = parts[f"Drawer front #{dr.index}"]
        assert panel.size[0] == pytest.approx(part.length)   # face width
        assert panel.size[2] == pytest.approx(part.width)    # face height
        assert dr.width == pytest.approx(part.length)

    # Doors: the cut list rolls all leaves into one qty>=1 part; the geometry
    # places one panel per leaf. Counts and per-leaf dimensions must agree.
    door_panels = [p for lbl, p in panels.items()
                   if lbl == "Door" or lbl.startswith("Door ")]
    if plan.doors:
        part = parts["Door"]
        assert part.qty == len(door_panels) == len(plan.doors)
        for panel in door_panels:
            assert panel.size[0] == pytest.approx(part.width)    # door width
            assert panel.size[2] == pytest.approx(part.length)   # door height


def test_front_plan_is_pure_and_repeatable():
    # No hidden state: two calls on equal specs give identical layouts.
    a = front_plan(_spec(doors=2, drawers=[Drawer(150)]))
    b = front_plan(_spec(doors=2, drawers=[Drawer(150)]))
    assert [vars(i) for i in a.items] == [vars(i) for i in b.items]


# --- one shared material-usage-label vocabulary --------------------------
# The stock descriptions, finish face-count sets, and estimator price book all
# key off Part.material. They now reference the canonical labels in materials.py,
# so a rename can't silently desync them. These guards lock that in.

def test_material_label_tables_use_canonical_vocabulary():
    from woodworking_ai.materials import MATERIAL_LABELS
    from woodworking_ai.stock import STOCK_DESCRIPTIONS
    from woodworking_ai.finishing import _HIDDEN, _BOTH_FACES
    from woodworking_ai.estimator import PriceBook

    assert set(STOCK_DESCRIPTIONS) <= MATERIAL_LABELS
    assert _HIDDEN <= MATERIAL_LABELS
    assert _BOTH_FACES <= MATERIAL_LABELS
    assert set(PriceBook().sheet_price) <= MATERIAL_LABELS


def test_appliance_facet_tables_key_off_one_vocabulary():
    # Void widths (dsl), rough-in + clearance guidance (appliances) are separate
    # *facets* keyed by the same ApplianceType vocabulary. Guard that none drifts
    # to an unknown appliance type.
    from woodworking_ai.dsl import ApplianceType, APPLIANCE_VOID_WIDTHS
    from woodworking_ai.appliances import _ROUGH_IN, _CLEARANCES
    known = {t.value for t in ApplianceType}
    for table in (APPLIANCE_VOID_WIDTHS, _ROUGH_IN, _CLEARANCES):
        assert set(table) <= known, f"unknown appliance type in {set(table) - known}"


def test_llm_model_is_resolved_at_call_time(monkeypatch):
    # get_model() reads WOODAI_MODEL when called, not once at import.
    monkeypatch.delenv("WOODAI_MODEL", raising=False)
    assert llm.get_model() == llm.DEFAULT_MODEL
    monkeypatch.setenv("WOODAI_MODEL", "claude-sonnet-4-6")
    assert llm.get_model() == "claude-sonnet-4-6"


def test_llm_client_is_injectable(monkeypatch):
    # A fake client can be injected without the SDK or an API key, and the
    # requested model flows through to it.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    seen = {}

    class _Block:
        type = "text"
        text = "hello"

    class _Resp:
        content = [_Block()]

    class _Messages:
        def create(self, **kw):
            seen.update(kw)
            return _Resp()

    class _Fake:
        messages = _Messages()

    fake = _Fake()
    assert isinstance(fake, llm.LLMClient)
    llm.set_client(fake)
    try:
        out = llm.complete("sys", [{"role": "user", "content": "hi"}],
                           model="claude-haiku-4-5-20251001")
    finally:
        llm.set_client(None)
    assert out == "hello"
    assert seen["model"] == "claude-haiku-4-5-20251001"


def test_taxonomy_is_single_sourced():
    # KNOWN_KINDS, the loader, and dispatch.spec_kind must all derive from the
    # one LEAF_SPEC_TYPES registry — adding a furniture type is one row, not
    # three hand-synced ladders.
    from woodworking_ai.dsl import (
        LEAF_SPEC_TYPES, KNOWN_KINDS, _GROUP_KINDS, spec_from_dict,
    )
    from woodworking_ai.dispatch import spec_kind

    # 1) KNOWN_KINDS == every leaf kind + alias + the group/placeholder kinds.
    leaf_kinds = {k for kind, _c, al in LEAF_SPEC_TYPES for k in (kind, *al)}
    assert KNOWN_KINDS == leaf_kinds | set(_GROUP_KINDS)

    # 2) The loader builds the registered class for each canonical kind, and
    #    spec_kind round-trips that spec back to the same kind string.
    minimal = dict(name="X", width=600, height=720, depth=560)
    for kind, cls, _aliases in LEAF_SPEC_TYPES:
        spec = spec_from_dict({**minimal, "kind": kind})
        assert isinstance(spec, cls), f"{kind} loaded as {type(spec).__name__}"
        assert spec_kind(spec) == kind, f"{kind} dispatches as {spec_kind(spec)}"


def test_schema_hint_documents_every_taxonomy_kind():
    # Belt-and-suspenders with the existing schema-hint test: every canonical
    # leaf kind in the registry appears in the designer prompt.
    from woodworking_ai.dsl import LEAF_SPEC_TYPES, DSL_SCHEMA_HINT
    for kind, _cls, _aliases in LEAF_SPEC_TYPES:
        assert f'"{kind}"' in DSL_SCHEMA_HINT, f"{kind} missing from schema hint"


def test_door_panel_dims_single_source():
    # The 5-piece door cut list and the 3D model must derive from one helper so
    # they can't silently drift: the model tiles the *visible* opening, the cut
    # list saws that opening plus a groove tongue at each end.
    from woodworking_ai.partmath import door_panel_dims
    from woodworking_ai.constants import (
        DOOR_STILE_WIDTH, DOOR_RAIL_WIDTH, DOOR_PANEL_GROOVE,
    )

    w, h = 597.0, 716.0
    d = door_panel_dims(w, h)
    # Visible opening = leaf minus the frame members.
    assert d.opening_w == pytest.approx(w - 2 * DOOR_STILE_WIDTH)
    assert d.opening_h == pytest.approx(h - 2 * DOOR_RAIL_WIDTH)
    # Cut sizes = visible opening + a tongue each end. This *is* the 20mm the
    # model and cut list legitimately differ by — now defined in exactly one place.
    assert d.rail_length == pytest.approx(d.opening_w + 2 * DOOR_PANEL_GROOVE)
    assert d.panel_w == pytest.approx(d.opening_w + 2 * DOOR_PANEL_GROOVE)
    assert d.panel_h == pytest.approx(d.opening_h + 2 * DOOR_PANEL_GROOVE)


def test_door_cutlist_and_geometry_agree_via_helper():
    # End-to-end: for the same shaker door, the cut-list centre panel and the
    # geometry centre panel differ by exactly the groove tongue (2*groove) — the
    # model tiles the visible opening, the cut list saws the tongue too. This
    # locks the two consumers to the shared door_panel_dims relationship.
    from woodworking_ai.constants import DOOR_PANEL_GROOVE

    spec = _spec(doors=2, door_style="shaker")
    parts = {p.name: p for p in generate_cutlist(spec).parts}
    panels = {p.label: p for p in panel_layout(spec)}

    model_panel = next(p for lbl, p in panels.items() if lbl.startswith("Panel"))
    cut_panel = parts["Door panel"]
    # PanelBox.size is (X=width, thickness, Z=height); the cut Part is (length=Z,
    # width=X).
    assert cut_panel.width == pytest.approx(model_panel.size[0] + 2 * DOOR_PANEL_GROOVE)
    assert cut_panel.length == pytest.approx(model_panel.size[2] + 2 * DOOR_PANEL_GROOVE)


def test_legged_drawer_box_uses_shared_partmath_dims():
    # The legged-furniture drawer builder (nightstand/desk/workbench) must size
    # its box through partmath.drawer_box_dims — not a local clearance. This
    # guards against re-introducing the retired 13.0 side clearance / 25mm drop
    # (the canonical values are SLIDE_SIDE_CLEARANCE=12.7, DRAWER_BOX_HEIGHT_DROP=40).
    from woodworking_ai.cutlist import CutList
    from woodworking_ai.furniture_types import _drawer_cut_parts
    from woodworking_ai.partmath import drawer_box_dims
    from woodworking_ai.constants import MIN_DRAWER_BOX_WIDTH_3D

    opening_w, box_depth, front_h = 400.0, 300.0, 150.0
    cl = CutList(spec_name="t")
    _drawer_cut_parts(cl, 1, opening_w, box_depth, front_h)

    box_w, box_h, _ = drawer_box_dims(
        opening_w, front_h, box_depth, width_floor=MIN_DRAWER_BOX_WIDTH_3D)
    parts = {p.name: p for p in cl.parts}
    bt = 12.0
    assert parts["Drawer end"].length == pytest.approx(max(box_w - 2 * bt, 40.0))
    assert parts["Drawer side"].width == pytest.approx(box_h)
    # And the old 13.0-clearance width must NOT be what we produce.
    assert box_w != pytest.approx(max(opening_w - 2 * 13.0, 80.0))


def test_generated_part_materials_are_canonical():
    # Every material a real cut list produces is a canonical label (or a declared
    # physical form like "plywood"); none is an ad-hoc string.
    from woodworking_ai.materials import MATERIAL_LABELS, MATERIAL_FORMS
    spec = _spec(doors=2, drawers=[Drawer(150)], construction=Construction.FACE_FRAME)
    allowed = MATERIAL_LABELS | set(MATERIAL_FORMS)
    for p in generate_cutlist(spec).parts:
        assert p.material in allowed, f"non-canonical material {p.material!r}"
