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


# --- C3: grain lock is honoured during cabinet nesting ----------------------

def test_length_grain_gable_never_rotates_even_when_rotation_would_fit():
    # A 2300x900 length-grain gable would fit a 1220-wide sheet only by rotating
    # (2300 along the 2440 length); the grain lock must forbid that rotation, so
    # it reports oversize instead of silently crossing the grain on a visible
    # face. The free (isotropic) pack of the same panel fits by rotating.
    sheet = SheetSize(length=2440, width=1220, kerf=0)
    free, free_over = pack([(900, 2300, "g", "none", "")], sheet)
    assert not free_over and free, "isotropic panel fits by rotating"
    locked, locked_over = pack([(900, 2300, "g", "length", "")], sheet)
    assert locked_over == ["g"], "length-grain gable is not rotated to fit"


def test_cabinet_gables_carry_length_grain_into_the_pack():
    from woodworking_ai import generate_cutlist
    spec = CabinetSpec(width=600, height=720, depth=560, doors=2)
    cl = generate_cutlist(spec)
    side = next(p for p in cl.parts if p.name == "Side")
    assert side.grain == "length", "gable grain must run along its height"
    # And the lock survives into a placed nest: the gable keeps length>=width
    # in the orientation chosen for it (never rotated to width-along-length).
    sheet = SheetSize(length=2440, width=1220, kerf=0)
    placed, _ = pack([(side.length, side.width, "Side", side.grain, "")], sheet)
    (_, _, l, w, _) = placed[0][0]
    assert (l, w) == (side.length, side.width)
