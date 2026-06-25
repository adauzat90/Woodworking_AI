"""Export geometry and cut lists to shop-ready files.

- STEP  -> CNC / any CAD program (B-Rep, the format cabinet shops want)
- STL   -> 3D printing / mesh preview
- GLB   -> web / AR preview
- DAE   -> Collada mesh; SketchUp imports it directly
- CSV   -> cut list & hardware schedule (from cutlist.py, no CAD needed)

The B-Rep formats (STEP/STL/GLB) go straight through build123d. The Collada
``.dae`` path additionally needs ``trimesh`` to write the mesh: build123d
tessellates the B-Rep, trimesh serialises it. Both imports are guarded and raise
a clear :class:`RuntimeError` if the optional dependency is missing, exactly like
the other CAD exporters.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .cutlist import CutList
from .dxf import export_cutlayout_dxf  # noqa: F401  (re-export, no CAD dep)


def export_step(model: Any, path: str | Path) -> Path:
    import build123d as b3d  # type: ignore
    path = Path(path)
    b3d.export_step(model, str(path))
    return path


def export_stl(model: Any, path: str | Path) -> Path:
    import build123d as b3d  # type: ignore
    path = Path(path)
    b3d.export_stl(model, str(path))
    return path


def export_glb(model: Any, path: str | Path) -> Path:
    import build123d as b3d  # type: ignore
    path = Path(path)
    # build123d exposes glTF export via the Mesher; .glb is the binary form.
    b3d.export_gltf(model, str(path), binary=True)
    return path


def _require_trimesh() -> Any:
    try:
        import trimesh  # type: ignore
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "trimesh is required for Collada (.dae) export. Install it with:\n"
            "    pip install trimesh\n"
            "(STEP/STL/GLB export and the cut list work without it.)"
        ) from exc
    return trimesh


def export_dae(model: Any, path: str | Path) -> Path:
    """Export *model* as a Collada ``.dae`` mesh (SketchUp-friendly).

    SketchUp imports Collada (and STL/glTF) directly, so this is the practical
    "SketchUp export" — a native ``.skp`` would need the proprietary SDK. The
    B-Rep is tessellated to STL by build123d, then re-serialised to Collada by
    trimesh. Both deps are guarded; a clear :class:`RuntimeError` is raised if
    either is missing (mirrors :func:`export_glb`).
    """
    import tempfile

    trimesh = _require_trimesh()
    path = Path(path)
    # Tessellate the B-Rep to a mesh via build123d's STL writer, then hand the
    # mesh to trimesh to write Collada. Going through STL keeps us off any one
    # build123d tessellation API and works the same across versions.
    with tempfile.TemporaryDirectory() as d:
        stl_path = export_stl(model, Path(d) / "mesh.stl")
        mesh = trimesh.load(str(stl_path), file_type="stl")
        mesh.export(str(path), file_type="dae")
    return path


def export_parts_step(model: Any, out_dir: str | Path) -> list[Path]:
    """Write each part/solid of *model* as its own STEP file in *out_dir*.

    Useful to build, machine or rearrange parts independently. *model* is a
    build123d ``Compound`` of labelled panel solids (as produced by
    :func:`woodworking_ai.builder.build_model`); each child becomes
    ``<out_dir>/<NN>_<label>.step``. Returns the written paths in order.
    """
    return _export_parts(model, out_dir, export_step, "step")


def export_parts_stl(model: Any, out_dir: str | Path) -> list[Path]:
    """Write each part/solid of *model* as its own STL file in *out_dir*.

    The mesh sibling of :func:`export_parts_step`; same naming and ordering.
    """
    return _export_parts(model, out_dir, export_stl, "stl")


def _slugify(text: str) -> str:
    """A filesystem-safe slug for a part label (keep word chars; collapse rest)."""
    out = []
    prev_us = False
    for ch in str(text):
        if ch.isalnum():
            out.append(ch)
            prev_us = False
        elif not prev_us:
            out.append("_")
            prev_us = True
    return "".join(out).strip("_") or "part"


def _export_parts(model: Any, out_dir: str | Path, fn, ext: str) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    children = list(getattr(model, "children", None) or [model])
    paths: list[Path] = []
    for i, part in enumerate(children, start=1):
        label = getattr(part, "label", "") or f"part{i}"
        name = f"{i:02d}_{_slugify(label)}.{ext}"
        paths.append(fn(part, out_dir / name))
    return paths


def write_cutlist_csv(cutlist: CutList, path: str | Path,
                      unit: str = "metric") -> Path:
    path = Path(path)
    path.write_text(cutlist.to_csv(unit) + "\n", encoding="utf-8")
    return path


def write_hardware_csv(cutlist: CutList, path: str | Path) -> Path:
    path = Path(path)
    path.write_text(cutlist.hardware_csv() + "\n", encoding="utf-8")
    return path
