"""Errors that carry a remedy, because a message without one becomes a guess."""

from __future__ import annotations


class GclError(Exception):
    """Base class for every error this tool raises on purpose."""


class PlanError(GclError):
    """The plan file could not be read, parsed, or trusted."""


class ContractError(GclError):
    """The plan parsed but violates a contract execution depends on."""


class StateError(GclError):
    """A requested state transition is not legal."""
