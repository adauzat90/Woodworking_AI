"""Tests for the renderer and the render-based (visual) review.

Rendering needs matplotlib; the LLM visual review must degrade gracefully when
the Anthropic SDK / API key are unavailable (the common case in CI).
"""


import pytest

from woodworking_ai import CabinetSpec, Material, ToeKick, Drawer
from woodworking_ai.agents.critic import render_review, visual_review, _extract_json


def base_spec(**overrides) -> CabinetSpec:
    defaults = dict(
        name="Test", width=600, height=720, depth=560,
        material=Material(carcass=18, back=6, door=18, shelf=18),
        toe_kick=ToeKick(height=100, setback=50),
        shelves=1, doors=2, drawers=[], reveal=3,
    )
    defaults.update(overrides)
    return CabinetSpec(**defaults)


PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


# --- rendering -----------------------------------------------------------

def test_render_writes_a_png(tmp_path):
    pytest.importorskip("matplotlib")
    from woodworking_ai.render import render_cabinet

    path = render_cabinet(base_spec(drawers=[Drawer(140)]), tmp_path / "cab.png")
    assert path.exists()
    data = path.read_bytes()
    assert data[:8] == PNG_MAGIC
    assert len(data) > 2000


def test_render_creates_parent_dirs(tmp_path):
    pytest.importorskip("matplotlib")
    from woodworking_ai.render import render_cabinet

    path = render_cabinet(base_spec(), tmp_path / "nested" / "deep" / "cab.png")
    assert path.exists()


# --- render_review without the LLM --------------------------------------

def test_render_review_no_llm_merges_report(tmp_path):
    pytest.importorskip("matplotlib")
    out = tmp_path / "render.png"
    result = render_review(base_spec(), image_path=out, use_llm=False)
    # Computational fields are present...
    assert result.report["interference_count"] == 0
    assert "width" in result.report
    # ...and the render was produced.
    assert result.report.get("render_path") == str(out)
    assert out.exists()


# --- visual review degrades gracefully ----------------------------------

def test_visual_review_skips_without_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = visual_review(base_spec(), image_path=tmp_path / "v.png")
    # Never raises; warns rather than erroring, so it stays "ok".
    assert result.ok
    assert any(i.kind == "visual" for i in result.warnings)


# --- vision verdict parsing ---------------------------------------------

def test_extract_json_plain():
    assert _extract_json('{"looks_correct": true, "issues": []}')["looks_correct"] is True


def test_extract_json_fenced_with_prose():
    text = 'Here is my review:\n```json\n{"looks_correct": false, "issues": ["gap"]}\n```'
    parsed = _extract_json(text)
    assert parsed["looks_correct"] is False
    assert parsed["issues"] == ["gap"]
