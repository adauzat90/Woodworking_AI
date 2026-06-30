"""Woodworking AI -- Fusion 360 add-in (Phase 2).

Adds an **Import Woodworking AI Spec** button to the Solid tab. It reads a
Woodworking AI spec (the same JSON the CLI and web app use), validates it with
the project's own validator, compiles it to **native Fusion geometry** via
:mod:`adapter` (no build123d / OpenCascade needed), and writes the cut list and
32 mm drilling schedule next to the spec file.

Phase 2 adds a dialog with options:

* **Cut joinery & bores** -- machine-honest dados/rabbets/grooves and bores from
  the project's own joinery + drilling schedules (the same numbers as the setup
  sheets), instead of plain slabs.
* **Component per subassembly** -- each buildable unit (Carcass, Doors, Drawer
  box, Countertop…) becomes its own Fusion component for a real assembly tree.
* The spec's primary dimensions are written as Fusion **user parameters** for
  reference.

The pure-Python ``woodworking_ai`` package (zero third-party deps) is reused
verbatim -- only the geometry *backend* is swapped for Fusion's API. See
``README.md`` in this folder for install instructions and the phase plan.
"""

import os
import sys
import json
import traceback

import adsk.core
import adsk.fusion

CMD_ID = "WoodworkingAI_ImportSpec"
CMD_NAME = "Import Woodworking AI Spec"
CMD_TOOLTIP = (
    "Import a Woodworking AI spec (JSON) as native Fusion geometry, with a "
    "cut list and 32 mm drilling schedule."
)
PANEL_ID = "SolidCreatePanel"

_app = None
_ui = None
_handlers = []          # keep handler refs alive
_state = {"spec_path": None}


# ---------------------------------------------------------------------------
# Make the pure-Python woodworking_ai package importable.
# ---------------------------------------------------------------------------
def _ensure_woodworking_ai_on_path():
    """Add the first location that actually contains ``woodworking_ai``.

    Tried in order so the add-in works both in-repo (this folder lives under the
    repository, beside ``src/``) and when distributed (copy ``woodworking_ai/``
    or ``src/`` next to this file).
    """
    here = os.path.dirname(os.path.realpath(__file__))
    candidates = [
        here,                                   # ./woodworking_ai
        os.path.join(here, "vendor"),           # ./vendor/woodworking_ai
        os.path.join(here, "src"),              # ./src/woodworking_ai
        os.path.join(here, "..", "src"),        # repo: ../src/woodworking_ai
    ]
    for path in candidates:
        path = os.path.realpath(path)
        if os.path.isdir(os.path.join(path, "woodworking_ai")):
            if path not in sys.path:
                sys.path.insert(0, path)
            return path
    return None


# ---------------------------------------------------------------------------
# Reports written beside the spec.
# ---------------------------------------------------------------------------
def _write_reports(spec, spec_path):
    """Write ``<spec>_cutlist.csv`` and ``<spec>_drilling.csv``; return notes."""
    from woodworking_ai.cutlist import generate_cutlist

    base, _ = os.path.splitext(spec_path)
    notes = []

    cutlist = generate_cutlist(spec)
    cut_path = base + "_cutlist.csv"
    with open(cut_path, "w", encoding="utf-8") as fh:
        fh.write(cutlist.to_csv())
    part_count = sum(p.qty for p in cutlist.parts)
    notes.append(f"{part_count} parts -> {os.path.basename(cut_path)}")

    try:
        from woodworking_ai.drilling import drilling_schedule

        sched = drilling_schedule(spec)
        drill_path = base + "_drilling.csv"
        with open(drill_path, "w", encoding="utf-8") as fh:
            fh.write(sched.to_csv())
        notes.append(
            f"{sched.total_holes} holes -> {os.path.basename(drill_path)}"
        )
    except Exception:
        notes.append("drilling schedule skipped (see Text Commands log)")
    return cutlist, notes


def _validation_blurb(result):
    """A short human summary of validation errors/warnings, or '' if clean."""
    if result.ok and not result.warnings:
        return ""
    lines = []
    for issue in result.errors:
        lines.append(f"  ERROR  {issue.field}: {issue.message}")
    for issue in result.warnings[:10]:
        lines.append(f"  warn   {issue.field}: {issue.message}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The build, given a chosen spec + options.
# ---------------------------------------------------------------------------
def _do_build(spec_path, *, machined, by_subassembly, write_reports):
    root_path = _ensure_woodworking_ai_on_path()
    if not root_path:
        _ui.messageBox(
            "Could not find the 'woodworking_ai' package.\n\n"
            "Place this add-in inside the repository (beside 'src/'), or copy "
            "the 'woodworking_ai' folder next to WoodworkingAI.py.",
            CMD_NAME,
        )
        return

    from woodworking_ai.dsl import spec_from_dict
    from woodworking_ai.validator import validate
    import adapter  # local module

    try:
        with open(spec_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        spec = spec_from_dict(data)
    except Exception as exc:
        _ui.messageBox(f"Could not load spec:\n{exc}", CMD_NAME)
        return

    result = validate(spec)
    blurb = _validation_blurb(result)
    if not result.ok:
        proceed = _ui.messageBox(
            "The spec has validation errors:\n\n"
            f"{blurb}\n\nBuild the geometry anyway?",
            CMD_NAME,
            adsk.core.MessageBoxButtonTypes.YesNoButtonType,
            adsk.core.MessageBoxIconTypes.WarningIconType,
        )
        if proceed != adsk.core.DialogResults.DialogYes:
            return

    design = adsk.fusion.Design.cast(_app.activeProduct)
    if not design:
        _ui.messageBox("Open or create a Fusion Design document first.", CMD_NAME)
        return

    component, bodies = adapter.import_spec(
        spec, design, machined=machined, by_subassembly=by_subassembly
    )

    notes = []
    if write_reports:
        _, notes = _write_reports(spec, spec_path)

    _app.activeViewport.fit()

    summary = [
        f"Imported '{component.name}'.",
        f"{len(bodies)} panels built as native Fusion bodies"
        + (" (machined)" if machined else "")
        + (", grouped by subassembly." if by_subassembly else "."),
    ]
    if notes:
        summary += ["", *notes]
    if blurb:
        summary += ["", "Validation:", blurb]
    _ui.messageBox("\n".join(summary), CMD_NAME)


# ---------------------------------------------------------------------------
# Command dialog plumbing.
# ---------------------------------------------------------------------------
def _pick_spec():
    dlg = _ui.createFileDialog()
    dlg.title = "Select a Woodworking AI spec"
    dlg.filter = "Woodworking AI spec (*.json);;All files (*.*)"
    if dlg.showOpen() == adsk.core.DialogResults.DialogOK:
        return dlg.filename
    return None


class _InputChangedHandler(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        try:
            if args.input.id != "browse":
                return
            path = _pick_spec()
            if not path:
                return
            _state["spec_path"] = path
            text = args.inputs.itemById("specPath")
            if text:
                text.text = os.path.basename(path)
        except Exception:
            if _ui:
                _ui.messageBox(traceback.format_exc(), CMD_NAME)


class _ExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            inputs = args.command.commandInputs
            path = _state.get("spec_path")
            if not path:
                _ui.messageBox("No spec selected — click Browse first.", CMD_NAME)
                return
            _do_build(
                path,
                machined=inputs.itemById("machined").value,
                by_subassembly=inputs.itemById("bysub").value,
                write_reports=inputs.itemById("reports").value,
            )
        except Exception:
            if _ui:
                _ui.messageBox(
                    "Woodworking AI import failed:\n" + traceback.format_exc(),
                    CMD_NAME,
                )


class _CommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd = args.command
            inputs = cmd.commandInputs

            # Pick the spec up front so the dialog can show the chosen file.
            _state["spec_path"] = _pick_spec()
            shown = (os.path.basename(_state["spec_path"])
                     if _state["spec_path"] else "<none — click Browse>")

            text = inputs.addTextBoxCommandInput("specPath", "Spec file",
                                                 shown, 1, True)
            text.isFullWidth = True
            inputs.addBoolValueInput("browse", "Browse…", False)
            inputs.addBoolValueInput("machined", "Cut joinery & bores",
                                     True, "", True)
            inputs.addBoolValueInput("bysub", "Component per subassembly",
                                     True, "", True)
            inputs.addBoolValueInput("reports", "Write cut list + drilling CSV",
                                     True, "", True)

            on_changed = _InputChangedHandler()
            cmd.inputChanged.add(on_changed)
            _handlers.append(on_changed)

            on_execute = _ExecuteHandler()
            cmd.execute.add(on_execute)
            _handlers.append(on_execute)
        except Exception:
            if _ui:
                _ui.messageBox(traceback.format_exc(), CMD_NAME)


def run(context):
    global _app, _ui
    try:
        _app = adsk.core.Application.get()
        _ui = _app.userInterface
        _ensure_woodworking_ai_on_path()

        cmd_def = _ui.commandDefinitions.itemById(CMD_ID)
        if not cmd_def:
            cmd_def = _ui.commandDefinitions.addButtonDefinition(
                CMD_ID, CMD_NAME, CMD_TOOLTIP
            )

        handler = _CommandCreatedHandler()
        cmd_def.commandCreated.add(handler)
        _handlers.append(handler)

        panel = _ui.allToolbarPanels.itemById(PANEL_ID)
        if panel and not panel.controls.itemById(CMD_ID):
            panel.controls.addCommand(cmd_def)
    except Exception:
        if _ui:
            _ui.messageBox("Add-in start failed:\n" + traceback.format_exc())


def stop(context):
    try:
        panel = _ui.allToolbarPanels.itemById(PANEL_ID)
        if panel:
            ctrl = panel.controls.itemById(CMD_ID)
            if ctrl:
                ctrl.deleteMe()
        cmd_def = _ui.commandDefinitions.itemById(CMD_ID)
        if cmd_def:
            cmd_def.deleteMe()
        _handlers.clear()
    except Exception:
        if _ui:
            _ui.messageBox("Add-in stop failed:\n" + traceback.format_exc())
