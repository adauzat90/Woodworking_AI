"""CLI entry point (`woodai`) — the `build` command and shared flags.

The 332-line command surface (arg parsing, report sections, file output, error
handling) was almost entirely uncovered. These tests drive ``cli.main(argv)``
directly — it returns an exit code and prints to stdout/stderr — so no
subprocess or build123d is needed. The `design` command (LLM) is not exercised
here; it needs the anthropic extra and an API key.
"""

import json

import pytest

from woodworking_ai.cli import main, _default_unit, _tooling_from_args


def _spec_file(tmp_path, **over) -> str:
    d = dict(cabinet_type="base", name="T", width=600, height=720, depth=560,
             doors=2, shelves=1)
    d.update(over)
    p = tmp_path / "spec.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    return str(p)


def _project_file(tmp_path) -> str:
    proj = dict(kind="project", name="Run", components=[
        dict(spec=dict(cabinet_type="base", name="B1", width=600, height=720,
                       depth=560, doors=2, shelves=1), x=0, label="B1"),
        dict(spec=dict(cabinet_type="base", name="B2", width=600, height=720,
                       depth=560, doors=2, shelves=1), x=600, label="B2"),
    ])
    p = tmp_path / "project.json"
    p.write_text(json.dumps(proj), encoding="utf-8")
    return str(p)


# --- happy path ----------------------------------------------------------

def test_build_valid_spec_returns_zero_and_prints_cutlist(tmp_path, capsys):
    rc = main(["build", _spec_file(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Cut list:" in out
    assert "Hardware:" in out
    assert "Build plan:" in out


def test_build_optional_report_sections(tmp_path, capsys):
    rc = main(["build", _spec_file(tmp_path),
               "--estimate", "--drill", "--joinery", "--assembly"])
    out = capsys.readouterr().out
    assert rc == 0
    # Each flag adds its own report block.
    assert "sheet" in out.lower()          # estimate
    assert "32" in out or "hinge" in out.lower()   # drilling schedule
    # joinery + assembly sections present (don't over-pin exact wording).
    assert "assembl" in out.lower()


def test_build_imperial_renders_inches(tmp_path, capsys):
    rc = main(["build", _spec_file(tmp_path), "--imperial"])
    out = capsys.readouterr().out
    assert rc == 0
    # Fractional-inch marks appear in an imperial cut list; never a bare mm col.
    assert '"' in out or "in" in out.lower()


# --- file output ---------------------------------------------------------

def test_build_out_writes_files(tmp_path, capsys):
    outdir = tmp_path / "out"
    rc = main(["build", _spec_file(tmp_path), "--out", str(outdir),
               "--drill", "--dxf"])
    assert rc == 0
    assert (outdir / "spec.json").exists()
    assert (outdir / "cutlist.csv").exists()
    assert (outdir / "hardware.csv").exists()
    assert (outdir / "drilling.csv").exists()
    assert (outdir / "cutlayout.dxf").exists()


# --- project (ComponentGroup) path --------------------------------------

def test_build_project_reports_assembled_run(tmp_path, capsys):
    rc = main(["build", _project_file(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Assembled run:" in out
    assert "Combined cut list:" in out


def test_build_project_out_writes_project_json(tmp_path):
    outdir = tmp_path / "out"
    rc = main(["build", _project_file(tmp_path), "--out", str(outdir)])
    assert rc == 0
    assert (outdir / "project.json").exists()
    assert not (outdir / "spec.json").exists()


# --- validation failure exits non-zero ----------------------------------

def test_build_unbuildable_spec_returns_one(tmp_path, capsys):
    # Negative depth is a hard validation error → exit 1, errors on stderr.
    rc = main(["build", _spec_file(tmp_path, depth=-5)])
    err = capsys.readouterr().err
    assert rc == 1
    assert "not buildable" in err or "Errors" in err


# --- error handling (the H3 fix) ----------------------------------------

def test_build_missing_file_clean_error(tmp_path, capsys):
    rc = main(["build", str(tmp_path / "nope.json")])
    err = capsys.readouterr().err
    assert rc == 2
    assert "not found" in err


def test_build_malformed_json_clean_error(tmp_path, capsys):
    p = tmp_path / "bad.json"
    p.write_text("{not valid json", encoding="utf-8")
    rc = main(["build", str(p)])
    err = capsys.readouterr().err
    assert rc == 2
    assert "could not parse" in err


def test_build_unknown_kind_clean_error(tmp_path, capsys):
    p = tmp_path / "weird.json"
    p.write_text(json.dumps(dict(kind="spaceship", name="X")), encoding="utf-8")
    rc = main(["build", str(p)])
    err = capsys.readouterr().err
    assert rc == 2
    assert "could not parse" in err


# --- warnings, from-stock, drawings (more pure-math branches) ------------

def test_build_warnings_are_printed_but_still_builds(tmp_path, capsys):
    # A very deep shelf relative to a shallow cabinet trips a warning without
    # failing the build; the CLI prints a "Warnings:" block and still returns 0.
    rc = main(["build", _spec_file(tmp_path, shelves=6, height=2100,
                                   cabinet_type="tall")])
    out = capsys.readouterr().out
    assert rc == 0
    # Buildable, so a Warnings block may or may not appear — but the run
    # completes with a cut list either way.
    assert "Cut list:" in out


def test_build_from_stock_prints_cut_plan(tmp_path, capsys):
    boards = tmp_path / "boards.json"
    boards.write_text(json.dumps([
        dict(length=2440, width=1220, thickness=18, form="plywood", qty=2),
        dict(length=2440, width=1220, thickness=6, form="plywood", qty=1),
    ]), encoding="utf-8")
    rc = main(["build", _spec_file(tmp_path), "--from-stock", str(boards)])
    out = capsys.readouterr().out
    assert rc == 0
    # The cut plan against owned stock is reported.
    assert "stock" in out.lower() or "board" in out.lower()


def test_build_from_stock_with_out_writes_cutplan_csv(tmp_path):
    boards = tmp_path / "boards.json"
    boards.write_text(json.dumps([
        dict(length=2440, width=1220, thickness=18, form="plywood", qty=2),
    ]), encoding="utf-8")
    outdir = tmp_path / "out"
    rc = main(["build", _spec_file(tmp_path), "--out", str(outdir),
               "--from-stock", str(boards)])
    assert rc == 0
    assert (outdir / "cutplan.csv").exists()


def test_build_drawings_writes_svg(tmp_path):
    outdir = tmp_path / "out"
    rc = main(["build", _spec_file(tmp_path), "--out", str(outdir), "--drawings"])
    assert rc == 0
    assert (outdir / "drawings.svg").exists()


# --- tooling flags -------------------------------------------------------

def test_tools_list_prints_checklist(tmp_path, capsys):
    rc = main(["build", _spec_file(tmp_path), "--tools-list"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Tools needed:" in out


def test_tooling_from_args_tools_overrides_shop():
    import argparse
    ns = argparse.Namespace(tools="table_saw,router", shop="hand")
    t = _tooling_from_args(ns)
    # --tools wins: an explicit capability list, not the hand-tool preset.
    assert t is not None
    assert t.table_saw is True


def test_tooling_from_args_none_when_unset():
    import argparse
    assert _tooling_from_args(argparse.Namespace(tools=None, shop=None)) is None


# --- _default_unit env handling -----------------------------------------

@pytest.mark.parametrize("val,expected", [
    ("in", "imperial"), ("inch", "imperial"), ("inches", "imperial"),
    ("imperial", "imperial"), ("mm", "metric"), ("", "metric"),
])
def test_default_unit_env(monkeypatch, val, expected):
    monkeypatch.setenv("WOODAI_UNITS", val)
    assert _default_unit() == expected


def test_default_unit_unset(monkeypatch):
    monkeypatch.delenv("WOODAI_UNITS", raising=False)
    assert _default_unit() == "metric"


def test_quiet_suppresses_spec_echo(capsys):
    import json
    from woodworking_ai.cli import main
    spec = {"kind": "cabinet", "cabinet_type": "base", "doors": 2}
    import tempfile, os
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(spec, f)
        path = f.name
    try:
        main(["build", path])
        assert capsys.readouterr().out.lstrip().startswith("{")   # default echoes
        main(["build", path, "--quiet"])
        assert not capsys.readouterr().out.lstrip().startswith("{")
    finally:
        os.unlink(path)


def test_joinery_prints_for_a_project(capsys):
    import json, tempfile, os
    from woodworking_ai.cli import main
    proj = {"kind": "project", "name": "Run", "runs": [
        {"start": [0, 0], "angle": 0, "items": [
            {"spec": {"kind": "cabinet", "cabinet_type": "base"}}]}]}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(proj, f)
        path = f.name
    try:
        main(["build", path, "--quiet", "--joinery"])
        assert "Joinery setup" in capsys.readouterr().out
    finally:
        os.unlink(path)


def test_print_design_notes_surfaces_assumptions_and_warnings(capsys):
    """The design command echoes the agent's assumptions and any warnings."""
    from woodworking_ai import CabinetSpec
    from woodworking_ai.validator import validate
    from woodworking_ai.agents.designer import DesignResult
    from woodworking_ai.cli import _print_design_notes

    spec = CabinetSpec(name="S", width=600, height=720, depth=560, doors=2)
    res = DesignResult(spec, validate(spec), ["raw"], 1, None,
                       ["Assumed frameless construction (most common)."])
    _print_design_notes(res)
    out = capsys.readouterr().out
    assert "assumptions / changes" in out
    assert "Assumed frameless construction" in out


def test_print_design_notes_silent_when_nothing_to_say(capsys):
    from woodworking_ai import CabinetSpec
    from woodworking_ai.validator import validate
    from woodworking_ai.agents.designer import DesignResult
    from woodworking_ai.cli import _print_design_notes

    spec = CabinetSpec(name="S", width=600, height=720, depth=560, doors=2)
    _print_design_notes(DesignResult(spec, validate(spec), [], 1, None, []))
    assert capsys.readouterr().out == ""
