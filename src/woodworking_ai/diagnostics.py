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
  diagnostic exposes (``severity``, ``field``, ``message``, ``rule_id``). Both
  ``Issue`` and ``LintIssue`` satisfy it, so a consumer (the web service, the
  repair loop, the UI) can treat a mixed stream uniformly and key off the stable
  ``rule_id`` rather than special-casing each type.

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

    A structural (duck-typed) protocol: any object carrying these four
    attributes *is* a ``Diagnostic`` — no inheritance required. ``Issue`` and
    ``LintIssue`` both conform, so consumers can iterate a heterogeneous list and
    filter/route by ``severity`` or the stable ``rule_id`` without knowing which
    layer produced each record.
    """

    @property
    def severity(self) -> str: ...

    @property
    def field(self) -> str: ...

    @property
    def message(self) -> str: ...

    @property
    def rule_id(self) -> str: ...
