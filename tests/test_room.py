"""Room-aware planning: wall fit, filler sizing, scribe allowances."""

from woodworking_ai.room import Wall, Room, fit_run, scribe_plan, plan_wall


def test_fit_run_reports_the_gap():
    fit = fit_run([600, 600, 900], 2400)
    assert fit["total"] == 2100
    assert fit["gap"] == 300
    assert fit["fits"] and fit["filler_width"] == 300


def test_overrun_does_not_fit():
    fit = fit_run([900, 900, 900], 2400)
    assert not fit["fits"]
    assert fit["overrun"] == 300


def test_plan_wall_recommends_a_filler():
    plan = plan_wall([600, 600], Wall(length=1300))
    assert plan["fillers"] == [{"kind": "filler", "width": 100.0, "side": "right"}]


def test_plan_wall_errors_when_run_too_long():
    plan = plan_wall([900, 900], Wall(length=1500))
    assert any(sev == "error" for (sev, _f, _m) in plan["issues"])


def test_exact_fit_warns_to_leave_a_filler():
    plan = plan_wall([600, 600], Wall(length=1200))
    assert any("filler" in f for (_s, f, _m) in plan["issues"])


def test_scribe_plan_flags_out_of_square_and_level():
    room = Room(out_of_square=6, floor_drop=8)
    sp = scribe_plan(room)
    assert any("out of square" in n for n in sp["notes"])
    assert any("drops" in n for n in sp["notes"])


def test_room_roundtrip():
    room = Room(name="Kitchen", floor_drop=8, out_of_square=6,
                walls=[Wall(length=3658, obstacles=[
                    {"kind": "window", "start": 1200, "width": 900, "sill": 1100}])])
    back = Room.from_dict(room.to_dict())
    assert back.walls[0].length == 3658
    assert back.walls[0].obstacles[0].kind == "window"


def test_wide_gap_warns_to_add_a_cabinet():
    plan = plan_wall([600], Wall(length=900))
    assert any("wide" in m for (_s, _f, m) in plan["issues"])
