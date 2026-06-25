"""A3 joinery / machining feasibility checks (analytic, no CAD).

Four hazards the envelope/sag checks miss, surfaced by the validator and folded
into the Critic's structured findings:

1. hinge-cup blow-through (depth axis): too little material behind a 35mm cup;
2. a housed joint cut too near a panel end (short-grain blow-out);
3. a drawer-slide screw line colliding with a shelf-pin row on a side panel;
4. a grooved back whose groove interferes with the back rabbet/recess.
"""

from woodworking_ai import CabinetSpec, Material, ToeKick, Drawer, validate
from woodworking_ai.dsl import BackStyle
from woodworking_ai.validator import _joinery_feasibility
from woodworking_ai.agents.critic import critique


def cab(**o) -> CabinetSpec:
    d = dict(name="C", width=600, height=720, depth=560,
             material=Material(carcass=18, back=6, door=18, shelf=18),
             toe_kick=ToeKick(height=100, setback=50),
             shelves=1, doors=2, drawers=[], reveal=3)
    d.update(o)
    return CabinetSpec(**d)


def _fields(spec):
    return {i.field for i in _joinery_feasibility(spec)}


# --- 1) hinge-cup blow-through (depth axis) -------------------------------

def test_thin_door_blows_through_cup():
    # A 15mm door with a 35mm cup: 15 - 12.5 = 2.5mm backing < 3mm minimum.
    spec = cab(material=Material(carcass=18, back=6, door=15, shelf=18))
    res = validate(spec)
    assert not res.ok
    assert any(e.field == "material.door" and "blows through" in e.message
               for e in res.errors)


def test_blow_through_surfaces_in_critic():
    spec = cab(material=Material(carcass=18, back=6, door=15, shelf=18))
    crit = critique(spec)
    assert not crit.ok
    assert any(i.kind == "joinery" and "blows through" in i.message
               for i in crit.errors)


def test_thick_door_hosts_cup_cleanly():
    spec = cab(material=Material(carcass=18, back=6, door=18, shelf=18))
    assert not any(e.field == "material.door" for e in validate(spec).errors)


# --- 2) housed joint too near a panel end ---------------------------------

def test_grooved_back_short_grain_warns():
    # A grooved back is housed 12mm in from the rear edge of an 18mm side —
    # under ~1x the stock, so the short-grain ledge can blow out.
    spec = cab(back=BackStyle.GROOVED)
    warns = [w for w in validate(spec).warnings if w.field == "joinery"]
    assert any("blow out" in w.message or "blow-out" in w.message for w in warns)


def test_rabbeted_back_has_no_short_grain_warning():
    # The default rabbeted back captures the back at the rear edge — no
    # short-grain ledge to split, so no joinery warning.
    spec = cab(back=BackStyle.RABBETED)
    assert "joinery" not in _fields(spec)


# --- 3) drawer-slide line vs. shelf-pin row collision ---------------------

def test_slide_line_collides_with_pin_row():
    # A drawer whose slide line lands in the shelf-pin band on the side panel.
    spec = cab(height=900, shelves=3, doors=0,
               drawers=[Drawer(front_height=180)])
    warns = [w for w in validate(spec).warnings
             if w.field == "drawers" and "pilots collide" in w.message]
    assert warns


def test_no_pins_no_slide_collision():
    # No shelves => no pin rows => nothing for the slide line to collide with.
    spec = cab(height=900, shelves=0, doors=0,
               drawers=[Drawer(front_height=180)])
    assert not any("pilots collide" in w.message for w in validate(spec).warnings)


# --- 4) grooved back vs. back rabbet/recess interference ------------------

def test_grooved_back_groove_recess_interference_warns():
    spec = cab(back=BackStyle.GROOVED)
    warns = [w for w in validate(spec).warnings
             if w.field == "back" and "interfere" in w.message]
    assert warns


# --- clean, well-proportioned cabinet produces none of these --------------

def test_clean_cabinet_has_no_joinery_feasibility_findings():
    spec = cab(width=600, height=720, depth=560, shelves=1, doors=2,
               back=BackStyle.RABBETED,
               material=Material(carcass=18, back=6, door=18, shelf=18))
    assert _joinery_feasibility(spec) == []
    crit = critique(spec)
    assert crit.ok
    assert not [i for i in crit.issues if i.kind == "joinery"]


def test_clean_cabinet_with_drawers_no_collision():
    # Drawers but no shelves above them — a common, clean base config.
    spec = cab(width=600, height=720, depth=560, shelves=0, doors=0,
               drawers=[Drawer(front_height=180), Drawer(front_height=180)])
    assert _joinery_feasibility(spec) == []
