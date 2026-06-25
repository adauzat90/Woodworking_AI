"""First-class typed appliances and their per-type validation rules."""

from woodworking_ai import (
    CabinetSpec, Appliance, ApplianceType, appliances_of, validate,
    ApplianceVoid, Project, Component,
)
from woodworking_ai.dsl import ApplianceVoid as _AV, spec_from_dict
from woodworking_ai.cutlist import generate_cutlist
from woodworking_ai.accessories import void_end_panels
from woodworking_ai.appliances import appliance_schedule


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


# --- B3: ApplianceVoid — a reserved gap in a run -------------------------

def _cab_comp(x, lbl):
    return Component(spec=CabinetSpec(name=lbl, width=600, height=720, depth=600),
                     x=x, label=lbl)


def _dw(x=600, width=600):
    return Component(
        spec=ApplianceVoid(type="dishwasher", width=width, depth=600, name="DW"),
        x=x, label="DW")


def test_appliance_void_roundtrips_through_the_dsl():
    av = ApplianceVoid(type="dishwasher", width=600, depth=600, name="DW gap")
    assert av.type is ApplianceType.DISHWASHER
    back = _AV.from_dict(av.to_dict())
    assert back == av
    # And it loads as a component spec inside a project payload.
    loaded = spec_from_dict({"kind": "project", "components": [
        {"spec": av.to_dict(), "x": 0}]})
    assert isinstance(loaded.components[0].spec, ApplianceVoid)


def test_void_adds_no_carcass_parts():
    proj = Project(name="Run", components=[
        _cab_comp(0, "B1"), _dw(600), _cab_comp(1200, "B3")])
    cl = generate_cutlist(proj)
    # Only the two cabinets contribute parts; the gap adds none.
    assert {p.id.split("-")[0] for p in cl.parts} == {"B1", "B3"}


def test_void_occupies_space_cabinet_overlap_errors():
    # A cabinet placed over the gap collides with the reserved space.
    proj = Project(name="Bad", components=[
        _cab_comp(0, "B1"), _dw(x=300)])
    res = validate(proj)
    assert not res.ok
    assert any("overlap" in e.message for e in res.errors)


def test_void_clear_of_cabinets_is_valid():
    proj = Project(name="Run", components=[
        _cab_comp(0, "B1"), _dw(600), _cab_comp(1200, "B3")])
    assert validate(proj).ok


def test_mis_sized_dishwasher_void_warns():
    res = validate(ApplianceVoid(type="dishwasher", width=450, depth=600))
    assert any("600mm" in w.message for w in res.warnings)


def test_standard_dishwasher_void_no_warning():
    assert validate(ApplianceVoid(type="dishwasher", width=600, depth=600)).ok
    assert not validate(ApplianceVoid(type="dishwasher", width=600)).warnings


def test_void_drives_end_panels_on_adjacent_cabinets():
    proj = Project(name="Run", components=[
        _cab_comp(0, "B1"), _dw(600), _cab_comp(1200, "B3")])
    panels = void_end_panels(proj)
    # B1 (component 1) is exposed on its right; B3 (component 3) on its left.
    assert panels == {1: ["right"], 3: ["left"]}


# --- B4: appliance schedule data -----------------------------------------

def _sink_cab():
    return CabinetSpec(name="Sink Base", width=900, height=720, depth=600,
                       accessories=[
                           {"kind": "countertop", "depth": 600},
                           {"kind": "appliance", "type": "sink",
                            "cutout_w": 700, "cutout_d": 450}])


def test_appliance_schedule_lists_a_sink_with_rough_in():
    sched = appliance_schedule(_sink_cab())
    assert len(sched) == 1
    row = sched[0]
    assert row["type"] == "sink"
    assert row["host"] == "Sink Base"
    assert row["cutout"] == "700×450mm"
    assert "Plumbing" in row["rough_in"]
    assert row["clearances"]


def test_appliance_schedule_empty_without_appliances():
    assert appliance_schedule(
        CabinetSpec(name="Plain", width=600, height=720, depth=560)) == []


def test_appliance_schedule_panel_ready_notes_a_panel():
    spec = CabinetSpec(name="DW front", width=600, height=720, depth=600,
                       accessories=[
                           {"kind": "end_panel", "side": "right"},
                           {"kind": "appliance", "type": "dishwasher",
                            "cutout_w": 600, "panel_ready": True}])
    row = next(r for r in appliance_schedule(spec) if r["type"] == "dishwasher")
    assert "panel" in row["panels"].lower()


def test_appliance_schedule_covers_run_cabinets_and_voids():
    proj = Project(name="Run", components=[
        Component(spec=_sink_cab(), x=0, label="B1"),
        _dw(900)])
    sched = appliance_schedule(proj)
    types = {r["type"] for r in sched}
    assert types == {"sink", "dishwasher"}
    dw = next(r for r in sched if r["type"] == "dishwasher")
    assert dw["host"].startswith("DW")            # the gap's component tag
    assert "600mm" in dw["clearances"]            # standard opening surfaced
