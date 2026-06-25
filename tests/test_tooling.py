"""Shop tooling inventory: design only against the tools you own.

Covers the capability model (what each joint needs), feasible-substitute
selection, validator integration (infeasible joints flagged, never blocking),
the designer prompt constraint, ShopProfile round-trip, and the service bundle's
tool checklist.
"""

from woodworking_ai.dsl import CabinetSpec, TableSpec, Drawer, Material, Joinery
from woodworking_ai import tooling as T
from woodworking_ai.tooling import (
    ShopTooling, HAND_TOOL_SHOP, HOBBYIST_SHOP, FULL_SHOP,
    can_make, substitute, required_operations, tooling_advisories,
    tools_needed, designer_constraint,
)
from woodworking_ai.validator import validate
from woodworking_ai.profile import ShopProfile, profile_from_dict, profile_to_dict
from woodworking_ai.service import build_result


def _cab(**kw):
    base = dict(width=600, height=720, depth=560, doors=2, shelves=1)
    base.update(kw)
    return CabinetSpec(**base)


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
