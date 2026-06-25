"""Dimensioned 2D shop drawings (SVG)."""

import xml.dom.minidom as minidom

from woodworking_ai.dsl import CabinetSpec, Drawer, TableSpec
from woodworking_ai.cutlist import generate_cutlist
from woodworking_ai.drawings import render_svg


def _cab():
    return CabinetSpec(width=600, height=720, depth=560, doors=2, shelves=1,
                       drawers=[Drawer(front_height=140)])


def test_render_is_well_formed_svg():
    svg = render_svg(_cab())
    # Parses as XML and is an <svg> root — i.e. valid, self-contained markup.
    doc = minidom.parseString(svg)
    assert doc.documentElement.tagName == "svg"


def test_has_three_named_views():
    svg = render_svg(_cab())
    for name in ("Front elevation", "Side", "Plan"):
        assert name in svg


def test_overall_dimensions_appear():
    svg = render_svg(_cab(), unit="metric")
    # The overall width (600), height (720) and depth (560) are dimensioned.
    assert "600" in svg and "720" in svg and "560" in svg


def test_front_panels_are_labelled_with_part_ids():
    spec = _cab()
    svg = render_svg(spec)
    front_ids = [p.id for p in generate_cutlist(spec).parts
                 if p.material == "door/front"]
    assert front_ids
    assert any(pid in svg for pid in front_ids)


def test_imperial_dimensions_render_fractional():
    svg = render_svg(_cab(), unit="imperial")
    assert '"' in svg   # inch marks present


def test_table_also_renders():
    svg = render_svg(TableSpec(width=1400, depth=800, height=740))
    assert "<svg" in svg and "Plan" in svg
