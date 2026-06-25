"""Every serialized spec carries a schema_version; it's accepted/ignored on input."""

import pytest

from woodworking_ai import (
    CabinetSpec, TableSpec, WallShelfSpec, BoxSpec, BenchSpec, ApplianceVoid,
    Project, Component, spec_from_dict,
)
from woodworking_ai.dsl import SCHEMA_VERSION


@pytest.mark.parametrize("spec", [
    CabinetSpec(name="C"),
    TableSpec(name="T"),
    WallShelfSpec(name="S"),
    BoxSpec(name="B"),
    BenchSpec(name="Bn"),
    ApplianceVoid(),
    Project(name="P", components=[Component(spec=CabinetSpec(width=600), x=0)]),
])
def test_to_dict_stamps_schema_version(spec):
    assert spec.to_dict()["schema_version"] == SCHEMA_VERSION


def test_input_schema_version_is_accepted_and_ignored():
    spec = spec_from_dict(
        {"kind": "cabinet", "width": 600, "schema_version": "0.9"})
    assert isinstance(spec, CabinetSpec) and spec.width == 600
    # On output we stamp the current version, regardless of what came in.
    assert spec.to_dict()["schema_version"] == SCHEMA_VERSION


def test_roundtrip_is_stable_with_version():
    p = Project(name="P", components=[Component(spec=CabinetSpec(width=600), x=0)])
    assert Project.from_json(p.to_json()).to_dict() == p.to_dict()
