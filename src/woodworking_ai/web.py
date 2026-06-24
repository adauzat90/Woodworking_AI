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
from fastapi.responses import HTMLResponse, JSONResponse

from .dsl import CabinetSpec
from .service import build_result

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
    }


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "capabilities": _capabilities()}


@app.post("/api/build")
def api_build(payload: dict[str, Any]) -> JSONResponse:
    """Build a full design bundle from a spec dict."""
    spec_data = payload.get("spec", payload)
    try:
        spec = CabinetSpec.from_dict(spec_data)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"bad spec: {exc}")
    want_glb = payload.get("glb", True)
    return JSONResponse(build_result(spec, want_glb=want_glb))


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
    bundle = build_result(res.spec, want_glb=payload.get("glb", True))
    bundle["attempts"] = res.attempts
    return JSONResponse(bundle)


def main() -> None:
    import uvicorn
    host = os.environ.get("WOODAI_HOST", "127.0.0.1")
    port = int(os.environ.get("WOODAI_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
