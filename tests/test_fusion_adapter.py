"""The Fusion 360 adapter maps PanelBoxes to the right Fusion box solids.

Fusion's ``adsk`` API isn't importable off-Fusion, so we stub the handful of
calls :mod:`fusion360.adapter` makes and assert on what it asks for: panels are
built in a centred local frame (mm->cm) and placed with a transform; through
``openings`` and machined joinery/bores become boolean cuts; subassemblies group
into components; and spec dimensions become user parameters. This keeps the
build123d-replacement honest without a Fusion install.
"""

import os
import sys
import math
import types

import pytest

from woodworking_ai import CabinetSpec
from woodworking_ai.geometry import PanelBox


# --- fake Fusion objects, recording what the adapter does ------------------
def _install_adsk_stub():
    rec = {"boxes": [], "cylinders": [], "bools": [], "transforms": [],
           "copies": 0, "params": []}
    counter = {"n": 0}

    class _Body:
        def __init__(self, is_copy=False):
            counter["n"] += 1
            self.uid = counter["n"]
            self.is_copy = is_copy
            self.name = ""

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
        def __init__(self):
            self.angle = 0.0
            self.translation = None

        @staticmethod
        def create():
            return Matrix3D()

        def setToRotation(self, angle, axis, origin):
            self.angle = angle

    class ValueInput:
        @staticmethod
        def createByString(expr):
            return ("str", expr)

        @staticmethod
        def createByReal(val):
            return ("real", val)

    core = types.ModuleType("adsk.core")
    core.Point3D = Point3D
    core.Vector3D = Vector3D
    core.OrientedBoundingBox3D = OrientedBoundingBox3D
    core.Matrix3D = Matrix3D
    core.ValueInput = ValueInput

    class BooleanTypes:
        DifferenceBooleanType = "diff"

    class _BRepMgr:
        def createBox(self, obb):
            rec["boxes"].append(obb.rec)
            return _Body()

        def createCylinderOrCone(self, p1, r1, p2, r2):
            rec["cylinders"].append((p1.xyz, r1, p2.xyz, r2))
            return _Body()

        def copy(self, body):
            rec["copies"] += 1
            return _Body(is_copy=True)

        def booleanOperation(self, target, tool, kind):
            rec["bools"].append(kind)
            return True

        def transform(self, body, matrix):
            rec["transforms"].append(
                (body, matrix.angle,
                 matrix.translation.xyz if matrix.translation else None)
            )
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
    return rec


@pytest.fixture
def adapter_and_rec():
    rec = _install_adsk_stub()
    fusion_dir = os.path.realpath(
        os.path.join(os.path.dirname(__file__), "..", "fusion360")
    )
    if fusion_dir not in sys.path:
        sys.path.insert(0, fusion_dir)
    sys.modules.pop("adapter", None)
    import adapter

    yield adapter, rec

    sys.modules.pop("adapter", None)
    for mod in ("adsk", "adsk.core", "adsk.fusion"):
        sys.modules.pop(mod, None)


def _mgr():
    import adsk.fusion

    return adsk.fusion.TemporaryBRepManager.get()


# --- placement -------------------------------------------------------------
def test_plain_panel_built_local_then_placed(adapter_and_rec):
    adapter, rec = adapter_and_rec
    panel = PanelBox(label="Side L", size=(18.0, 560.0, 620.0),
                     center=(-441.0, 280.0, 410.0))
    adapter.panel_to_brep(_mgr(), panel)

    center, length_dir, width_dir, length, width, height = rec["boxes"][-1]
    assert center == (0.0, 0.0, 0.0)            # built at the local origin
    assert (length, width, height) == (1.8, 56.0, 62.0)   # mm / 10
    assert length_dir == (1.0, 0.0, 0.0) and width_dir == (0.0, 1.0, 0.0)

    _, angle, translation = rec["transforms"][-1]
    assert angle == pytest.approx(0.0)
    assert translation == pytest.approx((-44.1, 28.0, 41.0))   # placed centre


def test_rotated_panel_places_with_z_rotation(adapter_and_rec):
    adapter, rec = adapter_and_rec
    panel = PanelBox(label="Door", size=(10, 10, 10), center=(5, 6, 7),
                     rot_z=45.0)
    adapter.panel_to_brep(_mgr(), panel)

    _, angle, translation = rec["transforms"][-1]
    assert angle == pytest.approx(math.radians(45.0))
    assert translation == pytest.approx((0.5, 0.6, 0.7))


def test_through_opening_subtracts_a_local_box(adapter_and_rec):
    adapter, rec = adapter_and_rec
    panel = PanelBox(label="Countertop", size=(900, 600, 30), center=(0, 300, 740),
                     subassembly="Countertop", openings=((100, -50, 400, 500),))
    adapter.panel_to_brep(_mgr(), panel)

    assert len(rec["boxes"]) == 2          # panel + one cutter
    assert rec["bools"] == ["diff"]
    cutter_center = rec["boxes"][1][0]     # local offset (100,-50) mm -> cm
    assert cutter_center == pytest.approx((10.0, -5.0, 0.0))
    assert rec["boxes"][1][5] == pytest.approx(6.0)   # through: 2x thickness


# --- machining -------------------------------------------------------------
def test_machining_cuts_dado_and_through_bore(adapter_and_rec):
    adapter, rec = adapter_and_rec
    # A side panel: thin in X (normal=0), plane axis Y, height Z.
    panel = PanelBox(label="Side L", size=(18.0, 560.0, 620.0),
                     center=(-441.0, 280.0, 410.0))
    dado = types.SimpleNamespace(width=18.0, depth=9.0,
                                 reference="near the bottom edge")
    through = types.SimpleNamespace(dia=5.0, depth=18.0, u=37.0, v=100.0)
    blind = types.SimpleNamespace(dia=8.0, depth=11.0, u=37.0, v=200.0)

    adapter.panel_to_brep(_mgr(), panel, machining=([dado], [through, blind]))

    assert rec["copies"] == 1                          # cut on a copy
    assert len(rec["cylinders"]) == 2                  # two bores
    # panel box + one dado box = 2 boxes; 1 dado + 2 bores = 3 booleans
    assert len(rec["boxes"]) == 2
    assert rec["bools"].count("diff") == 3
    # the placed body is the machined copy
    placed_body = rec["transforms"][-1][0]
    assert placed_body.is_copy is True


def test_machining_failure_degrades_to_slab(adapter_and_rec):
    adapter, rec = adapter_and_rec
    panel = PanelBox(label="Side L", size=(18.0, 560.0, 620.0),
                     center=(0, 0, 0))
    bad = types.SimpleNamespace(width="oops", depth=9.0, reference="bottom")
    # Should not raise; the bad op makes _apply_joinery throw, so we keep the slab.
    adapter.panel_to_brep(_mgr(), panel, machining=([bad], []))
    placed_body = rec["transforms"][-1][0]
    assert placed_body.is_copy is False                # fell back to the slab


# --- grouping + parameters (end-to-end over the real layout) ---------------
class _FakeComponent:
    def __init__(self, registry):
        self._reg = registry
        self.name = ""
        self.bRepBodies = self._Bodies(registry)
        self.occurrences = self._Occurrences(registry)
        self.features = self._Features()

    class _Base:
        def startEdit(self):
            pass

        def finishEdit(self):
            pass

    class _Features:
        class baseFeatures:
            @staticmethod
            def add():
                return _FakeComponent._Base()

    class _Bodies:
        def __init__(self, reg):
            self._reg = reg

        def add(self, temp, base):
            temp.name = ""
            self._reg["bodies"].append(temp)
            return temp

    class _Occurrences:
        def __init__(self, reg):
            self._reg = reg

        def addNewComponent(self, matrix):
            comp = _FakeComponent(self._reg)
            self._reg["components"].append(comp)
            return types.SimpleNamespace(component=comp)


class _FakeUserParameters:
    def __init__(self):
        self.items = {}

    def itemByName(self, name):
        return self.items.get(name)

    def add(self, name, value, units, comment):
        # value is the ValueInput stub: ("str", "<expr>").
        expr = value[1] if isinstance(value, tuple) else None
        param = types.SimpleNamespace(name=name, expression=expr,
                                      units=units, comment=comment)
        self.items[name] = param
        return param


class _FakeDesign:
    def __init__(self, registry):
        self.rootComponent = _FakeComponent(registry)
        self.userParameters = _FakeUserParameters()


def test_import_spec_groups_by_subassembly_and_writes_params(adapter_and_rec):
    adapter, rec = adapter_and_rec
    registry = {"bodies": [], "components": []}
    design = _FakeDesign(registry)
    spec = CabinetSpec(cabinet_type="base", name="Sink Base", width=900,
                       height=720, depth=560, doors=2, shelves=1)

    component, bodies = adapter.import_spec(spec, design, machined=False,
                                            by_subassembly=True)

    assert component.name == "Sink Base"
    assert len(bodies) > 0
    assert all(b.name for b in bodies)                 # every body named
    # at least the parent component plus one named subassembly component
    sub_names = {c.name for c in registry["components"] if c.name}
    assert "Carcass" in sub_names

    params = design.userParameters.items
    assert params["woodai_width"].expression == "900.0 mm"
    assert params["woodai_depth"].expression == "560.0 mm"
    assert "woodai_carcass_thickness" in params        # from spec.material


def test_import_spec_flat_uses_one_component(adapter_and_rec):
    adapter, rec = adapter_and_rec
    registry = {"bodies": [], "components": []}
    design = _FakeDesign(registry)
    spec = CabinetSpec(cabinet_type="base", name="Flat", width=600,
                       height=720, depth=560, doors=2)

    component, bodies = adapter.import_spec(spec, design, machined=False,
                                            by_subassembly=False)
    # only the parent component is created (no per-subassembly children)
    assert len([c for c in registry["components"]]) == 1
    assert component is registry["components"][0]
    assert len(bodies) > 0
