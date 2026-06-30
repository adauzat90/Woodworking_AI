"""The Fusion 360 adapter maps PanelBoxes to the right Fusion box solids.

Fusion's ``adsk`` API isn't importable off-Fusion, so we stub the handful of
calls :mod:`fusion360.adapter` makes and assert on the box parameters it asks
for: the mm->cm conversion, the Z-rotation direction vectors, and that a through
``opening`` becomes one extra box plus one boolean subtraction. This keeps the
build123d-replacement honest without a Fusion install.
"""

import os
import sys
import math
import types

import pytest

from woodworking_ai import CabinetSpec
from woodworking_ai.geometry import PanelBox


# --- stub the adsk API and import the adapter against it --------------------
def _install_adsk_stub():
    calls = {"boxes": [], "bools": []}

    class Point3D:
        def __init__(self, x, y, z):
            self.xyz = (x, y, z)

        @staticmethod
        def create(x, y, z):
            return Point3D(x, y, z)

    class Vector3D:
        def __init__(self, x, y, z):
            self.xyz = (x, y, z)

        @staticmethod
        def create(x, y, z):
            return Vector3D(x, y, z)

    class OrientedBoundingBox3D:
        def __init__(self, c, ld, wd, length, width, height):
            self.rec = (c.xyz, ld.xyz, wd.xyz, length, width, height)

        @staticmethod
        def create(c, ld, wd, length, width, height):
            return OrientedBoundingBox3D(c, ld, wd, length, width, height)

    class Matrix3D:
        @staticmethod
        def create():
            return object()

    core = types.ModuleType("adsk.core")
    core.Point3D = Point3D
    core.Vector3D = Vector3D
    core.OrientedBoundingBox3D = OrientedBoundingBox3D
    core.Matrix3D = Matrix3D

    class _Body:
        pass

    class BooleanTypes:
        DifferenceBooleanType = "diff"

    class _BRepMgr:
        def createBox(self, obb):
            calls["boxes"].append(obb.rec)
            body = _Body()
            body.obb = obb.rec
            return body

        def booleanOperation(self, target, tool, kind):
            calls["bools"].append(kind)
            return True

    class TemporaryBRepManager:
        @staticmethod
        def get():
            return _BRepMgr()

    fusion = types.ModuleType("adsk.fusion")
    fusion.BooleanTypes = BooleanTypes
    fusion.TemporaryBRepManager = TemporaryBRepManager

    adsk = types.ModuleType("adsk")
    adsk.core = core
    adsk.fusion = fusion
    sys.modules["adsk"] = adsk
    sys.modules["adsk.core"] = core
    sys.modules["adsk.fusion"] = fusion
    return calls


@pytest.fixture
def adapter_and_calls():
    calls = _install_adsk_stub()
    fusion_dir = os.path.join(os.path.dirname(__file__), "..", "fusion360")
    sys.path.insert(0, os.path.realpath(fusion_dir))
    sys.modules.pop("adapter", None)
    import adapter

    yield adapter, calls

    sys.modules.pop("adapter", None)
    for mod in ("adsk", "adsk.core", "adsk.fusion"):
        sys.modules.pop(mod, None)


def _mgr():
    import adsk.fusion

    return adsk.fusion.TemporaryBRepManager.get()


def test_plain_panel_converts_mm_to_cm_axis_aligned(adapter_and_calls):
    adapter, calls = adapter_and_calls
    panel = PanelBox(
        label="Side L", size=(18.0, 560.0, 620.0),
        center=(-441.0, 280.0, 410.0),
    )
    adapter.panel_to_brep(_mgr(), panel)

    center, length_dir, width_dir, length, width, height = calls["boxes"][-1]
    assert center == (-44.1, 28.0, 41.0)       # mm / 10
    assert (length, width, height) == (1.8, 56.0, 62.0)
    assert length_dir == (1.0, 0.0, 0.0)
    assert width_dir == (0.0, 1.0, 0.0)


def test_rotated_panel_sets_direction_vectors(adapter_and_calls):
    adapter, calls = adapter_and_calls
    panel = PanelBox(label="Door", size=(10, 10, 10), center=(0, 0, 0),
                     rot_z=45.0)
    adapter.panel_to_brep(_mgr(), panel)

    _, length_dir, width_dir, *_ = calls["boxes"][-1]
    r = math.sqrt(2) / 2
    assert length_dir == pytest.approx((r, r, 0.0))
    assert width_dir == pytest.approx((-r, r, 0.0))


def test_through_opening_subtracts_one_box(adapter_and_calls):
    adapter, calls = adapter_and_calls
    panel = PanelBox(
        label="Countertop", size=(900, 600, 30), center=(0, 300, 740),
        subassembly="Countertop", openings=((100, -50, 400, 500),),
    )
    adapter.panel_to_brep(_mgr(), panel)

    assert len(calls["boxes"]) == 2     # panel + one cutter
    assert calls["bools"] == ["diff"]
    cutter_center = calls["boxes"][1][0]
    # local opening offset (100, -50) mm -> world, then /10 cm; Z unchanged.
    assert cutter_center == pytest.approx((10.0, 25.0, 74.0))
    cutter_height = calls["boxes"][1][5]
    assert cutter_height == pytest.approx(6.0)   # 2 * panel thickness (cm)


def test_build_into_component_names_bodies_and_uses_one_base_feature():
    """End-to-end over the real layout, with fake Fusion component/objects."""
    _install_adsk_stub()
    fusion_dir = os.path.realpath(
        os.path.join(os.path.dirname(__file__), "..", "fusion360")
    )
    sys.path.insert(0, fusion_dir)
    sys.modules.pop("adapter", None)
    import adapter

    made = {"base_edits": 0, "bodies": []}

    class _Base:
        def startEdit(self):
            made["base_edits"] += 1

        def finishEdit(self):
            made["base_edits"] -= 1

    class _BodyRec:
        def __init__(self, name):
            self.name = name

    class _Bodies:
        def add(self, temp, base):
            assert made["base_edits"] == 1   # added while the base is open
            body = _BodyRec("")
            made["bodies"].append(body)
            return body

    class _Features:
        class baseFeatures:
            @staticmethod
            def add():
                return _Base()

    class _Component:
        def __init__(self):
            self.features = _Features()
            self.bRepBodies = _Bodies()

    spec = CabinetSpec(cabinet_type="base", name="Sink Base",
                       width=900, height=720, depth=560, doors=2, shelves=1)
    comp = _Component()
    bodies = adapter.build_into_component(spec, comp)

    assert len(bodies) == len(made["bodies"]) > 0
    assert made["base_edits"] == 0                       # finishEdit ran
    assert all(b.name for b in bodies)                   # every body named
    assert any("Carcass" in b.name for b in bodies)      # subassembly prefix

    sys.modules.pop("adapter", None)
    for mod in ("adsk", "adsk.core", "adsk.fusion"):
        sys.modules.pop(mod, None)
