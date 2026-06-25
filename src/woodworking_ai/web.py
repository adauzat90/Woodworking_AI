"""FastAPI web app for the cabinet designer.

Serves a single-page front end plus a small JSON API:

    GET  /              -> the SPA
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

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response

from .dsl import CabinetSpec, TableSpec, ComponentGroup, spec_from_dict
from .validator import validate
from .service import build_result, export_bytes
from .estimator import (
    PriceBook, SheetSize, pricebook_to_dict, pricebook_from_dict,
    sheetsize_to_dict, sheetsize_from_dict,
)
from .profile import ShopProfile, profile_to_dict, profile_from_dict

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Woodworking AI", version="0.1.0")


def _capabilities() -> dict[str, bool]:
    def has(mod: str) -> bool:
        try:
            __import__(mod)
            return True
        except Exception:
            return False
    return {
        "render": has("matplotlib"),
        "glb": has("build123d"),
        "llm": has("anthropic") and bool(os.environ.get("ANTHROPIC_API_KEY")),
        "convex": bool(os.environ.get("CONVEX_URL")),
    }


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    # Expose an optional Convex deployment URL to the front end.
    convex = os.environ.get("CONVEX_URL", "")
    inject = f'<script>window.__CONVEX_URL__={convex!r};</script>'
    return html.replace("<!--CONVEX_URL-->", inject)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "capabilities": _capabilities()}


@app.get("/api/pricing")
def pricing() -> dict[str, Any]:
    """The shop's default price book + sheet size, for the UI to seed its editor."""
    return {"prices": pricebook_to_dict(PriceBook()),
            "sheet": sheetsize_to_dict(SheetSize())}


@app.get("/api/profile")
def profile() -> dict[str, Any]:
    """The shop's default standards profile, for the UI to seed its editor."""
    return profile_to_dict(ShopProfile())


def _profile_of(payload: dict[str, Any]) -> ShopProfile | None:
    """The :class:`ShopProfile` in *payload*, or ``None`` when absent."""
    return profile_from_dict(payload["profile"]) if payload.get("profile") else None


def _pricing_overrides(payload: dict[str, Any]):
    """Pull optional ``prices`` / ``sheet`` overrides from a request payload.

    An explicit ``prices``/``sheet`` wins; otherwise a supplied ``profile``
    provides them; otherwise ``None`` means "use the server defaults", so
    requests that omit pricing behave exactly as before.
    """
    prof = _profile_of(payload)
    prices = (pricebook_from_dict(payload["prices"]) if payload.get("prices")
              else (prof.prices if prof else None))
    sheet = (sheetsize_from_dict(payload["sheet"]) if payload.get("sheet")
             else (prof.sheet if prof else None))
    return prices, sheet


def _parse_spec(payload: dict[str, Any]) -> CabinetSpec | TableSpec | ComponentGroup:
    """Build a furniture spec (cabinet, table, project, or assembly) from a payload.

    A ``profile`` in the payload fills the shop's construction defaults into any
    field the design left unset before the spec is parsed.
    """
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="expected a JSON object")
    spec_data = payload.get("spec", payload)
    prof = _profile_of(payload)
    if prof is not None and isinstance(spec_data, dict):
        spec_data = prof.apply_defaults(spec_data)
    try:
        return spec_from_dict(spec_data)
    except (TypeError, ValueError, AttributeError) as exc:
        raise HTTPException(status_code=400, detail=f"bad spec: {exc}")


@app.post("/api/build")
def api_build(payload: dict[str, Any]) -> JSONResponse:
    """Build a full design bundle from a spec dict."""
    spec = _parse_spec(payload)
    prices, sheet = _pricing_overrides(payload)
    try:
        return JSONResponse(build_result(
            spec, want_glb=payload.get("glb", True), prices=prices, sheet=sheet))
    except Exception as exc:  # defensive: never 500 with a stack trace
        raise HTTPException(status_code=500, detail=f"build failed: {exc}")


@app.post("/api/design")
def api_design(payload: dict[str, Any]) -> JSONResponse:
    """Natural language → spec (via Claude) → full design bundle."""
    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="empty prompt")
    if not _capabilities()["llm"]:
        raise HTTPException(
            status_code=503,
            detail="LLM unavailable: install 'anthropic' and set ANTHROPIC_API_KEY",
        )
    from .agents import design_from_prompt
    try:
        res = design_from_prompt(prompt, max_attempts=payload.get("attempts", 3))
    except Exception as exc:  # surface the agent error to the UI
        raise HTTPException(status_code=502, detail=f"designer failed: {exc}")
    prices, sheet = _pricing_overrides(payload)
    bundle = build_result(res.spec, want_glb=payload.get("glb", True),
                          prices=prices, sheet=sheet)
    bundle["attempts"] = res.attempts
    return JSONResponse(bundle)


@app.post("/api/model")
def api_model(payload: dict[str, Any]) -> Response:
    """A GLB of the model — assembled, exploded, or a progressive subset.

    Body: ``{"spec": ..., "factor": 0..1, "include": ["Carcass", ...]}``.
    ``factor`` > 0 explodes the sub-assemblies; ``include`` keeps only those
    named sub-assemblies (for the build-view stepper). Needs build123d.
    """
    spec = _parse_spec(payload)
    v = validate(spec)
    if not v.ok:
        raise HTTPException(status_code=422, detail=v.as_feedback())
    from .service import model_glb_bytes
    factor = float(payload.get("factor", 0.0) or 0.0)
    inc = payload.get("include")
    include = set(inc) if inc else None
    try:
        data = model_glb_bytes(spec, factor=factor, include=include)
    except RuntimeError as exc:   # build123d missing
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"model build failed: {exc}")
    return Response(content=data, media_type="model/gltf-binary")


@app.post("/api/diff")
def api_diff(payload: dict[str, Any]) -> dict[str, Any]:
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
        spec_a = spec_from_dict(payload.get("from") or {})
        spec_b = spec_from_dict(payload.get("to") or {})
    except (TypeError, ValueError, AttributeError) as exc:
        raise HTTPException(status_code=400, detail=f"bad spec: {exc}")
    changes = spec_diff(spec_a.to_dict(), spec_b.to_dict())
    prices, sheet = _pricing_overrides(payload)
    try:
        quote = quote_diff(spec_a, spec_b, prices=prices, sheet=sheet)
    except Exception:  # costing is best-effort; never fail the field diff
        quote = None
    return {"changes": changes, "summary": diff_summary(changes), "quote": quote}


@app.post("/api/room/plan")
def api_room_plan(payload: dict[str, Any]) -> dict[str, Any]:
    """Fit a run to a wall: filler sizing + scribe allowances.

    Body: ``{"widths": [600, 600, 900], "wall": {"length": 3658, ...},
    "room": {"floor_drop": 8, "out_of_square": 6, ...}}``.
    """
    from .room import Wall, Room, plan_wall
    widths = [float(w) for w in payload.get("widths", [])
              if isinstance(w, (int, float))]
    wall = Wall.from_dict(payload.get("wall") or {})
    room = Room.from_dict(payload["room"]) if payload.get("room") else None
    return plan_wall(widths, wall, room)


@app.post("/api/export/{fmt}")
def api_export(fmt: str, payload: dict[str, Any]) -> Response:
    """Return a downloadable file (STEP/STL/GLB/DXF/cut list/drilling) for a spec."""
    spec = _parse_spec(payload)
    v = validate(spec)
    if not v.ok:
        raise HTTPException(status_code=422, detail=v.as_feedback())
    units = payload.get("units", "metric")
    try:
        data, mime, filename = export_bytes(spec, fmt, units=units)
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc))
    except RuntimeError as exc:  # e.g. build123d missing for STEP/STL/GLB
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:  # never leak a stack trace to the client
        raise HTTPException(status_code=500, detail=f"export failed: {exc}")
    return Response(content=data, media_type=mime, headers={
        "Content-Disposition": f'attachment; filename="{filename}"'})


def main() -> None:
    import uvicorn
    host = os.environ.get("WOODAI_HOST", "127.0.0.1")
    port = int(os.environ.get("WOODAI_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
