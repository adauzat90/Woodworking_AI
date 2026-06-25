"""Woodworking AI — design cabinets and furniture with AI agents that write a
parametric design language and compile it to machinable geometry + cut lists.
"""

from .dsl import (
    CabinetSpec, CabinetType, TableSpec, spec_from_dict, Material, ToeKick,
    Drawer, Construction, BackStyle, Joinery,
    CornerJoint, DovetailTails, SlideType, Grain, TopFixing,
    ApplianceType, Appliance, appliances_of, ApplianceVoid,
    Component, ComponentGroup, Project, Assembly, place_run,
)
from .validator import validate, ValidationResult
from . import engineering, stock, proportion, units
from .cutlist import generate_cutlist, CutList, Part, Hardware
from .estimator import estimate, Estimate, PriceBook, SheetSize, pack_sheets
from .drilling import (
    drilling_schedule, DrillingSchedule, hinge_count, grid_violations,
)

__version__ = "0.1.0"

__all__ = [
    "CabinetSpec",
    "CabinetType",
    "TableSpec",
    "spec_from_dict",
    "Construction",
    "BackStyle",
    "Joinery",
    "CornerJoint",
    "DovetailTails",
    "SlideType",
    "Grain",
    "TopFixing",
    "ApplianceType",
    "Appliance",
    "appliances_of",
    "ApplianceVoid",
    "Component",
    "ComponentGroup",
    "Project",
    "Assembly",
    "place_run",
    "Material",
    "ToeKick",
    "Drawer",
    "units",
    "validate",
    "ValidationResult",
    "engineering",
    "stock",
    "proportion",
    "generate_cutlist",
    "CutList",
    "Part",
    "Hardware",
    "estimate",
    "Estimate",
    "PriceBook",
    "SheetSize",
    "pack_sheets",
    "drilling_schedule",
    "DrillingSchedule",
    "hinge_count",
    "grid_violations",
]
