"""
SAJHA MCP Server — the quantitative workspace's refusals.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Every refusal of the workspace (a unit that cannot be converted, an operation whose inputs do not
fit, a table that is too large) is a :class:`QuantError`. Its message is written for a model to
read and act on: it says what was refused and, where there is one, what to do instead. A planner
passes ``str(error)`` back to the model unchanged.
"""

from __future__ import annotations


class QuantError(ValueError):
    """A refused quantity or operation. ``code`` is a short machine name; ``str()`` is for the model."""

    def __init__(self, message: str, code: str = "refused"):
        super().__init__(message)
        self.code = code


class UnitError(QuantError):
    """A unit that does not parse, or a conversion or operation the unit rules (§2.2) do not allow."""

    def __init__(self, message: str, code: str = "unit"):
        super().__init__(message, code)
