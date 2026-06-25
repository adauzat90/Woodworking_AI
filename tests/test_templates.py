"""Starter-project gallery (G3) — the curated specs must all be buildable."""

from woodworking_ai import spec_from_dict, validate, generate_cutlist, estimate
from woodworking_ai.templates import templates, template, gallery


def test_gallery_has_a_spread_of_categories():
    cats = {t.category for t in templates()}
    # At least cabinets, tables/seating, storage, bedroom, and decor.
    assert len(cats) >= 4
    ids = {t.id for t in templates()}
    assert {"bookcase", "dining_table", "picture_frame", "queen_bed",
            "blanket_chest"} <= ids


def test_every_starter_validates_and_builds():
    for t in templates():
        spec = spec_from_dict(t.spec)
        res = validate(spec)
        assert res.ok, f"{t.id}: {[i.message for i in res.issues if i.severity=='error']}"
        assert generate_cutlist(spec).parts
        assert estimate(spec).total > 0


def test_template_lookup_by_id():
    assert template("bookcase").label == "Bookcase"
    assert template("nope") is None


def test_gallery_dicts_are_serialisable_and_complete():
    for d in gallery():
        assert d["id"] and d["label"] and d["category"] and d["blurb"]
        assert isinstance(d["spec"], dict) and d["spec"]
