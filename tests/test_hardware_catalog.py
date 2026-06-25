"""Hardware catalogue: brand SKUs, undermount geometry, BOM, drilling."""

from woodworking_ai.hardware import (
    select_hinge, select_slide, select_pull, hinge_count, normalize_brand,
)
from woodworking_ai.dsl import CabinetSpec, Drawer
from woodworking_ai.cutlist import generate_cutlist
from woodworking_ai.drilling import drilling_schedule


def test_brand_normalization():
    assert normalize_brand("BLUM") == "blum"
    assert normalize_brand("nonsense") == "generic"
    assert normalize_brand(None) == "generic"


def test_blum_hinge_has_sku_and_plate():
    h = select_hinge("blum", "overlay")
    assert h.sku and h.plate_sku, "a named brand carries a hinge + plate SKU"
    assert h.overlay == "overlay"


def test_undermount_box_is_narrower_than_side_mount():
    under = select_slide("blum", "undermount")
    side = select_slide("blum", "side_mount")
    opening = 600.0
    assert under.box_width(opening) < side.box_width(opening)
    assert under.rear_notch and under.locking_holes >= 1


def test_pull_has_hole_spacing():
    assert select_pull("hettich").hole_spacing > 0


def test_hinge_count_scales():
    assert hinge_count(700) == 2
    assert hinge_count(1800) == 4


def test_bom_includes_brand_sku_and_fasteners():
    spec = CabinetSpec(width=600, height=720, depth=560, doors=2, shelves=1,
                       hardware_brand="blum")
    cl = generate_cutlist(spec)
    names = {h.name for h in cl.hardware}
    assert "Concealed hinge" in names
    assert "Hinge mounting plate" in names
    # An orderable BOM names assembly fasteners and back fixings, not just hinges.
    assert any(h.category == "fastener" for h in cl.hardware)
    hinge = next(h for h in cl.hardware if h.name == "Concealed hinge")
    assert hinge.brand == "blum" and hinge.sku


def test_undermount_drawer_changes_drilling_and_bom():
    spec = CabinetSpec(width=600, height=720, depth=560, doors=0,
                       drawers=[Drawer(front_height=150, slide_type="undermount")],
                       hardware_brand="blum")
    cl = generate_cutlist(spec)
    assert any("locking device" in h.name for h in cl.hardware)
    sched = drilling_schedule(spec)
    assert any("undermount slide" in op.operation for op in sched.ops)


def test_sidemount_drawer_keeps_slide_line():
    spec = CabinetSpec(width=600, height=720, depth=560, doors=0,
                       drawers=[Drawer(front_height=150, slide_type="side_mount")])
    sched = drilling_schedule(spec)
    assert any("slide line" in op.operation for op in sched.ops)
