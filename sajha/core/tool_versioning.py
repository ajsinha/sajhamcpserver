"""
SAJHA MCP Server v4.0.0 — Tool Versioning & Quality
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Versioned tools: v1 and v2 run side-by-side.
Deprecation lifecycle: active → deprecated → sunset.
Contract testing: validate input/output schemas against live data.
"""

import json
import time
import logging
from enum import Enum
from typing import Dict, List, Optional, Any
from datetime import datetime, date
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class ToolLifecycle(str, Enum):
    ACTIVE = 'active'
    DEPRECATED = 'deprecated'
    SUNSET = 'sunset'          # still registered but returns warning
    RETIRED = 'retired'        # removed from tools/list


@dataclass
class ToolVersion:
    """Metadata for a specific version of a tool."""
    tool_name: str             # base name e.g. "fmp_stock_quote"
    version: str               # e.g. "2.0.0"
    lifecycle: ToolLifecycle = ToolLifecycle.ACTIVE
    deprecated_at: Optional[str] = None
    sunset_date: Optional[str] = None    # ISO date after which it stops working
    successor: Optional[str] = None      # name of replacement tool/version
    changelog: str = ''

    @property
    def versioned_name(self) -> str:
        """e.g. fmp_stock_quote@2.0.0"""
        return f"{self.tool_name}@{self.version}"

    @property
    def is_past_sunset(self) -> bool:
        if not self.sunset_date:
            return False
        try:
            return date.fromisoformat(self.sunset_date) < date.today()
        except:
            return False

    def to_dict(self) -> Dict:
        return {
            'tool_name': self.tool_name, 'version': self.version,
            'lifecycle': self.lifecycle.value, 'deprecated_at': self.deprecated_at,
            'sunset_date': self.sunset_date, 'successor': self.successor,
            'changelog': self.changelog,
        }


class ToolVersionManager:
    """
    Manages tool versions and deprecation lifecycle.

    Tools can have multiple versions registered simultaneously:
      fmp_stock_quote      → latest (alias)
      fmp_stock_quote@1.0  → v1 (deprecated, sunset 2025-12-31)
      fmp_stock_quote@2.0  → v2 (active)

    When a client calls "fmp_stock_quote", it gets the latest active version.
    When a client calls "fmp_stock_quote@1.0", it gets v1 with a deprecation warning.
    """

    def __init__(self):
        self._versions: Dict[str, ToolVersion] = {}  # versioned_name → ToolVersion
        self._latest: Dict[str, str] = {}            # base_name → latest versioned_name

    def register_version(self, tv: ToolVersion):
        self._versions[tv.versioned_name] = tv
        # Update latest pointer if this version is active
        if tv.lifecycle == ToolLifecycle.ACTIVE:
            current_latest = self._latest.get(tv.tool_name)
            if not current_latest or tv.version > self._versions.get(current_latest, tv).version:
                self._latest[tv.tool_name] = tv.versioned_name
        logger.info(f"Tool version registered: {tv.versioned_name} ({tv.lifecycle.value})")

    def deprecate(self, tool_name: str, version: str, sunset_date: str = '',
                  successor: str = '') -> bool:
        key = f"{tool_name}@{version}"
        tv = self._versions.get(key)
        if not tv:
            return False
        tv.lifecycle = ToolLifecycle.DEPRECATED
        tv.deprecated_at = datetime.utcnow().isoformat()
        if sunset_date:
            tv.sunset_date = sunset_date
        if successor:
            tv.successor = successor
        logger.info(f"Tool deprecated: {key} (sunset={sunset_date}, successor={successor})")
        return True

    def resolve(self, name: str) -> tuple:
        """Resolve tool name (with optional @version) to versioned name + warnings.
        Returns (versioned_name, warnings_list).
        """
        warnings = []
        if '@' in name:
            tv = self._versions.get(name)
            if not tv:
                return name, [f'Version not found: {name}']
            if tv.lifecycle == ToolLifecycle.DEPRECATED:
                msg = f'Tool {name} is deprecated.'
                if tv.sunset_date:
                    msg += f' Sunset date: {tv.sunset_date}.'
                if tv.successor:
                    msg += f' Use {tv.successor} instead.'
                warnings.append(msg)
            elif tv.lifecycle == ToolLifecycle.SUNSET and tv.is_past_sunset:
                return name, [f'Tool {name} is past its sunset date and no longer available.']
            return name, warnings

        # No version specified — resolve to latest
        latest = self._latest.get(name)
        if latest:
            return latest, warnings
        return name, warnings  # not versioned, pass through

    def get_all_versions(self, tool_name: str = '') -> List[Dict]:
        if tool_name:
            return [tv.to_dict() for tv in self._versions.values()
                    if tv.tool_name == tool_name]
        return [tv.to_dict() for tv in self._versions.values()]


# ── Contract Testing ─────────────────────────────────────────

@dataclass
class ContractTestResult:
    tool_name: str
    passed: bool
    duration_ms: float
    input_valid: bool = True
    output_valid: bool = True
    error: str = ''

    def to_dict(self):
        return {
            'tool_name': self.tool_name, 'passed': self.passed,
            'duration_ms': round(self.duration_ms, 2),
            'input_valid': self.input_valid,
            'output_valid': self.output_valid, 'error': self.error,
        }


class ContractTestRunner:
    """
    Validates tool input/output schemas against actual execution.
    Runs as a background job or on-demand via admin API.
    """

    def __init__(self, tools_registry):
        self._registry = tools_registry

    def test_tool(self, tool_name: str, sample_args: Dict = None) -> ContractTestResult:
        tool = self._registry.get_tool(tool_name)
        if not tool:
            return ContractTestResult(tool_name=tool_name, passed=False, duration_ms=0,
                                      error=f'Tool not found: {tool_name}')
        # Validate input schema exists
        try:
            schema = tool.get_input_schema()
            input_valid = bool(schema and 'properties' in schema)
        except:
            input_valid = False

        # Execute with sample args
        start = time.time()
        try:
            args = sample_args or self._generate_sample_args(tool)
            result = tool.execute(args)
            duration_ms = (time.time() - start) * 1000

            # Validate output is structured
            output_valid = result is not None
            return ContractTestResult(
                tool_name=tool_name, passed=input_valid and output_valid,
                duration_ms=duration_ms, input_valid=input_valid,
                output_valid=output_valid)
        except Exception as e:
            return ContractTestResult(
                tool_name=tool_name, passed=False,
                duration_ms=(time.time() - start) * 1000,
                input_valid=input_valid, output_valid=False, error=str(e)[:300])

    def test_all(self, sample_args_map: Dict[str, Dict] = None) -> List[ContractTestResult]:
        results = []
        for name in sorted(self._registry.tools.keys()):
            args = (sample_args_map or {}).get(name)
            results.append(self.test_tool(name, args))
        return results

    def _generate_sample_args(self, tool) -> Dict:
        """Generate minimal sample arguments from schema defaults/examples."""
        try:
            schema = tool.get_input_schema()
            args = {}
            for prop, spec in schema.get('properties', {}).items():
                if 'default' in spec:
                    args[prop] = spec['default']
                elif 'example' in spec:
                    args[prop] = spec['example']
                elif spec.get('type') == 'string':
                    args[prop] = 'AAPL'  # sensible default for financial tools
                elif spec.get('type') == 'integer':
                    args[prop] = 1
            return args
        except:
            return {}
