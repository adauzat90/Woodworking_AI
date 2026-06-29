"""Shared diagnostic vocabulary for the validation layer.

Three layers emit diagnostics — the deterministic validator (:class:`Issue` in
:mod:`validator`), the parse-time linter (:class:`LintIssue` in :mod:`dsl_lint`),
and the assembly critic — and each historically had its own record shape with no
common surface. This module gives them one:

* :class:`Severity` — the ``error``/``warning``/``info`` enum, a ``StrEnum`` so
  members compare equal to the bare strings the engine and ~120 tests already use
  (``Severity.ERROR == "error"`` is ``True``). Lives here, not in
  :mod:`validator`, so :mod:`dsl_lint` can share it without importing the
  CAD-aware validator.
* :class:`Diagnostic` — a structural ``Protocol`` describing the four fields any
  diagnostic exposes (``severity``, ``field``, ``message``, ``rule_id``). It
  establishes one *common shape* so a future consumer can fold a mixed stream and
  key off the stable ``rule_id`` instead of special-casing each type. Today it is
  a latent contract: ``Issue`` and ``LintIssue`` both conform and the conformance
  is tested, but the existing consumers (designer loop, CLI, web service) still
  handle the two streams separately — wiring one through the protocol is the
  follow-up this shape enables.

Pure data — no CAD, no spec types — so every layer can import it freely.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol, runtime_checkable


class Severity(StrEnum):
    """Diagnostic severity.

    A ``StrEnum`` so members compare equal to the bare strings
    (``"error"``/``"warning"``/``"info"``) the rest of the engine and the tests
    already use — ``Severity.ERROR == "error"`` is ``True`` — while giving call
    sites a typo-proof symbol to emit.
    """
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@runtime_checkable
class Diagnostic(Protocol):
    """The common shape every diagnostic record exposes.

    A structural (duck-typed) protocol: an object carrying these four attributes
    conforms — no inheritance required. ``Issue`` and ``LintIssue`` both do, so a
    consumer can iterate a heterogeneous list and filter/route by ``severity`` or
    the stable ``rule_id`` without knowing which layer produced each record.

    Note on ``field``: both records expose it, but the granularity differs —
    ``Issue.field`` is a spec field name (``"shelves"``, ``"material.door"``)
    while ``LintIssue.field`` is the dotted *location* of a dropped key
    (``"components[1].spec.widht"``). Treat it as "where", not "which attribute".

    ``@runtime_checkable`` makes ``isinstance(x, Diagnostic)`` work, but — per the
    CPython protocol semantics — it checks only that the four *attributes are
    present*, not their types. It is a duck-type gate, not input validation;
    don't rely on it to reject a malformed record.
    """

    @property
    def severity(self) -> str: ...

    @property
    def field(self) -> str: ...

    @property
    def message(self) -> str: ...

    @property
    def rule_id(self) -> str: ...
