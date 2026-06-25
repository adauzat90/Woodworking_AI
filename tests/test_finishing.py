"""Finishing schedule + cost."""

from woodworking_ai.dsl import CabinetSpec
from woodworking_ai.finishing import finishing_schedule, finish_area_m2
from woodworking_ai.estimator import estimate


def _cab(finish="none"):
    return CabinetSpec(width=600, height=720, depth=560, doors=2, shelves=1,
                       finish=finish)


def test_no_finish_has_zero_coats_and_cost():
    sched = finishing_schedule(_cab("none"))
    assert sched["coats"] == 0 and sched["area_m2"] == 0
    assert estimate(_cab("none")).finish_cost == 0


def test_clear_finish_has_grits_and_coats():
    sched = finishing_schedule(_cab("clear"))
    assert sched["grits"] and sched["coats"] == 3
    assert sched["area_m2"] > 0
    assert sched["litres"] > 0


def test_finish_area_excludes_hidden_parts():
    # Adding a finish doesn't change geometry, so the area is stable; it should
    # be a positive, sane number of square metres for a 600mm cabinet.
    area = finish_area_m2(_cab("clear"))
    assert 1.0 < area < 12.0


def test_finish_adds_to_the_quote_total():
    plain = estimate(_cab("none"))
    finished = estimate(_cab("clear"))
    assert finished.finish_cost > 0
    assert finished.total > plain.total
    assert abs(finished.total - plain.total - finished.finish_cost) < 0.01


def test_more_coats_costs_more():
    clear = estimate(_cab("clear"))        # 3 coats
    oil = estimate(_cab("oil"))            # 2 coats
    assert clear.finish_cost > oil.finish_cost


def test_schedule_steps_mention_sanding_and_coats():
    steps = finishing_schedule(_cab("stain_clear"))["steps"]
    assert any("Sand" in s for s in steps)
    assert any("Stain" in s or "topcoat" in s for s in steps)
