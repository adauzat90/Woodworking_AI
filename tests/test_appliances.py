"""First-class typed appliances and their per-type validation rules."""

import pytest

from woodworking_ai import (
    CabinetSpec, Appliance, ApplianceType, appliances_of, validate,
)


def _cab(accessories, **o):
    d = dict(cabinet_type="base", name="Sink Base", width=900, height=720,
             depth=600, accessories=accessories)
    d.update(o)
    return CabinetSpec(**d)


# --- round-trip ----------------------------------------------------------

def test_appliance_roundtrips_and_type_is_enum():
    a = Appliance(type="sink", width=760, height=200, depth=480,
                  cutout_w=700, cutout_d=450, panel_ready=False)
    assert a.type is ApplianceType.SINK
    back = Appliance.from_dict(a.to_dict())
    assert back == a
    assert back.type is ApplianceType.SINK


def test_appliance_from_legacy_dict_form():
    raw = {"kind": "appliance", "type": "sink", "cutout_w": 700, "cutout_d": 450}
    a = Appliance.from_dict(raw)
    assert a.type is ApplianceType.SINK
    assert a.cutout_w == 700 and a.cutout_d == 450
    # to_dict re-stamps the accessory kind so it round-trips into the list.
    assert a.to_dict()["kind"] == "appliance"


def test_unknown_type_degrades_to_string_not_raise():
    a = Appliance.from_dict({"type": "toaster"})
    assert a.type == "toaster"


# --- appliances_of bridges the loose dict form ---------------------------

def test_appliances_of_yields_typed_from_legacy_dicts():
    spec = _cab([
        {"kind": "countertop", "depth": 640},
        {"kind": "appliance", "type": "sink", "cutout_w": 700, "cutout_d": 450},
        {"kind": "filler", "width": 75},
    ])
    apps = appliances_of(spec)
    assert len(apps) == 1
    assert isinstance(apps[0], Appliance)
    assert apps[0].type is ApplianceType.SINK


def test_appliances_of_passes_through_objects():
    a = Appliance(type="cooktop", cutout_w=560)
    spec = _cab([a])
    out = appliances_of(spec)
    assert out == [a]


# --- validation: existing cutout-fit behaviour preserved -----------------

def test_sink_cutout_wider_than_interior_errors():
    spec = _cab([
        {"kind": "countertop", "depth": 640},
        {"kind": "appliance", "type": "sink", "cutout_w": 2000, "cutout_d": 450},
    ])
    res = validate(spec)
    assert not res.ok
    assert any("wider than" in e.message for e in res.errors)


# --- validation: per-type rules ------------------------------------------

def test_sink_without_countertop_warns():
    spec = _cab([
        {"kind": "appliance", "type": "sink", "cutout_w": 700, "cutout_d": 450},
    ])
    res = validate(spec)
    assert any("countertop" in w.message for w in res.warnings)


def test_sink_with_countertop_no_counter_warning():
    spec = _cab([
        {"kind": "countertop", "depth": 640},
        {"kind": "appliance", "type": "sink", "cutout_w": 700, "cutout_d": 450},
    ])
    res = validate(spec)
    assert not any("needs a countertop" in w.message for w in res.warnings)


def test_panel_ready_dishwasher_without_panel_warns():
    spec = _cab([
        {"kind": "appliance", "type": "dishwasher", "cutout_w": 600,
         "panel_ready": True},
    ])
    res = validate(spec)
    assert any("finish panel" in w.message for w in res.warnings)


def test_panel_ready_with_end_panel_no_warning():
    spec = _cab([
        {"kind": "end_panel", "side": "right"},
        {"kind": "appliance", "type": "dishwasher", "cutout_w": 600,
         "panel_ready": True},
    ])
    res = validate(spec)
    assert not any("finish panel" in w.message for w in res.warnings)


def test_gap_appliance_emits_advisory():
    spec = _cab([
        {"kind": "appliance", "type": "range", "cutout_w": 760},
    ])
    res = validate(spec)
    assert any("occupies a GAP" in i.message for i in res.infos)
