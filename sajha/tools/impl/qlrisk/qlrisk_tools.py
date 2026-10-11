# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
The qlrisk tools as ordinary SAJHA tools: one class per tool, configured by config/tools/qlrisk/*.json.

The JSON config holds the name, description, title, metadata and annotations; the input schema is
built from the installed qlrisk when the tool loads (sajha/tools/impl/qlrisk/tools/, enums and product
terms read from qlrisk). The configs declare ``"requires": ["qlrisk"]``, so without qlrisk installed
the registry skips them (docs/architecture/Architecture.md §5).

A call runs the handler in SAJHA's normal execution path (worker thread, validation, policy, metrics).
The result is the handler's structured object; an MCP caller gets it as structuredContent plus a text
block with a one-line summary followed by the JSON (cut at the max_text_chars bound).
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Dict

from sajha.tools.base_mcp_tool import BaseMCPTool, ToolArgumentError

log = logging.getLogger(__name__)

_REGISTRIES: Dict[Any, Dict[str, Any]] = {}
_LOCK = threading.Lock()


def quiet_qlrisk(level: int = logging.ERROR) -> None:
    """qlrisk logs to stderr at INFO through its own singleton; keep it to errors."""
    try:
        from qlrisk.core import logger as qlog
        qlog.get_logger()
        inst = getattr(qlog, "_logger_instance", None)
        if inst is not None:
            inst.set_level(level)
    except Exception:                                     # logging is cosmetic; never block loading
        pass
    logging.getLogger("qlrisk").setLevel(level)


_QUIETED = []


def _quiet_once() -> None:
    if not _QUIETED:
        _QUIETED.append(True)
        quiet_qlrisk()


def registry_for(limits) -> Dict[str, Any]:
    """The ToolDefs (schemas built from qlrisk) for these bounds, built once per distinct bounds."""
    with _LOCK:
        reg = _REGISTRIES.get(limits)
        if reg is None:
            from .tools import build_registry
            _quiet_once()
            reg = _REGISTRIES[limits] = build_registry(limits)
        return reg


class QlriskResult(dict):
    """A handler's structured result, carrying its one-line summary for the MCP text block."""
    summary: str = ""


class QlriskTool(BaseMCPTool):
    """Base class: TOOL names the qlrisk handler (the tool name without the ``qlrisk_`` prefix)."""

    TOOL = ""
    passthrough_result = True              # the MCP result is built by format_mcp_result below

    def __init__(self, config=None):
        super().__init__(config)
        from .options import Limits
        self.limits = Limits.from_config(self.config.get("bounds"))
        self.tool_def = self._tool_def()
        from .tools.layout import present
        self.presented_schema = present(self.TOOL, self.tool_def.input_schema)
        self._input_schema = self.presented_schema
        if not self._description:                          # the config's description wins
            self._description = self.tool_def.description
        if not self._output_schema:
            self._output_schema = {"type": "object"}

    def _tool_def(self):
        return registry_for(self.limits)[self.TOOL]

    def get_input_schema(self) -> Dict:
        return self.presented_schema

    def get_output_schema(self) -> Dict:
        return {"type": "object"}

    def execute(self, arguments: Dict[str, Any]) -> Any:
        from .inputs import InvalidInput
        from .tools import Ctx
        from .tools.layout import to_handler_args
        ctx = Ctx(self.limits)
        try:
            structured, summary = self.tool_def.handler(to_handler_args(self.TOOL, dict(arguments or {})), ctx)
        except InvalidInput as exc:
            raise ToolArgumentError(self.name, str(exc)) from None
        except Exception as exc:                          # a qlrisk failure on valid-looking input
            log.exception("tool %s failed", self.name)
            raise RuntimeError(f"{self.name} failed inside qlrisk: {type(exc).__name__}: {exc}") from None
        if ctx.warnings:
            structured = {**structured, "warnings": list(structured.get("warnings", [])) + ctx.warnings}
        out = QlriskResult(json.loads(json.dumps(structured, default=str)))     # plain JSON for every caller
        out.summary = summary
        return out

    def format_mcp_result(self, result: Any, advertise_output_schema: bool = True) -> Dict[str, Any]:
        """structuredContent plus a text block: the summary line, then the JSON (cut at max_text_chars)."""
        body = json.dumps(result, default=str, separators=(",", ":"))
        if len(body) > self.limits.max_text_chars:
            body = body[: self.limits.max_text_chars] + " ... [truncated; the full result is in structuredContent]"
        summary = getattr(result, "summary", "") or f"{self.name} result"
        out: Dict[str, Any] = {"content": [{"type": "text", "text": f"{summary}\n{body}"}]}
        if advertise_output_schema and isinstance(result, dict):
            out["structuredContent"] = dict(result)
        return out


class QlriskCatalogTool(QlriskTool):
    TOOL = "catalog"


class QlriskPriceTradesTool(QlriskTool):
    TOOL = "price_trades"


class QlriskSensitivitiesTool(QlriskTool):
    TOOL = "sensitivities"


class QlriskValueAtRiskTool(QlriskTool):
    TOOL = "value_at_risk"


class QlriskBacktestTool(QlriskTool):
    TOOL = "backtest"


class QlriskPnlExplainTool(QlriskTool):
    TOOL = "pnl_explain"


class QlriskStressTestTool(QlriskTool):
    TOOL = "stress_test"


class QlriskFrtbSaCapitalTool(QlriskTool):
    TOOL = "frtb_sa_capital"


class QlriskFrtbImaCapitalTool(QlriskTool):
    TOOL = "frtb_ima_capital"


class QlriskBasel25CapitalTool(QlriskTool):
    TOOL = "basel25_capital"


class QlriskCcrExposureTool(QlriskTool):
    TOOL = "ccr_exposure"


class QlriskSaccrTool(QlriskTool):
    TOOL = "saccr"


class QlriskInitialMarginTool(QlriskTool):
    TOOL = "initial_margin"


class QlriskCreditRiskTool(QlriskTool):
    TOOL = "credit_risk"


class QlriskXvaTool(QlriskTool):
    TOOL = "xva"


class QlriskSimulatePathsTool(QlriskTool):
    TOOL = "simulate_paths"


class QlriskRiskReportTool(QlriskTool):
    TOOL = "risk_report"


class QlriskCheckLimitsTool(QlriskTool):
    TOOL = "check_limits"


class QlriskPriceProductTool(QlriskTool):
    """One implementation for every per-product pricing tool (qlrisk_price_<product>): the config's
    ``"product"`` names the qlrisk product class; the configs are generated by
    ``python -m sajha.tools.impl.qlrisk.generate``."""

    def _tool_def(self):
        product = self.config.get("product")
        if not product:
            raise ValueError(f"{self.name}: the config names no qlrisk product (\"product\")")
        _quiet_once()
        from .tools.products import product_tool
        return product_tool(product, self.limits)
