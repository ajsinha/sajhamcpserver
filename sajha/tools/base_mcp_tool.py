"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Base MCP Tool Class
"""

import json
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from datetime import datetime

class ToolArgumentError(ValueError):
    """Tool arguments that do not satisfy the tool's input schema.

    MCP 2026-07-28 answers it with -32602 (Invalid params); MCP 2025-11-25 with a
    CallToolResult carrying ``isError: true`` (input validation is a tool execution error
    there); the REST API with 400."""

    def __init__(self, tool_name: str, detail: str, count: int = 1):
        more = f" (and {count - 1} more problem{'s' if count > 2 else ''})" if count > 1 else ''
        super().__init__(f"Invalid arguments for tool {tool_name}: {detail}{more}")
        self.tool_name = tool_name
        self.detail = detail


_VALIDATORS: Dict[str, Any] = {}       # json.dumps(schema) -> validator, or None (unusable schema)


def _schema_validator(schema: Dict, tool_name: str, logger):
    """A cached jsonschema validator for ``schema``; None when the schema is not usable."""
    if not isinstance(schema, dict) or not schema:
        return None
    try:
        key = json.dumps(schema, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return None
    if key in _VALIDATORS:
        return _VALIDATORS[key]
    try:
        import jsonschema
        cls = jsonschema.validators.validator_for(schema, default=jsonschema.Draft202012Validator)
        cls.check_schema(schema)
        validator = cls(schema)
    except ImportError:
        validator = None
    except Exception as e:
        logger.warning(f"Tool {tool_name}: inputSchema is not valid JSON Schema "
                       f"({str(e).splitlines()[0]}); only its 'required' list is enforced")
        validator = None
    if len(_VALIDATORS) > 2048:
        _VALIDATORS.clear()
    _VALIDATORS[key] = validator
    return validator


def _error_order(err) -> tuple:
    # missing required arguments first, then the shallowest problem
    return (0 if err.validator == 'required' else 1, len(err.absolute_path), str(err.message))


def _describe_schema_error(err) -> str:
    where = '.'.join(str(p) for p in err.absolute_path)
    if err.validator == 'required':
        # "'symbol' is a required property" -> "Missing required parameter: symbol"
        missing = err.message.split(' is a required property')[0].strip("'")
        prefix = f"'{where}': " if where else ''
        return f"{prefix}Missing required parameter: {missing}"
    if err.validator == 'additionalProperties':
        return err.message + (f" (in '{where}')" if where else '')
    return f"'{where}': {err.message}" if where else err.message


class BaseMCPTool(ABC):
    """
    Abstract base class for all MCP tools
    """
    
    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize the tool
        
        Args:
            config: Tool configuration dictionary
        """
        self.config = config or {}
        self.logger = logging.getLogger(self.__class__.__name__)
        self._name = self.config.get('name', self.__class__.__name__)
        self._description = self.config.get('description', '')
        self._version = self.config.get('version', '1.0.0')
        self._enabled = self.config.get('enabled', True)
        self._input_schema = self.config.get('inputSchema', {})
        self._output_schema = self.config.get('outputSchema', {})
        self._metadata = self.config.get('metadata', {})
        self._execution_count = 0
        self._last_execution = None
        self._total_execution_time = 0.0
    
    @property
    def name(self) -> str:
        """Get tool name"""
        return self._name
    
    @property
    def description(self) -> str:
        """Get tool description"""
        return self._description
    
    @property
    def version(self) -> str:
        """Get tool version"""
        return self._version
    
    @property
    def enabled(self) -> bool:
        """Check if tool is enabled"""
        return self._enabled
    
    @property
    def input_schema(self) -> Dict:
        """Get input schema for the tool (invalid x-mcp-header annotations removed, with a warning)"""
        raw = self._input_schema or self.get_input_schema()
        cached = getattr(self, '_sanitized_input_schema', None)
        if cached is not None and cached[0] is raw:
            return cached[1]
        from sajha.core.mcp_modern import sanitize_x_mcp_headers
        clean = sanitize_x_mcp_headers(raw, self._name)
        self._sanitized_input_schema = (raw, clean)
        return clean

    @property
    def output_schema(self) -> Dict:
        if not self._output_schema:
            return self.get_output_schema()
        return self._output_schema


    def enable(self):
        """Enable the tool"""
        self._enabled = True
        self.logger.info(f"Tool enabled: {self.name}")
    
    def disable(self):
        """Disable the tool"""
        self._enabled = False
        self.logger.info(f"Tool disabled: {self.name}")
    
    @abstractmethod
    def execute(self, arguments: Dict[str, Any]) -> Any:
        """
        Execute the tool with given arguments
        
        Args:
            arguments: Tool arguments
            
        Returns:
            Tool execution result
        """
        pass
    
    @abstractmethod
    def get_input_schema(self) -> Dict:
        """
        Get the JSON schema for tool inputs
        
        Returns:
            JSON schema dictionary
        """
        pass

    @abstractmethod
    def get_output_schema(self) -> Dict:
        """
            Get the JSON schema for tool outputs

            Returns:
                JSON schema dictionary
            """
        pass


    def validate_arguments(self, arguments: Dict[str, Any]) -> bool:
        """
        Validate arguments against the tool's input schema (JSON Schema: required,
        type, enum, pattern, minimum/maximum, additionalProperties, ...).

        Raises :class:`ToolArgumentError` (a ValueError) naming the first offending
        argument. A schema that is itself not valid JSON Schema is reported once in the
        log and only its ``required`` list is enforced, so a broken config never blocks
        every call.
        """
        if not isinstance(arguments, dict):
            raise ToolArgumentError(self.name, "arguments must be an object")
        schema = self.input_schema or {}
        validator = _schema_validator(schema, self.name, self.logger)
        if validator is None:
            for param in schema.get('required', []) or []:
                if param not in arguments:
                    raise ToolArgumentError(self.name, f"Missing required parameter: {param}")
            return True
        errors = sorted(validator.iter_errors(arguments), key=_error_order)
        if errors:
            raise ToolArgumentError(self.name, _describe_schema_error(errors[0]), len(errors))
        return True

    def execute_with_tracking(self, arguments: Dict[str, Any]) -> Any:
        """
        Execute tool with performance tracking: the policy engine (sajha/policy/: rules,
        approvals, limits before the call; redaction and screening of the result), the
        enabled check, argument validation, the tool cache, the circuit breaker, and
        observability (a ``tool`` span, the ``sajha_tool_*`` metrics and a usage-ledger row;
        sajha/observability/). Every path that runs a tool comes through here.

        Args:
            arguments: Tool arguments

        Returns:
            Tool execution result
        """
        import time as _time
        from sajha.core.mcp_mrtr import InputRequired
        from sajha.observability import metrics as _metrics, tracing as _tracing
        from sajha.observability.caller import current as _caller
        from sajha.policy.errors import PolicyError as _PolicyError
        outcome = {'v': 'ok'}
        error = ''
        t0 = _time.perf_counter()
        with _tracing.span(f'tool {self.name}', {'sajha.tool.name': self.name,
                                                 'sajha.tool.group': _metrics.tool_group(self.name),
                                                 'enduser.id': _caller().user_id}) as span:
            try:
                # Connected accounts: a tool whose config declares auth.connected_account runs with
                # the caller's token bound (sajha/accounts/injection.py); a no-op for every other tool
                from sajha.accounts.injection import bind as _bind_account
                # Policy (docs/architecture/Policy and Audit.md): may deny, ask for approval or
                # rate-limit (raises); a None enforcement means nothing to do with the result
                from sajha import policy as _policy
                enforcement = _policy.enforce(self, arguments)
                with _bind_account(self, arguments):
                    result = self._execute_tracked(arguments, outcome)
                return result if enforcement is None else enforcement.apply_output(result)
            except InputRequired:
                outcome['v'] = 'input_required'
                raise
            except _PolicyError as e:
                outcome['v'] = {'approval_required': 'approval_required',
                                'rate_limited': 'rate_limited'}.get(e.kind, 'policy_denied')
                error = str(e)
                _tracing.set_error(span, error)
                raise
            except Exception as e:
                if outcome['v'] == 'ok':
                    outcome['v'] = 'error'
                error = str(e)
                _tracing.set_error(span, error)
                raise
            finally:
                _tracing.set_attrs(span, **{'sajha.tool.outcome': outcome['v']})
                _metrics.record_tool(self.name, outcome['v'], _time.perf_counter() - t0, error)

    def _execute_tracked(self, arguments: Dict[str, Any], outcome: Dict[str, str]) -> Any:
        """The body of :meth:`execute_with_tracking`; sets ``outcome['v']`` for a cache hit
        or an open circuit."""
        if not self.enabled:
            raise RuntimeError(f"Tool is disabled: {self.name}")
        
        # Validate arguments
        self.validate_arguments(arguments)
        
        # ── Cache check (only if tool has cache_ttl in config) ──
        from sajha.core.cache import get_tool_cache, get_tool_ttl
        cache = get_tool_cache()
        tool_ttl = get_tool_ttl(self.name, self.config if hasattr(self, 'config') else None)
        if tool_ttl > 0:
            cached = cache.get(self.name, arguments)
            if cached is not None:
                self.logger.debug(f"Cache hit: {self.name}")
                outcome['v'] = 'cache_hit'
                return cached

        # ── Circuit breaker check ────────────────────────────
        from sajha.core.circuit_breaker import get_circuit_registry
        breaker = get_circuit_registry().get_breaker(self.name)
        if breaker and not breaker.can_execute():
            self.logger.warning(f"Circuit open: {self.name} — returning degraded error")
            outcome['v'] = 'circuit_open'
            raise RuntimeError(f"Service temporarily unavailable for {self.name} (circuit breaker open)")

        # ── Execute ──────────────────────────────────────────
        from sajha.core.mcp_mrtr import InputRequired
        start_time = datetime.now()
        try:
            result = self.execute(arguments)
            execution_time = (datetime.now() - start_time).total_seconds()
            
            # Update metrics
            self._execution_count += 1
            self._last_execution = datetime.now()
            self._total_execution_time += execution_time

            # Record success in circuit breaker
            if breaker:
                breaker.record_success()

            # Cache the result (only if tool has cache_ttl in its config)
            from sajha.core.cache import get_tool_ttl
            tool_ttl = get_tool_ttl(self.name, self.config if hasattr(self, 'config') else None)
            if tool_ttl > 0:
                cache.put(self.name, arguments, result, ttl=tool_ttl)

            # Record for replay
            from sajha.core.tool_health import get_replay_store
            get_replay_store().record(
                self.name, arguments, result,
                duration_ms=execution_time * 1000, success=True)

            self.logger.info(f"Tool executed successfully: {self.name} ({execution_time:.2f}s)")
            return result

        except InputRequired:
            # MRTR: the tool needs client input first; not a failure (no breaker, no replay)
            raise
        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds()

            # Record failure in circuit breaker
            if breaker:
                breaker.record_failure()

            # Record for replay
            try:
                from sajha.core.tool_health import get_replay_store
                get_replay_store().record(
                    self.name, arguments, {'error': str(e)},
                    duration_ms=execution_time * 1000, success=False)
            except Exception:
                pass

            self.logger.error(f"Tool execution failed: {self.name} - {str(e)}", exc_info=True)
            raise
    
    def get_metrics(self) -> Dict:
        """
        Get tool execution metrics
        
        Returns:
            Metrics dictionary
        """
        avg_execution_time = (
            self._total_execution_time / self._execution_count 
            if self._execution_count > 0 else 0
        )
        
        return {
            "name": self.name,
            "version": self.version,
            "enabled": self.enabled,
            "execution_count": self._execution_count,
            "last_execution": self._last_execution.isoformat() + "Z" if self._last_execution else None,
            "total_execution_time": self._total_execution_time,
            "average_execution_time": avg_execution_time
        }
    
    def to_mcp_format(self) -> Dict:
        """
        Convert tool to MCP format for tools/list response
        
        Returns:
            MCP formatted tool dictionary
        """
        tool = {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema
        }
        config = self.config or {}
        title = config.get('title') or (self._metadata or {}).get('title')
        if title:
            tool["title"] = title
        # outputSchema must be a JSON Schema object of type "object" (MCP 2025-11-25)
        try:
            output_schema = self.output_schema
        except Exception:
            output_schema = None
        if isinstance(output_schema, dict) and output_schema.get('type') == 'object':
            tool["outputSchema"] = output_schema
        annotations = config.get('annotations')
        if isinstance(annotations, dict) and annotations:
            tool["annotations"] = annotations
        from sajha.core.mcp_2025_11_25 import build_tool_icons
        icons = build_tool_icons(config)
        if icons:
            tool["icons"] = icons
        return tool
    
    def load_from_config(self, config_path: str):
        """
        Load tool configuration from JSON file
        
        Args:
            config_path: Path to configuration file
        """
        try:
            with open(config_path, 'r') as f:
                self.config = json.load(f)
                self._name = self.config.get('name', self.name)
                self._description = self.config.get('description', self.description)
                self._version = self.config.get('version', self.version)
                self._enabled = self.config.get('enabled', True)
                self._input_schema = self.config.get('inputSchema', {})
                self._metadata = self.config.get('metadata', {})
                self.logger.info(f"Tool configuration loaded: {self.name}")
        except Exception as e:
            self.logger.error(f"Error loading tool configuration: {e}", exc_info=True)
            raise
