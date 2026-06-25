"""Grain-aware nesting: locked parts never rotate; fronts stay in sequence."""

from woodworking_ai.packing import pack
from woodworking_ai.estimator import SheetSize, estimate
from woodworking_ai.dsl import CabinetSpec, Drawer


def test_length_grain_part_is_not_rotated():
    sheet = SheetSize(length=2440, width=1220, kerf=0)
    # A tall narrow part: free packing would rotate it (longest along length);
    # length-grain locks it upright.
    placed, oversize = pack([(2000, 300, "gable", "length", "")], sheet)
    assert not oversize
    (x, y, l, w, label) = placed[0][0]
    assert (l, w) == (2000, 300), "length-grain part must keep its orientation"


def test_free_part_is_oriented_longest_along_length():
    sheet = SheetSize(length=2440, width=1220, kerf=0)
    placed, _ = pack([(300, 2000, "iso", "none", "")], sheet)
    (x, y, l, w, label) = placed[0][0]
    assert (l, w) == (2000, 300), "free part orients longest-side-along-length"


def test_width_grain_runs_along_sheet_length():
    sheet = SheetSize(length=2440, width=1220, kerf=0)
    placed, _ = pack([(300, 800, "panel", "width", "")], sheet)
    (x, y, l, w, label) = placed[0][0]
    assert (l, w) == (800, 300), "width-grain rotates so grain runs along sheet"


def test_grain_lock_can_increase_sheet_count():
    # A part 1300 long, 1000 wide on a 1220-wide sheet: free packing rotates it
    # to fit (1300 along the 2440 length); length-grain forbids that.
    sheet = SheetSize(length=2440, width=1220, kerf=0)
    free, free_over = pack([(1000, 1300, "p", "none", "")], sheet)
    assert not free_over and free, "free part fits by rotating"
    locked, locked_over = pack([(1000, 1300, "p", "length", "")], sheet)
    assert locked_over == ["p"], "length-grain part is oversize (would cross grain)"


def test_fronts_kept_contiguous_in_sequence():
    sheet = SheetSize(length=2440, width=1220, kerf=0)
    items = [
        (400, 200, "F1", "length", "front"),
        (900, 700, "BIG", "none", ""),       # tall: height sort would jump it first
        (400, 200, "F2", "length", "front"),
    ]
    placed, _ = pack(items, sheet)
    flat = [lbl for shelf in placed for (_, _, _, _, lbl) in shelf]
    assert flat.index("F1") < flat.index("F2"), "fronts keep input order"
    assert flat.index("F2") == flat.index("F1") + 1, "fronts stay contiguous"


def test_estimate_still_produces_sheets_for_a_cabinet():
    spec = CabinetSpec(width=800, height=720, depth=560, doors=2, shelves=2,
                       drawers=[Drawer(front_height=150)])
    est = estimate(spec)
    assert est.total_sheets >= 1
