"""Shop profile: a saved set of *your shop's* standards and rates.

A :class:`ShopProfile` bundles the three things a shop wants to set once and
have every design honour:

* **Construction defaults** — your house reveal, construction, back style,
  joinery, edge banding, and stock thickness. Applied to any spec that omits a
  field, so an AI- or form-authored design comes out in your standards instead
  of the library defaults.
* **Hardware brand** — which catalogue (Blum / Hettich / Grass / generic) the
  hardware schedule and drilling should target (see :mod:`hardware`).
* **Pricing & stock** — the existing :class:`~estimator.PriceBook` and
  :class:`~estimator.SheetSize`, so quotes use your numbers.

Pure data — no CAD dependency. JSON round-trips so the web UI can persist it in
``localStorage``/Convex and the server can apply it per request.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from .estimator import (
    PriceBook, SheetSize, pricebook_to_dict, pricebook_from_dict,
    sheetsize_to_dict, sheetsize_from_dict,
)

# Cabinet fields the profile may default when a spec omits them. Each maps a
# spec key to the profile attribute that supplies the fallback value.
_CABINET_DEFAULT_FIELDS = {
    "construction": "construction",
    "back": "back",
    "joinery": "joinery",
    "reveal": "reveal",
    "edge_banding": "edge_banding",
}


@dataclass
class ShopProfile:
    """A shop's standing defaults, hardware brand, and pricing."""

    name: str = "Default Shop"

    # --- construction defaults (applied to specs that omit the field) --------
    construction: str = "frameless"
    back: str = "rabbeted"
    joinery: str = "dado"
    reveal: float = 3.0
    edge_banding: bool = True
    carcass_thickness: float = 18.0

    # --- hardware ------------------------------------------------------------
    hardware_brand: str = "generic"   # generic | blum | hettich | grass

    # --- pricing & stock -----------------------------------------------------
    prices: PriceBook = field(default_factory=PriceBook)
    sheet: SheetSize = field(default_factory=SheetSize)

    # ---- serialization ------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "construction": self.construction,
            "back": self.back,
            "joinery": self.joinery,
            "reveal": self.reveal,
            "edge_banding": self.edge_banding,
            "carcass_thickness": self.carcass_thickness,
            "hardware_brand": self.hardware_brand,
            "prices": pricebook_to_dict(self.prices),
            "sheet": sheetsize_to_dict(self.sheet),
        }

    @classmethod
    def from_dict(cls, data) -> "ShopProfile":
        p = cls()
        if not isinstance(data, dict):
            return p
        for f in ("name", "construction", "back", "joinery", "hardware_brand"):
            if isinstance(data.get(f), str):
                setattr(p, f, data[f])
        if isinstance(data.get("reveal"), (int, float)):
            p.reveal = float(data["reveal"])
        if isinstance(data.get("carcass_thickness"), (int, float)):
            p.carcass_thickness = float(data["carcass_thickness"])
        if "edge_banding" in data:
            p.edge_banding = bool(data["edge_banding"])
        if data.get("prices"):
            p.prices = pricebook_from_dict(data["prices"])
        if data.get("sheet"):
            p.sheet = sheetsize_from_dict(data["sheet"])
        return p

    # ---- defaulting ---------------------------------------------------------

    def apply_defaults(self, spec_data: dict) -> dict:
        """Return a copy of *spec_data* with missing fields filled from this
        profile.

        Only fills keys the design did not set, so an explicit choice always
        wins. Recurses into a project/assembly's components and definitions so
        a whole run inherits the shop's standards. Non-dict input is returned
        unchanged.
        """
        if not isinstance(spec_data, dict):
            return spec_data
        data = copy.deepcopy(spec_data)
        kind = str(data.get("kind", "")).lower()
        if kind in ("project", "assembly") or "components" in data:
            data["components"] = [
                self._apply_to_component(c) for c in data.get("components", [])
                if isinstance(c, dict)
            ]
            defs = data.get("definitions")
            if isinstance(defs, dict):
                data["definitions"] = {
                    k: self.apply_defaults(v) for k, v in defs.items()}
            return data
        if kind == "table" or "leg" in data or "top_thickness" in data:
            return data   # tables carry their own defaults
        # A leaf cabinet: fill the construction defaults it omitted.
        for spec_key, attr in _CABINET_DEFAULT_FIELDS.items():
            if spec_key not in data:
                data[spec_key] = getattr(self, attr)
        mat = data.get("material")
        if not isinstance(mat, dict):
            mat = {}
        mat.setdefault("carcass", self.carcass_thickness)
        data["material"] = mat
        return data

    def _apply_to_component(self, comp: dict) -> dict:
        comp = dict(comp)
        if isinstance(comp.get("spec"), dict):
            comp["spec"] = self.apply_defaults(comp["spec"])
        return comp


def profile_to_dict(profile: ShopProfile) -> dict:
    return profile.to_dict()


def profile_from_dict(data) -> ShopProfile:
    return ShopProfile.from_dict(data)
