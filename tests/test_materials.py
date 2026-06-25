"""Optional material make-up: form (plywood/mdf/.../solid) + wood species.

Covers the DSL fields, per-area resolution, BOM grouping/labelling, per-species
pricing, build hints, and round-trip serialisation.
"""

from woodworking_ai.dsl import (CabinetSpec, Stock, Material, Drawer,
                                Construction)
from woodworking_ai import materials
from woodworking_ai.cutlist import generate_cutlist
from woodworking_ai.estimator import estimate
from woodworking_ai.validator import validate
from woodworking_ai.service import build_result


def _cab(**kw):
    base = dict(width=600, height=720, depth=560, doors=2, shelves=1,
                construction=Construction.FACE_FRAME)
    base.update(kw)
    if isinstance(base.get("construction"), str):
        base["construction"] = Construction(base["construction"])
    return CabinetSpec(**base)


# --- resolution ------------------------------------------------------------
def test_unset_means_generic_sheet():
    f, sp = materials.resolve(_cab(), "carcass")
    assert f == "" and sp == ""              # nothing declared → generic sheet


def test_global_form_and_species_apply_to_sheet_areas():
    spec = _cab(material_form="plywood", species="oak")
    assert materials.resolve(spec, "carcass") == ("plywood", "oak")
    assert materials.resolve(spec, "shelf") == ("plywood", "oak")


def test_intrinsically_solid_area_stays_solid_under_a_sheet_default():
    # A global plywood default must not turn the face frame into plywood.
    spec = _cab(material_form="plywood", species="maple")
    assert materials.resolve(spec, "frame") == ("solid", "maple")


def test_per_area_override_beats_global():
    spec = _cab(material_form="plywood", species="birch",
                stock={"front": Stock(form="solid", species="oak")})
    assert materials.resolve(spec, "carcass") == ("plywood", "birch")
    assert materials.resolve(spec, "front") == ("solid", "oak")


def test_area_aliases_resolve():
    spec = _cab(stock={"door": Stock(species="walnut")})  # "door" → "front"
    assert materials.resolve(spec, "front")[1] == "walnut"


# --- labels ----------------------------------------------------------------
def test_stock_name_reads_like_a_purchase():
    assert materials.stock_name("plywood", "oak") == "Oak plywood"
    assert materials.stock_name("solid", "walnut") == "Walnut solid lumber"
    assert materials.stock_name("mdf", "") == "MDF"
    assert materials.stock_name("", "oak", solid=True) == "Oak solid lumber"
    assert materials.stock_name("", "oak") == "Oak sheet"
    assert materials.stock_name("", "", fallback="Carcass sheet") == "Carcass sheet"


# --- cut list carries resolved stock ---------------------------------------
def test_parts_get_form_and_species():
    spec = _cab(material_form="plywood", species="oak",
                stock={"front": Stock(form="solid", species="oak")})
    cl = generate_cutlist(spec)
    sides = next(p for p in cl.parts if p.name == "Side")
    assert sides.form == "plywood" and sides.species == "oak"
    door = next(p for p in cl.parts if p.material == "door/front")
    assert door.form == "solid" and door.species == "oak"
    # A solid front counts as board-foot lumber now, not a sheet.
    assert door.is_solid_lumber


def test_solid_carcass_expands_to_glue_up_boards():
    spec = _cab(doors=0, shelves=0, material_form="solid", species="maple")
    cl = generate_cutlist(spec)
    assert any(p.material == "solid panel" for p in cl.parts)
    assert any(p.species == "maple" for p in cl.parts)


# --- BOM grouping ----------------------------------------------------------
def test_same_physical_stock_merges_across_usage_areas():
    # Carcass + doors both oak ply 18mm → one buyable sheet group, not two.
    spec = _cab(doors=2, material_form="plywood", species="oak",
                material=Material(carcass=18, back=6, door=18, shelf=18),
                door_style="slab")
    est = estimate(spec)
    ply18 = [g for g in est.groups if g.form == "plywood"
             and abs(g.thickness - 18) < 0.1]
    assert len(ply18) == 1
    assert ply18[0].species == "oak"


def test_legacy_specs_still_group_by_usage_label():
    spec = _cab(doors=2, door_style="slab")
    est = estimate(spec)
    labels = {g.material for g in est.groups}
    assert "door/front" in labels and "sheet" in labels   # unchanged behaviour


# --- per-species pricing ---------------------------------------------------
def test_walnut_costs_more_than_pine():
    common = dict(width=600, height=720, depth=560, doors=2, shelves=1,
                  material_form="plywood")
    walnut = estimate(CabinetSpec(species="walnut", **common)).material_cost
    pine = estimate(CabinetSpec(species="pine", **common)).material_cost
    assert walnut > pine > 0


def test_solid_lumber_priced_per_species():
    # The face frame is solid lumber; a pricey species lifts the lumber cost.
    cheap = estimate(_cab(species="pine")).lumber_cost
    dear = estimate(_cab(species="walnut")).lumber_cost
    assert dear > cheap > 0


# --- build hints -----------------------------------------------------------
def test_mdf_emits_a_build_hint():
    spec = _cab(material_form="mdf")
    msgs = [i.message for i in validate(spec).infos]
    assert any("MDF" in m or "confirmat" in m.lower() for m in msgs)


def test_no_material_declared_emits_no_material_hint():
    # A plain frameless cabinet shouldn't suddenly grow material advisories.
    infos = validate(_cab(construction="frameless")).infos
    assert not any(i.field == "material" for i in infos)


# --- serialisation round-trip ----------------------------------------------
def test_round_trip_preserves_material_declaration():
    spec = _cab(material_form="plywood", species="oak",
                stock={"front": Stock(form="solid", species="oak"),
                       "frame": Stock(form="solid", species="oak")})
    d = spec.to_dict()
    assert d["material_form"] == "plywood" and d["species"] == "oak"
    assert d["stock"]["front"] == {"form": "solid", "species": "oak"}
    back = CabinetSpec.from_dict(d)
    assert back.material_form == "plywood" and back.species == "oak"
    assert back.stock["front"].form == "solid"


def test_string_shorthand_in_stock_is_species():
    spec = CabinetSpec.from_dict({"width": 600, "height": 720, "depth": 560,
                                  "stock": {"front": "oak"}})
    assert spec.stock["front"].species == "oak"


def test_empty_stock_not_emitted():
    assert "stock" not in _cab().to_dict()


def test_schema_hint_advertises_material_fields():
    from woodworking_ai.dsl import DSL_SCHEMA_HINT
    for token in ('"material_form"', '"species"', '"stock"',
                  "plywood", "mdf", "particleboard", "melamine", "hardboard"):
        assert token in DSL_SCHEMA_HINT, token


# --- service bundle exposes the physical stock -----------------------------
def test_service_cutlist_and_groups_carry_stock_name():
    spec = _cab(material_form="plywood", species="oak", drawers=[Drawer(140)])
    res = build_result(spec, want_png=False, want_glb=False)
    assert any(p.get("stock") == "Oak plywood" for p in res["cutlist"])
    assert any(g.get("species") == "oak" for g in res["estimate"]["groups"])
