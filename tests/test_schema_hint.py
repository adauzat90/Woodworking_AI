"""The LLM schema hint must advertise exactly the vocabulary the code accepts.

These guard against the hint drifting from the dataclasses/enums — the bug the
original review flagged (10 joinery values in code, 4 in the prompt).
"""

from woodworking_ai.dsl import (
    DSL_SCHEMA_HINT, CabinetType, Construction, BackStyle, Joinery,
    CornerJoint, DovetailTails, SlideType, Grain, TopFixing, ShelfFixing,
)

ALL_ENUMS = [CabinetType, Construction, BackStyle, Joinery,
             CornerJoint, DovetailTails, SlideType, Grain, TopFixing,
             ShelfFixing]


def test_every_enum_value_appears_in_hint():
    missing = [f"{e.__name__}.{m.value}"
               for e in ALL_ENUMS for m in e if m.value not in DSL_SCHEMA_HINT]
    assert not missing, f"schema hint omits: {missing}"


def test_hint_describes_both_cabinet_and_table():
    assert "== CABINET ==" in DSL_SCHEMA_HINT
    assert "== TABLE ==" in DSL_SCHEMA_HINT
    assert '"kind": "table"' in DSL_SCHEMA_HINT


def test_hint_describes_wall_shelf_box_and_bench():
    assert "== WALL SHELF ==" in DSL_SCHEMA_HINT
    assert '"kind": "wall_shelf"' in DSL_SCHEMA_HINT
    assert "== BOX / CHEST ==" in DSL_SCHEMA_HINT
    assert '"kind": "box"' in DSL_SCHEMA_HINT
    assert "== BENCH / STOOL ==" in DSL_SCHEMA_HINT
    assert '"kind": "bench"' in DSL_SCHEMA_HINT


def test_hint_mentions_imperial_units():
    assert '"units": "in"' in DSL_SCHEMA_HINT


def test_hint_leads_with_pick_kind_step():
    # The preamble tells the model to choose `kind` before filling fields.
    assert "STEP 1" in DSL_SCHEMA_HINT
    assert "choose the \"kind\" first" in DSL_SCHEMA_HINT


def test_hint_carries_a_minimal_example_per_kind():
    for kind in ("cabinet", "table", "wall_shelf", "box", "bench", "project"):
        assert f'"kind": "{kind}"' in DSL_SCHEMA_HINT, kind
    # The project example uses the declarative run form.
    assert '"runs"' in DSL_SCHEMA_HINT


def test_hint_explains_appliance_hosting_split():
    assert '"kind": "appliance_void"' in DSL_SCHEMA_HINT
    assert '"kind": "appliance"' in DSL_SCHEMA_HINT
