"""Appliance schedule for the build package.

A kitchen's appliances drive work the cabinets alone don't show: a sink/cooktop
cut-out routed in a countertop, a finished panel on a panel-ready dishwasher, a
gap reserved for a range, and the plumbing/electric rough-in behind each. This
module rolls those up into one schedule the build package and the web bundle can
render — one row per appliance, listing its host, cut-out size, the clearances
it needs, any panel-ready panels, and free-text rough-in notes.

Pure data — no CAD. It reads the typed :class:`~dsl.Appliance` cut-outs hosted by
cabinets (:func:`~dsl.appliances_of`) and the :class:`~dsl.ApplianceVoid` gaps
placed in a run, so a single cabinet *or* a whole :class:`~dsl.Project` works.
"""

from __future__ import annotations

from .dsl import (
    Appliance, ApplianceVoid, ComponentGroup, appliances_of,
    APPLIANCE_VOID_WIDTHS,
)
from .geometry import component_tag

# Free-text rough-in notes per appliance type: what the trades need to bring to
# the opening. Kept human-readable — these print straight into the package.
_ROUGH_IN = {
    "sink": "Plumbing: hot/cold supply + trapped waste below; vent per code.",
    "cooktop": "Electric: dedicated 230V circuit (or gas line for gas); "
               "no outlet directly behind the cut-out.",
    "range": "Electric: dedicated high-load circuit (or gas line); "
             "anti-tip bracket anchored to the floor/wall.",
    "wall_oven": "Electric: dedicated high-load circuit to the cabinet opening.",
    "dishwasher": "Plumbing: supply + drain to the adjacent sink trap; "
                  "Electric: switched outlet in the neighbouring cabinet.",
    "fridge": "Electric: dedicated outlet behind the gap; "
              "water line if plumbed for ice/water.",
    "microwave": "Electric: outlet in the cabinet above / behind.",
    "hood": "Electric: switched outlet; duct the exhaust to outside.",
}

# Standard clearances each appliance asks for, in plain language.
_CLEARANCES = {
    "sink": "centre the cut-out over the sink base; keep 50mm of counter "
            "front and back.",
    "cooktop": "min. combustible clearance to side walls; hood above per the "
               "cooktop spec.",
    "range": "30mm side air-gap typical; non-combustible or spaced side panels.",
    "wall_oven": "follow the oven's cabinet-cutout spec for height and depth.",
    "dishwasher": "~600mm clear opening, full counter depth, level to the "
                  "neighbours.",
    "fridge": "≥25mm top/side air-gap; door swing clear of adjacent fronts.",
    "microwave": "vent clearance per the unit; support the shelf for its weight.",
    "hood": "mounting height above the cooktop per the hood spec.",
}


def _type_str(t) -> str:
    return t.value if hasattr(t, "value") else str(t)


def _clearance(atype: str, void: ApplianceVoid | None = None) -> str:
    base = _CLEARANCES.get(atype, "follow the appliance's installation spec.")
    if void is not None:
        widths = APPLIANCE_VOID_WIDTHS.get(atype)
        if widths:
            std = "/".join(f"{w:.0f}" for w in widths)
            base = f"standard opening ~{std}mm; " + base
    return base


def _entry(atype: str, *, host: str, cutout: tuple | None,
           panel_ready: bool, void: ApplianceVoid | None = None) -> dict:
    """One appliance-schedule row as a plain dict."""
    return {
        "type": atype,
        "host": host,
        "cutout": (f"{cutout[0]:.0f}×{cutout[1]:.0f}mm"
                   if cutout and cutout[0] and cutout[1] else ""),
        "clearances": _clearance(atype, void),
        "panels": ("finished panel (panel-ready)" if panel_ready else ""),
        "rough_in": _ROUGH_IN.get(atype, ""),
    }


def _spec_entries(spec, host: str) -> list[dict]:
    """Schedule rows for the cut-out appliances hosted by one cabinet *spec*."""
    out: list[dict] = []
    for a in appliances_of(spec):
        atype = _type_str(a.type)
        cutout = (a.cutout_w, a.cutout_d) if (a.cutout_w or a.cutout_d) else None
        out.append(_entry(atype, host=host, cutout=cutout,
                          panel_ready=bool(a.panel_ready)))
    return out


def appliance_schedule(spec) -> list[dict]:
    """The appliance schedule for *spec* — a cabinet, table, or whole project.

    Returns one dict per appliance with ``type``, ``host`` (the cabinet label or
    gap name), ``cutout`` size, required ``clearances``, panel-ready ``panels``,
    and free-text ``rough_in`` notes. Empty when the design has no appliances, so
    the report/web bundle can show the section only when it has rows.
    """
    if isinstance(spec, ComponentGroup):
        out: list[dict] = []
        for i, comp in enumerate(spec.components, start=1):
            tag = component_tag(comp, i)
            sub = comp.spec
            if isinstance(sub, ApplianceVoid):
                atype = _type_str(sub.type)
                out.append(_entry(
                    atype, host=f"{tag} ({sub.name})", cutout=None,
                    panel_ready=False, void=sub))
            elif isinstance(sub, ComponentGroup):
                out.extend(appliance_schedule(sub))
            else:
                out.extend(_spec_entries(sub, host=tag))
        return out
    if isinstance(spec, (Appliance, ApplianceVoid)):
        return []
    return _spec_entries(spec, host=getattr(spec, "name", "") or "cabinet")
