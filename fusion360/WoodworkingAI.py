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

CMD_AI_ID = "WoodworkingAI_Design"
CMD_AI_NAME = "Design with Woodworking AI"
CMD_AI_TOOLTIP = (
    "Describe furniture in plain language; Claude writes a validated spec and "
    "it is built as native Fusion geometry. Needs an Anthropic API key."
)
PANEL_ID = "SolidCreatePanel"

_PROMPT_EXAMPLE = "36 inch sink base, two shaker doors, soft-close, one shelf"

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


def _resolve_api_key():
    """The Anthropic API key from the env or a key file, or ``None``.

    Checked in order: ``ANTHROPIC_API_KEY``; ``anthropic_key.txt`` next to this
    add-in; ``~/.woodai/anthropic_key``. A key file keeps the secret out of the
    (unmasked) command dialog.
    """
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key and key.strip():
        return key.strip()
    here = os.path.dirname(os.path.realpath(__file__))
    for path in (os.path.join(here, "anthropic_key.txt"),
                 os.path.expanduser("~/.woodai/anthropic_key")):
        try:
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as fh:
                    text = fh.read().strip()
                if text:
                    return text
        except Exception:
            pass
    return None


def _place_spec(spec, *, machined, by_subassembly):
    """Build *spec* into the active design; return ``(component, bodies)`` or None."""
    design = adsk.fusion.Design.cast(_app.activeProduct)
    if not design:
        _ui.messageBox("Open or create a Fusion Design document first.", CMD_NAME)
        return None
    import adapter  # local module

    component, bodies = adapter.import_spec(
        spec, design, machined=machined, by_subassembly=by_subassembly
    )
    _app.activeViewport.fit()
    return component, bodies


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

    placed = _place_spec(spec, machined=machined, by_subassembly=by_subassembly)
    if not placed:
        return
    component, bodies = placed

    notes = []
    if write_reports:
        _, notes = _write_reports(spec, spec_path)

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
# The AI designer: natural language -> validated spec -> geometry.
# ---------------------------------------------------------------------------
def _do_design(prompt, *, model, machined, by_subassembly, run_critic,
               save_spec):
    root_path = _ensure_woodworking_ai_on_path()
    if not root_path:
        _ui.messageBox(
            "Could not find the 'woodworking_ai' package — see the add-in "
            "README for install steps.", CMD_AI_NAME,
        )
        return

    api_key = _resolve_api_key()
    if not api_key:
        _ui.messageBox(
            "No Anthropic API key found.\n\nSet the ANTHROPIC_API_KEY "
            "environment variable, or put the key in 'anthropic_key.txt' next "
            "to this add-in (or ~/.woodai/anthropic_key), then try again.",
            CMD_AI_NAME,
        )
        return

    from woodworking_ai.agents import llm
    from woodworking_ai.agents.designer import design_from_prompt
    from anthropic_client import AnthropicHTTPClient

    llm.set_client(AnthropicHTTPClient(api_key))
    try:
        result = design_from_prompt(
            prompt, model=(model or None), run_critic=run_critic
        )
    except Exception as exc:
        _ui.messageBox(f"The AI designer failed:\n{exc}", CMD_AI_NAME)
        return
    finally:
        llm.set_client(None)   # never leave the injected client behind

    spec = result.spec
    placed = _place_spec(spec, machined=machined, by_subassembly=by_subassembly)
    if not placed:
        return
    component, bodies = placed

    notes = []
    if save_spec:
        dlg = _ui.createFileDialog()
        dlg.title = "Save the generated spec"
        dlg.filter = "Woodworking AI spec (*.json)"
        dlg.initialFilename = (getattr(spec, "name", None) or "design") + ".json"
        if dlg.showSave() == adsk.core.DialogResults.DialogOK:
            spec_path = dlg.filename
            try:
                with open(spec_path, "w", encoding="utf-8") as fh:
                    fh.write(spec.to_json())
                notes.append(f"spec -> {os.path.basename(spec_path)}")
                _, report_notes = _write_reports(spec, spec_path)
                notes += report_notes
            except Exception as exc:
                notes.append(f"could not save spec: {exc}")

    crit_line = ""
    if result.critique is not None:
        crit_line = "geometry critic: " + ("passed" if result.critique.ok
                                           else "flagged issues (see spec)")
    summary = [
        f"Designed '{component.name}' in {result.attempts} attempt(s).",
        f"validation: {'passed' if result.validation.ok else 'has errors'}",
    ]
    if crit_line:
        summary.append(crit_line)
    summary.append(
        f"{len(bodies)} panels built"
        + (" (machined)" if machined else "")
        + (", grouped by subassembly." if by_subassembly else ".")
    )
    if notes:
        summary += ["", *notes]
    _ui.messageBox("\n".join(summary), CMD_AI_NAME)


class _DesignCommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd = args.command
            inputs = cmd.commandInputs

            prompt = inputs.addTextBoxCommandInput(
                "prompt", "Describe the furniture", _PROMPT_EXAMPLE, 3, False
            )
            prompt.isFullWidth = True
            inputs.addStringValueInput("model", "Model (blank = default)", "")
            inputs.addBoolValueInput("machined", "Cut joinery & bores",
                                     True, "", True)
            inputs.addBoolValueInput("bysub", "Component per subassembly",
                                     True, "", True)
            inputs.addBoolValueInput("critic", "Run geometry critic",
                                     True, "", True)
            inputs.addBoolValueInput("savespec", "Save spec + cut list",
                                     True, "", True)

            on_execute = _DesignExecuteHandler()
            cmd.execute.add(on_execute)
            _handlers.append(on_execute)
        except Exception:
            if _ui:
                _ui.messageBox(traceback.format_exc(), CMD_AI_NAME)


class _DesignExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            inputs = args.command.commandInputs
            prompt = inputs.itemById("prompt").text.strip()
            if not prompt:
                _ui.messageBox("Describe the furniture first.", CMD_AI_NAME)
                return
            _do_design(
                prompt,
                model=inputs.itemById("model").value.strip(),
                machined=inputs.itemById("machined").value,
                by_subassembly=inputs.itemById("bysub").value,
                run_critic=inputs.itemById("critic").value,
                save_spec=inputs.itemById("savespec").value,
            )
        except Exception:
            if _ui:
                _ui.messageBox(
                    "Woodworking AI design failed:\n" + traceback.format_exc(),
                    CMD_AI_NAME,
                )


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

        ai_def = _ui.commandDefinitions.itemById(CMD_AI_ID)
        if not ai_def:
            ai_def = _ui.commandDefinitions.addButtonDefinition(
                CMD_AI_ID, CMD_AI_NAME, CMD_AI_TOOLTIP
            )
        ai_handler = _DesignCommandCreatedHandler()
        ai_def.commandCreated.add(ai_handler)
        _handlers.append(ai_handler)

        panel = _ui.allToolbarPanels.itemById(PANEL_ID)
        if panel:
            if not panel.controls.itemById(CMD_ID):
                panel.controls.addCommand(cmd_def)
            if not panel.controls.itemById(CMD_AI_ID):
                panel.controls.addCommand(ai_def)
    except Exception:
        if _ui:
            _ui.messageBox("Add-in start failed:\n" + traceback.format_exc())


def stop(context):
    try:
        panel = _ui.allToolbarPanels.itemById(PANEL_ID)
        for cmd_id in (CMD_ID, CMD_AI_ID):
            if panel:
                ctrl = panel.controls.itemById(cmd_id)
                if ctrl:
                    ctrl.deleteMe()
            cmd_def = _ui.commandDefinitions.itemById(cmd_id)
            if cmd_def:
                cmd_def.deleteMe()
        _handlers.clear()
    except Exception:
        if _ui:
            _ui.messageBox("Add-in stop failed:\n" + traceback.format_exc())
