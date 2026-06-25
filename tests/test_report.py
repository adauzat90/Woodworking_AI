"""Printable build package (PDF). Skipped when reportlab is unavailable."""

import pytest

from woodworking_ai.dsl import CabinetSpec, Drawer, Project, Component

reportlab = pytest.importorskip("reportlab")

from woodworking_ai.report import (  # noqa: E402
    build_package_pdf, build_template_pdf)
from woodworking_ai.proposal import build_proposal_pdf  # noqa: E402
from woodworking_ai.service import export_bytes  # noqa: E402
from woodworking_ai.cutlist import generate_cutlist  # noqa: E402


def _cab():
    return CabinetSpec(width=600, height=720, depth=560, doors=2, shelves=1,
                       drawers=[Drawer(front_height=140)], hardware_brand="blum")


def _sink_cab():
    return CabinetSpec(name="Sink Base", width=900, height=720, depth=600,
                       doors=2, hardware_brand="blum", accessories=[
                           {"kind": "countertop", "depth": 600},
                           {"kind": "appliance", "type": "sink",
                            "cutout_w": 700, "cutout_d": 450}])


def test_package_is_a_pdf():
    data = build_package_pdf(_cab())
    assert data[:5] == b"%PDF-", "output must be a PDF document"
    assert len(data) > 1500, "a full package should be more than a stub"


def test_package_via_export_bytes():
    data, mime, fname = export_bytes(_cab(), "package")
    assert mime == "application/pdf"
    assert fname.endswith("_build_package.pdf")
    assert data[:5] == b"%PDF-"


def test_imperial_package_builds():
    data, _mime, _f = export_bytes(_cab(), "package", units="imperial")
    assert data[:5] == b"%PDF-"


def test_project_package_builds():
    proj = Project(name="Run", components=[
        Component(spec=_cab(), label="B1"),
        Component(spec=_cab(), x=600, label="B2"),
    ])
    data = build_package_pdf(proj)
    assert data[:5] == b"%PDF-"


def test_manual_orders_cut_then_process_then_build():
    import pytest
    fitz = pytest.importorskip("fitz")
    data = build_package_pdf(_cab())
    doc = fitz.open(stream=data, filetype="pdf")
    text = "\n".join(p.get_text() for p in doc)
    # Use the unique section headings; the cover/overview mention similar phrases.
    cut = text.index("Cut & label all parts")
    process = text.index("Process all parts (while flat)")
    build = text.index("Build: Carcass")
    final = text.rindex("Final assembly")   # the heading, not the overview mention
    assert cut < process < build < final, "cut → process → build → final order"


def test_shopping_list_is_the_first_section():
    import pytest
    fitz = pytest.importorskip("fitz")
    spec = _cab()
    data = build_package_pdf(spec)
    doc = fitz.open(stream=data, filetype="pdf")
    text = "\n".join(p.get_text() for p in doc)
    shop = text.index("Shopping list — buy this first")
    overview = text.index("Overview — what you're building")
    cut = text.index("Cut & label all parts")
    # The BOM/shopping list comes before everything else.
    assert shop < overview < cut
    # It lists hardware to buy with SKUs and the sheet count.
    assert "Hardware & fasteners" in text or "Hardware" in text


# --- B4: appliance schedule renders in the PDF only when present ---------

def test_package_shows_appliance_section_only_when_present():
    fitz = pytest.importorskip("fitz")

    def _text(spec):
        doc = fitz.open(stream=build_package_pdf(spec), filetype="pdf")
        return "\n".join(p.get_text() for p in doc)

    with_app = _text(_sink_cab())
    assert "Appliance schedule" in with_app
    without = _text(_cab())
    assert "Appliance schedule" not in without


# --- 1:1 tiled template (H6) ---------------------------------------------

def test_template_is_a_pdf():
    data = build_template_pdf(_cab())
    assert data[:5] == b"%PDF-"
    assert len(data) > 1000


def test_template_via_export_bytes():
    data, mime, fname = export_bytes(_cab(), "template")
    assert mime == "application/pdf"
    assert fname.endswith("_template.pdf")
    assert data[:5] == b"%PDF-"


def test_template_specific_part_and_a4():
    cl = generate_cutlist(_cab())
    pid = cl.parts[0].id
    data = build_template_pdf(_cab(), part_id=pid, page="a4")
    assert data[:5] == b"%PDF-"


def test_template_unknown_part_raises():
    with pytest.raises(ValueError, match="part id"):
        build_template_pdf(_cab(), part_id="ZZ999")


def test_template_unknown_page_raises():
    with pytest.raises(ValueError, match="page size"):
        build_template_pdf(_cab(), page="tabloid")


def _pdf_page_count(data):
    # The page tree's /Count is authoritative; reportlab writes it once.
    import re
    m = re.search(rb"/Count\s+(\d+)", data)
    return int(m.group(1)) if m else 0


def test_template_large_part_tiles_multiple_pages():
    # A 2.1m tall pantry side won't fit one Letter/A4 page, so the template must
    # span several pages.
    tall = CabinetSpec(name="Pantry", width=600, height=2100, depth=600,
                       doors=2, shelves=6)
    cl = generate_cutlist(tall)
    side = max(cl.parts, key=lambda p: p.length * p.width)
    data = build_template_pdf(tall, part_id=side.id)
    assert _pdf_page_count(data) >= 2


def test_template_has_scale_check_cover_page():
    # The leading cover page carries the 100mm / 4in scale-check squares and the
    # print-at-100% instruction, so a hobbyist can verify printer scale (G6a).
    text = _pdf_text(build_template_pdf(_cab())).lower()
    assert "100 mm" in text
    assert "4 in" in text
    assert "100%" in text
    assert "1:1 template" in text


# --- customer proposal (D3) ----------------------------------------------

def test_proposal_is_a_pdf():
    data = build_proposal_pdf(_cab())
    assert data[:5] == b"%PDF-", "proposal must be a PDF document"
    assert len(data) > 1500


def test_proposal_via_export_bytes():
    data, mime, fname = export_bytes(_cab(), "proposal")
    assert mime == "application/pdf"
    assert fname.endswith("_proposal.pdf")
    assert data[:5] == b"%PDF-"


def _pdf_text(data):
    import pytest
    fitz = pytest.importorskip("fitz")
    doc = fitz.open(stream=data, filetype="pdf")
    return "\n".join(p.get_text() for p in doc)


def test_proposal_has_price_dimensions_and_signoff():
    text = _pdf_text(build_proposal_pdf(_cab()))
    assert "Proposal" in text
    assert "Price" in text
    assert "Approval" in text
    assert "signature" in text.lower()
    # Overall dimensions are surfaced for the customer.
    assert "Width" in text and "Height" in text


def test_proposal_omits_shop_floor_detail():
    """The customer document must NOT carry joinery/drilling/cut-list/bench detail."""
    text = _pdf_text(build_proposal_pdf(_cab())).lower()
    for banned in ("joinery", "drilling", "cut list", "cut & label",
                   "process all parts", "32mm"):
        assert banned not in text, f"proposal leaked shop detail: {banned!r}"


def test_shop_package_still_includes_shop_floor_detail():
    """The shop build package is unchanged — it keeps joinery/drilling/assembly."""
    text = _pdf_text(build_package_pdf(_cab())).lower()
    assert "joinery" in text
    assert "drilling" in text
    assert "process all parts" in text
