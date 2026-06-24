"""Export geometry and cut lists to shop-ready files.

- STEP  -> CNC / any CAD program (B-Rep, the format cabinet shops want)
- STL   -> 3D printing / mesh preview
- GLB   -> web / AR preview
- CSV   -> cut list & hardware schedule (from cutlist.py, no CAD needed)
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


def write_cutlist_csv(cutlist: CutList, path: str | Path,
                      unit: str = "metric") -> Path:
    path = Path(path)
    path.write_text(cutlist.to_csv(unit) + "\n", encoding="utf-8")
    return path


def write_hardware_csv(cutlist: CutList, path: str | Path) -> Path:
    path = Path(path)
    path.write_text(cutlist.hardware_csv() + "\n", encoding="utf-8")
    return path
