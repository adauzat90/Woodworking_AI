"""The LLM schema hint must advertise exactly the vocabulary the code accepts.

These guard against the hint drifting from the dataclasses/enums — the bug the
original review flagged (10 joinery values in code, 4 in the prompt).
"""

from woodworking_ai.dsl import (
    DSL_SCHEMA_HINT, CabinetType, Construction, BackStyle, Joinery,
    CornerJoint, DovetailTails, SlideType, Grain, TopFixing,
)

ALL_ENUMS = [CabinetType, Construction, BackStyle, Joinery,
             CornerJoint, DovetailTails, SlideType, Grain, TopFixing]


def test_every_enum_value_appears_in_hint():
    missing = [f"{e.__name__}.{m.value}"
               for e in ALL_ENUMS for m in e if m.value not in DSL_SCHEMA_HINT]
    assert not missing, f"schema hint omits: {missing}"


def test_hint_describes_both_cabinet_and_table():
    assert "== CABINET ==" in DSL_SCHEMA_HINT
    assert "== TABLE ==" in DSL_SCHEMA_HINT
    assert '"kind": "table"' in DSL_SCHEMA_HINT


def test_hint_mentions_imperial_units():
    assert '"units": "in"' in DSL_SCHEMA_HINT
