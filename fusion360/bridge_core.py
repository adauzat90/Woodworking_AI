"""Pure, Fusion-free core for the folder bridge.

Kept deliberately free of ``adsk`` imports so it can be unit-tested outside
Fusion. It only turns a raw request (parsed JSON) into a normalized spec source
plus build options, and flattens a validator result into a JSON-able dict. The
actual geometry placement (which needs Fusion) lives in ``WoodworkingAI.py``.

Request shapes accepted:

* an **envelope** -- ``{"spec": {...}, "options": {...}}`` to build an existing
  spec, or ``{"prompt": "...", "options": {...}}`` to have Claude design one;
* a **bare spec** -- any other object is treated as the spec itself.
"""


_DEFAULT_OPTIONS = {
    "machined": True,          # cut dados/rabbets/grooves + bores
    "by_subassembly": True,    # one Fusion component per buildable unit
    "write_reports": False,    # write cut list + drilling CSV to the outbox
    "run_critic": True,        # (design only) run the CAD-free geometry critic
    "model": None,             # (design only) override the Claude model
    "new_document": False,     # build into a fresh Fusion document, not the active one
}


def normalize_options(raw):
    """Merge *raw* option overrides onto the defaults (unknown keys ignored)."""
    raw = raw or {}
    opts = dict(_DEFAULT_OPTIONS)
    for key in opts:
        if key in raw:
            opts[key] = raw[key]
    opts["machined"] = bool(opts["machined"])
    opts["by_subassembly"] = bool(opts["by_subassembly"])
    opts["write_reports"] = bool(opts["write_reports"])
    opts["run_critic"] = bool(opts["run_critic"])
    opts["new_document"] = bool(opts["new_document"])
    return opts


def normalize_request(request):
    """Return ``{"prompt", "spec", "options"}`` for any accepted request shape.

    ``prompt`` and ``spec`` are mutually exclusive-ish: if a prompt is present it
    wins (the spec is designed, not read). Exactly one should drive the build.
    """
    if isinstance(request, dict) and ("spec" in request or "prompt" in request):
        return {
            "prompt": request.get("prompt"),
            "spec": request.get("spec"),
            "options": normalize_options(request.get("options")),
        }
    # Bare spec: the whole object is the spec, all options default.
    return {"prompt": None, "spec": request, "options": normalize_options(None)}


def validation_dict(result):
    """Flatten a ``validator.validate`` result into a JSON-serializable dict."""
    return {
        "ok": bool(result.ok),
        "errors": [{"field": i.field, "message": i.message}
                   for i in result.errors],
        "warnings": [{"field": i.field, "message": i.message}
                     for i in result.warnings],
    }
