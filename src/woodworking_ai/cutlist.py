"""Cut list + hardware schedule generation.

Turns a validated :class:`CabinetSpec` into the parts a shop actually cuts and
the hardware they buy. This is pure arithmetic — no CAD dependency — so it is
fast, deterministic, and fully unit-testable. It models a **frameless base
cabinet**.

Conventions: every dimension is in the spec's units (mm by default). For each
panel, ``length`` is the longer face dimension and ``width`` the shorter; this
is the convention a cut list / nesting tool expects.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

from .dsl import (CabinetSpec, TableSpec, ComponentGroup, BackStyle,
                  Construction, CabinetType)
from .geometry import front_plan, component_tag
# Construction constants now live in one neutral module shared with geometry.
from .constants import (
    SHELF_SIDE_CLEARANCE, SHELF_SETBACK, STRETCHER_WIDTH,
    FRAME_WIDTH, FRAME_THICKNESS,
    SLIDE_SIDE_CLEARANCE, DRAWER_BOX_HEIGHT_DROP, DRAWER_BOX_DEPTH_GAP,
    DOOR_STILE_WIDTH, DOOR_RAIL_WIDTH, DOOR_PANEL_GROOVE,
    GLUE_UP_BOARD_WIDTH,
)
from .hardware import (
    select_hinge, select_slide, select_pull, hinge_count,
    CONFIRMAT, ASSEMBLY_SCREW,
)

# Materials cut from solid/dimensional lumber rather than sheet goods. A shop
# buys these by the board foot (and often by the running length), not the sheet.
SOLID_LUMBER_MATERIALS = frozenset({"frame", "top", "leg", "apron", "solid panel"})
# One board foot is 144 cubic inches; expressed in mm³ for our mm-native parts.
BOARD_FOOT_MM3 = 144.0 * (25.4 ** 3)   # ≈ 2_359_737.2 mm³


@dataclass
class Part:
    name: str
    qty: int
    length: float
    width: float
    thickness: float
    material: str = "sheet"    # internal *usage* label (role), not the product
    grain: str = "length"      # grain direction runs along `length`
    notes: str = ""
    id: str = ""               # stable part code (e.g. "A1"), set by assign_ids
    # Physical make-up, resolved from the spec's material/species declaration
    # (both optional; "" = generic / inherited). Drives the BOM and the quote.
    form: str = ""             # plywood|mdf|particleboard|melamine|hardboard|solid
    species: str = ""          # wood species, e.g. oak | maple | pine

    @property
    def area_m2(self) -> float:
        """Single-part face area in m² (assumes mm input)."""
        return (self.length / 1000.0) * (self.width / 1000.0)

    @property
    def stock_label(self) -> str:
        """Display name of the physical stock: declared form, else usage label."""
        return self.form or self.material

    @property
    def stock_key(self) -> tuple[str, str, str, float]:
        """Merge key for parts that buy as one stock.

        ``(stock_label, form, species, thickness)`` — parts sharing a declared
        form+species+thickness nest as one buyable sheet; legacy parts fall back
        to their usage label, keeping distinct products apart.
        """
        return (self.stock_label, self.form, self.species, self.thickness)

    @property
    def is_solid_lumber(self) -> bool:
        """True when this part is cut from solid stock (bought by the board foot).

        Either an intrinsically-solid usage label (frame/leg/apron/top) or an
        explicit ``form == "solid"`` declared on the spec.
        """
        return self.material in SOLID_LUMBER_MATERIALS or self.form == "solid"

    @property
    def board_feet(self) -> float:
        """Volume of a single part expressed in board feet (144 in³)."""
        return (self.length * self.width * self.thickness) / BOARD_FOOT_MM3


# --- stable part identity ---------------------------------------------------
# Every part gets a short code (e.g. "A1") grouped by a broad category, numbered
# in cut-list order. The same code is referenced by the nesting diagram, the
# drilling schedule, and the shop drawings, so a shop can cross-reference one
# physical part across every output. Codes are deterministic because cut-list
# generation is deterministic.
_CATEGORY_PREFIX = {
    "carcass": "A",        # sides, bottom, top, stretcher, toe kick
    "back": "B",           # back panel(s) and captured drawer bottoms
    "shelf": "C",
    "front": "D",          # doors, drawer fronts, mullion, blind filler
    "drawer_box": "E",
    "frame": "F",          # face-frame stiles/rails
    "solid": "T",          # table top / leg / apron (solid stock)
    "accessory": "G",      # countertop / molding / end panel
}


def _part_category(p: "Part") -> str:
    """Broad category key for *p*, used to pick its ID prefix."""
    n = p.name.lower()
    if "box" in n and "drawer" in n:
        return "drawer_box"
    if p.material in ("countertop", "molding"):
        return "accessory"
    if p.material in ("door/front", "door panel"):
        return "front"
    if p.material == "frame":
        return "frame"
    if p.material in ("top", "leg", "apron"):
        return "solid"
    if p.material == "back panel":
        return "back"
    if "shelf" in n:
        return "shelf"
    return "carcass"


# Cut-list category (from _part_category) → the spec `stock` override area.
_CATEGORY_TO_AREA = {
    "carcass": "carcass", "back": "back", "shelf": "shelf", "front": "front",
    "drawer_box": "drawer_box", "frame": "frame", "solid": "solid",
}


def _resolve_part_stock(parts: list["Part"], spec) -> None:
    """Stamp each part's physical ``form``/``species`` from *spec*, in place.

    The role→material declaration lives on the spec (global default + per-area
    ``stock`` overrides); this resolves it once per part so every downstream
    surface (BOM, quote, drawings) reads the same physical stock. Accessories
    keep their own material unless an ``accessory`` override is given.
    """
    from .materials import resolve
    table = getattr(spec, "stock", None) or {}
    for p in parts:
        cat = _part_category(p)
        if cat == "accessory":
            if "accessory" in table:
                p.form, p.species = resolve(spec, "accessory")
            continue
        area = "door_panel" if p.material == "door panel" else \
            _CATEGORY_TO_AREA.get(cat, "carcass")
        p.form, p.species = resolve(spec, area)


def assign_ids(parts: list["Part"], prefix: str = "") -> None:
    """Assign a stable ``id`` to each part in *parts*, in place.

    ``prefix`` namespaces the codes for one component of a project (e.g. the
    component tag), so a run's parts read ``B2-A1`` without colliding.
    """
    counters: dict[str, int] = {}
    for p in parts:
        cat = _part_category(p)
        letter = _CATEGORY_PREFIX[cat]
        counters[letter] = counters.get(letter, 0) + 1
        code = f"{letter}{counters[letter]}"
        p.id = f"{prefix}-{code}" if prefix else code


# Map a geometry panel label (e.g. "Side L", "Shelf 2", "Drawer front 1") to the
# cut-list part name it belongs to, so the drilling schedule and drawings can
# resolve the shared part ID. Both label sets are produced by this codebase, so
# the table is small and stable.
_PANEL_LABEL_TO_PART = {
    "Side": "Side", "Bottom": "Bottom", "Top": "Top",
    "Stretcher front": "Top stretcher", "Stretcher back": "Top stretcher",
    "Back": "Back", "Shelf": "Adjustable shelf", "Corner shelf": "Corner shelf",
    "Toe kick": "Toe kick", "Door": "Door", "Mullion": "Mullion",
    "Stile": "Face-frame stile", "Rail": "Face-frame rail",
    "Center stile": "Face-frame center stile", "Blind filler": "Blind filler",
    "Front rail": "Front rail", "Side L": "Side L", "Side R": "Side R",
    "Leg": "Leg", "Apron long": "Apron (long)", "Apron short": "Apron (short)",
}


def _panel_label_base(label: str) -> str:
    """Strip a trailing hand ('L'/'R') or index ('1') from a panel label."""
    parts = label.rsplit(" ", 1)
    if len(parts) == 2 and (parts[1] in ("L", "R") or parts[1].isdigit()):
        return parts[0]
    return label


@dataclass
class Hardware:
    name: str
    qty: int
    notes: str = ""
    sku: str = ""               # orderable part number (catalogue), if any
    brand: str = ""             # hardware brand (blum/hettich/grass/generic)
    category: str = "hardware"  # hardware | fastener | connector


@dataclass
class CutList:
    spec_name: str
    parts: list[Part] = field(default_factory=list)
    hardware: list[Hardware] = field(default_factory=list)

    @property
    def sheet_area_m2(self) -> float:
        """Total face area of all panels (gross, before nesting waste)."""
        return sum(p.area_m2 * p.qty for p in self.parts)

    def to_csv(self, unit: str = "metric") -> str:
        """Cut list as CSV. ``unit="imperial"`` renders fractional inches."""
        from .units import format_length, length_unit_label
        lbl = length_unit_label(unit)

        def f(v: float) -> str:
            return format_length(v, unit, mark=False)

        lines = [f"id,part,qty,length_{lbl},width_{lbl},thickness_{lbl},"
                 "material,grain,notes"]
        for p in self.parts:
            lines.append(
                f"{p.id},{p.name},{p.qty},{f(p.length)},{f(p.width)},"
                f"{f(p.thickness)},{p.material},{p.grain},{p.notes}"
            )
        return "\n".join(lines)

    def part_id_for_label(self, label: str) -> str:
        """Resolve a geometry panel label to its cut-list part ID (or "").

        Tries an exact part-name match, then the panel→part table, then a
        prefix match (for indexed fronts like "Drawer front 1"). A project's
        labels are tagged ("B2 · Side"); the tag is stripped and re-applied.
        """
        tag = ""
        if " · " in label:
            tag, label = label.split(" · ", 1)
        by_name = {p.name: p for p in self.parts}
        cand = (by_name.get(label)
                or by_name.get(_PANEL_LABEL_TO_PART.get(label, label))
                or by_name.get(_PANEL_LABEL_TO_PART.get(
                    _panel_label_base(label), "")))
        if cand is None:
            base = _panel_label_base(label)
            cand = next((p for p in self.parts if p.name.startswith(base)), None)
        if cand is None:
            return ""
        if tag:
            # Project IDs are already namespaced on the part; match the tag.
            return cand.id
        return cand.id

    def hardware_csv(self) -> str:
        lines = ["item,qty,brand,sku,category,notes"]
        for h in self.hardware:
            lines.append(
                f"{h.name},{h.qty},{h.brand},{h.sku},{h.category},{h.notes}")
        return "\n".join(lines)

    def lumber_breakdown(self) -> list[dict]:
        """Solid-lumber requirement grouped by (material, thickness).

        Sheet goods (plywood/MDF, bought by the sheet — see the estimate) are
        excluded. Each group reports the total board feet and running length so
        a shop can order solid stock the way it actually buys it: legs and
        aprons by the linear metre/foot, tops and frames by the board foot.
        """
        groups: dict[tuple[str, float, str, str], dict] = {}
        for p in self.parts:
            if not p.is_solid_lumber:
                continue
            key = (p.material, p.thickness, p.form, p.species)
            g = groups.setdefault(key, {
                "material": p.material, "thickness": p.thickness,
                "form": p.form, "species": p.species,
                "parts": 0, "board_feet": 0.0, "length_mm": 0.0,
            })
            g["parts"] += p.qty
            g["board_feet"] += p.board_feet * p.qty
            g["length_mm"] += p.length * p.qty
        return [groups[k] for k in sorted(groups)]

    @property
    def total_board_feet(self) -> float:
        """Board feet of solid lumber across the whole cut list."""
        return sum(p.board_feet * p.qty for p in self.parts if p.is_solid_lumber)

    def summary(self, unit: str = "metric") -> str:
        from .units import format_area
        n_panels = sum(p.qty for p in self.parts)
        n_hw = sum(h.qty for h in self.hardware)
        return (
            f"{self.spec_name}: {n_panels} panels "
            f"({len(self.parts)} unique), {n_hw} hardware items, "
            f"~{format_area(self.sheet_area_m2, unit)} sheet goods"
        )


def glue_up_boards(width: float, board_width: float = GLUE_UP_BOARD_WIDTH
                   ) -> tuple[int, float]:
    """Boards needed to edge-glue a panel of *width*: ``(count, board_width)``.

    Splits the panel into the fewest equal boards no wider than *board_width*,
    the way a shop rips and edge-glues a solid panel.
    """
    n = max(2, math.ceil(width / board_width)) if width > board_width else 1
    return n, round(width / n, 1)


def _expand_glue_ups(cl: "CutList", board_width: float = GLUE_UP_BOARD_WIDTH) -> None:
    """Rewrite sheet carcass panels as edge-glued solid boards, in place.

    Each carcass panel wider than a board becomes N solid boards (priced by the
    board foot) with a note of the glue-line length, so a solid-wood cabinet
    quotes and cuts as the boards a shop actually buys.
    """
    new_parts: list[Part] = []
    for p in cl.parts:
        if p.material == "sheet" and p.width > board_width:
            n, bw = glue_up_boards(p.width, board_width)
            glue_m = (n - 1) * p.length / 1000.0
            new_parts.append(Part(
                f"{p.name} board", p.qty * n, length=p.length, width=bw,
                thickness=p.thickness, material="solid panel", grain="length",
                notes=f"glue-up: {n} boards/panel, ~{glue_m:.1f}m glue line"))
        else:
            new_parts.append(p)
    cl.parts = new_parts


def _add_drawer_box(cl: "CutList", spec: CabinetSpec, index: int,
                    opening_w: float, front_height: float,
                    interior_depth: float) -> None:
    """Append the four box panels + bottom for one drawer."""
    m = spec.material
    t = m.drawer_box
    box_w = opening_w - 2 * SLIDE_SIDE_CLEARANCE          # outer box width
    box_h = max(front_height - DRAWER_BOX_HEIGHT_DROP, 60.0)
    box_d = max(interior_depth - DRAWER_BOX_DEPTH_GAP, 100.0)
    cl.parts.append(Part(
        f"Drawer {index} box side", 2, length=box_d, width=box_h, thickness=t,
        material="drawer box", grain="none", notes="grooved for bottom",
    ))
    cl.parts.append(Part(
        f"Drawer {index} box front/back", 2, length=box_w - 2 * t, width=box_h,
        thickness=t, material="drawer box", grain="none",
    ))
    cl.parts.append(Part(
        f"Drawer {index} box bottom", 1, length=box_w, width=box_d,
        thickness=m.back, material="back panel", grain="none",
        notes="captured in groove",
    ))


def _add_door_parts(cl: "CutList", spec: CabinetSpec, doors, front_note: str) -> None:
    """Append door parts: one slab, or 5-piece stile-and-rail components.

    For a non-slab ``door_style`` each leaf becomes two stiles, two rails and a
    centre panel (flat for shaker/cope-and-stick, solid for raised panel), sized
    so the rails tenon into the stiles and the panel floats in the frame groove.
    """
    m = spec.material
    d0 = doors[0]
    n = len(doors)
    style = str(getattr(spec, "door_style", "slab")).lower()
    if style == "slab":
        cl.parts.append(Part(
            "Door", n, length=d0.height, width=d0.width, thickness=m.door,
            material="door/front", notes=f"{front_note} slab ({n})"))
        return
    # Five-piece frame-and-panel door.
    cl.parts.append(Part(
        "Door stile", 2 * n, length=d0.height, width=DOOR_STILE_WIDTH,
        thickness=m.door, material="door/front", grain="length",
        notes=f"{style} door, vertical"))
    rail_len = d0.width - 2 * DOOR_STILE_WIDTH + 2 * DOOR_PANEL_GROOVE
    cl.parts.append(Part(
        "Door rail", 2 * n, length=max(rail_len, 50.0), width=DOOR_RAIL_WIDTH,
        thickness=m.door, material="door/front",
        notes="cope-and-stick into stiles"))
    panel_h = d0.height - 2 * DOOR_RAIL_WIDTH + 2 * DOOR_PANEL_GROOVE
    panel_w = d0.width - 2 * DOOR_STILE_WIDTH + 2 * DOOR_PANEL_GROOVE
    solid = style == "raised_panel"
    cl.parts.append(Part(
        "Door panel", n, length=max(panel_h, 50.0), width=max(panel_w, 50.0),
        thickness=m.door_panel, material="door panel", grain="length",
        notes="raised, solid" if solid else "flat panel, floats in groove"))


def _add_assembly_hardware(cl: "CutList", spec: CabinetSpec) -> None:
    """Append carcass assembly hardware (a buyable estimate) for *spec*.

    Knock-down joinery (screw/pocket) uses Confirmats or cam-and-dowel
    connectors; captured joinery (dado/rabbet/dowel/domino) is glued with a few
    assembly screws. Counts are per-cabinet estimates a shop rounds up — the
    point is that the BOM is orderable, not that it is exact to the screw.
    """
    j = str(spec.joinery).strip().lower()
    # Four carcass corners; tall/dressers add fixed shelves/dividers → more.
    base = 8 if spec.has_full_top else 6
    if j in ("screw",):
        cl.hardware.append(Hardware(
            CONFIRMAT.name, base, CONFIRMAT.note, sku=CONFIRMAT.sku,
            category="fastener"))
    elif j in ("pocket",):
        cl.hardware.append(Hardware(
            "Pocket screw 1-1/4in", base, "pocket-hole assembly",
            category="fastener"))
    else:  # dado / rabbet / dowel / domino / butt: glue + a few screws
        cl.hardware.append(Hardware(
            ASSEMBLY_SCREW.name, max(base // 2, 4), "edge fixing + glue",
            sku=ASSEMBLY_SCREW.sku, category="fastener"))
    # Back panel fixing (screws/pins around the perimeter).
    cl.hardware.append(Hardware(
        "Back panel screw 4×16", 10, "fix back to rear edges",
        category="fastener"))


def _diagonal_cutlist(spec: CabinetSpec) -> CutList:
    """Parts + hardware for a diagonal (angled-front) corner cabinet."""
    m = spec.material
    cl = CutList(spec_name=spec.name)
    W, D, t, c = spec.width, spec.depth, m.carcass, spec.corner_cut
    toe_h = spec.toe_kick_height
    box_h = spec.box_height
    front_w = (W / 2 - c) - (-W / 2 + t)

    cl.parts.append(Part("Side L", 1, length=box_h, width=D, thickness=t,
                         notes="full gable"))
    cl.parts.append(Part("Side R", 1, length=box_h, width=D - c, thickness=t,
                         notes="short gable (chamfer)"))
    cl.parts.append(Part("Back", 1, length=box_h, width=W - 2 * t, thickness=t))
    cl.parts.append(Part("Front rail", 1, length=box_h, width=front_w, thickness=t))
    cl.parts.append(Part("Bottom", 1, length=W - 2 * t, width=D - 2 * t,
                         thickness=t, notes="trim front-right corner"))
    cl.parts.append(Part("Top", 1, length=W - 2 * t, width=D - 2 * t,
                         thickness=t, notes="trim front-right corner"))
    if spec.toe_kick and toe_h > 0:
        cl.parts.append(Part("Toe kick", 1, length=W, width=toe_h, thickness=t))
    if spec.shelves > 0:
        cl.parts.append(Part("Corner shelf", spec.shelves, length=W - 2 * t - 4,
                             width=D - 2 * t - 4, thickness=m.shelf,
                             notes="trim to corner"))
        cl.hardware.append(Hardware("Shelf pin", spec.shelves * 4, "5mm"))
    door_len = max(c * math.sqrt(2) - 2 * spec.reveal, 50.0)
    cl.parts.append(Part("Door", 1, length=box_h - 2 * spec.reveal, width=door_len,
                         thickness=m.door, material="door/front",
                         notes="angled 45° door"))
    cl.hardware.append(Hardware("Concealed hinge", 2, "soft-close"))
    cl.hardware.append(Hardware("Door pull", 1))
    if spec.edge_banding:
        cl.hardware.append(Hardware("Edge banding", 1, "match carcass front edges"))
    _resolve_part_stock(cl.parts, spec)
    assign_ids(cl.parts)
    return cl


def _table_cutlist(spec: TableSpec) -> CutList:
    """Parts + hardware for a four-legged table."""
    cl = CutList(spec_name=spec.name)
    leg_h = spec.height - spec.top_thickness
    li, leg = spec.leg_inset, spec.leg
    apron_x = (spec.width - 2 * li - leg) - leg
    apron_y = (spec.depth - 2 * li - leg) - leg
    if getattr(spec, "solid_top", True) and spec.depth > GLUE_UP_BOARD_WIDTH:
        n, bw = glue_up_boards(spec.depth)
        glue_m = (n - 1) * spec.width / 1000.0
        cl.parts.append(Part(
            "Top board", n, length=spec.width, width=bw,
            thickness=spec.top_thickness, material="top", grain="length",
            notes=f"edge-glued top: {n} boards, ~{glue_m:.1f}m glue line"))
    else:
        cl.parts.append(Part("Top", 1, length=spec.width, width=spec.depth,
                             thickness=spec.top_thickness, material="top",
                             notes="solid/sheet top"))
    cl.parts.append(Part("Leg", 4, length=leg_h, width=leg, thickness=leg,
                         material="leg", notes="square stock"))
    cl.parts.append(Part("Apron (long)", 2, length=apron_x, width=spec.apron_height,
                         thickness=spec.apron_thickness, material="apron"))
    cl.parts.append(Part("Apron (short)", 2, length=apron_y, width=spec.apron_height,
                         thickness=spec.apron_thickness, material="apron"))
    cl.hardware.append(Hardware("Corner bracket", 4, "leg-to-apron"))
    cl.hardware.append(Hardware("Tabletop fastener", 8, "expansion clip"))
    _resolve_part_stock(cl.parts, spec)
    assign_ids(cl.parts)
    return cl


def _project_cutlist(project: ComponentGroup) -> CutList:
    """One combined cut list for a whole group, parts tagged by component.

    Each component's parts and hardware are merged under a short label so a shop
    sees one list but can still tell which cabinet a panel belongs to.
    """
    cl = CutList(spec_name=project.name)
    for i, comp in enumerate(project.components, start=1):
        tag = component_tag(comp, i)
        sub = generate_cutlist(comp.spec)   # already ID'd per component
        for p in sub.parts:
            cl.parts.append(replace(
                p, name=f"{tag} · {p.name}", id=f"{tag}-{p.id}" if p.id else ""))
        for h in sub.hardware:
            cl.hardware.append(replace(h, name=f"{tag} · {h.name}"))
    return cl


def generate_cutlist(spec) -> CutList:
    """Derive the full parts + hardware list for a cabinet, table, or group."""
    if isinstance(spec, ComponentGroup):
        return _project_cutlist(spec)
    if isinstance(spec, TableSpec):
        return _table_cutlist(spec)
    if spec.cabinet_type == CabinetType.CORNER_DIAGONAL:
        return _diagonal_cutlist(spec)

    m = spec.material
    cl = CutList(spec_name=spec.name)

    toe_h = spec.toe_kick_height
    box_height = spec.box_height
    interior_width = spec.interior_width
    interior_depth = spec.interior_depth  # back recessed by its thickness

    # ---- carcass --------------------------------------------------------
    cl.parts.append(Part(
        "Side", 2, length=box_height, width=spec.depth, thickness=m.carcass,
        grain="length", notes="full-height gable",
    ))
    cl.parts.append(Part(
        "Bottom", 1, length=interior_width, width=interior_depth,
        thickness=m.carcass, grain="none", notes="between sides",
    ))
    # Wall/tall cabinets are enclosed with a full top panel; base cabinets use
    # two top rails, leaving room for a sink/drawers and to fasten the counter.
    if spec.has_full_top:
        cl.parts.append(Part(
            "Top", 1, length=interior_width, width=interior_depth,
            thickness=m.carcass, grain="none", notes="enclosed top",
        ))
    else:
        cl.parts.append(Part(
            "Top stretcher", 2, length=interior_width, width=STRETCHER_WIDTH,
            thickness=m.carcass, grain="none", notes="front & back top rail",
        ))

    # ---- back -----------------------------------------------------------
    if spec.back == BackStyle.APPLIED:
        back_l, back_w = box_height, spec.width
        back_note = "applied to rear edges"
    else:  # rabbeted / grooved: captured between the sides
        back_l, back_w = box_height - m.carcass, interior_width
        back_note = f"{spec.back.value} back"
    cl.parts.append(Part(
        "Back", 1, length=max(back_l, back_w), width=min(back_l, back_w),
        thickness=m.back, material="back panel", grain="none", notes=back_note,
    ))

    # ---- shelves --------------------------------------------------------
    if spec.shelves > 0:
        shelf_w = interior_width - 2 * SHELF_SIDE_CLEARANCE
        shelf_d = interior_depth - SHELF_SETBACK
        cl.parts.append(Part(
            "Adjustable shelf", spec.shelves,
            length=shelf_w, width=shelf_d, thickness=m.shelf, grain="none",
            notes="on shelf pins",
        ))
        cl.hardware.append(Hardware("Shelf pin", spec.shelves * 4, "5mm"))

    # ---- toe kick -------------------------------------------------------
    if spec.toe_kick and toe_h > 0:
        cl.parts.append(Part(
            "Toe kick", 1, length=spec.width, width=toe_h, thickness=m.carcass,
            grain="none", notes=f"set back {spec.toe_kick.setback:.0f}mm",
        ))

    # ---- face frame (solid hardwood stiles + rails) ---------------------
    is_ff = spec.construction == Construction.FACE_FRAME
    if is_ff:
        cl.parts.append(Part(
            "Face-frame stile", 2, length=box_height, width=FRAME_WIDTH,
            thickness=FRAME_THICKNESS, material="frame", grain="length",
            notes="vertical, hardwood",
        ))
        cl.parts.append(Part(
            "Face-frame rail", 2, length=spec.width - 2 * FRAME_WIDTH,
            width=FRAME_WIDTH, thickness=FRAME_THICKNESS, material="frame",
            notes="top & bottom, hardwood",
        ))

    # ---- fronts: doors, drawers, mullion, blind filler ------------------
    # Sizes/positions come from the shared front_plan (also drives geometry), so
    # the parts list and the 3D model can never disagree about the fronts.
    plan = front_plan(spec)
    front_note = "inset" if is_ff else "overlay"
    brand = getattr(spec, "hardware_brand", "generic")

    filler = next((it for it in plan.items if it.kind == "filler"), None)
    if filler is not None:
        cl.parts.append(Part(
            "Blind filler", 1, length=filler.height, width=filler.width,
            thickness=filler.thickness, material="door/front",
            notes="covers blind return",
        ))

    for dr in plan.drawers:
        note = "false front" if dr.false_front else front_note
        cl.parts.append(Part(
            f"Drawer front #{dr.index}", 1,
            length=dr.width, width=dr.height, thickness=dr.thickness,
            material="door/front", notes=note,
        ))
        if dr.false_front:
            continue  # fixed panel: no box, no slides
        # The drawer box itself, sized for slide and depth clearance.
        _add_drawer_box(cl, spec, dr.index, plan.opening_w, dr.height,
                        interior_depth)
        sdr = spec.drawers[dr.index - 1] if dr.index - 1 < len(spec.drawers) else None
        slide = select_slide(
            brand, str(getattr(sdr, "slide_type", "side_mount")),
            float(getattr(sdr, "slide_length", 0.0) or 0.0))
        cl.hardware.append(Hardware(
            "Drawer slide (pair)", 1, slide.name, sku=slide.sku, brand=slide.brand))
        if slide.locking_holes:
            cl.hardware.append(Hardware(
                "Drawer slide locking device (pair)", 1,
                f"{slide.rear_notch and 'box rear notch required' or ''}".strip(),
                brand=slide.brand, category="connector"))
        pull = select_pull(brand)
        cl.hardware.append(Hardware(
            "Drawer pull", 1,
            f"{pull.hole_spacing:.0f}mm CC" if pull.hole_spacing else "knob",
            sku=pull.sku, brand=pull.brand))

    mullion = plan.mullion
    if mullion is not None:
        if is_ff:
            cl.parts.append(Part(
                "Face-frame center stile", 1, length=mullion.height,
                width=mullion.width, thickness=mullion.thickness,
                material="frame", notes="between doors",
            ))
        else:
            cl.parts.append(Part(
                "Mullion", 1, length=mullion.height, width=mullion.width,
                thickness=mullion.thickness, material="door/front",
                notes="center post",
            ))

    doors = plan.doors
    if doors:
        d0 = doors[0]
        _add_door_parts(cl, spec, doors, front_note)
        overlay = "inset" if is_ff else getattr(spec, "hinge_overlay", "overlay")
        hinge = select_hinge(brand, overlay)
        n_hinges = len(doors) * hinge_count(d0.height)
        cl.hardware.append(Hardware(
            "Concealed hinge", n_hinges, f"{hinge.name} ({overlay})",
            sku=hinge.sku, brand=hinge.brand))
        cl.hardware.append(Hardware(
            "Hinge mounting plate", n_hinges, "one per hinge",
            sku=hinge.plate_sku, brand=hinge.brand))
        pull = select_pull(brand)
        cl.hardware.append(Hardware(
            "Door pull", len(doors),
            f"{pull.hole_spacing:.0f}mm CC" if pull.hole_spacing else "knob",
            sku=pull.sku, brand=pull.brand))

    # ---- carcass assembly hardware (estimate from joinery) --------------
    _add_assembly_hardware(cl, spec)

    # ---- edge banding (rough running length on exposed front edges) -----
    if spec.edge_banding:
        # Front edges of the two sides + bottom + stretcher front.
        cl.hardware.append(Hardware(
            "Edge banding", 1, "match carcass front edges (see estimate for run)",
        ))

    # Solid-wood carcass: edge-glue the sheet panels from boards. Triggered by an
    # explicit panel_construction, or by declaring the carcass form as "solid".
    from .materials import resolve as _resolve_area
    carcass_form, _ = _resolve_area(spec, "carcass")
    if (str(getattr(spec, "panel_construction", "sheet")).lower() == "glue_up"
            or carcass_form == "solid"):
        _expand_glue_ups(cl)

    # Accessories: countertop, filler, end panel, moldings.
    if getattr(spec, "accessories", None):
        from .accessories import add_accessory_parts
        add_accessory_parts(cl, spec)

    _resolve_part_stock(cl.parts, spec)
    assign_ids(cl.parts)
    return cl
