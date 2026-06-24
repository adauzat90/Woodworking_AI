"""Regression tests for the shared helpers introduced in the tech-debt pass.

These lock in the de-duplications so the consolidated code paths cannot quietly
drift apart again: spec dimension properties, the single shelf-nester shared by
the estimator and the DXF export, the shared JSON extractor, and the expanded
designer schema hint.
"""

from woodworking_ai import (
    CabinetSpec, CabinetType, Material, ToeKick, Drawer, SheetSize, pack_sheets,
)
from woodworking_ai.dsl import DSL_SCHEMA_HINT
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
