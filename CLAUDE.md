# Woodworking AI — agent guide

Parametric furniture as code: an AI writes a JSON **spec** in the project DSL →
**validate** → **compile** to real geometry, cut lists, and drilling schedules.
The core package is `src/woodworking_ai` — **pure Python, zero third-party deps**.
Start with [README.md](README.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

Skills: **`woodworking-dsl`** (author/verify a spec with the `woodai` CLI) and
**`furniture-design`** (decide *what* to build and size it). Prefer them over
guessing the DSL.

Test/lint: `make check` (ruff + pytest). The suite covers `src/woodworking_ai`
in full; see the Fusion caveat below for what is *not* headlessly testable.

## Fusion 360 add-in (`fusion360/`)

A Fusion 360 add-in that builds the **same specs** as native Fusion geometry by
swapping only the geometry backend (`adapter.py`) for Fusion's API and reusing
the rest of `woodworking_ai` verbatim. Full docs: [fusion360/README.md](fusion360/README.md).

**Read this before touching `fusion360/` — non-obvious traps:**

- Modules that `import adsk…` (`WoodworkingAI.py`, `adapter.py`, `bridge.py`)
  **only run inside Fusion's embedded CPython**. Do **not** import or run them
  from a normal shell — `adsk` does not exist there, and clicking *Run* / the
  actual geometry build happen only in Fusion's GUI. Check their *syntax* with
  `python -m py_compile`, nothing more. Everything else **is** testable
  headlessly: `src/woodworking_ai/*`, plus `fusion360/bridge_core.py` and
  `fusion360/bridge_client.py` (both stdlib-only).
- **Fusion's API is single-threaded and not thread-safe.** Never call `adsk`
  from a background thread. The folder bridge obeys this: its poller only does
  file I/O and fires a Fusion *custom event*; the build runs on the main thread.
- The add-in loads `../src/woodworking_ai` at **runtime**, so its install
  location matters and it is **not** pip-installed into Fusion. Deploy with
  `fusion360/install.ps1` (default: a directory junction, so `os.path.realpath`
  resolves `../src`; `-Copy` vendors a standalone snapshot; `-Uninstall` removes).

**Headless driving (the "folder bridge"):** an external script/agent can build
into the open Fusion document with no network port. In Fusion, Run the add-in
and click *Woodworking AI: Auto-build bridge* (or set `WOODAI_FUSION_BRIDGE=1`
before launch); then from a shell:
`python fusion360/bridge_client.py status | import <spec.json> | design "<prompt>"`.
The `design` path needs `ANTHROPIC_API_KEY`. Drop dir: `~/.woodai/fusion_drop`.
