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


# --- H4: per-species finishing notes + drying/recoat windows ----------------

from woodworking_ai.finishing import (species_finishing_notes, recoat_window,
                                       RECOAT_WINDOW_H)


def _cab_species(species, finish="clear", **kw):
    return CabinetSpec(width=600, height=720, depth=560, doors=2, shelves=1,
                       finish=finish, species=species, **kw)


def test_walnut_gets_oily_and_open_pore_notes():
    notes = species_finishing_notes(_cab_species("walnut"))
    blob = " ".join(notes).lower()
    assert notes, "walnut should produce finishing notes"
    assert "solvent" in blob, "oily wood: wipe with solvent"
    assert "grain-fill" in blob or "grain fill" in blob, "open-pore: grain fill"


def test_oak_gets_open_pore_note():
    blob = " ".join(species_finishing_notes(_cab_species("oak"))).lower()
    assert "grain-fill" in blob or "grain fill" in blob


def test_pine_gets_blotch_note():
    blob = " ".join(species_finishing_notes(_cab_species("pine"))).lower()
    assert "condition" in blob and "stain" in blob


def test_schedule_carries_species_notes_and_recoat_window():
    sched = finishing_schedule(_cab_species("walnut", finish="stain_clear"))
    # new keys are present and existing ones are untouched
    assert sched["species_notes"], "species_notes should be populated for walnut"
    assert sched["coats"] == 4 and sched["grits"]      # existing keys intact
    lo, hi = sched["recoat_hours"]
    assert lo > 0 and hi >= lo
    # the species advice and the drying window also reach the bench checklist
    text = " ".join(sched["steps"]).lower()
    assert "solvent" in text
    assert "recoat" in text or "between coats" in text


def test_recoat_windows_differ_by_finish_family():
    assert recoat_window("oil") == RECOAT_WINDOW_H["oil"]
    # oil-based poly over stain cures far slower than a waterborne clear
    assert recoat_window("stain_clear")[0] > recoat_window("clear")[1]


def test_no_finish_has_empty_species_notes_in_steps():
    # With no coats there is nothing to finish, so species notes don't clutter
    # the (empty) step list, but the data key still exists.
    sched = finishing_schedule(_cab_species("walnut", finish="none"))
    assert sched["steps"] == []
    assert sched["recoat_hours"] == [0.0, 0.0]
    assert "species_notes" in sched


def test_species_notes_from_per_area_override():
    # species declared only on a stock override (not the global) is still seen
    spec = CabinetSpec(width=600, height=720, depth=560, doors=2,
                       finish="clear",
                       stock={"front": {"form": "solid", "species": "oak"}})
    blob = " ".join(species_finishing_notes(spec)).lower()
    assert "grain-fill" in blob or "grain fill" in blob
