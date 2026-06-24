"""Woodworking AI — design cabinets and furniture with AI agents that write a
parametric design language and compile it to machinable geometry + cut lists.
"""

from .dsl import CabinetSpec, Material, ToeKick, Drawer
from .validator import validate, ValidationResult
from .cutlist import generate_cutlist, CutList, Part, Hardware

__version__ = "0.1.0"

__all__ = [
    "CabinetSpec",
    "Material",
    "ToeKick",
    "Drawer",
    "validate",
    "ValidationResult",
    "generate_cutlist",
    "CutList",
    "Part",
    "Hardware",
]
