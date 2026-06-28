"""Designer accuracy eval — does natural language actually become the spec asked for?

The value of this project is the deterministic DSL + validator + compiler; the
*weak* link is the natural-language step that writes the spec. This harness
measures that step with two independent scores per case:

* **Buildable** — the produced spec passes :func:`validate` (no errors) *and* the
  geometry :func:`critique` (no errors). This is the same gate the agent already
  repairs against, so a buildable=False here means the agent gave up.
* **Intent match** — a set of per-case checks (``IntentCheck``) asserting the spec
  matches what the prompt unambiguously asked for (a 36" base with two doors is a
  ``base`` ~914 mm wide with ``doors == 2``). Defaults the prompt left open are
  *not* checked, so a miss is a real disagreement, not a stylistic choice.

A case **passes** only when it is buildable *and* every *required* intent holds.
The scoring (``score_design`` / ``score_spec``) is pure and deterministic — it
runs headless against a hand-built spec with no API key, so CI covers the logic.
``run_eval`` is the only part that calls the agent (and so needs a key); it is
imported lazily. The CLI entry point is ``woodai eval``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable

from .validator import ValidationResult
from .agents.critic import CritiqueResult


# --------------------------------------------------------------------------- #
# Intent predicates — small, robust readers over a spec of any furniture type. #
# They never raise on the "wrong" spec type; they simply return False, which   #
# is the correct behaviour (the agent produced the wrong kind of thing).       #
# --------------------------------------------------------------------------- #

def _enum_str(value) -> str:
    return str(getattr(value, "value", value)).strip().lower()


def cabinet_type_is(name: str) -> Callable[[object], bool]:
    return lambda s: _enum_str(getattr(s, "cabinet_type", "")) == name


def is_table() -> Callable[[object], bool]:
    return lambda s: type(s).__name__ == "TableSpec"


def dim_near(attr: str, target: float, tol: float = 30.0) -> Callable[[object], bool]:
    def check(s):
        v = getattr(s, attr, None)
        return v is not None and abs(float(v) - target) <= tol
    return check


def doors_eq(n: int) -> Callable[[object], bool]:
    return lambda s: int(getattr(s, "doors", 0) or 0) == n


def doors_at_least(n: int) -> Callable[[object], bool]:
    return lambda s: int(getattr(s, "doors", 0) or 0) >= n


def drawers_eq(n: int) -> Callable[[object], bool]:
    return lambda s: len(getattr(s, "drawers", []) or []) == n


def drawers_at_least(n: int) -> Callable[[object], bool]:
    return lambda s: len(getattr(s, "drawers", []) or []) >= n


def shelves_at_least(n: int) -> Callable[[object], bool]:
    return lambda s: int(getattr(s, "shelves", 0) or 0) >= n


def dim_between(attr: str, lo: float, hi: float) -> Callable[[object], bool]:
    def check(s):
        v = getattr(s, attr, None)
        return v is not None and lo <= float(v) <= hi
    return check


def no_toe_kick() -> Callable[[object], bool]:
    return lambda s: float(getattr(s, "toe_kick_height", 0) or 0) == 0


def drawer_front_heights(values, tol: float = 2.0) -> Callable[[object], bool]:
    """Every drawer front height the prompt named is present (order-free)."""
    want = sorted(float(v) for v in values)

    def check(s):
        ds = getattr(s, "drawers", []) or []
        got = sorted(float(getattr(d, "front_height", 0) or 0) for d in ds)
        return (len(got) == len(want)
                and all(abs(a - b) <= tol for a, b in zip(got, want, strict=False)))
    return check


def all_drawers_attr(attr: str, value: str) -> Callable[[object], bool]:
    """Every drawer sets *attr* to *value* (enum or string)."""
    def check(s):
        ds = getattr(s, "drawers", []) or []
        return bool(ds) and all(_enum_str(getattr(d, attr, None)) == value for d in ds)
    return check


def cabinet_type_in(names) -> Callable[[object], bool]:
    """The cabinet type is one of *names* — for prompts with several defensible
    readings, where the test is sanity, not an exact answer."""
    want = {n.lower() for n in names}
    return lambda s: _enum_str(getattr(s, "cabinet_type", "")) in want


def has_storage() -> Callable[[object], bool]:
    """The piece actually stores something — a shelf, a door, or a drawer."""
    def check(s):
        return (int(getattr(s, "shelves", 0) or 0) > 0
                or int(getattr(s, "doors", 0) or 0) > 0
                or len(getattr(s, "drawers", []) or []) > 0)
    return check


# --- project (multi-cabinet) predicates ------------------------------------- #

def is_project() -> Callable[[object], bool]:
    return lambda s: type(s).__name__ == "Project"


def _component_specs(s):
    return [c.spec for c in (getattr(s, "components", []) or [])
            if getattr(c, "spec", None) is not None]


def component_count(n: int) -> Callable[[object], bool]:
    return lambda s: len(getattr(s, "components", []) or []) == n


def component_widths_include(values, tol: float = 10.0) -> Callable[[object], bool]:
    """Each named component width is matched by some component (greedy, order-free)."""
    want = [float(v) for v in values]

    def check(s):
        pool = [float(getattr(sp, "width", 0) or 0) for sp in _component_specs(s)]
        for w in want:
            m = next((g for g in pool if abs(g - w) <= tol), None)
            if m is None:
                return False
            pool.remove(m)
        return True
    return check


def all_components_type(name: str) -> Callable[[object], bool]:
    def check(s):
        specs = _component_specs(s)
        return bool(specs) and all(
            _enum_str(getattr(sp, "cabinet_type", "")) == name for sp in specs)
    return check


def door_style_is(name: str) -> Callable[[object], bool]:
    return lambda s: _enum_str(getattr(s, "door_style", "")) == name


def construction_is(name: str) -> Callable[[object], bool]:
    return lambda s: _enum_str(getattr(s, "construction", "")) == name


@dataclass(frozen=True)
class IntentCheck:
    """One checkable thing the prompt asked for. ``required`` checks gate the
    pass/fail verdict; non-required ones are scored but never fail a case."""

    desc: str
    check: Callable[[object], bool]
    required: bool = True


@dataclass(frozen=True)
class EvalCase:
    name: str
    prompt: str
    intents: tuple[IntentCheck, ...]


# An inch is 25.4 mm; the band on inch-authored prompts allows the agent's own
# rounding (e.g. 36" -> 900 or 914 mm both count).
def _in(x: float) -> float:
    return x * 25.4


DEFAULT_CASES: tuple[EvalCase, ...] = (
    EvalCase(
        "sink_base_36in_two_doors",
        "36 inch sink base cabinet, two shaker doors, one shelf",
        (
            IntentCheck("is a base cabinet", cabinet_type_is("base")),
            IntentCheck("~36in wide", dim_near("width", _in(36), tol=20)),
            IntentCheck("two doors", doors_eq(2)),
            IntentCheck("shaker door style", door_style_is("shaker")),
            IntentCheck("at least one shelf", shelves_at_least(1)),
        ),
    ),
    EvalCase(
        "tall_pantry_600_4_shelves",
        "tall pantry cabinet 600 wide, 4 shelves",
        (
            IntentCheck("is a tall cabinet", cabinet_type_is("tall")),
            IntentCheck("600 wide", dim_near("width", 600)),
            IntentCheck("at least 4 shelves", shelves_at_least(4)),
        ),
    ),
    EvalCase(
        "drawer_base_30in_3_drawers",
        "30 inch drawer base, 3 drawers, no doors",
        (
            IntentCheck("is a base cabinet", cabinet_type_is("base")),
            IntentCheck("~30in wide", dim_near("width", _in(30), tol=20)),
            IntentCheck("three drawers", drawers_eq(3)),
            IntentCheck("no doors", doors_eq(0)),
        ),
    ),
    EvalCase(
        "wall_cabinet_760x700_two_doors",
        "wall cabinet 760 wide and 700 tall, two doors",
        (
            IntentCheck("is a wall cabinet", cabinet_type_is("wall")),
            IntentCheck("760 wide", dim_near("width", 760)),
            IntentCheck("700 tall", dim_near("height", 700)),
            IntentCheck("two doors", doors_eq(2)),
        ),
    ),
    EvalCase(
        "coffee_table_1200x600",
        "coffee table 1200 long, 600 deep, 450 tall",
        (
            IntentCheck("is a table", is_table()),
            IntentCheck("1200 long", dim_near("width", 1200)),
            IntentCheck("600 deep", dim_near("depth", 600)),
            IntentCheck("450 tall", dim_near("height", 450)),
        ),
    ),
    EvalCase(
        "faceframe_bookcase_900x1800",
        "face frame bookcase 900 wide, 1800 tall, 4 shelves",
        (
            IntentCheck("is a bookcase", cabinet_type_is("bookcase")),
            IntentCheck("face-frame construction", construction_is("face_frame")),
            IntentCheck("at least 4 shelves", shelves_at_least(4)),
        ),
    ),
    EvalCase(
        "frameless_base_450_single_door",
        "frameless base cabinet 450 wide with a single door",
        (
            IntentCheck("is a base cabinet", cabinet_type_is("base")),
            IntentCheck("450 wide", dim_near("width", 450)),
            IntentCheck("one door", doors_eq(1)),
            IntentCheck("frameless", construction_is("frameless")),
        ),
    ),
    EvalCase(
        "dresser_800_5_drawers",
        "dresser 800 wide with 5 drawers",
        (
            IntentCheck("is a dresser", cabinet_type_is("dresser")),
            IntentCheck("800 wide", dim_near("width", 800)),
            IntentCheck("five drawers", drawers_eq(5)),
        ),
    ),
)


# Adversarial set — the cases that actually probe the natural-language step:
# unit traps (feet / metres / mixed units in one prompt), type that must be
# *inferred* from a use-case with no type word, missing dimensions the agent must
# default sanely, an over-constrained prompt that must still build, and an
# implied quantity. Intent checks stay objective; where the "right" answer is
# genuinely open the tighter checks are marked optional so only real disagreement
# (or an unbuildable result) fails a case.
DEFAULT_TOL = 25.0   # mm slack for unit-conversion rounding to tidy numbers

ADVERSARIAL_CASES: tuple[EvalCase, ...] = (
    EvalCase(
        "unit_trap_feet",
        "base cabinet two feet wide and three feet tall, one door",
        (
            IntentCheck("is a base cabinet", cabinet_type_is("base")),
            IntentCheck("2 ft -> ~610 mm wide",
                        dim_near("width", 2 * 304.8, tol=DEFAULT_TOL)),
            IntentCheck("3 ft -> ~914 mm tall",
                        dim_near("height", 3 * 304.8, tol=DEFAULT_TOL)),
            IntentCheck("one door", doors_eq(1)),
        ),
    ),
    EvalCase(
        "unit_trap_metres",
        "wall cabinet 0.8 metres wide and 0.35 deep, two doors",
        (
            IntentCheck("is a wall cabinet", cabinet_type_is("wall")),
            IntentCheck("0.8 m -> 800 mm wide", dim_near("width", 800, tol=DEFAULT_TOL)),
            IntentCheck("0.35 m -> 350 mm deep", dim_near("depth", 350, tol=DEFAULT_TOL)),
            IntentCheck("two doors", doors_eq(2)),
        ),
    ),
    EvalCase(
        "mixed_units_one_prompt",
        "base cabinet 24 inches wide and 720 mm tall, single door",
        (
            IntentCheck("is a base cabinet", cabinet_type_is("base")),
            IntentCheck("24 in -> ~610 mm wide",
                        dim_near("width", 24 * 25.4, tol=DEFAULT_TOL)),
            IntentCheck("720 mm tall", dim_near("height", 720, tol=DEFAULT_TOL)),
            IntentCheck("one door", doors_eq(1)),
        ),
    ),
    EvalCase(
        "implicit_wall_from_use",
        "I want to hang a cupboard above my kitchen counter for mugs and "
        "plates, about 700 wide",
        (
            IntentCheck("inferred a wall cabinet", cabinet_type_is("wall")),
            IntentCheck("~700 wide", dim_near("width", 700, tol=40)),
            IntentCheck("has at least one door", doors_at_least(1), required=False),
        ),
    ),
    EvalCase(
        "implicit_open_shelving",
        "open shelving for my paperback books in the living room",
        (
            # Type is genuinely open (bookcase or a doorless tall unit); score the
            # *observable* intent: open (no doors), several shelves, and buildable.
            IntentCheck("open — no doors", doors_eq(0)),
            IntentCheck("multiple shelves", shelves_at_least(3)),
            IntentCheck("a bookcase", cabinet_type_is("bookcase"), required=False),
        ),
    ),
    EvalCase(
        "over_constrained_narrow",
        "300 mm wide base cabinet with two doors and a center mullion",
        (
            # 300 mm is too narrow for a sensible two-door split; the honest
            # outcome is *something buildable* near 300 wide. Two-door + mullion
            # are optional — the test is whether it degrades gracefully.
            IntentCheck("is a base cabinet", cabinet_type_is("base")),
            IntentCheck("~300 wide", dim_near("width", 300, tol=DEFAULT_TOL)),
            IntentCheck("kept two doors", doors_eq(2), required=False),
        ),
    ),
    EvalCase(
        "implied_drawer_quantity",
        "a dresser about 1200 mm tall, filled with as many equal drawers as "
        "look right",
        (
            IntentCheck("is a dresser", cabinet_type_is("dresser")),
            IntentCheck("~1200 tall", dim_near("height", 1200, tol=50)),
            IntentCheck("several drawers (>=4)", drawers_at_least(4)),
        ),
    ),
    EvalCase(
        "dimensionless_side_table",
        "a small side table to go next to a sofa",
        (
            IntentCheck("is a table", is_table()),
            IntentCheck("sane sofa-side height (350-700 mm)",
                        dim_between("height", 350, 700)),
            IntentCheck("small footprint (<=700 mm)",
                        dim_between("width", 250, 700)),
        ),
    ),
)


# Stress set — strict, compositional checks meant to find the failure boundary:
# fractional-inch and odd-metric conversions held to a few mm, specific enum
# values (raised-panel doors, undermount slides), per-drawer attributes, an exact
# multiset of drawer heights, and an exclusion the model must honour (no toe
# kick). Buildability is cheap (the repair loop fixes it); these probe whether
# the spec is *what was asked* down to the detail. All checks are required.
STRESS_CASES: tuple[EvalCase, ...] = (
    EvalCase(
        "fractional_inch_width",
        "base cabinet 37 and 3/8 inches wide, one door, one shelf",
        (
            IntentCheck("is a base cabinet", cabinet_type_is("base")),
            IntentCheck("37-3/8 in -> ~949 mm wide",
                        dim_near("width", 37.375 * 25.4, tol=4)),
            IntentCheck("one door", doors_eq(1)),
            IntentCheck("one shelf", shelves_at_least(1)),
        ),
    ),
    EvalCase(
        "exact_drawer_heights",
        "drawer base 600 wide, four drawers with front heights 140, 180, 180 "
        "and 220 mm from top to bottom, no doors",
        (
            IntentCheck("is a base cabinet", cabinet_type_is("base")),
            IntentCheck("600 wide", dim_near("width", 600, tol=10)),
            IntentCheck("no doors", doors_eq(0)),
            IntentCheck("four drawers", drawers_eq(4)),
            IntentCheck("exact front heights 140/180/180/220",
                        drawer_front_heights([140, 180, 180, 220])),
        ),
    ),
    EvalCase(
        "open_cubby_no_toe_no_doors",
        "a base cabinet 500 wide, no toe kick and no doors — just an open cubby "
        "with two fixed shelves",
        (
            IntentCheck("is a base cabinet", cabinet_type_is("base")),
            IntentCheck("500 wide", dim_near("width", 500, tol=10)),
            IntentCheck("no doors", doors_eq(0)),
            IntentCheck("no toe kick", no_toe_kick()),
            IntentCheck("two shelves", shelves_at_least(2)),
        ),
    ),
    EvalCase(
        "undermount_dovetail_drawers",
        "30 inch drawer base, three drawers, on undermount slides with "
        "dovetailed boxes, no doors",
        (
            IntentCheck("is a base cabinet", cabinet_type_is("base")),
            IntentCheck("~30in wide", dim_near("width", 30 * 25.4, tol=20)),
            IntentCheck("three drawers", drawers_eq(3)),
            IntentCheck("all undermount slides",
                        all_drawers_attr("slide_type", "undermount")),
            IntentCheck("all dovetailed boxes",
                        all_drawers_attr("corner_joint", "dovetail")),
        ),
    ),
    EvalCase(
        "raised_panel_faceframe",
        "a face frame base cabinet 800 wide with two raised panel doors",
        (
            IntentCheck("is a base cabinet", cabinet_type_is("base")),
            IntentCheck("800 wide", dim_near("width", 800, tol=10)),
            IntentCheck("two doors", doors_eq(2)),
            IntentCheck("face-frame construction", construction_is("face_frame")),
            IntentCheck("raised-panel door style", door_style_is("raised_panel")),
        ),
    ),
    EvalCase(
        "tight_metric_odd",
        "wall cabinet 0.725 metres wide and 0.34 deep, two doors, frameless",
        (
            IntentCheck("is a wall cabinet", cabinet_type_is("wall")),
            IntentCheck("0.725 m -> 725 mm wide", dim_near("width", 725, tol=3)),
            IntentCheck("0.34 m -> 340 mm deep", dim_near("depth", 340, tol=3)),
            IntentCheck("two doors", doors_eq(2)),
            IntentCheck("frameless", construction_is("frameless")),
        ),
    ),
)


# Ambiguous set — prompts with no single right answer. The model can't ask a
# clarifying question (the agent always emits a spec), so the test is whether it
# lands inside a *defensible envelope* rather than on one answer: a sane type, a
# real storage function, proportions a human would accept. A failure here means
# it produced something absurd or unbuildable, not merely a different valid call.
AMBIGUOUS_CASES: tuple[EvalCase, ...] = (
    EvalCase(
        "ambiguous_kitchen_cabinet",
        "a cabinet for my kitchen",
        (
            IntentCheck("some kitchen cabinet type",
                        cabinet_type_in(["base", "wall", "tall", "corner_blind",
                                         "corner_diagonal", "dresser"])),
            IntentCheck("a sane cabinet width (250-1300 mm)",
                        dim_between("width", 250, 1300)),
        ),
    ),
    EvalCase(
        "ambiguous_shoe_storage",
        "somewhere to store shoes by the front door",
        (
            IntentCheck("actually stores things", has_storage()),
            IntentCheck("a sane footprint width (300-1300 mm)",
                        dim_between("width", 300, 1300)),
        ),
    ),
    EvalCase(
        "ambiguous_metre_tall",
        "a piece of furniture about a metre tall",
        (
            # The only firm thing the prompt says is the height — hold it there.
            IntentCheck("about a metre tall (850-1150 mm)",
                        dim_between("height", 850, 1150)),
        ),
    ),
    EvalCase(
        "ambiguous_nightstand",
        "a nightstand",
        (
            IntentCheck("bedside height (400-750 mm)",
                        dim_between("height", 400, 750)),
            IntentCheck("small footprint width (300-650 mm)",
                        dim_between("width", 300, 650)),
        ),
    ),
)


# Project set — the multi-cabinet path (kind: "project"), which every other suite
# leaves untested. Scores that the result is a Project with the right components
# AND that it builds — buildable here includes the placement / footprint-overlap
# check, so a run whose cabinets collide fails.
PROJECT_CASES: tuple[EvalCase, ...] = (
    EvalCase(
        "project_three_base_run",
        "a small kitchen run of three base cabinets in a row: 900 wide, 600 "
        "wide and 450 wide",
        (
            IntentCheck("is a project", is_project()),
            IntentCheck("three components", component_count(3)),
            IntentCheck("all base cabinets", all_components_type("base")),
            IntentCheck("widths 900/600/450 present",
                        component_widths_include([900, 600, 450])),
        ),
    ),
    EvalCase(
        "project_two_wall_builtin",
        "a built-in of two 600 mm wall cabinets side by side",
        (
            IntentCheck("is a project", is_project()),
            IntentCheck("two components", component_count(2)),
            IntentCheck("all wall cabinets", all_components_type("wall")),
            IntentCheck("both 600 wide", component_widths_include([600, 600])),
        ),
    ),
    EvalCase(
        "project_l_shaped_run",
        "an L-shaped kitchen: two 600 mm base cabinets along one wall and one "
        "600 mm base cabinet on the perpendicular return",
        (
            IntentCheck("is a project", is_project()),
            IntentCheck("three components", component_count(3)),
            IntentCheck("all base cabinets", all_components_type("base")),
            # buildable (scored separately) covers the inner-corner collision.
        ),
    ),
)


# Named suites for the runner / CLI.
SUITES: dict[str, tuple[EvalCase, ...]] = {
    "default": DEFAULT_CASES,
    "adversarial": ADVERSARIAL_CASES,
    "stress": STRESS_CASES,
    "ambiguous": AMBIGUOUS_CASES,
    "projects": PROJECT_CASES,
    "all": (DEFAULT_CASES + ADVERSARIAL_CASES + STRESS_CASES
            + AMBIGUOUS_CASES + PROJECT_CASES),
}


# --------------------------------------------------------------------------- #
# Scoring (pure, deterministic, no API).                                       #
# --------------------------------------------------------------------------- #

@dataclass
class CaseResult:
    name: str
    prompt: str
    buildable: bool
    intents_passed: int
    intents_total: int
    required_missed: list[str] = field(default_factory=list)
    optional_missed: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)
    critic_errors: list[str] = field(default_factory=list)
    attempts: int | None = None
    error: str | None = None      # the agent raised or never returned a spec

    @property
    def passed(self) -> bool:
        """A case passes only if it built and met every *required* intent."""
        return (self.error is None and self.buildable
                and not self.required_missed)

    @property
    def intent_score(self) -> float:
        if self.intents_total == 0:
            return 1.0
        return self.intents_passed / self.intents_total

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "prompt": self.prompt,
            "passed": self.passed,
            "buildable": self.buildable,
            "intent_score": round(self.intent_score, 3),
            "intents_passed": self.intents_passed,
            "intents_total": self.intents_total,
            "required_missed": self.required_missed,
            "optional_missed": self.optional_missed,
            "validation_errors": self.validation_errors,
            "critic_errors": self.critic_errors,
            "attempts": self.attempts,
            "error": self.error,
        }


def score_spec(case: EvalCase, spec, validation: ValidationResult,
               crit: CritiqueResult | None = None, *,
               attempts: int | None = None) -> CaseResult:
    """Score a produced *spec* against *case* — the deterministic core.

    Buildable means it passes validation with no errors and, when a critique is
    supplied, the geometry critic with no errors. Each intent is evaluated and
    bucketed into required/optional misses.
    """
    buildable = validation.ok and (crit is None or crit.ok)
    passed = 0
    required_missed: list[str] = []
    optional_missed: list[str] = []
    for ic in case.intents:
        try:
            ok = bool(ic.check(spec))
        except Exception:
            ok = False
        if ok:
            passed += 1
        elif ic.required:
            required_missed.append(ic.desc)
        else:
            optional_missed.append(ic.desc)
    return CaseResult(
        name=case.name, prompt=case.prompt, buildable=buildable,
        intents_passed=passed, intents_total=len(case.intents),
        required_missed=required_missed, optional_missed=optional_missed,
        validation_errors=[str(i) for i in validation.errors],
        critic_errors=[str(i) for i in crit.errors] if crit else [],
        attempts=attempts,
    )


def score_design(case: EvalCase, design_result) -> CaseResult:
    """Score a :class:`agents.designer.DesignResult` for *case*."""
    return score_spec(
        case, design_result.spec, design_result.validation,
        design_result.critique, attempts=design_result.attempts,
    )


def _failure_result(case: EvalCase, error: str) -> CaseResult:
    """A case where the agent raised or never produced a usable spec."""
    return CaseResult(
        name=case.name, prompt=case.prompt, buildable=False,
        intents_passed=0, intents_total=len(case.intents),
        required_missed=[ic.desc for ic in case.intents if ic.required],
        error=error,
    )


@dataclass
class EvalReport:
    results: list[CaseResult]

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def pass_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.passed for r in self.results) / self.total

    @property
    def buildable_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.buildable for r in self.results) / self.total

    @property
    def intent_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.intent_score for r in self.results) / self.total

    def to_dict(self) -> dict:
        return {
            "pass_rate": round(self.pass_rate, 3),
            "buildable_rate": round(self.buildable_rate, 3),
            "intent_rate": round(self.intent_rate, 3),
            "total": self.total,
            "passed": sum(r.passed for r in self.results),
            "cases": [r.to_dict() for r in self.results],
        }

    def format(self) -> str:
        lines = ["Designer accuracy eval", "=" * 60]
        for r in self.results:
            mark = "PASS" if r.passed else "FAIL"
            lines.append(
                f"[{mark}] {r.name}  "
                f"intent {r.intents_passed}/{r.intents_total}"
                f"  {'buildable' if r.buildable else 'NOT buildable'}"
            )
            if r.error:
                lines.append(f"        agent error: {r.error}")
            for m in r.required_missed:
                lines.append(f"        missed (required): {m}")
            for m in r.optional_missed:
                lines.append(f"        missed (optional): {m}")
            for e in r.validation_errors:
                lines.append(f"        validation: {e}")
            for e in r.critic_errors:
                lines.append(f"        critic: {e}")
        lines.append("-" * 60)
        lines.append(
            f"pass rate {self.pass_rate:.0%}  ·  "
            f"buildable {self.buildable_rate:.0%}  ·  "
            f"intent {self.intent_rate:.0%}  "
            f"({sum(r.passed for r in self.results)}/{self.total} cases)"
        )
        return "\n".join(lines)


def run_eval(cases: Iterable[EvalCase] | None = None, *,
             model: str | None = None, max_attempts: int = 3,
             run_critic: bool = True,
             progress: Callable[[EvalCase], None] | None = None) -> EvalReport:
    """Run the agent over *cases* and score each. Needs ``ANTHROPIC_API_KEY``.

    The designer import is lazy so importing this module (and its pure scoring)
    never requires the optional ``anthropic`` dependency.
    """
    from .agents.designer import design_from_prompt

    cases = list(cases) if cases is not None else list(DEFAULT_CASES)
    results: list[CaseResult] = []
    for case in cases:
        if progress is not None:
            progress(case)
        try:
            dr = design_from_prompt(
                case.prompt, model=model, max_attempts=max_attempts,
                run_critic=run_critic,
            )
        except Exception as exc:  # the agent itself failed — record, don't abort
            results.append(_failure_result(case, f"{type(exc).__name__}: {exc}"))
            continue
        results.append(score_design(case, dr))
    return EvalReport(results)
