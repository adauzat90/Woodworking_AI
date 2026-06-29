"""Ergonomic dimension rules (Tier 3 #7): DIM-003 seat height, DIM-004 seat↔top
coupling, DIM-005 desk height/depth, DIM-006 knee clearance under an apron."""

from __future__ import annotations

from woodworking_ai import spec_from_dict, validate


def _desk(**kw):
    base = dict(kind="desk", width=1200, depth=600, height=730, top_thickness=25,
                leg=60, apron_height=80, apron_thickness=20, leg_inset=40)
    base.update(kw)
    return base


def _bench(**kw):
    base = dict(kind="bench", width=1000, depth=350, height=450, top_thickness=40,
                leg=60, apron_height=70, apron_thickness=20, leg_inset=40)
    base.update(kw)
    return base


def _table(**kw):
    base = dict(kind="table", width=1400, depth=800, height=740, top_thickness=25,
                leg=70, apron_height=90, apron_thickness=25, leg_inset=50)
    base.update(kw)
    return base


def _val(spec_dict):
    return validate(spec_from_dict(spec_dict))


def _project(*spec_dicts):
    comps = [{"label": f"C{i}", "x": i * 2000, "y": 0, "spec": s}
             for i, s in enumerate(spec_dicts)]
    return spec_from_dict(dict(kind="project", components=comps))


# --- DIM-005 desk ----------------------------------------------------------

def test_dim005_flags_low_desk_and_shallow_depth():
    r = _val(_desk(height=600, depth=450))
    dim005 = r.by_rule("DIM-005")
    assert {i.field for i in dim005} == {"height", "depth"}
    low = next(i for i in dim005 if i.field == "height")
    assert low.direction == "min" and low.observed == 600 and low.units == "mm"


def test_dim005_quiet_for_a_standard_desk():
    assert _val(_desk(height=730, depth=600)).by_rule("DIM-005") == []


# --- DIM-006 knee clearance ------------------------------------------------

def test_dim006_flags_a_deep_apron_on_a_sit_at_surface():
    r = _val(_table(height=740, apron_height=200))
    knee = r.by_rule("DIM-006")
    assert len(knee) == 1
    assert knee[0].severity == "info" and knee[0].direction == "min"


def test_dim006_quiet_below_sit_at_height():
    # A coffee table isn't sat at, so a low apron underside is fine.
    assert _val(_table(height=450, apron_height=120)).by_rule("DIM-006") == []


# --- DIM-003 seat height ---------------------------------------------------

def test_dim003_flags_unusual_seat_height():
    r = _val(_bench(height=850))
    seat = r.by_rule("DIM-003")
    assert len(seat) == 1
    assert seat[0].direction == "max" and seat[0].observed == 850.0


def test_dim003_quiet_for_a_normal_bench():
    assert _val(_bench(height=450)).by_rule("DIM-003") == []


# --- DIM-004 seat ↔ top coupling -------------------------------------------

def test_dim004_warns_when_seat_and_top_are_mismatched():
    proj = _project(_table(height=740), _bench(height=700))  # 40mm gap, too small
    dim004 = validate(proj).by_rule("DIM-004")
    assert len(dim004) == 1
    assert dim004[0].severity == "warning"       # advisory, not the catalog's ERROR
    assert "S" not in dim004[0].field or dim004[0].field.endswith(".height")
    assert dim004[0].observed == 40 and dim004[0].direction == "target"


def test_dim004_quiet_for_a_comfortable_pairing():
    proj = _project(_table(height=740), _bench(height=460))  # 280mm gap, ideal
    assert validate(proj).by_rule("DIM-004") == []


def test_dim004_best_fit_avoids_cross_flagging_in_a_mixed_project():
    # A counter + bar stools (gap ~250) AND a dining table + chairs (gap ~280):
    # each seat's best-matched table is comfortable, so nothing fires even though
    # cross-pairing (dining table vs bar stool) would be wildly off.
    counter = _table(height=910)
    bar_stool = _bench(height=660)        # 910-660 = 250, comfortable
    dining = _table(height=740)
    chair = _bench(height=460)            # 740-460 = 280, comfortable
    proj = _project(counter, bar_stool, dining, chair)
    assert validate(proj).by_rule("DIM-004") == []


def test_dim004_ignores_a_coffee_table_as_a_pairing_target():
    # A coffee/side table (below sit-at height) isn't sat at, so a bench beside
    # one in a living-room layout isn't an ergonomic mismatch.
    proj = _project(_table(height=450, apron_height=60), _bench(height=450))
    assert validate(proj).by_rule("DIM-004") == []


def test_dim004_needs_both_a_table_and_a_seat():
    assert validate(_project(_table(height=740), _table(height=900))) \
        .by_rule("DIM-004") == []
    assert validate(_project(_bench(height=700), _bench(height=720))) \
        .by_rule("DIM-004") == []
