"""Where to buy it — a sourcing map for the purchase order (G4b).

The :mod:`woodworking_ai.purchasing` order says *what* to buy and *how much*;
this module answers *where*. It maps each buy category — and each hardware brand —
to a sensible retailer, an optional search link, and (for the pro/Euro hardware
brands a hobbyist can't get at a home center) a **big-box equivalent** to buy
instead. It is purely advisory: it never changes a price or a quantity, so the
purchase order's reconciliation with the quote is untouched.

Pure data + string formatting — no CAD dependency, no network access. The links
are stable web-search URLs (no affiliate, no expiring product pages); a shop can
override any of this in its own price book / profile.
"""

from __future__ import annotations

from urllib.parse import quote_plus

# Retailer a hobbyist can realistically order each trade from.
RETAILER_HOME_CENTER = "Home center"
RETAILER_HARDWARE_DEALER = "Cabinet-hardware dealer"
RETAILER_HARDWOOD_DEALER = "Hardwood dealer / lumberyard"
RETAILER_SHEET_GOODS = "Home center / sheet-goods yard"
RETAILER_FINISH = "Paint store / home center"
RETAILER_WOODWORKING = "Woodworking store (Rockler / Lee Valley / Woodcraft)"

# Pro / Euro hardware brands a home center usually doesn't stock, with the
# generic equivalent to buy off the shelf instead.
_EURO_BRANDS = {"blum", "hettich", "grass"}
_BIG_BOX_ALT = {
    "hinge": "generic 110° concealed (Euro) hinge + plate",
    "slide": "generic ball-bearing or soft-close drawer slide",
    "default": "generic equivalent from a home center",
}

# Per-category retailer. Hardware is special-cased by brand in :func:`source_for`.
_CATEGORY_RETAILER = {
    "sheet": RETAILER_SHEET_GOODS,
    "lumber": RETAILER_HARDWOOD_DEALER,
    "banding": RETAILER_WOODWORKING,
    "finish": RETAILER_FINISH,
    "consumable": RETAILER_HOME_CENTER,
    "abrasive": RETAILER_HOME_CENTER,
    "clamp": RETAILER_WOODWORKING,
    "labour": "",            # in-house; nothing to source
}


def _search_url(*terms: str) -> str:
    """A stable web-search link for the given terms (no expiring product page)."""
    query = " ".join(t for t in terms if t).strip()
    if not query:
        return ""
    return f"https://duckduckgo.com/?q={quote_plus(query)}"


def _big_box_alt(item: str) -> str:
    low = item.lower()
    if "hinge" in low:
        return _BIG_BOX_ALT["hinge"]
    if "slide" in low:
        return _BIG_BOX_ALT["slide"]
    return _BIG_BOX_ALT["default"]


def source_for(category: str, *, brand: str = "", item: str = "",
               sku: str = "") -> tuple[str, str, str]:
    """Return ``(retailer, url, alt)`` for a buy line.

    * ``retailer`` — where a hobbyist buys this trade.
    * ``url`` — a stable search link (empty for in-house labour).
    * ``alt`` — a home-center equivalent, set only for pro/Euro hardware brands a
      home center won't stock (empty otherwise).
    """
    cat = (category or "").strip().lower()
    brand = (brand or "").strip().lower()

    if cat == "hardware":
        if brand in _EURO_BRANDS:
            # A pro brand: point at a hardware dealer (with the SKU) and offer the
            # off-the-shelf substitute.
            url = _search_url(brand, sku or item)
            return (RETAILER_HARDWARE_DEALER, url, _big_box_alt(item))
        # Generic / connector / fastener hardware: a woodworking store or home
        # center carries it.
        return (RETAILER_WOODWORKING, _search_url(item, sku), "")

    retailer = _CATEGORY_RETAILER.get(cat, RETAILER_HOME_CENTER)
    if not retailer:                      # labour — nothing to buy
        return ("", "", "")
    return (retailer, _search_url(item), "")
