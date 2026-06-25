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


def _pricing_overrides(payload: dict[str, Any]):
    """Pull optional ``prices`` / ``sheet`` overrides from a request payload.

    Returns (PriceBook | None, SheetSize | None) — ``None`` means "use the
    server defaults", so requests that omit pricing behave exactly as before.
    """
    prices = pricebook_from_dict(payload["prices"]) if payload.get("prices") else None
    sheet = sheetsize_from_dict(payload["sheet"]) if payload.get("sheet") else None
    return prices, sheet


def _parse_spec(payload: dict[str, Any]) -> CabinetSpec | TableSpec | ComponentGroup:
    """Build a furniture spec (cabinet, table, project, or assembly) from a payload."""
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="expected a JSON object")
    spec_data = payload.get("spec", payload)
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
