"""Solid-wood glue-ups: panels become edge-glued boards priced by the foot."""

import math

from woodworking_ai.dsl import CabinetSpec, TableSpec
from woodworking_ai.cutlist import generate_cutlist, glue_up_boards
from woodworking_ai.estimator import estimate
from woodworking_ai.constants import GLUE_UP_BOARD_WIDTH


def test_glue_up_boards_splits_into_equal_boards():
    n, bw = glue_up_boards(600, board_width=140)
    assert n == math.ceil(600 / 140)
    assert bw * n == 600 or abs(bw * n - 600) < 1.0
    assert bw <= 140


def test_narrow_panel_needs_no_glue_up():
    n, bw = glue_up_boards(120, board_width=140)
    assert n == 1


def test_glue_up_cabinet_emits_solid_boards():
    spec = CabinetSpec(width=600, height=720, depth=560, doors=2, shelves=1,
                       panel_construction="glue_up")
    cl = generate_cutlist(spec)
    names = [p.name for p in cl.parts]
    assert any("board" in n.lower() for n in names), "panels become boards"
    assert any(p.material == "solid panel" for p in cl.parts)
    # Boards are solid lumber, so the cabinet now reports board feet.
    assert cl.total_board_feet > 0


def test_sheet_cabinet_unchanged_by_default():
    spec = CabinetSpec(width=600, height=720, depth=560, doors=2, shelves=1)
    cl = generate_cutlist(spec)
    assert not any("board" in p.name.lower() for p in cl.parts)
    assert all(p.material != "solid panel" for p in cl.parts)


def test_glue_up_cabinet_priced_as_lumber():
    spec = CabinetSpec(width=900, height=720, depth=560, doors=2,
                       panel_construction="glue_up")
    est = estimate(spec)
    assert est.lumber_cost > 0


def test_solid_table_top_is_edge_glued():
    cl = generate_cutlist(TableSpec(width=1400, depth=800, height=740))
    top = next(p for p in cl.parts if p.name.startswith("Top"))
    assert "glue" in top.notes.lower()
    assert top.qty >= 2
    assert top.width <= GLUE_UP_BOARD_WIDTH
