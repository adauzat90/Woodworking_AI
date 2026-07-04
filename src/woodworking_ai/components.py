"""Shared parametric sub-components — reusable furniture substructures.

A :class:`Subcomponent` is a building block that recurs across furniture: a
four-leg base, a run of shelves, … Unlike a :class:`~furniture.LeafFurniture`
(a whole buildable piece registered under a dispatch kind), a component is *not*
a leaf kind — it is composed *inside* leaves and generic ``piece`` specs. Each
component owns, in one place, the four things that used to be re-derived per
furniture type and could drift between them:

* ``panels(origin)``     → ``list[PanelBox]`` placed relative to a min-corner
  *origin* (so the same math serves an X-centred leaf and a min-corner piece);
* ``cut_parts()``        → ``list[Part]`` (raw — the caller assigns IDs/stock);
* ``joinery_ops(cl, …)`` → ``list[JoineryOp]`` for the component's own joints;
* ``validate()``         → ``list[Issue]`` — the component's OWN compiler rules.

The parameters are a dataclass with ``from_dict``/``to_dict`` and imperial
conversion in the ``dsl._to_mm`` style, so a component instance can be authored
in a ``piece`` spec (``{"component": "legged_base", "at": […], …}``) exactly the
way a part is. Pure math; no CAD dependency.

Two concrete components live here:

* :class:`LeggedBase` — four legs + aprons + optional stretchers. Consolidates
  the leg/apron/stretcher layout and the legged compiler rules (leg fit,
  leg-section sanity, slenderness, apron-vs-leg mortise room, stretcher setback)
  that bench / workbench (and, historically, the table) each hand-rolled.
* :class:`ShelfBank` — a run of evenly spaced shelves between two uprights, with
  the shelf-sag and shelf-spacing rules that ``wall_shelf`` / the cabinet
  bookcase use, so garage-shelving-style pieces get real deflection checks.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, fields

from . import engineering
from .dsl import leg_section, leg_stock_note, joinery_key
from .geometry import PanelBox
from .cutlist import CutList, Part
from .materials import MAT_LEG, MAT_APRON, MAT_SOLID, MAT_SHEET
from .validator import Issue
from .joinery import JoineryOp
from .materials import is_solid_form


def _finite_positive(v) -> bool:
    return isinstance(v, (int, float)) and math.isfinite(v) and v > 0


def _translate(panels: list[PanelBox], origin) -> list[PanelBox]:
    """Shift every panel centre by *origin* (a component's min-corner anchor)."""
    ox, oy, oz = origin
    for p in panels:
        cx, cy, cz = p.center
        p.center = (cx + ox, cy + oy, cz + oz)
    return panels


# ===========================================================================
# LeggedBase — four legs + aprons + optional stretchers
# ===========================================================================

@dataclass(frozen=True)
class _LeggedNaming:
    """Cosmetic labels/notes so re-based leaves stay byte-identical.

    The *geometry* and *rules* are shared (that is the anti-drift win); only the
    part names and note strings differ between a bench ("Seat", "Apron short")
    and a workbench ("Top", "Apron side"). Not user-facing — never serialised.
    """
    piece_noun: str = "base"           # used in advisory messages ("…-tall base")
    surface_noun: str = "top"          # "top" | "seat" — the surface above the legs
    leg_note_prefix: str = ""          # e.g. "heavy " for a workbench leg
    long_apron_panel: str = "Apron front/back"
    long_apron_cut: str = "Apron front/back"
    long_apron_note: str = ""
    side_apron_panel: str = "Apron side"
    side_apron_cut: str = "Apron side"
    side_apron_note: str = ""
    stretcher_note: str = "lower rail, resists racking"
    base_unit: str = "Base"            # subassembly for legs + aprons
    stretcher_unit: str = "Stretchers"


# Legroom for the slenderness advisory (fraction of overall height), matching
# proportion.LEG_MIN_RATIO / LEG_MAX_RATIO so the rule can't drift from table's.
_LEG_SPINDLY_FACTOR = 0.06
_LEG_HEAVY_FACTOR = 0.08


@dataclass
class LeggedBase:
    """Four legs joined by aprons and optional lower stretchers.

    Parameterised by the overall envelope (``width`` × ``depth`` × ``height``),
    the leg section (``leg`` = X-face, ``leg_depth`` = Y-face, 0 = square — the
    :func:`dsl.leg_section` convention), ``leg_inset``, the apron section
    (``apron_height`` / ``apron_thickness``), and the stretcher run. ``height`` is
    the surface height; the legs run ``height - top_thickness`` and the surface
    itself is the composing leaf's concern, not the base's.

    The layout is computed in a local min-corner frame (the base occupies
    ``[0,width] × [0,depth] × [0,height]``) and translated to ``panels(origin)``'s
    origin, so an X-centred leaf passes ``origin=(-width/2, -depth/2, 0)`` and a
    min-corner piece passes the instance's ``at``.
    """

    name: str = "Base"
    at: tuple[float, float, float] = (0.0, 0.0, 0.0)
    width: float = 900.0
    depth: float = 450.0
    height: float = 740.0
    top_thickness: float = 20.0
    leg: float = 60.0
    leg_depth: float = 0.0
    leg_inset: float = 40.0
    apron_height: float = 90.0
    apron_thickness: float = 20.0
    leg_taper: bool = False
    leg_tip: float = 0.0
    stretchers: bool = False
    stretcher_height: float = 40.0
    stretcher_thickness: float = 22.0
    stretcher_setback: float = 150.0
    joinery: str = "mortise_tenon"

    # Cosmetic only (see _LeggedNaming); excluded from to_dict.
    naming: _LeggedNaming = field(default_factory=_LeggedNaming)

    component = "legged_base"
    _LENGTH_FIELDS = (
        "width", "depth", "height", "top_thickness", "leg", "leg_depth",
        "leg_inset", "apron_height", "apron_thickness", "leg_tip",
        "stretcher_height", "stretcher_thickness", "stretcher_setback",
    )

    # --- derived geometry --------------------------------------------------
    def _layout(self):
        """``(lx, ly, apron_x, apron_y, leg_x, leg_y, leg_h, az)`` for the base.

        ``lx``/``ly`` are the leg-centre offsets from the footprint centre;
        ``apron_x``/``apron_y`` the clear apron lengths between the legs; ``az``
        the apron centre height. Mirrors ``furniture_types._leg_offsets_and_aprons``
        so a re-based leaf is byte-identical.
        """
        leg_x, leg_y = leg_section(self)
        lx = self.width / 2 - self.leg_inset - leg_x / 2
        ly = self.depth / 2 - self.leg_inset - leg_y / 2
        apron_x = 2 * lx - leg_x
        apron_y = 2 * ly - leg_y
        leg_h = self.height - self.top_thickness
        az = self.height - self.top_thickness - self.apron_height / 2
        return lx, ly, apron_x, apron_y, leg_x, leg_y, leg_h, az

    # --- stage: panels -----------------------------------------------------
    def panels(self, origin=None) -> list[PanelBox]:
        """Legs, four aprons, and (optionally) two stretchers, min-corner local.

        Legs are emitted ``Leg 1..4`` in ``(left,right) × (front,back)`` order;
        the aprons canonically long-pair then side-pair; the stretchers along the
        long sides — the exact order the bench/workbench layouts used, so a
        re-based leaf's panel list is unchanged.
        """
        if origin is None:
            origin = self.at
        n = self.naming
        lx, ly, apron_x, apron_y, leg_x, leg_y, leg_h, az = self._layout()
        cx, cy = self.width / 2, self.depth / 2
        panels: list[PanelBox] = []

        def add(label, size, center, category, unit):
            panels.append(PanelBox(label, size, center, category, subassembly=unit))

        k = 0
        for sx in (-1, 1):
            for sy in (-1, 1):
                k += 1
                add(f"Leg {k}", (leg_x, leg_y, leg_h),
                    (cx + sx * lx, cy + sy * ly, leg_h / 2), "leg", n.base_unit)
        for sy in (-1, 1):
            add(n.long_apron_panel, (apron_x, self.apron_thickness, self.apron_height),
                (cx, cy + sy * ly, az), "apron", n.base_unit)
        for sx in (-1, 1):
            add(n.side_apron_panel, (self.apron_thickness, apron_y, self.apron_height),
                (cx + sx * lx, cy, az), "apron", n.base_unit)
        if self.stretchers:
            for sy in (-1, 1):
                add("Stretcher",
                    (apron_x, self.stretcher_thickness, self.stretcher_height),
                    (cx, cy + sy * ly, self.stretcher_setback), "stretcher",
                    n.stretcher_unit)
        return _translate(panels, origin)

    # --- stage: cut parts --------------------------------------------------
    def cut_parts(self) -> list[Part]:
        """Raw cut parts (Leg ×4, both apron pairs, Stretcher ×2 if enabled).

        Returns bare :class:`~cutlist.Part` objects with no ID / resolved stock —
        the composing leaf or piece appends them to its cut list and runs
        ``resolve_part_stock`` + ``assign_ids`` once over the merged list.
        """
        n = self.naming
        lx, ly, apron_x, apron_y, leg_x, leg_y, leg_h, _az = self._layout()
        parts = [
            Part("Leg", 4, length=leg_h, width=max(leg_x, leg_y),
                 thickness=min(leg_x, leg_y), material=MAT_LEG,
                 notes=n.leg_note_prefix + leg_stock_note(self)),
            Part(n.long_apron_cut, 2, length=apron_x, width=self.apron_height,
                 thickness=self.apron_thickness, material=MAT_APRON,
                 notes=n.long_apron_note),
            Part(n.side_apron_cut, 2, length=apron_y, width=self.apron_height,
                 thickness=self.apron_thickness, material=MAT_APRON,
                 notes=n.side_apron_note),
        ]
        if self.stretchers:
            parts.append(Part(
                "Stretcher", 2, length=apron_x, width=self.stretcher_height,
                thickness=self.stretcher_thickness, material=MAT_APRON,
                notes=n.stretcher_note))
        return parts

    # --- stage: joinery ----------------------------------------------------
    def joinery_ops(self, cl: CutList, prefix: str = "") -> list[JoineryOp]:
        """The leg-to-apron (+ leg-to-stretcher) joints, by joinery family.

        *prefix* namespaces the part-label lookup when the component's parts were
        merged into a larger cut list with prefixed names (a ``piece`` instance).
        """
        pid = cl.part_id_for_label
        j = joinery_key(self)
        if j == "mortise_tenon":
            tool, w, d, note = ("mortiser / saw", round(self.apron_thickness / 3, 1),
                                round(self.leg * 0.6, 1), "haunched M&T into the leg")
        elif j == "domino":
            tool, w, d, note = ("Festool Domino (10mm)", 10.0, 28.0,
                                "two 10×50 Dominoes per leg-apron joint")
        elif j == "dowel":
            tool, w, d, note = ("doweling jig (10mm)", 10.0, 30.0,
                                "two 10mm dowels per joint + corner block")
        else:
            tool, w, d, note = ("pocket-hole jig", 0.0, 0.0,
                                "pocket screws + glue blocks (racks more than M&T)")
        ops = [JoineryOp(
            part="Leg / apron", operation="leg-to-apron joint", tool=tool,
            width=w, depth=d, reference="apron into leg",
            part_id=pid(f"{prefix}Leg"), note=note)]
        if self.stretchers:
            ops.append(JoineryOp(
                part="Leg / stretcher", operation="leg-to-stretcher joint",
                tool=tool, width=w, depth=d, reference="stretcher into leg",
                part_id=pid(f"{prefix}Stretcher"), note="lower rail tenons into the leg"))
        return ops

    # --- stage: validate ---------------------------------------------------
    def validate(self) -> list[Issue]:
        """The legged base's own compiler rules.

        Structural feasibility first (positive sections, a valid leg section, the
        legs fitting the footprint, a tall-enough envelope); on any error it
        stops. Otherwise the geometry/proportion advisories run: apron-vs-leg
        mortise room, leg slenderness, and stretcher-setback sanity. Ported from
        the table/legged validators so messages and thresholds stay consistent;
        the *type-specific* advice (racking-under-load, ergonomic heights) stays
        with the composing leaf.
        """
        issues: list[Issue] = []

        def err(f, m, rule="", **kw):
            issues.append(Issue("error", f, m, rule, **kw))

        def warn(f, m, rule="", **kw):
            issues.append(Issue("warning", f, m, rule, **kw))

        def info(f, m, rule="", **kw):
            issues.append(Issue("info", f, m, rule, **kw))

        for name in ("width", "depth", "height", "top_thickness", "leg",
                     "apron_height", "apron_thickness", "leg_inset"):
            if not _finite_positive(getattr(self, name)):
                err(name,
                    f"must be a positive, finite number, got {getattr(self, name)!r}")
        ld = self.leg_depth
        if ld and not _finite_positive(ld):
            err("leg_depth",
                f"must be a positive, finite number when set (0 = square), got {ld!r}")
        if any(i.severity == "error" for i in issues):
            return issues

        surface = self.naming.surface_noun
        if self.height <= self.top_thickness + self.apron_height:
            err("height", f"too short for the {surface} plus an apron")
        leg_x, leg_y = leg_section(self)
        if (2 * self.leg_inset + leg_x >= self.width
                or 2 * self.leg_inset + leg_y >= self.depth):
            err("leg_inset",
                f"legs do not fit within the {surface} with this inset")
        if any(i.severity == "error" for i in issues):
            return issues

        # --- geometry / proportion advisories --------------------------------
        if self.apron_thickness >= self.leg:
            warn("apron_thickness", "apron is as thick as the leg; unusual")

        noun = self.naming.piece_noun
        slim = self.leg / self.height if self.height > 0 else 0.0
        if slim < 0.045:
            info("leg", f"a {self.leg:.0f}mm leg looks spindly under a "
                        f"{self.height:.0f}mm-tall {noun}; "
                        f"~{self.height * _LEG_SPINDLY_FACTOR:.0f}mm "
                        "reads sturdier", "PROP-002")
        elif slim > 0.13:
            info("leg", f"a {self.leg:.0f}mm leg looks heavy for a "
                        f"{self.height:.0f}mm {noun}; "
                        f"~{self.height * _LEG_HEAVY_FACTOR:.0f}mm is "
                        "lighter", "PROP-002")

        if self.stretchers:
            if self.stretcher_setback - self.stretcher_height / 2 < 0:
                warn("stretcher_setback",
                     "the stretcher sits below the floor; raise stretcher_setback")
            apron_underside = self.height - self.top_thickness - self.apron_height
            if self.stretcher_setback + self.stretcher_height / 2 > apron_underside:
                warn("stretcher_setback",
                     "the stretcher runs up into the apron zone; lower "
                     "stretcher_setback")
        return issues

    # --- (de)serialisation -------------------------------------------------
    def to_dict(self) -> dict:
        d = {"component": self.component, "name": self.name, "at": list(self.at)}
        for f in self._LENGTH_FIELDS:
            d[f] = getattr(self, f)
        d["stretchers"] = self.stretchers
        d["leg_taper"] = self.leg_taper
        d["joinery"] = self.joinery
        return d

    @classmethod
    def from_dict(cls, data: dict, naming: _LeggedNaming | None = None) -> "LeggedBase":
        known = {f.name for f in fields(cls)} - {"naming"}
        kw = {k: v for k, v in data.items() if k in known}
        if "at" in kw:
            kw["at"] = tuple(kw["at"]) if isinstance(kw["at"], (list, tuple)) \
                else (0.0, 0.0, 0.0)
        obj = cls(**kw)
        if naming is not None:
            object.__setattr__(obj, "naming", naming)
        return obj


# ===========================================================================
# ShelfBank — a run of evenly spaced shelves between two uprights
# ===========================================================================

@dataclass(frozen=True)
class _ShelfNaming:
    upright_panel: str = "Upright"
    upright_cut: str = "Upright"
    shelf_panel: str = "Shelf"
    shelf_cut: str = "Shelf"
    unit: str = "Shelving"


@dataclass
class ShelfBank:
    """A run of ``shelves`` evenly spaced horizontal boards between two uprights.

    Parameterised by the overall envelope (``width`` × ``depth`` × ``height``),
    the shelf/upright ``thickness``es, and either a shelf ``count`` or a
    ``spacing`` (spacing wins when > 0, deriving the count from the height). The
    shelves span the clear width between the uprights; the bank carries the
    shelf-deflection and shelf-spacing rules so a lumber-rack / garage-shelving
    piece gets a real sag check the way ``wall_shelf`` does.
    """

    name: str = "Shelving"
    at: tuple[float, float, float] = (0.0, 0.0, 0.0)
    width: float = 900.0
    depth: float = 400.0
    height: float = 1000.0
    shelf_thickness: float = 18.0
    upright_thickness: float = 38.0
    shelves: int = 3
    spacing: float = 0.0            # 0 = derive from `shelves`; else fixes the gap
    load_kg_per_m: float = 40.0
    species: str = ""
    material_form: str = ""

    naming: _ShelfNaming = field(default_factory=_ShelfNaming)

    component = "shelf_bank"
    _LENGTH_FIELDS = (
        "width", "depth", "height", "shelf_thickness", "upright_thickness",
        "spacing",
    )

    # --- derived geometry --------------------------------------------------
    @property
    def shelf_count(self) -> int:
        if self.spacing and self.spacing > 0 and self.height > 0:
            return max(int(self.height // self.spacing), 1)
        return max(int(self.shelves), 1)

    @property
    def clear_span(self) -> float:
        """Clear shelf span between the two upright inner faces (mm)."""
        return self.width - 2 * self.upright_thickness

    def _shelf_z_centers(self) -> list[float]:
        """Shelf centre heights, evenly distributed over the height.

        ``count`` shelves at ``height·(i+1)/(count+1)`` — evenly spaced without a
        shelf pinned to the floor or the very top.
        """
        n = self.shelf_count
        return [self.height * (i + 1) / (n + 1) for i in range(n)]

    # --- stage: panels -----------------------------------------------------
    def panels(self, origin=None) -> list[PanelBox]:
        if origin is None:
            origin = self.at
        nm = self.naming
        W, D, H, ut = self.width, self.depth, self.height, self.upright_thickness
        panels: list[PanelBox] = []

        def add(label, size, center, category):
            panels.append(PanelBox(label, size, center, category, subassembly=nm.unit))

        for i, x in enumerate(((ut / 2), (W - ut / 2)), start=1):
            add(f"{nm.upright_panel} {i}", (ut, D, H), (x, D / 2, H / 2), "carcass")
        span = self.clear_span
        for i, z in enumerate(self._shelf_z_centers(), start=1):
            add(f"{nm.shelf_panel} {i}", (span, D, self.shelf_thickness),
                (W / 2, D / 2, z), "shelf")
        return _translate(panels, origin)

    # --- stage: cut parts --------------------------------------------------
    def cut_parts(self) -> list[Part]:
        nm = self.naming
        mat = MAT_SOLID if (not self.material_form
                            or is_solid_form(self.material_form)) else MAT_SHEET
        parts = [
            Part(nm.upright_cut, 2, length=self.height, width=self.depth,
                 thickness=self.upright_thickness, material=mat,
                 notes="upright / end panel"),
            Part(nm.shelf_cut, self.shelf_count, length=self.clear_span,
                 width=self.depth, thickness=self.shelf_thickness, material=mat,
                 notes="shelf between the uprights"),
        ]
        return parts

    # --- stage: joinery ----------------------------------------------------
    def joinery_ops(self, cl: CutList, prefix: str = "") -> list[JoineryOp]:
        pid = cl.part_id_for_label
        return [JoineryOp(
            part="Shelf / upright", operation="shelf-to-upright housing",
            tool="dado / router", width=round(self.shelf_thickness, 1), depth=6.0,
            reference="housed dado in each upright", part_id=pid(f"{prefix}{self.naming.shelf_cut}"),
            note="each shelf housed into both uprights")]

    # --- stage: validate ---------------------------------------------------
    def validate(self) -> list[Issue]:
        """Shelf-span deflection + shelf-spacing sanity.

        Reuses :func:`engineering.evaluate_shelf` (the shelf "Sagulator") exactly
        as ``wall_shelf`` / the cabinet bookcase do, so the sag limits are
        consistent app-wide.
        """
        issues: list[Issue] = []

        def err(f, m, rule="", **kw):
            issues.append(Issue("error", f, m, rule, **kw))

        def warn(f, m, rule="", **kw):
            issues.append(Issue("warning", f, m, rule, **kw))

        for name in ("width", "depth", "height", "shelf_thickness",
                     "upright_thickness"):
            if not _finite_positive(getattr(self, name)):
                err(name,
                    f"must be a positive, finite number, got {getattr(self, name)!r}")
        if any(i.severity == "error" for i in issues):
            return issues

        if self.clear_span <= 0:
            err("width",
                "the uprights are wider than the bank; nothing spans between them")
            return issues
        if self.shelf_count < 1:
            err("shelves", "a shelf bank needs at least one shelf")
            return issues

        # --- shelf deflection over the clear span ----------------------------
        span = self.clear_span
        res = engineering.evaluate_shelf(
            span=span, depth=self.depth, thickness=self.shelf_thickness,
            load_kg_per_m=self.load_kg_per_m, species=(self.species or "plywood"))
        if res.status == "fail":
            err("shelf_thickness",
                f"shelf will sag {res.deflection:.1f}mm over a {span:.0f}mm span, "
                f"past the {res.engineering_limit:.1f}mm structural limit (span/360); "
                "shorten the span, thicken the shelf, or add a mid support")
        elif res.status == "visible":
            warn("shelf_thickness",
                 f"shelf sag {res.deflection:.1f}mm over {span:.0f}mm will be "
                 f"visible (> {res.visible_limit:.1f}mm); thicken the shelf, use a "
                 "stiffer material, or add a mid support")

        # --- shelf-spacing sanity --------------------------------------------
        n = self.shelf_count
        if n > 1:
            gap = self.height / (n + 1)
            if gap < 150:
                warn("shelves",
                     f"only {gap:.0f}mm clear between shelves; that is tight for "
                     "stored items — use fewer shelves or a taller bank")
        return issues

    # --- (de)serialisation -------------------------------------------------
    def to_dict(self) -> dict:
        d = {"component": self.component, "name": self.name, "at": list(self.at)}
        for f in self._LENGTH_FIELDS:
            d[f] = getattr(self, f)
        d["shelves"] = self.shelves
        d["load_kg_per_m"] = self.load_kg_per_m
        if self.species:
            d["species"] = self.species
        if self.material_form:
            d["material_form"] = self.material_form
        return d

    @classmethod
    def from_dict(cls, data: dict, naming: _ShelfNaming | None = None) -> "ShelfBank":
        known = {f.name for f in fields(cls)} - {"naming"}
        kw = {k: v for k, v in data.items() if k in known}
        if "at" in kw:
            kw["at"] = tuple(kw["at"]) if isinstance(kw["at"], (list, tuple)) \
                else (0.0, 0.0, 0.0)
        obj = cls(**kw)
        if naming is not None:
            object.__setattr__(obj, "naming", naming)
        return obj


# ===========================================================================
# Registry — the one place the available component names are declared
# ===========================================================================

_COMPONENTS: dict[str, type] = {
    LeggedBase.component: LeggedBase,
    ShelfBank.component: ShelfBank,
}


def available_components() -> list[str]:
    """Sorted names of the components a ``piece`` may place."""
    return sorted(_COMPONENTS)


def is_component(name: str) -> bool:
    return str(name or "").strip().lower() in _COMPONENTS


def length_fields(name: str) -> tuple[str, ...]:
    """The length-valued parameter names of *name* (for imperial conversion)."""
    cls = _COMPONENTS.get(str(name or "").strip().lower())
    return cls._LENGTH_FIELDS if cls is not None else ()


def component_params(name: str) -> frozenset[str] | None:
    """Every key a ``components`` entry for *name* may carry, or None if unknown.

    Derived from the component dataclass (the exact set ``from_dict`` accepts,
    minus the cosmetic ``naming``) plus the ``component`` discriminator, so the
    spec lint can't drift from what the loader actually keeps.
    """
    cls = _COMPONENTS.get(str(name or "").strip().lower())
    if cls is None:
        return None
    return frozenset(f.name for f in fields(cls)
                     if f.name != "naming") | {"component"}


def component_from_dict(data: dict):
    """Build a component instance from a ``piece`` ``components`` entry.

    Raises ``KeyError`` (with the unknown name) when ``component`` is not a
    registered name, so the caller can turn it into a repairable validate error
    rather than crashing the pipeline.
    """
    name = str((data or {}).get("component", "")).strip().lower()
    cls = _COMPONENTS[name]           # KeyError -> unknown component
    return cls.from_dict(data)
