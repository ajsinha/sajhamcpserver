"""
SAJHA MCP Server — the policy rule language: parse, validate, match.

A policy is one YAML or JSON document::

    name: finance-guardrails      # default: the file name
    description: ...
    enabled: true                 # false: listed and testable, not enforced
    rules:
      - id: approve-large-payments
        match: {tools: ["payments_*"], arguments: {amount: {gt: 10000}}}
        effect: require_approval  # allow | deny | require_approval (optional)
        reason: ...
        approval: {approver: admin, ttl: 1h}
        constraints: {currency: {enum: [USD, EUR]}}
        rate_limit: {limit: 10, window: 1m, per: [user]}
        quota: {limit: 200, period: day, per: [user]}
        redact: {emails: true, cards: true, mode: mask}
        screen_output: strip      # flag | strip | block

Parsing is strict: an unknown key, effect, condition, source or day, or a regex that does
not compile, is a :class:`PolicyParseError` naming where, so a typo never silently widens
access. The language is documented in docs/architecture/Policy and Audit.md, section 3.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from datetime import datetime, time as dtime
from typing import Any, Dict, List, Optional, Tuple

from sajha.policy.context import SOURCES

EFFECTS = ('allow', 'deny', 'require_approval')
APPROVERS = ('admin', 'caller')
SCREEN_MODES = ('flag', 'strip', 'block')
SCREEN_RANK = {'flag': 1, 'strip': 2, 'block': 3}
REDACT_MODES = ('redact', 'mask')
NATIONAL_IDS = ('us_ssn', 'uk_nino', 'in_aadhaar', 'in_pan', 'ca_sin')
PER_DIMENSIONS = ('tool', 'user', 'api_key', 'caller', 'global')
PERIODS = {'hour': 3600, 'day': 86400, 'week': 7 * 86400, 'month': 31 * 86400}
DAYS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
CONDITION_KEYS = ('required', 'eq', 'ne', 'enum', 'in', 'not_in', 'min', 'max', 'gt', 'lt',
                  'min_length', 'max_length', 'pattern', 'not_pattern', 'type')
JSON_TYPES = ('string', 'number', 'integer', 'boolean', 'array', 'object', 'null')

POLICY_KEYS = {'name', 'description', 'enabled', 'rules', 'version'}
RULE_KEYS = {'id', 'description', 'match', 'effect', 'reason', 'approval', 'constraints', 'rate_limit',
             'quota', 'redact', 'screen_output', 'enabled'}
MATCH_KEYS = {'tools', 'exclude_tools', 'groups', 'annotations', 'callers', 'sources', 'time', 'arguments',
              'data_classes', 'flow', 'destination'}
FLOWS = ('arguments', 'results')
#: facts of a destination (SAJHA Net residency): net, instance, region, labels.<key>, here
DESTINATION_FACTS = ('net', 'instance', 'region', 'labels', 'here')
CALLER_KEYS = {'anonymous', 'users', 'roles', 'api_keys', 'auth_types'}


class PolicyParseError(ValueError):
    """A policy document that does not follow the rule language."""


def parse_duration(v: Any, where: str) -> float:
    if isinstance(v, bool):
        raise PolicyParseError(f'{where}: {v!r} is not a duration')
    if isinstance(v, (int, float)):
        if v <= 0:
            raise PolicyParseError(f'{where}: a duration must be positive')
        return float(v)
    m = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*([smhd]?)\s*', str(v or ''))
    if not m or float(m.group(1)) <= 0:
        raise PolicyParseError(f'{where}: {v!r} is not a duration (use 30s, 5m, 1h, 1d)')
    return float(m.group(1)) * {'': 1, 's': 1, 'm': 60, 'h': 3600, 'd': 86400}[m.group(2)]


def _str_list(v: Any, where: str) -> List[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    if isinstance(v, list) and all(isinstance(x, (str, int, float)) and not isinstance(x, bool) for x in v):
        return [str(x) for x in v]
    raise PolicyParseError(f'{where}: expected a string or a list of strings')


def _unknown(d: Dict, allowed, where: str) -> None:
    extra = sorted(set(d) - set(allowed))
    if extra:
        raise PolicyParseError(f'{where}: unknown key{"s" if len(extra) > 1 else ""} {", ".join(extra)} '
                               f'(allowed: {", ".join(sorted(allowed))})')


# ── conditions ──────────────────────────────────────────────────────

_MISSING = object()


def get_path(args: Any, path: str) -> Any:
    cur = args
    for part in path.split('.'):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return _MISSING
    return cur


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip())
        except ValueError:
            return None
    return None


def _json_type(v: Any) -> str:
    if v is None:
        return 'null'
    if isinstance(v, bool):
        return 'boolean'
    if isinstance(v, int):
        return 'integer'
    if isinstance(v, float):
        return 'number'
    if isinstance(v, str):
        return 'string'
    if isinstance(v, list):
        return 'array'
    if isinstance(v, dict):
        return 'object'
    return type(v).__name__


@dataclass
class Condition:
    """Conditions on one argument (docs: section 3.3)."""
    path: str
    spec: Dict[str, Any]
    regex: Dict[str, 're.Pattern'] = field(default_factory=dict)

    @classmethod
    def parse(cls, path: str, raw: Any, where: str) -> 'Condition':
        if not isinstance(path, str) or not path:
            raise PolicyParseError(f'{where}: argument names must be non-empty strings')
        if not isinstance(raw, dict):
            # shorthand: {currency: USD} means eq, {currency: [USD, EUR]} means enum
            raw = {'enum': raw} if isinstance(raw, list) else {'eq': raw}
        _unknown(raw, CONDITION_KEYS, f'{where}.{path}')
        spec = dict(raw)
        if 'in' in spec:
            spec['enum'] = spec.pop('in')
        rx = {}
        for k in ('pattern', 'not_pattern'):
            if k in spec:
                try:
                    rx[k] = re.compile(str(spec[k]))
                except re.error as e:
                    raise PolicyParseError(f'{where}.{path}.{k}: invalid regex ({e})')
        for k in ('min', 'max', 'gt', 'lt', 'min_length', 'max_length'):
            if k in spec and _num(spec[k]) is None:
                raise PolicyParseError(f'{where}.{path}.{k}: must be a number')
        for k in ('enum', 'not_in'):
            if k in spec and not isinstance(spec[k], list):
                raise PolicyParseError(f'{where}.{path}.{k}: must be a list')
        if 'type' in spec:
            types = _str_list(spec['type'], f'{where}.{path}.type')
            bad = [t for t in types if t not in JSON_TYPES]
            if bad:
                raise PolicyParseError(f'{where}.{path}.type: unknown type {", ".join(bad)}')
            spec['type'] = types
        return cls(path, spec, rx)

    def failure(self, args: Dict[str, Any], absent_ok: bool) -> Optional[str]:
        """None when the argument satisfies every condition, else why not."""
        v = get_path(args, self.path)
        s = self.spec
        if v is _MISSING:
            if s.get('required'):
                return f"'{self.path}' is required"
            if absent_ok:
                return None
            # in a match: an absent argument satisfies only negative conditions
            if set(s) - {'ne', 'not_in', 'required'}:
                return f"'{self.path}' is absent"
            return None
        if 'eq' in s and v != s['eq']:
            return f"'{self.path}' must equal {s['eq']!r}"
        if 'ne' in s and v == s['ne']:
            return f"'{self.path}' must not equal {s['ne']!r}"
        if 'enum' in s and v not in s['enum']:
            return f"'{self.path}' must be one of {', '.join(map(str, s['enum']))}"
        if 'not_in' in s and v in s['not_in']:
            return f"'{self.path}' must not be {v!r}"
        if 'type' in s:
            t = _json_type(v)
            ok = t in s['type'] or (t == 'integer' and 'number' in s['type'])
            if not ok:
                return f"'{self.path}' must be of type {' or '.join(s['type'])}"
        for k, op, word in (('min', lambda a, b: a >= b, 'at least'), ('max', lambda a, b: a <= b, 'at most'),
                            ('gt', lambda a, b: a > b, 'more than'), ('lt', lambda a, b: a < b, 'less than')):
            if k in s:
                n = _num(v)
                if n is None or not op(n, _num(s[k])):
                    return f"'{self.path}' must be {word} {s[k]}"
        if 'min_length' in s or 'max_length' in s:
            if not isinstance(v, (str, list, dict)):
                return f"'{self.path}' has no length"
            if 'min_length' in s and len(v) < _num(s['min_length']):
                return f"'{self.path}' must have at least {s['min_length']} characters/items"
            if 'max_length' in s and len(v) > _num(s['max_length']):
                return f"'{self.path}' must have at most {s['max_length']} characters/items"
        if 'pattern' in self.regex:
            if not isinstance(v, str) or not self.regex['pattern'].search(v):
                return f"'{self.path}' does not match the required pattern"
        if 'not_pattern' in self.regex:
            if isinstance(v, str) and self.regex['not_pattern'].search(v):
                return f"'{self.path}' matches a forbidden pattern"
        return None


def parse_conditions(raw: Any, where: str) -> List[Condition]:
    if raw is None:
        return []
    if not isinstance(raw, dict):
        raise PolicyParseError(f'{where}: expected a mapping of argument name to conditions')
    return [Condition.parse(k, v, where) for k, v in raw.items()]


# ── match ───────────────────────────────────────────────────────────

@dataclass
class TimeWindow:
    days: Tuple[int, ...] = ()
    start: Optional[dtime] = None
    end: Optional[dtime] = None
    tz: str = 'UTC'

    @classmethod
    def parse(cls, raw: Any, where: str) -> 'TimeWindow':
        if not isinstance(raw, dict):
            raise PolicyParseError(f'{where}: expected {{days, hours, timezone}}')
        _unknown(raw, {'days', 'hours', 'timezone'}, where)
        days: List[int] = []
        for d in _str_list(raw.get('days'), f'{where}.days'):
            ends = [x.strip().lower()[:3] for x in d.split('-', 1)]      # "mon" or a range "mon-fri"
            if any(e not in DAYS for e in ends):
                raise PolicyParseError(f'{where}.days: unknown day {d!r} (mon..sun, or a range mon-fri)')
            i, j = DAYS.index(ends[0]), DAYS.index(ends[-1])
            days.extend(range(i, j + 1) if i <= j else list(range(i, 7)) + list(range(0, j + 1)))
        start = end = None
        if raw.get('hours') is not None:
            m = re.fullmatch(r'\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*', str(raw['hours']))
            if not m:
                raise PolicyParseError(f'{where}.hours: use "HH:MM-HH:MM"')
            h1, m1, h2, m2 = map(int, m.groups())
            if h1 > 23 or h2 > 24 or m1 > 59 or m2 > 59:
                raise PolicyParseError(f'{where}.hours: not a time of day')
            start, end = dtime(h1, m1), (dtime(23, 59, 59, 999999) if h2 == 24 else dtime(h2, m2))
        tz = str(raw.get('timezone') or 'UTC')
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(tz)
        except Exception:
            raise PolicyParseError(f'{where}.timezone: unknown time zone {tz!r}')
        return cls(tuple(sorted(set(days))), start, end, tz)

    def holds(self, now: datetime) -> bool:
        from zoneinfo import ZoneInfo
        local = now.astimezone(ZoneInfo(self.tz))
        if self.days and local.weekday() not in self.days:
            return False
        if self.start is not None:
            t = local.time()
            if self.start <= self.end:
                return self.start <= t < self.end
            return t >= self.start or t < self.end          # wraps midnight
        return True


@dataclass
class Match:
    tools: List[str] = field(default_factory=list)
    exclude_tools: List[str] = field(default_factory=list)
    groups: List[str] = field(default_factory=list)
    annotations: Dict[str, Any] = field(default_factory=dict)
    anonymous: Optional[bool] = None
    users: List[str] = field(default_factory=list)
    roles: List[str] = field(default_factory=list)
    api_keys: List[str] = field(default_factory=list)
    auth_types: List[str] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)
    time: Optional[TimeWindow] = None
    arguments: List[Condition] = field(default_factory=list)
    data_classes: List[str] = field(default_factory=list)
    flow: List[str] = field(default_factory=list)
    destination: List[Condition] = field(default_factory=list)
    differs_from_here: List[str] = field(default_factory=list)

    @property
    def residency(self) -> bool:
        """A residency rule: it names data classes, a flow or a destination (SAJHA Net, design §12)."""
        return bool(self.data_classes or self.flow or self.destination or self.differs_from_here)

    @classmethod
    def parse(cls, raw: Any, where: str) -> 'Match':
        if raw is None:
            return cls()
        if not isinstance(raw, dict):
            raise PolicyParseError(f'{where}: expected a mapping')
        _unknown(raw, MATCH_KEYS, where)
        m = cls(tools=_str_list(raw.get('tools'), f'{where}.tools'),
                exclude_tools=_str_list(raw.get('exclude_tools'), f'{where}.exclude_tools'),
                groups=_str_list(raw.get('groups'), f'{where}.groups'))
        ann = raw.get('annotations')
        if ann is not None:
            if not isinstance(ann, dict):
                raise PolicyParseError(f'{where}.annotations: expected a mapping')
            m.annotations = dict(ann)
        callers = raw.get('callers')
        if callers is not None:
            if not isinstance(callers, dict):
                raise PolicyParseError(f'{where}.callers: expected a mapping')
            _unknown(callers, CALLER_KEYS, f'{where}.callers')
            if 'anonymous' in callers:
                if not isinstance(callers['anonymous'], bool):
                    raise PolicyParseError(f'{where}.callers.anonymous: true or false')
                m.anonymous = callers['anonymous']
            m.users = _str_list(callers.get('users'), f'{where}.callers.users')
            m.roles = _str_list(callers.get('roles'), f'{where}.callers.roles')
            m.api_keys = _str_list(callers.get('api_keys'), f'{where}.callers.api_keys')
            m.auth_types = [a.lower() for a in _str_list(callers.get('auth_types'), f'{where}.callers.auth_types')]
        m.sources = [s.lower() for s in _str_list(raw.get('sources'), f'{where}.sources')]
        bad = [s for s in m.sources if s not in SOURCES]
        if bad:
            raise PolicyParseError(f'{where}.sources: unknown source {", ".join(bad)} (one of {", ".join(SOURCES)})')
        if raw.get('time') is not None:
            m.time = TimeWindow.parse(raw['time'], f'{where}.time')
        m.arguments = parse_conditions(raw.get('arguments'), f'{where}.arguments')
        m.data_classes = _str_list(raw.get('data_classes'), f'{where}.data_classes')
        m.flow = [f.lower() for f in _str_list(raw.get('flow'), f'{where}.flow')]
        bad = [f for f in m.flow if f not in FLOWS]
        if bad:
            raise PolicyParseError(f'{where}.flow: unknown flow {", ".join(bad)} (one of {", ".join(FLOWS)})')
        dest = raw.get('destination')
        if dest is not None:
            if not isinstance(dest, dict):
                raise PolicyParseError(f'{where}.destination: expected a mapping of conditions')
            dest = dict(dest)
            m.differs_from_here = _str_list(dest.pop('differs_from_here', None), f'{where}.destination.differs_from_here')
            for path in list(dest) + m.differs_from_here:
                if str(path).split('.')[0] not in DESTINATION_FACTS or (path.startswith('labels') and path.count('.') != 1):
                    raise PolicyParseError(f'{where}.destination: unknown fact {path!r} (net, instance, region, '
                                           f'labels.<key>, here, differs_from_here)')
            m.destination = parse_conditions(dest, f'{where}.destination')
        return m

    def matches(self, call) -> bool:
        name = call.tool
        if self.tools and not any(fnmatch.fnmatchcase(name, p) for p in self.tools):
            return False
        if self.exclude_tools and any(fnmatch.fnmatchcase(name, p) for p in self.exclude_tools):
            return False
        if self.groups and call.group not in self.groups:
            return False
        for k, v in self.annotations.items():
            if (call.annotations or {}).get(k) != v:
                return False
        c = call.caller
        anonymous = not c.user_id or c.user_id == 'anonymous'
        if self.anonymous is not None and anonymous != self.anonymous:
            return False
        if self.users and not any(fnmatch.fnmatchcase(c.user_id or '', p) for p in self.users):
            return False
        if self.roles and not set(self.roles) & set(c.roles or ()):
            return False
        if self.api_keys and not (c.api_key and any(fnmatch.fnmatchcase(c.api_key, p) for p in self.api_keys)):
            return False
        if self.auth_types and (c.auth_type or '').lower() not in self.auth_types:
            return False
        if self.sources and call.source not in self.sources:
            return False
        if self.time is not None and not self.time.holds(call.now):
            return False
        for cond in self.arguments:
            if cond.failure(call.arguments, absent_ok=False) is not None:
                return False
        if self.data_classes:
            have = getattr(call, 'data_classes', None) or ()
            if not any(fnmatch.fnmatchcase(c, p) for c in have for p in self.data_classes):
                return False
        if self.flow and getattr(call, 'flow', None) not in self.flow:
            return False
        if self.destination or self.differs_from_here:
            dest = getattr(call, 'destination', None)
            if not isinstance(dest, dict):
                return False                                  # not a call that sends data elsewhere
            for cond in self.destination:
                if cond.failure(dest, absent_ok=False) is not None:
                    return False
            if self.differs_from_here:
                here = getattr(call, 'here', None) or {}
                if not any(get_path(dest, p) != get_path(here, p) for p in self.differs_from_here):
                    return False
        return True


# ── obligations ─────────────────────────────────────────────────────

@dataclass
class Limit:
    limit: int
    seconds: float
    per: Tuple[str, ...]
    period: str = ''            # quota: hour | day | week | month; '' for a sliding window

    @classmethod
    def parse(cls, raw: Any, where: str, quota: bool) -> 'Limit':
        if not isinstance(raw, dict):
            raise PolicyParseError(f'{where}: expected a mapping')
        _unknown(raw, {'limit', 'period', 'per'} if quota else {'limit', 'window', 'per'}, where)
        lim = raw.get('limit')
        if isinstance(lim, bool) or not isinstance(lim, int) or lim < 0:
            raise PolicyParseError(f'{where}.limit: a whole number of calls (0 or more)')
        per = tuple(p.lower() for p in (_str_list(raw.get('per'), f'{where}.per') or ['tool', 'caller']))
        bad = [p for p in per if p not in PER_DIMENSIONS]
        if bad:
            raise PolicyParseError(f'{where}.per: unknown dimension {", ".join(bad)} '
                                   f'(one of {", ".join(PER_DIMENSIONS)})')
        if quota:
            period = str(raw.get('period') or 'day').lower()
            if period not in PERIODS:
                raise PolicyParseError(f'{where}.period: one of {", ".join(PERIODS)}')
            return cls(lim, PERIODS[period], per, period)
        return cls(lim, parse_duration(raw.get('window', '1m'), f'{where}.window'), per)


@dataclass
class CustomPattern:
    name: str
    regex: 're.Pattern'
    replacement: Optional[str] = None


@dataclass
class RedactSpec:
    kinds: Tuple[str, ...] = ()                 # emails, phones, cards, and national id kinds
    custom: Tuple[CustomPattern, ...] = ()
    mode: str = 'redact'
    data_classes: Tuple[str, ...] = ()          # fields marked with these classes (x-sajha-data-class)

    @classmethod
    def parse(cls, raw: Any, where: str) -> 'RedactSpec':
        if raw is True:
            raw = {'emails': True, 'phones': True, 'cards': True, 'national_ids': True}
        if not isinstance(raw, dict):
            raise PolicyParseError(f'{where}: expected a mapping or true')
        _unknown(raw, {'emails', 'phones', 'cards', 'national_ids', 'custom', 'mode', 'data_classes'}, where)
        kinds = [k for k in ('emails', 'phones', 'cards') if raw.get(k)]
        ids = raw.get('national_ids')
        if ids is True:
            kinds.extend(NATIONAL_IDS)
        elif ids:
            got = [i.lower() for i in _str_list(ids, f'{where}.national_ids')]
            bad = [i for i in got if i not in NATIONAL_IDS]
            if bad:
                raise PolicyParseError(f'{where}.national_ids: unknown {", ".join(bad)} '
                                       f'(one of {", ".join(NATIONAL_IDS)})')
            kinds.extend(got)
        custom = []
        for i, c in enumerate(raw.get('custom') or []):
            w = f'{where}.custom[{i}]'
            if not isinstance(c, dict) or not c.get('pattern'):
                raise PolicyParseError(f'{w}: expected {{name, pattern, replacement?}}')
            _unknown(c, {'name', 'pattern', 'replacement'}, w)
            try:
                rx = re.compile(str(c['pattern']))
            except re.error as e:
                raise PolicyParseError(f'{w}.pattern: invalid regex ({e})')
            custom.append(CustomPattern(str(c.get('name') or f'custom{i}'), rx,
                                        None if c.get('replacement') is None else str(c['replacement'])))
        mode = str(raw.get('mode') or 'redact').lower()
        if mode not in REDACT_MODES:
            raise PolicyParseError(f'{where}.mode: one of {", ".join(REDACT_MODES)}')
        return cls(tuple(kinds), tuple(custom), mode, tuple(_str_list(raw.get('data_classes'), f'{where}.data_classes')))

    def merge(self, other: 'RedactSpec') -> 'RedactSpec':
        kinds = tuple(dict.fromkeys(self.kinds + other.kinds))
        mode = 'redact' if 'redact' in (self.mode, other.mode) else 'mask'
        return RedactSpec(kinds, self.custom + other.custom, mode,
                          tuple(dict.fromkeys(self.data_classes + other.data_classes)))

    def empty(self) -> bool:
        return not self.kinds and not self.custom and not self.data_classes


@dataclass
class Rule:
    id: str
    policy: str
    description: str = ''
    match: Match = field(default_factory=Match)
    effect: Optional[str] = None
    reason: str = ''
    approver: str = 'admin'
    approval_ttl: Optional[float] = None
    constraints: List[Condition] = field(default_factory=list)
    rate_limit: Optional[Limit] = None
    quota: Optional[Limit] = None
    redact: Optional[RedactSpec] = None
    screen_output: Optional[str] = None
    enabled: bool = True
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f'{self.policy}/{self.id}'

    @classmethod
    def parse(cls, raw: Any, policy: str, index: int) -> 'Rule':
        where = f'{policy}: rules[{index}]'
        if not isinstance(raw, dict):
            raise PolicyParseError(f'{where}: expected a mapping')
        rid = str(raw.get('id') or f'rule{index + 1}')
        where = f'{policy}: rule {rid}'
        _unknown(raw, RULE_KEYS, where)
        r = cls(id=rid, policy=policy, description=str(raw.get('description') or ''), raw=raw)
        r.enabled = raw.get('enabled', True) is not False
        r.match = Match.parse(raw.get('match'), f'{where}.match')
        if raw.get('effect') is not None:
            eff = str(raw['effect']).lower()
            if eff not in EFFECTS:
                raise PolicyParseError(f'{where}.effect: one of {", ".join(EFFECTS)}')
            r.effect = eff
        r.reason = str(raw.get('reason') or '')
        appr = raw.get('approval')
        if appr is not None:
            if not isinstance(appr, dict):
                raise PolicyParseError(f'{where}.approval: expected {{approver, ttl}}')
            _unknown(appr, {'approver', 'ttl'}, f'{where}.approval')
            r.approver = str(appr.get('approver') or 'admin').lower()
            if r.approver not in APPROVERS:
                raise PolicyParseError(f'{where}.approval.approver: one of {", ".join(APPROVERS)}')
            if appr.get('ttl') is not None:
                r.approval_ttl = parse_duration(appr['ttl'], f'{where}.approval.ttl')
        r.constraints = parse_conditions(raw.get('constraints'), f'{where}.constraints')
        if raw.get('rate_limit') is not None:
            r.rate_limit = Limit.parse(raw['rate_limit'], f'{where}.rate_limit', quota=False)
        if raw.get('quota') is not None:
            r.quota = Limit.parse(raw['quota'], f'{where}.quota', quota=True)
        if raw.get('redact') not in (None, False):
            r.redact = RedactSpec.parse(raw['redact'], f'{where}.redact')
        so = raw.get('screen_output')
        if so not in (None, False):
            if isinstance(so, dict):
                _unknown(so, {'mode'}, f'{where}.screen_output')
                so = so.get('mode')
            so = 'flag' if so is True else str(so or '').lower()
            if so not in SCREEN_MODES:
                raise PolicyParseError(f'{where}.screen_output: one of {", ".join(SCREEN_MODES)}')
            r.screen_output = so
        return r

    def summary(self) -> Dict[str, Any]:
        ob = []
        if self.constraints:
            ob.append('constraints')
        if self.rate_limit:
            ob.append(f'rate limit {self.rate_limit.limit}/{int(self.rate_limit.seconds)}s')
        if self.quota:
            ob.append(f'quota {self.quota.limit}/{self.quota.period}')
        if self.redact:
            ob.append('redact ' + ','.join(list(self.redact.kinds) + [c.name for c in self.redact.custom]
                                           + [f'class:{c}' for c in self.redact.data_classes]))
        if self.screen_output:
            ob.append(f'screen {self.screen_output}')
        return {'id': self.id, 'key': self.key, 'description': self.description, 'effect': self.effect,
                'reason': self.reason, 'approver': self.approver if self.effect == 'require_approval' else None,
                'obligations': ob, 'enabled': self.enabled, 'match': self.raw.get('match') or {}}


@dataclass
class Policy:
    name: str
    source: str = ''
    description: str = ''
    enabled: bool = True
    rules: List[Rule] = field(default_factory=list)
    error: str = ''

    @classmethod
    def parse(cls, raw: Any, name: str, source: str = '') -> 'Policy':
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise PolicyParseError(f'{name}: a policy is a mapping with a rules list')
        name = str(raw.get('name') or name)
        _unknown(raw, POLICY_KEYS, name)
        enabled = raw.get('enabled', True)
        if not isinstance(enabled, bool):
            raise PolicyParseError(f'{name}.enabled: true or false')
        rules_raw = raw.get('rules') or []
        if not isinstance(rules_raw, list):
            raise PolicyParseError(f'{name}.rules: expected a list')
        rules = [Rule.parse(r, name, i) for i, r in enumerate(rules_raw)]
        ids = [r.id for r in rules]
        dup = sorted({i for i in ids if ids.count(i) > 1})
        if dup:
            raise PolicyParseError(f'{name}: duplicate rule id {", ".join(dup)}')
        return cls(name, source, str(raw.get('description') or ''), enabled, rules)

    def summary(self) -> Dict[str, Any]:
        return {'name': self.name, 'source': self.source, 'description': self.description,
                'enabled': self.enabled, 'error': self.error, 'rules': [r.summary() for r in self.rules]}


def parse_text(text: str, name: str, source: str = '') -> Policy:
    """A policy from YAML or JSON text (JSON is YAML)."""
    import yaml
    try:
        raw = yaml.safe_load(text) if text.strip() else {}
    except yaml.YAMLError as e:
        raise PolicyParseError(f'{name}: not valid YAML/JSON ({str(e).splitlines()[0]})')
    return Policy.parse(raw, name, source)
