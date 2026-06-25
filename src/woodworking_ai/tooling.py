"""Shop tool table — what the machines in the shop can actually do.

The Critic uses this to check a design is *machinable*: a dado the dado stack
can cut, a hinge cup a Forstner bit can bore, a box shallow enough to line-bore
by hand. Pure data; a shop can tune it (e.g. wider dado stack, CNC reach).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ToolTable:
    saw_kerf: float = 3.0
    dado_min: float = 6.0          # narrowest a dado stack reliably cuts
    dado_max: float = 20.0         # widest single-setup dado stack
    # Straight router-bit diameters on hand (mm) — used for wider housings.
    router_bits: tuple = (6.0, 8.0, 10.0, 12.0, 12.7)
    forstner_sizes: tuple = (15.0, 20.0, 25.0, 35.0)   # incl. 35mm hinge cup
    max_handdrill_reach: float = 600.0   # depth a hand drill comfortably reaches


DEFAULT_TOOLS = ToolTable()
