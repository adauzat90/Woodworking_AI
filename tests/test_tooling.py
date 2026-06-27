"""Shop tooling inventory: design only against the tools you own.

Covers the capability model (what each joint needs), feasible-substitute
selection, validator integration (infeasible joints flagged, never blocking),
the designer prompt constraint, ShopProfile round-trip, and the service bundle's
tool checklist.
"""

from woodworking_ai.dsl import TableSpec, Drawer, Joinery
from woodworking_ai.tooling import (
    ShopTooling, HAND_TOOL_SHOP, HOBBYIST_SHOP, can_make, substitute,
    required_operations, tooling_advisories, tools_needed, designer_constraint,
)
from woodworking_ai.validator import validate
from woodworking_ai.profile import ShopProfile, profile_from_dict, profile_to_dict
from woodworking_ai.service import build_result
from factories import cab as _cab


# --- capability model ------------------------------------------------------

def test_hand_shop_can_make_traditional_but_not_domino():
    assert can_make("dado", HAND_TOOL_SHOP)          # by hand
    assert can_make("dovetail", HAND_TOOL_SHOP)
    assert can_make("mortise_tenon", HAND_TOOL_SHOP)
    assert can_make("butt", HAND_TOOL_SHOP)          # glue only
    assert not can_make("domino", HAND_TOOL_SHOP)    # needs a Domino
    assert not can_make("pocket", HAND_TOOL_SHOP)    # needs a pocket jig
    assert not can_make("biscuit", HAND_TOOL_SHOP)


def test_hobbyist_shop_makes_dado_pocket_but_not_domino_or_dovetail_jig():
    assert can_make("dado", HOBBYIST_SHOP)
    assert can_make("pocket", HOBBYIST_SHOP)
    assert can_make("dowel", HOBBYIST_SHOP)
    assert not can_make("domino", HOBBYIST_SHOP)
    # No dovetail jig, but hand tools are on in the hobbyist preset.
    assert can_make("dovetail", HOBBYIST_SHOP)


def test_unknown_joint_is_not_blocked():
    assert can_make("space_laser", HAND_TOOL_SHOP)


def test_from_names_turns_everything_else_off():
    t = ShopTooling.from_names(["table_saw", "router"])
    assert t.table_saw and t.router
    assert not t.domino and not t.pocket_jig and not t.hand_tools


# --- substitution ----------------------------------------------------------

def test_substitute_picks_a_feasible_joint_for_the_role():
    # A shop with no Domino asked for a Domino carcass joint -> suggest one it can do.
    no_domino = ShopTooling.from_names(["hand_tools", "router", "drill"])
    alt = substitute("domino", "carcass", no_domino)
    assert alt is not None and can_make(alt, no_domino)


def test_substitute_none_when_joint_is_feasible():
    assert substitute("dado", "carcass", HOBBYIST_SHOP) is None


def test_drawer_role_substitute_avoids_dovetail_without_capability():
    only_ts = ShopTooling.from_names(["table_saw", "drill"])
    alt = substitute("dovetail", "drawer", only_ts)
    assert alt in ("box", "locking_rabbet", "rabbet", "dowel", "pocket", "butt")
    assert can_make(alt, only_ts)


# --- required operations walk ----------------------------------------------

def test_required_operations_lists_cabinet_joints_and_boring():
    spec = _cab(joinery="domino", drawers=[Drawer(front_height=140,
                                                  corner_joint="dovetail")])
    joints = {r.joint for r in required_operations(spec)}
    assert "domino" in joints           # carcass
    assert "dovetail" in joints         # drawer corner
    assert "hinge_cup" in joints        # has doors
    assert "shelf_pins" in joints       # has shelves


def test_required_operations_recurses_projects():
    from woodworking_ai.dsl import Project, Component
    proj = Project(name="run", components=[
        Component(spec=_cab(joinery="domino"), x=0, y=0, label="B1"),
    ])
    joints = {r.joint for r in required_operations(proj)}
    assert "domino" in joints


# --- validator integration -------------------------------------------------

def test_validate_flags_infeasible_joinery_as_warning_not_error():
    spec = _cab(joinery="domino")
    res = validate(spec, tooling=HAND_TOOL_SHOP)
    tw = [w for w in res.warnings if w.field == "tooling"]
    assert tw, "expected a tooling warning for a Domino joint in a hand shop"
    assert "switch to" in tw[0].message.lower()
    # Advisory only: the design is still buildable.
    assert res.ok


def test_validate_without_tooling_adds_no_tooling_warnings():
    spec = _cab(joinery="domino")
    res = validate(spec)
    assert not any(w.field == "tooling" for w in res.warnings)


def test_feasible_joinery_produces_no_tooling_warning():
    spec = _cab(joinery="dado",
                drawers=[Drawer(front_height=140, corner_joint="box")])
    # table_saw covers box joints; dado_set covers the dado; drill bores.
    res = validate(spec, tooling=HOBBYIST_SHOP)
    assert not any(w.field == "tooling" for w in res.warnings)


def test_table_joinery_checked_against_tooling():
    table = TableSpec(joinery="domino")
    res = validate(table, tooling=HAND_TOOL_SHOP)
    assert any(w.field == "tooling" for w in res.warnings)


def test_advisories_empty_when_tooling_none():
    assert tooling_advisories(_cab(), None) == []


# --- designer constraint ---------------------------------------------------

def test_designer_constraint_lists_owned_and_allowed_joints():
    text = designer_constraint(HAND_TOOL_SHOP)
    assert "TOOLING CONSTRAINT" in text
    assert "domino" not in text.lower().split("owns only")[-1].split("allowed")[0] \
        or "domino" not in text.lower()  # Domino never offered as allowed
    assert "slab" in text  # no router table -> slab doors


def test_designer_constraint_empty_without_tooling():
    assert designer_constraint(None) == ""


# --- profile round-trip ----------------------------------------------------

def test_profile_persists_tooling():
    prof = ShopProfile(tooling=HOBBYIST_SHOP)
    d = profile_to_dict(prof)
    assert isinstance(d["tooling"], dict)
    back = profile_from_dict(d)
    assert isinstance(back.tooling, ShopTooling)
    assert back.tooling.to_dict() == HOBBYIST_SHOP.to_dict()


def test_profile_tooling_defaults_none():
    prof = ShopProfile()
    assert prof.tooling is None
    assert profile_to_dict(prof)["tooling"] is None
    assert profile_from_dict(profile_to_dict(prof)).tooling is None


# --- service bundle --------------------------------------------------------

def test_build_result_marks_tools_owned_and_missing():
    spec = _cab(joinery=Joinery.DOMINO)   # enum, as from_dict would coerce
    bundle = build_result(spec, want_png=False, want_glb=False,
                          tooling=HAND_TOOL_SHOP)
    tools = bundle["tools"]
    assert tools, "expected a tools checklist"
    domino = [t for t in tools if "domino" in t["operation"].lower()]
    assert domino and domino[0]["owned"] is False
    # And a tooling warning surfaced in the bundle.
    assert any(w["field"] == "tooling" for w in bundle["warnings"])


def test_build_result_tools_owned_none_without_inventory():
    bundle = build_result(_cab(), want_png=False, want_glb=False)
    assert bundle["tools"]
    assert all(t["owned"] is None for t in bundle["tools"])


# --- new furniture types flow through the tooling walk ---------------------

def test_box_lists_corner_joint_and_lid_hinges():
    from woodworking_ai.dsl import spec_from_dict
    box = spec_from_dict({"kind": "box", "name": "Chest", "width": 500,
                          "height": 300, "depth": 350,
                          "corner_joint": "dovetail", "lid": True})
    joints = {r.joint for r in required_operations(box)}
    assert "dovetail" in joints and "butt_hinge" in joints
    # A drill-only shop can't cut dovetails — gets a feasible drawer-corner sub.
    only_drill = ShopTooling.from_names(["drill"])
    adv = tooling_advisories(box, only_drill)
    assert any("box corners" in m and "switch to" in m for _, _, m in adv)


def test_bench_lists_leg_apron_frame_joint():
    from woodworking_ai.dsl import spec_from_dict
    bench = spec_from_dict({"kind": "bench", "name": "Bench", "width": 1100,
                            "height": 450, "depth": 350, "joinery": "mortise_tenon"})
    reqs = required_operations(bench)
    assert reqs and reqs[0].role == "frame" and reqs[0].joint == "mortise_tenon"


def test_wall_shelf_cleat_needs_bevel_no_bogus_substitute():
    from woodworking_ai.dsl import spec_from_dict
    shelf = spec_from_dict({"kind": "wall_shelf", "name": "Shelf", "length": 800,
                            "depth": 250, "fixing": "french_cleat"})
    joints = {r.joint for r in required_operations(shelf)}
    assert "bevel_rip" in joints
    # No table saw / hand tools: flagged, but NOT told to "switch to" a joint.
    only_drill = ShopTooling.from_names(["drill"])
    adv = [m for _, _, m in tooling_advisories(shelf, only_drill)
           if "cleat" in m.lower()]
    assert adv and "switch to" not in adv[0]


def test_required_operations_handles_every_leaf_kind_without_crashing():
    """Regression: bed/frame/cutting_board lack a ``joinery`` field, so the old
    cabinet fall-through raised AttributeError on ``spec.joinery`` (degrading the
    drilling/build plan). Every leaf kind must dispatch and never read a missing
    field."""
    from woodworking_ai.dsl import spec_from_dict
    cases = {
        "bed": {"kind": "bed", "size": "queen"},
        "frame": {"kind": "frame", "opening_w": 400, "opening_h": 500},
        "cutting_board": {"kind": "cutting_board", "length": 450, "width": 300},
        "nightstand": {"kind": "nightstand", "drawers": 1},
        "desk": {"kind": "desk", "drawers": 1},
        "workbench": {"kind": "workbench", "vise": True},
    }
    for kind, d in cases.items():
        reqs = required_operations(spec_from_dict(d))  # must not raise
        assert isinstance(reqs, list), kind
    # The bed's head/foot are mortise-and-tenon frames; the legged pieces carry a
    # leg-to-apron frame joint — not a (non-existent) cabinet ``carcass`` joint.
    bed = required_operations(spec_from_dict({"kind": "bed", "size": "queen"}))
    assert any(r.role == "frame" and r.joint == "mortise_tenon" for r in bed)
    for kind in ("nightstand", "desk", "workbench"):
        reqs = required_operations(spec_from_dict({"kind": kind}))
        assert reqs and reqs[0].role == "frame"
        assert not any(r.role == "carcass" for r in reqs), kind
    # A picture frame's tool-gated joint is its mitered corner (frame_corner role).
    frame = required_operations(spec_from_dict(
        {"kind": "frame", "opening_w": 400, "opening_h": 500,
         "corner_joint": "half_lap"}))
    assert any(r.role == "frame_corner" and r.joint == "half_lap" for r in frame)


def test_frame_corner_joint_checked_against_tooling():
    """A picture/mirror frame's mitered corner is a tool-gated joint. The
    FrameJoint vocabulary (splined_miter/half_lap/miter) must be known to the
    capability tables, and an infeasible corner must be swapped for another
    *miter* corner — never a leg-to-apron mortise & tenon."""
    from woodworking_ai.dsl import spec_from_dict
    from woodworking_ai.tooling import can_make
    frame = spec_from_dict({"kind": "frame", "name": "Mirror", "opening_w": 500,
                            "opening_h": 700, "corner_joint": "splined_miter"})
    reqs = required_operations(frame)
    assert reqs and reqs[0].role == "frame_corner"
    assert reqs[0].joint == "splined_miter"
    # A full shop can cut the spline slot; a drill-only shop cannot.
    assert can_make("splined_miter", ShopTooling.from_names(["table_saw"]))
    only_drill = ShopTooling.from_names(["drill"])
    assert not can_make("splined_miter", only_drill)
    adv = tooling_advisories(frame, only_drill)
    msgs = [m for _, _, m in adv if "frame corners" in m]
    assert msgs, "drill-only shop should be warned it can't cut a splined miter"
    # The substitute is another miter corner, not a mortise & tenon.
    assert "switch to" in msgs[0] and "mortise" not in msgs[0].lower()
    # A hand-tool shop CAN cut a splined miter — no advisory.
    assert not tooling_advisories(frame, HAND_TOOL_SHOP)


def test_new_types_tools_needed_nonempty():
    from woodworking_ai.dsl import spec_from_dict
    for d in ({"kind": "box", "name": "B", "width": 400, "height": 250,
               "depth": 300, "lid": True},
              {"kind": "bench", "name": "Bn", "width": 1000, "height": 450,
               "depth": 320},
              {"kind": "wall_shelf", "name": "S", "length": 700, "depth": 220}):
        needs = tools_needed(spec_from_dict(d), HAND_TOOL_SHOP)
        assert needs, f"{d['kind']} should list tools"
