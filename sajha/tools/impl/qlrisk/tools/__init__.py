# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
The tool registry: every tool is a ToolDef (name, description, JSON Schema, handler).

A handler takes the validated arguments and a Ctx (the work bounds) and returns
(structured result, one-line summary). The SAJHA tool classes (sajha/tools/impl/qlrisk/qlrisk_tools.py)
turn that into the tool result: structuredContent plus a text block with the summary; InvalidInput
becomes an invalid-arguments error with its message. Schemas are built when the registry is built,
from the installed qlrisk.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Tuple

from ..inputs import history_schema, market_data_schema, trades_schema
from ..options import Limits

READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}


@dataclass
class Ctx:
    limits: Limits
    warnings: List[str] = field(default_factory=list)


@dataclass
class ToolDef:
    name: str
    title: str
    description: str
    input_schema: Dict[str, Any]
    handler: Callable[[Dict[str, Any], Ctx], Tuple[Dict[str, Any], str]]
    annotations: Dict[str, Any] = field(default_factory=lambda: dict(READ_ONLY))


def currency_prop(default: str = "USD") -> Dict[str, Any]:
    from ..introspect import enum_values
    return {"type": "string", "enum": enum_values("Currency"), "default": default,
            "description": "Currency every amount is reported in (converted with the market data's FX spots)."}


def portfolio_props(limits: Limits, history: bool = False) -> Dict[str, Any]:
    props = {"trades": trades_schema(limits), "market_data": market_data_schema(),
             "reporting_currency": currency_prop()}
    if history:
        props["history"] = history_schema(limits)
    return props


def obj(props: Dict[str, Any], required: List[str] = (), **extra) -> Dict[str, Any]:
    out = {"type": "object", "properties": props, "additionalProperties": False}
    if required:
        out["required"] = list(required)
    out.update(extra)
    return out


def build_registry(limits: Limits) -> Dict[str, ToolDef]:
    from . import counterparty, discovery, engine, market_risk, pricing, regulatory
    tools: List[ToolDef] = []
    for module in (discovery, pricing, market_risk, regulatory, counterparty, engine):
        tools.extend(module.tools(limits))
    out = {}
    for t in tools:
        assert t.name not in out, t.name
        out[t.name] = t
    return out
