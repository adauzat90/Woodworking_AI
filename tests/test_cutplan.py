"""H2 — "build from the lumber I already have": cut plan from owned boards.

Covers the generalised single-bin packer, assignment correctness, grain
alignment, kerf accounting, the shortfall path, and a board too small to hold
any part.
"""

from woodworking_ai.packing import pack_into_bin, pack
from woodworking_ai.estimator import SheetSize
from woodworking_ai.cutplan import (
    StockBoard, CutPlan, cut_plan, boards_from_dicts, boards_to_dicts,
    cutplan_dxf,
)
from woodworking_ai.cutlist import CutList, Part, generate_cutlist
from woodworking_ai.dsl import CabinetSpec, Drawer
from woodworking_ai import service


# --- the generalised packer, tested directly --------------------------------

def test_pack_into_bin_places_what_fits():
    placed, leftover, oversize = pack_into_bin(
        [(1000, 200, "a", "none", ""), (1000, 200, "b", "none", "")],
        2400, 400, kerf=0)
    assert len(placed) == 2 and not leftover and not oversize


def test_pack_into_bin_leftover_when_full():
    # Three 1000-long parts on a 1-shelf bin only 2400 long, 200 tall: only two
    # fit the single shelf; the bin is too short (200) for a second shelf.
    placed, leftover, oversize = pack_into_bin(
        [(1000, 200, "a", "none", ""), (1000, 200, "b", "none", ""),
         (1000, 200, "c", "none", "")],
        2400, 200, kerf=0)
    assert len(placed) == 2
    assert leftover == ["c"] and not oversize


def test_pack_into_bin_oversize_is_separate_from_leftover():
    placed, leftover, oversize = pack_into_bin(
        [(5000, 200, "big", "none", "")], 2400, 1200, kerf=0)
    assert not placed and not leftover and oversize == ["big"]


def test_pack_into_bin_is_kerf_aware():
    # Two 1200-long parts exactly fill a 2400 bin with no kerf...
    placed, leftover, _ = pack_into_bin(
        [(1200, 100, "a", "none", ""), (1200, 100, "b", "none", "")],
        2400, 100, kerf=0)
    assert len(placed) == 2 and not leftover
    # ...but a 5mm kerf pushes the second past the end (1200+5+1200 > 2400) and
    # the 100-tall bin has no room for a second shelf.
    placed, leftover, _ = pack_into_bin(
        [(1200, 100, "a", "none", ""), (1200, 100, "b", "none", "")],
        2400, 100, kerf=5)
    assert len(placed) == 1 and leftover == ["b"]


def test_pack_into_bin_arbitrary_size_matches_full_sheet_pack():
    # A bin the size of a standard sheet places the same single part the
    # original sheet packer does (the generalisation keeps existing behaviour).
    items = [(620, 560, "side", "length", "")]
    placed, _, _ = pack_into_bin(items, 2440, 1220, kerf=3)
    sheet = SheetSize(length=2440, width=1220, kerf=3)
    sheets, _ = pack(items, sheet)
    assert placed[0][2:4] == sheets[0][0][2:4]   # same (length, width) chosen


def test_existing_pack_unchanged():
    # The original multi-sheet packer must still spill onto extra sheets.
    sheet = SheetSize(length=2440, width=1220, kerf=0)
    items = [(2400, 1200, f"p{i}", "none", "") for i in range(3)]
    sheets, oversize = pack(items, sheet)
    assert len(sheets) == 3 and not oversize


# --- StockBoard (de)serialisation -------------------------------------------

def test_stockboard_round_trip():
    b = StockBoard(length=2440, width=300, thickness=20.6, species="walnut",
                   form="solid", qty=3, id="walnut 8/4")
    b2 = StockBoard.from_dict(b.to_dict())
    assert b2 == b


def test_boards_from_dicts_tolerates_partial_and_wrapper():
    boards = boards_from_dicts([{"length": 1000, "width": 200, "thickness": 18}])
    assert boards[0].qty == 1 and boards[0].species == ""
    wrapped = boards_from_dicts({"boards": [{"length": 1000, "width": 200,
                                             "thickness": 18, "qty": "2"}]})
    assert wrapped[0].qty == 2
    assert boards_to_dicts(boards)[0]["length"] == 1000


# --- assignment correctness -------------------------------------------------

def test_parts_assigned_to_matching_board():
    spec = CabinetSpec(width=600, height=720, depth=560, doors=2)
    cl = generate_cutlist(spec)
    sheet_parts = [p for p in cl.parts if not p.is_solid_lumber
                   and p.thickness == 18.0]
    n_pieces = sum(p.qty for p in sheet_parts)
    # Plenty of 18mm boards; everything 18mm should be placed, none lost.
    boards = [StockBoard(length=2440, width=1220, thickness=18.0, qty=10)]
    plan = cut_plan(spec, boards)
    placed_18 = [pp for bp in plan.boards for pp in bp.placements]
    assert len(placed_18) == n_pieces
    # Every placement sits inside its board.
    for bp in plan.boards:
        for p in bp.placements:
            assert p.x + p.length <= bp.board.length + 1e-6
            assert p.y + p.width <= bp.board.width + 1e-6


def test_thickness_grouping_isolates_stock():
    # An 18mm board cannot hold a 6mm back panel -> that part falls to shortfall.
    spec = CabinetSpec(width=600, height=720, depth=560, doors=2)
    boards = [StockBoard(length=2440, width=1220, thickness=18.0, qty=10)]
    plan = cut_plan(spec, boards)
    short_labels = [s.label for s in plan.shortfall]
    assert any("Back" in s for s in short_labels)
    assert all(s.thickness != 18.0 for s in plan.shortfall)


def test_species_and_form_filter_assignment():
    # A walnut-solid part only goes on a walnut-solid board; an oak board of the
    # right thickness is rejected for it.
    parts = [Part("Leg", 4, length=700, width=60, thickness=60.0,
                  material="leg", form="solid", species="walnut")]
    cl = CutList(spec_name="t", parts=parts)
    oak = StockBoard(length=2400, width=200, thickness=60.0, form="solid",
                     species="oak", qty=4)
    plan = cut_plan(cl, [oak])
    assert plan.placed_count == 0 and len(plan.shortfall) == 4
    assert plan.shortfall[0].reason == "no matching board"
    walnut = StockBoard(length=2400, width=200, thickness=60.0, form="solid",
                        species="walnut", qty=4)
    plan2 = cut_plan(cl, [walnut])
    assert plan2.placed_count == 4 and plan2.complete


# --- grain alignment --------------------------------------------------------

def test_grain_aligned_along_board_length():
    # A length-grained part on a narrow board: its length must run with the
    # board length (never rotated across the grain).
    part = Part("Gable", 1, length=2000, width=300, thickness=18.0,
                grain="length")
    cl = CutList(spec_name="g", parts=[part])
    board = StockBoard(length=2440, width=1220, thickness=18.0)
    plan = cut_plan(cl, [board])
    p = plan.boards[0].placements[0]
    assert (p.length, p.width) == (2000.0, 300.0)


def test_grain_lock_can_force_shortfall():
    # A 1000-long, 1300-wide length-grain part keeps its orientation, so its
    # 1300 width must run across the 1220-wide board -> oversize -> shortfall.
    # The same part free to rotate orients its 1300 along the board length and
    # fits.
    grained = Part("Panel", 1, length=1000, width=1300, thickness=18.0,
                   grain="length")
    cl = CutList(spec_name="x", parts=[grained])
    board = StockBoard(length=2440, width=1220, thickness=18.0)
    plan = cut_plan(cl, [board])
    assert plan.placed_count == 0 and len(plan.shortfall) == 1
    assert plan.shortfall[0].reason == "too big for every board"

    free = Part("Panel", 1, length=1000, width=1300, thickness=18.0,
                grain="none")
    plan2 = cut_plan(CutList(spec_name="x", parts=[free]), [board])
    assert plan2.placed_count == 1 and plan2.complete


# --- kerf accounting --------------------------------------------------------

def test_kerf_reduces_what_fits_on_a_board():
    # Two parts that exactly fill the board length only both fit with no kerf.
    parts = [Part("A", 1, length=1220, width=300, thickness=18.0, grain="none"),
             Part("B", 1, length=1220, width=300, thickness=18.0, grain="none")]
    cl = CutList(spec_name="k", parts=parts)
    board = StockBoard(length=2440, width=300, thickness=18.0)
    assert cut_plan(cl, [board], kerf=0).placed_count == 2
    plan = cut_plan(cl, [board], kerf=5)
    assert plan.placed_count == 1 and len(plan.shortfall) == 1


# --- shortfall path & rollover ----------------------------------------------

def test_shortfall_when_not_enough_board():
    # One small board can hold only some parts; the rest are a shortfall.
    parts = [Part("Panel", 6, length=1000, width=400, thickness=18.0,
                  grain="none")]
    cl = CutList(spec_name="s", parts=parts)
    board = StockBoard(length=1000, width=850, thickness=18.0)  # holds 2 (kerf)
    plan = cut_plan(cl, [board])
    assert plan.placed_count == 2
    assert len(plan.shortfall) == 4
    assert all(s.reason == "too big for every board" for s in plan.shortfall)
    assert not plan.complete


def test_parts_roll_over_to_next_matching_board():
    parts = [Part("Panel", 4, length=1000, width=400, thickness=18.0,
                  grain="none")]
    cl = CutList(spec_name="r", parts=parts)
    boards = [StockBoard(length=1000, width=850, thickness=18.0, qty=2)]  # 2 each
    plan = cut_plan(cl, boards)
    assert plan.placed_count == 4 and plan.complete
    assert plan.boards_used == 2


# --- board too small to hold any part ---------------------------------------

def test_board_too_small_holds_nothing():
    parts = [Part("Panel", 2, length=1000, width=400, thickness=18.0,
                  grain="none")]
    cl = CutList(spec_name="tiny", parts=parts)
    tiny = StockBoard(length=200, width=100, thickness=18.0)
    plan = cut_plan(cl, [tiny])
    assert plan.placed_count == 0
    assert plan.boards_used == 0
    assert len(plan.shortfall) == 2
    assert all(s.reason == "too big for every board" for s in plan.shortfall)


def test_no_boards_at_all_is_all_shortfall():
    spec = CabinetSpec(width=600, height=720, depth=560, doors=2)
    plan = cut_plan(spec, [])
    assert plan.placed_count == 0 and not plan.complete
    assert all(s.reason == "no matching board" for s in plan.shortfall)


# --- yield / offcuts --------------------------------------------------------

def test_yield_and_offcut_consistency():
    parts = [Part("Panel", 1, length=1220, width=610, thickness=18.0,
                  grain="none")]   # exactly a quarter of a 2440x1220 board
    cl = CutList(spec_name="y", parts=parts)
    board = StockBoard(length=2440, width=1220, thickness=18.0)
    plan = cut_plan(cl, [board])
    bp = plan.boards[0]
    assert abs(bp.yield_pct - 0.25) < 0.01
    assert abs(bp.used_area_m2 + bp.offcut_area_m2 - board.area_m2) < 1e-6
    assert abs(plan.yield_pct - 0.25) < 0.01


# --- reports & service wiring ------------------------------------------------

def test_report_text_and_csv():
    spec = CabinetSpec(width=600, height=720, depth=560, doors=2)
    boards = [StockBoard(length=2440, width=1220, thickness=18.0, qty=4)]
    plan = cut_plan(spec, boards)
    txt = plan.report_text()
    assert "Cut plan from stock" in txt
    csv = plan.to_csv()
    header, *rows = csv.splitlines()
    assert header.startswith("board,instance,part_id,part")
    assert any(",placed" in r for r in rows)
    # Back panel (6mm) has no matching 18mm board -> a shortfall row.
    assert any(",shortfall" in r for r in rows)


def test_cutplan_dxf_renders_used_boards():
    spec = CabinetSpec(width=600, height=720, depth=560, doors=2)
    boards = [StockBoard(length=2440, width=1220, thickness=18.0, qty=4)]
    dxf = cutplan_dxf(cut_plan(spec, boards))
    assert dxf.startswith("0\nSECTION")
    assert dxf.rstrip().endswith("EOF")
    assert "SHORTFALL" in dxf   # the 6mm back panel


def test_service_cutplan_result_shape():
    spec = CabinetSpec(width=600, height=720, depth=560, doors=2)
    boards = [{"length": 2440, "width": 1220, "thickness": 18.0, "qty": 4}]
    res = service.cutplan_result(spec, boards)
    assert res["placed_count"] > 0
    assert res["boards"] and "placements" in res["boards"][0]
    assert res["shortfall"]   # 6mm back


def test_build_result_embeds_cutplan_only_when_boards_given():
    spec = CabinetSpec(width=600, height=720, depth=560, doors=2)
    base = service.build_result(spec, want_png=False, want_glb=False)
    assert "cutplan" not in base
    with_stock = service.build_result(
        spec, want_png=False, want_glb=False,
        boards=[{"length": 2440, "width": 1220, "thickness": 18.0, "qty": 4}])
    assert "cutplan" in with_stock
    assert with_stock["cutplan"]["placed_count"] > 0
