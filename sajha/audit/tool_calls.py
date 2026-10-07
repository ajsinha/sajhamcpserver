"""
SAJHA MCP Server — every tool call as a ``tool.call`` record in the tamper-evident audit chain.

``BaseMCPTool.execute_with_tracking`` (the choke point every path goes through) calls
:func:`record_call` once per call, after the outcome is known. The record names who called
(user, API key, roles, auth type), the tool, the outcome, the duration, the trace id, the
source surface (and MCP era), and the arguments as a SHA-256 of their canonical JSON (not
the values), unless ``audit.tool_calls.arguments`` asks for redacted values or nothing.

Volume control (``audit.tool_calls.*``): failures, policy outcomes and calls to destructive
tools are always recorded; successful calls can be filtered by tool glob and sampled per
tool. The record is hashed into the chain on the calling thread and stored by the chain's
background flusher, so a call never waits for the database. Design:
docs/architecture/Policy and Audit.md, section 13.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import fnmatch
import hashlib
import logging
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

EVENT = 'tool.call'
#: outcomes that are always recorded (never sampled or filtered away)
ALWAYS = frozenset({'error', 'circuit_open', 'policy_denied', 'approval_required', 'rate_limited'})
ARGUMENT_MODES = ('hash', 'redacted', 'none')
_SECRET_KEY = re.compile(r'(pass(word|wd)?|secret|token|api[_-]?key|auth|credential|private[_-]?key|cookie)', re.I)

_SKIPPED = None


def _skipped_counter():
    global _SKIPPED
    if _SKIPPED is None:
        from sajha.observability import metrics as m
        _SKIPPED = m.REGISTRY._families.get('sajha_audit_tool_calls_skipped_total') or m.Counter(
            m.REGISTRY, 'sajha_audit_tool_calls_skipped_total',
            'Tool calls not written to the audit chain, by reason (excluded, sampled).', ('reason',))
    return _SKIPPED


@dataclass
class Settings:
    enabled: bool = True
    success_sample_rate: float = 1.0
    sample_rates: List[Tuple[str, float]] = field(default_factory=list)   # (glob, rate), first match wins
    include_tools: List[str] = field(default_factory=list)
    exclude_tools: List[str] = field(default_factory=list)
    arguments: str = 'hash'
    max_argument_bytes: int = 4096
    loaded_at: float = 0.0

    def rate_for(self, tool: str) -> float:
        for glob, rate in self.sample_rates:
            if fnmatch.fnmatchcase(tool, glob):
                return rate
        return self.success_sample_rate


def _rate(v: Any, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return default


def load_settings() -> Settings:
    from sajha.core.config import _bool, _get, _int, _list
    rates = []
    for item in _list('audit.tool_calls.sample_rates', []):
        glob, sep, val = item.rpartition('=')
        if sep and glob.strip():
            rates.append((glob.strip(), _rate(val, 1.0)))
    mode = (_get('audit.tool_calls.arguments', 'hash') or 'hash').strip().lower()
    return Settings(enabled=_bool('audit.tool_calls.enabled', True),
                    success_sample_rate=_rate(_get('audit.tool_calls.success_sample_rate', '1.0'), 1.0),
                    sample_rates=rates,
                    include_tools=_list('audit.tool_calls.include_tools', []),
                    exclude_tools=_list('audit.tool_calls.exclude_tools', []),
                    arguments=mode if mode in ARGUMENT_MODES else 'hash',
                    max_argument_bytes=max(256, _int('audit.tool_calls.max_argument_bytes', 4096)),
                    loaded_at=time.time())


_settings: Optional[Settings] = None
_RELOAD_SECONDS = 5.0


def settings() -> Settings:
    global _settings
    s = _settings
    if s is None or time.time() - s.loaded_at > _RELOAD_SECONDS:
        try:
            s = _settings = load_settings()
        except Exception as e:
            logger.debug(f'audit.tool_calls settings: {e}')
            s = _settings = s or Settings(loaded_at=time.time())
    return s


def set_settings(s: Optional[Settings]) -> None:
    """Install settings (tests); None reloads from configuration on next use."""
    global _settings
    if s is not None and not s.loaded_at:
        s.loaded_at = time.time() + 10 ** 9           # never reloaded while installed
    _settings = s


def is_destructive(tool) -> bool:
    cfg = getattr(tool, 'config', None) or {}
    ann = cfg.get('annotations') if isinstance(cfg, dict) else None
    return isinstance(ann, dict) and ann.get('destructiveHint') is True


def decide(s: Settings, tool_name: str, outcome: str, destructive: bool,
           rand=random.random) -> Tuple[bool, Optional[float], str]:
    """(record?, sample rate applied or None, reason when not)."""
    if not s.enabled:
        return False, None, 'disabled'
    if outcome in ALWAYS or destructive:
        return True, None, ''
    if s.include_tools and not any(fnmatch.fnmatchcase(tool_name, g) for g in s.include_tools):
        return False, None, 'excluded'
    if any(fnmatch.fnmatchcase(tool_name, g) for g in s.exclude_tools):
        return False, None, 'excluded'
    rate = s.rate_for(tool_name)
    if rate >= 1.0:
        return True, None, ''
    if rate <= 0.0 or rand() >= rate:
        return False, rate, 'sampled'
    return True, rate, ''


def arguments_digest(arguments: Any) -> str:
    from sajha.audit.chain import canonical
    return hashlib.sha256(canonical(arguments if arguments is not None else {}).encode('utf-8')).hexdigest()


def _mask_secrets(value: Any, depth: int = 0) -> Any:
    if depth > 20:
        return '[...]'
    if isinstance(value, dict):
        return {k: ('[REDACTED:secret]' if isinstance(k, str) and _SECRET_KEY.search(k) else
                    _mask_secrets(v, depth + 1)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_mask_secrets(v, depth + 1) for v in value]
    return value


_ALL_PII = None


def redacted_arguments(arguments: Any, max_bytes: int) -> Any:
    """Arguments with secret-named keys masked and personal data redacted (the policy engine's
    patterns), cut to ``max_bytes`` of canonical JSON (then a string ending in ``...``)."""
    global _ALL_PII
    from sajha.audit.chain import canonical
    from sajha.policy import redact as R
    if _ALL_PII is None:
        from sajha.policy.model import RedactSpec
        _ALL_PII = RedactSpec.parse(True, 'audit.tool_calls')
    value, _ = R.redact(_mask_secrets(arguments), _ALL_PII)
    text = canonical(value)
    if len(text.encode('utf-8')) > max_bytes:
        return text.encode('utf-8')[:max_bytes].decode('utf-8', 'ignore') + '...'
    return value


def record_call(tool, arguments: Any, outcome: str, duration_s: float, error: str = '') -> None:
    """Write the ``tool.call`` record for one finished call (or skip it, per the settings).
    Never raises: auditing must not break the call it records."""
    try:
        s = settings()
        name = getattr(tool, 'name', '') or str(tool)
        destructive = is_destructive(tool)
        ok, rate, reason = decide(s, name, outcome, destructive)
        if not ok:
            if reason in ('excluded', 'sampled'):
                try:
                    _skipped_counter().inc((reason,))
                except Exception:
                    pass
            return
        from sajha import audit
        from sajha.observability import tracing
        from sajha.observability.caller import current
        from sajha.policy import context as pctx
        c = current()
        details: Dict[str, Any] = {'duration_ms': round(duration_s * 1000.0, 3), 'source': pctx.source()}
        era = pctx.era()
        if era:
            details['era'] = era
        tid = tracing.current_trace_id()
        if tid:
            details['trace_id'] = tid
        if s.arguments == 'hash':
            details['arguments_sha256'] = arguments_digest(arguments)
        elif s.arguments == 'redacted':
            details['arguments'] = redacted_arguments(arguments, s.max_argument_bytes)
        if destructive:
            details['destructive'] = True
        if rate is not None:
            details['sample_rate'] = rate
        if error and outcome not in ('ok', 'cache_hit'):
            details['error'] = str(error)[:300]
        audit.record(EVENT, actor={'user': c.user_id or 'anonymous', 'api_key': c.api_key or '',
                                   'roles': list(c.roles or ()), 'auth': c.auth_type or ''},
                     resource={'type': 'tool', 'id': name}, outcome=outcome, details=details, defer=True)
    except Exception as e:
        logger.debug(f'tool-call audit: {e}')
