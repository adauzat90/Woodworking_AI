"""FastAPI web app for the cabinet designer.

Serves a single-page front end plus a small JSON API:

    GET  /              -> the SPA
    GET  /api/config    -> front-end config (Convex URL, …)
    POST /api/build     -> {spec}   -> full design bundle (cut list, cost,
                                        drilling, render PNG, interactive GLB)
    POST /api/design    -> {prompt} -> NL → spec via Claude, then the bundle
                                        (requires ANTHROPIC_API_KEY)
    GET  /api/health    -> capability flags

Run it with:

    pip install -e ".[web,cad,render]"
    python -m woodworking_ai.web         # http://127.0.0.1:8000
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field, field_validator

from .dsl import CabinetSpec, TableSpec, ComponentGroup, spec_from_dict
from .validator import validate
from .service import build_result, export_bytes
from .estimator import (
    PriceBook, SheetSize, pricebook_to_dict, pricebook_from_dict,
    sheetsize_to_dict, sheetsize_from_dict,
)
from .profile import ShopProfile, profile_to_dict, profile_from_dict

logger = logging.getLogger(__name__)

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Woodworking AI", version="0.1.0")


def _import_ok(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except Exception:
        return False


# The installed-package capabilities (matplotlib/build123d/anthropic) never
# change for the life of the process, so detect them once at startup rather than
# importing on every request. The two env-backed flags (LLM key / Convex URL)
# *can* change between requests (and the tests flip them via monkeypatch), so
# those are recomputed live in :func:`_live_capabilities`.
_PKG_CAPS = {
    "render": _import_ok("matplotlib"),
    "glb": _import_ok("build123d"),
    "anthropic": _import_ok("anthropic"),
}

# Read the SPA template once at startup; per-request we only splice in the
# (request-time) Convex URL, which is cheap and lets the env var change live.
_INDEX_TEMPLATE = (STATIC / "index.html").read_text(encoding="utf-8")
# Rendered SPA HTML keyed by the spliced-in CONVEX_URL (usually one entry).
_INDEX_CACHE: dict[str, str] = {}


def _live_capabilities() -> dict[str, bool]:
    return {
        "render": _PKG_CAPS["render"],
        "glb": _PKG_CAPS["glb"],
        "llm": _PKG_CAPS["anthropic"] and bool(os.environ.get("ANTHROPIC_API_KEY")),
        "convex": bool(os.environ.get("CONVEX_URL")),
    }


# --- request models ----------------------------------------------------------
# Typed bodies give FastAPI validation + OpenAPI docs for free, and declare the
# Phase-1 cost clamps once. ``spec``/``profile``/``prices``/``sheet`` stay loose
# dicts because they are parsed by the DSL/estimator's own ``from_dict`` paths
# (which already tolerate partial/garbage input). ``extra="allow"`` keeps a bare
# spec posted as the whole body working (``spec`` then defaults to that body).


class _SpecBody(BaseModel):
    spec: dict[str, Any] | None = None
    profile: dict[str, Any] | None = None
    prices: dict[str, Any] | None = None
    sheet: dict[str, Any] | None = None

    model_config = {"extra": "allow"}

    def spec_data(self) -> Any:
        if self.spec is not None:
            return self.spec
        # A bare spec posted as the whole body: rebuild it from the extra fields.
        extra = dict(self.__pydantic_extra__ or {})
        if extra:
            return extra
        return {}


class BuildRequest(_SpecBody):
    glb: bool = True
    # Owned offcuts / sheets to cut from first ("cut from my stock"). Each item:
    # {length, width, thickness, qty, form?, species?, id?}. Loose dicts — parsed
    # by StockBoard.from_dict, which tolerates partial/string input.
    boards: list[dict[str, Any]] | None = None


class DesignRequest(BaseModel):
    prompt: str = ""
    profile: dict[str, Any] | None = None
    prices: dict[str, Any] | None = None
    sheet: dict[str, Any] | None = None
    boards: list[dict[str, Any]] | None = None
    glb: bool = True
    # Cap the paid LLM repair loop: a client cannot drive an unbounded number of
    # round-trips (Phase 1.4). Out-of-range values are clamped, not rejected, so
    # a generous client value is honoured up to the ceiling rather than 422-ing.
    attempts: int = 3

    @field_validator("attempts")
    @classmethod
    def _clamp_attempts(cls, v: int) -> int:
        return max(1, min(5, int(v)))


class ModelRequest(_SpecBody):
    # ``factor`` explodes the sub-assemblies (0 = assembled, 1 = fully exploded);
    # clamp it to a sane range rather than trusting the client.
    factor: float = 0.0
    include: list[str] | None = None

    @field_validator("factor")
    @classmethod
    def _clamp_factor(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))


class ExportRequest(_SpecBody):
    units: str = "metric"


class DiffRequest(BaseModel):
    from_: dict[str, Any] | None = Field(default=None, alias="from")
    to: dict[str, Any] | None = None
    profile: dict[str, Any] | None = None
    prices: dict[str, Any] | None = None
    sheet: dict[str, Any] | None = None

    model_config = {"populate_by_name": True}


class RoomRequest(BaseModel):
    widths: list[Any] = Field(default_factory=list)
    wall: dict[str, Any] | None = None
    room: dict[str, Any] | None = None


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    # Expose an optional Convex deployment URL to the front end. Read live so the
    # value can change without a restart (and so the test harness can flip it),
    # but cache the spliced HTML per distinct URL so the common case is a dict
    # lookup, not an O(n) string replace over the whole template every request.
    convex = os.environ.get("CONVEX_URL", "")
    html = _INDEX_CACHE.get(convex)
    if html is None:
        inject = f'<script>window.__CONVEX_URL__={convex!r};</script>'
        html = _INDEX_TEMPLATE.replace("<!--CONVEX_URL-->", inject)
        _INDEX_CACHE[convex] = html
    return html


@app.get("/api/config")
def config() -> dict[str, Any]:
    """Front-end runtime config the SPA can fetch (Convex URL, capabilities)."""
    return {
        "convex_url": os.environ.get("CONVEX_URL", ""),
        "capabilities": _live_capabilities(),
    }


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "capabilities": _live_capabilities()}


@app.get("/api/pricing")
def pricing() -> dict[str, Any]:
    """The shop's default price book + sheet size, for the UI to seed its editor."""
    return {"prices": pricebook_to_dict(PriceBook()),
            "sheet": sheetsize_to_dict(SheetSize())}


@app.get("/api/profile")
def profile() -> dict[str, Any]:
    """The shop's default standards profile, for the UI to seed its editor."""
    return profile_to_dict(ShopProfile())


@app.get("/api/templates")
def templates() -> dict[str, Any]:
    """The starter-project gallery (G3): ready-to-build designs for a cold start."""
    from .templates import gallery
    return {"templates": gallery()}


def _profile_of(body) -> ShopProfile | None:
    """The :class:`ShopProfile` in *body*, or ``None`` when absent."""
    return profile_from_dict(body.profile) if body.profile else None


def _tooling_of(body):
    """The shop tooling inventory from *body*'s profile, or ``None``.

    ``None`` means "design against any joinery" (unchanged behaviour); a
    declared inventory constrains validation and the AI designer to makeable
    joints.
    """
    prof = _profile_of(body)
    return prof.tooling if prof else None


def _combine_stock(body) -> bool:
    """Whether to nest all same-thickness sheet parts together (shop policy)."""
    prof = _profile_of(body)
    return bool(prof.combine_sheet_stock) if prof else False


def _pricing_overrides(body):
    """Pull optional ``prices`` / ``sheet`` overrides from a request body.

    An explicit ``prices``/``sheet`` wins; otherwise a supplied ``profile``
    provides them; otherwise ``None`` means "use the server defaults", so
    requests that omit pricing behave exactly as before.
    """
    prof = _profile_of(body)
    prices = (pricebook_from_dict(body.prices) if body.prices
              else (prof.prices if prof else None))
    sheet = (sheetsize_from_dict(body.sheet) if body.sheet
             else (prof.sheet if prof else None))
    return prices, sheet


def _parse_spec(body: _SpecBody) -> CabinetSpec | TableSpec | ComponentGroup:
    """Build a furniture spec (cabinet, table, project, or assembly) from a body.

    A ``profile`` in the body fills the shop's construction defaults into any
    field the design left unset before the spec is parsed.
    """
    spec_data = body.spec_data()
    prof = _profile_of(body)
    if prof is not None and isinstance(spec_data, dict):
        spec_data = prof.apply_defaults(spec_data)
    try:
        return spec_from_dict(spec_data)
    except (TypeError, ValueError, AttributeError):
        # Log the detail server-side; the parse error is built from
        # user-influenced spec data, so do not echo it back to the client.
        logger.exception("spec parse failed")
        raise HTTPException(status_code=400, detail="invalid spec")


@app.post("/api/build")
def api_build(body: BuildRequest) -> JSONResponse:
    """Build a full design bundle from a spec dict."""
    spec = _parse_spec(body)
    prices, sheet = _pricing_overrides(body)
    try:
        return JSONResponse(build_result(
            spec, want_glb=body.glb, prices=prices, sheet=sheet,
            tooling=_tooling_of(body), combine_sheet_stock=_combine_stock(body),
            boards=body.boards or None))
    except Exception:  # defensive: never 500 with a stack trace
        logger.exception("build failed")
        raise HTTPException(status_code=500, detail="build failed")


@app.post("/api/design")
def api_design(body: DesignRequest) -> JSONResponse:
    """Natural language → spec (via Claude) → full design bundle."""
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="empty prompt")
    if not _live_capabilities()["llm"]:
        raise HTTPException(
            status_code=503,
            detail="LLM unavailable: install 'anthropic' and set ANTHROPIC_API_KEY",
        )
    from .agents import design_from_prompt
    tooling = _tooling_of(body)
    try:
        res = design_from_prompt(prompt, max_attempts=body.attempts,
                                 tooling=tooling)
    except Exception:  # surface a generic agent error to the UI
        logger.exception("designer failed")
        raise HTTPException(status_code=502, detail="designer failed")
    prices, sheet = _pricing_overrides(body)
    bundle = build_result(res.spec, want_glb=body.glb, prices=prices, sheet=sheet,
                          tooling=tooling, combine_sheet_stock=_combine_stock(body),
                          boards=body.boards or None)
    bundle["attempts"] = res.attempts
    return JSONResponse(bundle)


@app.post("/api/model")
def api_model(body: ModelRequest) -> Response:
    """A GLB of the model — assembled, exploded, or a progressive subset.

    Body: ``{"spec": ..., "factor": 0..1, "include": ["Carcass", ...]}``.
    ``factor`` > 0 explodes the sub-assemblies; ``include`` keeps only those
    named sub-assemblies (for the build-view stepper). Needs build123d.
    """
    spec = _parse_spec(body)
    v = validate(spec)
    if not v.ok:
        raise HTTPException(status_code=422, detail=v.as_feedback())
    from .service import model_glb_bytes
    include = set(body.include) if body.include else None
    try:
        data = model_glb_bytes(spec, factor=body.factor, include=include)
    except RuntimeError as exc:   # build123d missing
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception:
        logger.exception("model build failed")
        raise HTTPException(status_code=500, detail="model build failed")
    return Response(content=data, media_type="model/gltf-binary")


@app.post("/api/diff")
def api_diff(body: DiffRequest) -> dict[str, Any]:
    """Field-level diff between two specs (e.g. an earlier revision vs current).

    Body: ``{"from": <spec>, "to": <spec>}``. Specs are normalised through the
    DSL first so cosmetic differences (defaults, key order) don't show up.

    The response also carries a "what changed since last quote" view: the parts
    added/removed/changed and the **price delta** (the estimate re-run on each
    spec and the totals differenced). Optional ``prices``/``sheet``/``profile``
    in the body apply to both sides, so the delta reflects only the design change.
    """
    from .diffing import spec_diff, diff_summary, quote_diff
    try:
        spec_a = spec_from_dict(body.from_ or {})
        spec_b = spec_from_dict(body.to or {})
    except (TypeError, ValueError, AttributeError):
        logger.exception("diff spec parse failed")
        raise HTTPException(status_code=400, detail="invalid spec")
    changes = spec_diff(spec_a.to_dict(), spec_b.to_dict())
    prices, sheet = _pricing_overrides(body)
    try:
        quote = quote_diff(spec_a, spec_b, prices=prices, sheet=sheet)
    except Exception:  # costing is best-effort; never fail the field diff
        logger.exception("quote diff failed")
        quote = None
    return {"changes": changes, "summary": diff_summary(changes), "quote": quote}


@app.post("/api/room/plan")
def api_room_plan(body: RoomRequest) -> dict[str, Any]:
    """Fit a run to a wall: filler sizing + scribe allowances.

    Body: ``{"widths": [600, 600, 900], "wall": {"length": 3658, ...},
    "room": {"floor_drop": 8, "out_of_square": 6, ...}}``.
    """
    from .room import Wall, Room, plan_wall
    widths = [float(w) for w in body.widths if isinstance(w, (int, float))]
    wall = Wall.from_dict(body.wall or {})
    room = Room.from_dict(body.room) if body.room else None
    return plan_wall(widths, wall, room)


@app.post("/api/export/{fmt}")
def api_export(fmt: str, body: ExportRequest) -> Response:
    """Return a downloadable file (STEP/STL/GLB/DXF/cut list/drilling) for a spec."""
    spec = _parse_spec(body)
    v = validate(spec)
    if not v.ok:
        raise HTTPException(status_code=422, detail=v.as_feedback())
    try:
        data, mime, filename = export_bytes(spec, fmt, units=body.units)
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc))
    except RuntimeError as exc:  # e.g. build123d missing for STEP/STL/GLB
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception:  # never leak a stack trace to the client
        logger.exception("export failed (fmt=%s)", fmt)
        raise HTTPException(status_code=500, detail="export failed")
    return Response(content=data, media_type=mime, headers={
        "Content-Disposition": f'attachment; filename="{filename}"'})


def main() -> None:
    import uvicorn
    host = os.environ.get("WOODAI_HOST", "127.0.0.1")
    port = int(os.environ.get("WOODAI_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
