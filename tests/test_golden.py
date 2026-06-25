"""Golden-output safety net for the tech-debt cleanup epic.

Snapshots the deterministic, CAD-free outputs of the pipeline (validation, cut
list, estimate, drilling, DXF, panel layout, joinery, purchasing) for a spread
of representative specs. Refactor PRs must keep these byte-identical; a phase
that *intends* to change output (e.g. the slide-clearance correctness fix)
regenerates the affected fixtures in the same PR and reviews the diff.

Regenerate:  WOODAI_REGEN_GOLDEN=1 pytest tests/test_golden.py
"""

import dataclasses as dc
import enum
import json
import os
from pathlib import Path

import pytest

from woodworking_ai import (
    validate, generate_cutlist, estimate, drilling_schedule, purchase_order,
)
from woodworking_ai.geometry import panel_layout
from woodworking_ai.joinery import joinery_schedule
from woodworking_ai.dxf import export_cutlayout_dxf
from tests.golden_specs import golden_specs

GOLDEN_DIR = Path(__file__).parent / "golden"
REGEN = os.environ.get("WOODAI_REGEN_GOLDEN") == "1"


def _ser(obj):
    """Stable, FP-noise-free serialization of any pipeline output."""
    if dc.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _ser(getattr(obj, f.name)) for f in dc.fields(obj)}
    if isinstance(obj, enum.Enum):
        return obj.value
    if isinstance(obj, float):
        return round(obj, 4)
    if isinstance(obj, (list, tuple)):
        return [_ser(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): _ser(v) for k, v in obj.items()}
    return obj


def _snapshot(spec, tmp_path) -> dict:
    panels = [_ser(p) for p in panel_layout(spec)]
    val = validate(spec)
    return {
        "valid": val.ok,
        "issues": sorted(f"{i.severity}:{i.message}" for i in val.issues),
        "cutlist": _ser(generate_cutlist(spec)),
        "estimate": _ser(estimate(spec)),
        "drilling": _ser(drilling_schedule(spec)),
        "purchasing": _ser(purchase_order(spec)),
        "joinery": _ser(joinery_schedule(spec)),
        "panels": panels,
        "dxf": export_cutlayout_dxf(spec, tmp_path / "n.dxf").read_text(),
    }


@pytest.mark.parametrize("key", list(golden_specs().keys()))
def test_golden_output(key, tmp_path):
    spec = golden_specs()[key]
    snap = _snapshot(spec, tmp_path)
    fixture = GOLDEN_DIR / f"{key}.json"

    if REGEN:
        GOLDEN_DIR.mkdir(exist_ok=True)
        fixture.write_text(json.dumps(snap, indent=2, sort_keys=True) + "\n")
        pytest.skip(f"regenerated {fixture.name}")

    assert fixture.exists(), (
        f"missing golden fixture {fixture}; run WOODAI_REGEN_GOLDEN=1 pytest")
    expected = json.loads(fixture.read_text())
    # Compare via normalized JSON so float rounding / key order never flaps.
    assert json.loads(json.dumps(snap, sort_keys=True)) == expected, (
        f"{key} output drifted from golden fixture {fixture.name}. If intended, "
        f"regenerate with WOODAI_REGEN_GOLDEN=1 and review the diff.")
