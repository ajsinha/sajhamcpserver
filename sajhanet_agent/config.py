"""
The agent's configuration file (``--config``, JSON): the part of an agent's set-up that is a document
rather than a flag. Users and their keys (what makes the agent a home), the identity resolvers it sends
and accepts, import rules, blocks, residency rules and re-export rules. The file is read at start and
again when it changes (checked every protocol period), so a block or a revoked key takes effect without
a restart. The guide is docs/clients/SAJHA Net Agent.md, section 6.

    {
      "identity": ["assertion", "api_key"],
      "users": [{"user_name": "alice", "roles": ["analyst"],
                 "keys": [{"id": "alice-1", "key": "sk-...", "tool_access_mode": "all"}]}],
      "import": [{"tools": ["*"], "instances": ["*"]}],
      "blocks": [{"id": "b1", "level": "outbound", "target_instance": "risk-us", "reason": "..."}],
      "residency": {"default_effect": "allow", "rules": [...], "tools": {...}},
      "reexport": {"enabled": true, "rules": [{"tools": ["ledger"], "to_instances": ["risk-eu"]}]}
    }

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from sajha.net import crypto, names
from sajha.net import residency as R
from sajha.net.blocks import LEVELS

IDENTITIES = ('api_key', 'assertion', 'token_exchange')
EFFECTS = ('allow', 'deny', 'require_approval')
FLOWS = ('arguments', 'results')
FACTS = ('net', 'instance', 'region', 'here')
CONDITION_KEYS = ('eq', 'ne', 'in', 'enum', 'not_in', 'pattern', 'not_pattern')
ACCESS_MODES = ('all', 'allowlist', 'denylist', 'regex')
TOP_KEYS = ('identity', 'users', 'anonymous_calls', 'import', 'blocks', 'residency', 'reexport', 'max_hops',
            'max_call_chain', 'token_ttl_seconds', 'assertion_ttl_seconds', 'bare_aliases')


class ConfigError(ValueError):
    pass


def _list(v: Any, where: str) -> List[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [x.strip() for x in v.split(',') if x.strip()]
    if isinstance(v, list) and all(isinstance(x, (str, int)) for x in v):
        return [str(x) for x in v]
    raise ConfigError(f'{where}: expected a list of strings')


def _unknown(raw: Dict[str, Any], allowed, where: str) -> None:
    bad = sorted(set(raw) - set(allowed))
    if bad:
        raise ConfigError(f'{where}: unknown key {", ".join(bad)} (one of {", ".join(allowed)})')


def match_any(value: str, patterns: List[str]) -> bool:
    return any(fnmatch.fnmatchcase(value or '', str(p)) for p in patterns or [])


# ── users and keys ─────────────────────────────────────────────────

@dataclass
class Key:
    id: str
    key_hash: str
    key_prefix: str = ''
    name: str = ''
    enabled: bool = True
    expires_at: Optional[str] = None
    tool_access_mode: str = 'all'
    tool_access_list: List[str] = field(default_factory=list)


@dataclass
class User:
    user_name: str
    display_name: str = ''
    roles: List[str] = field(default_factory=list)
    enabled: bool = True
    keys: List[Key] = field(default_factory=list)


def _user(raw: Any, i: int) -> User:
    where = f'users[{i}]'
    if not isinstance(raw, dict):
        raise ConfigError(f'{where}: expected an object')
    _unknown(raw, ('user_name', 'display_name', 'roles', 'enabled', 'keys'), where)
    login = str(raw.get('user_name') or '').strip()
    if not login or '@' in login or len(login) > 128:
        raise ConfigError(f'{where}.user_name: a login name without "@", at most 128 characters')
    keys = []
    for j, k in enumerate(raw.get('keys') or []):
        kw = f'{where}.keys[{j}]'
        if not isinstance(k, dict):
            raise ConfigError(f'{kw}: expected an object')
        _unknown(k, ('id', 'key', 'sha256', 'name', 'enabled', 'expires_at', 'tool_access_mode', 'tool_access_list'),
                 kw)
        kid = str(k.get('id') or '').strip()
        if not kid or len(kid) > 64:
            raise ConfigError(f'{kw}.id: a key id of at most 64 characters')
        raw_key = str(k.get('key') or '')
        kh = str(k.get('sha256') or '').strip().lower()
        if bool(raw_key) == bool(kh):
            raise ConfigError(f'{kw}: give exactly one of key (the raw key) and sha256 (its hash)')
        if raw_key:
            kh = hashlib.sha256(raw_key.encode('utf-8')).hexdigest()
        if not re.fullmatch(r'[0-9a-f]{64}', kh):
            raise ConfigError(f'{kw}.sha256: the lowercase hex SHA-256 of the key')
        mode = str(k.get('tool_access_mode') or 'all').lower()
        if mode not in ACCESS_MODES:
            raise ConfigError(f'{kw}.tool_access_mode: one of {", ".join(ACCESS_MODES)}')
        exp = k.get('expires_at')
        if exp is not None:
            try:
                crypto.parse_rfc3339(str(exp))
            except Exception:
                raise ConfigError(f'{kw}.expires_at: an RFC 3339 timestamp')
        keys.append(Key(id=kid, key_hash=kh, key_prefix=raw_key[:8], name=str(k.get('name') or kid)[:255],
                        enabled=bool(k.get('enabled', True)), expires_at=str(exp) if exp else None,
                        tool_access_mode=mode, tool_access_list=_list(k.get('tool_access_list'), f'{kw}.tool_access_list')))
    return User(user_name=login, display_name=str(raw.get('display_name') or login), roles=_list(raw.get('roles'),
                f'{where}.roles'), enabled=bool(raw.get('enabled', True)), keys=keys)


# ── residency rules (the shape of SAJHA's policy residency rules, Policy and Audit §3.5) ──

@dataclass
class Condition:
    path: str
    spec: Dict[str, Any]

    def holds(self, facts: Dict[str, Any]) -> bool:
        v = _get(facts, self.path)
        s = self.spec
        if v is None:                                 # an absent fact satisfies only ne and not_in
            return not (set(s) - {'ne', 'not_in'})
        sv = v if isinstance(v, bool) else str(v)
        if 'eq' in s and sv != (s['eq'] if isinstance(s['eq'], bool) else str(s['eq'])):
            return False
        if 'ne' in s and sv == (s['ne'] if isinstance(s['ne'], bool) else str(s['ne'])):
            return False
        if 'enum' in s and sv not in [str(x) for x in s['enum']]:
            return False
        if 'not_in' in s and sv in [str(x) for x in s['not_in']]:
            return False
        if 'pattern' in s and not re.search(str(s['pattern']), str(sv)):
            return False
        if 'not_pattern' in s and re.search(str(s['not_pattern']), str(sv)):
            return False
        return True


def _get(d: Dict[str, Any], path: str) -> Any:
    if path.startswith('labels.'):
        return (d.get('labels') or {}).get(path[len('labels.'):])
    return d.get(path)


def _condition(path: str, raw: Any, where: str) -> Condition:
    if not (path in FACTS or path.startswith('labels.')):
        raise ConfigError(f'{where}: unknown fact {path!r} (net, instance, region, here, labels.<key>)')
    if not isinstance(raw, dict):
        raw = {'enum': raw} if isinstance(raw, list) else {'eq': raw}
    _unknown(raw, CONDITION_KEYS, f'{where}.{path}')
    spec = dict(raw)
    if 'in' in spec:
        spec['enum'] = spec.pop('in')
    for k in ('enum', 'not_in'):
        if k in spec and not isinstance(spec[k], list):
            raise ConfigError(f'{where}.{path}.{k}: must be a list')
    for k in ('pattern', 'not_pattern'):
        if k in spec:
            try:
                re.compile(str(spec[k]))
            except re.error as e:
                raise ConfigError(f'{where}.{path}.{k}: invalid regex ({e})')
    return Condition(path, spec)


@dataclass
class ResidencyRule:
    id: str
    effect: str = 'allow'
    data_classes: List[str] = field(default_factory=list)
    flow: List[str] = field(default_factory=list)
    destination: List[Condition] = field(default_factory=list)
    differs_from_here: List[str] = field(default_factory=list)
    redact: List[str] = field(default_factory=list)
    reason: str = ''

    def matches(self, classes: List[str], flow: str, dest: Dict[str, Any], here: Dict[str, Any]) -> bool:
        if self.data_classes and not any(fnmatch.fnmatchcase(c, p) for c in classes for p in self.data_classes):
            return False
        if self.flow and flow not in self.flow:
            return False
        if not all(c.holds(dest) for c in self.destination):
            return False
        if self.differs_from_here and not any(_get(dest, p) != _get(here, p) for p in self.differs_from_here):
            return False
        return True


def _residency_rule(raw: Any, i: int) -> ResidencyRule:
    where = f'residency.rules[{i}]'
    if not isinstance(raw, dict):
        raise ConfigError(f'{where}: expected an object')
    _unknown(raw, ('id', 'match', 'effect', 'redact', 'reason'), where)
    m = raw.get('match') or {}
    if not isinstance(m, dict):
        raise ConfigError(f'{where}.match: expected an object')
    _unknown(m, ('data_classes', 'flow', 'destination'), f'{where}.match')
    effect = str(raw.get('effect') or 'allow').lower()
    if effect not in EFFECTS:
        raise ConfigError(f'{where}.effect: one of {", ".join(EFFECTS)}')
    flow = [f.lower() for f in _list(m.get('flow'), f'{where}.match.flow')]
    bad = [f for f in flow if f not in FLOWS]
    if bad:
        raise ConfigError(f'{where}.match.flow: unknown flow {", ".join(bad)} (arguments or results)')
    dest = dict(m.get('destination') or {})
    differs = _list(dest.pop('differs_from_here', None), f'{where}.match.destination.differs_from_here')
    conds = [_condition(k, v, f'{where}.match.destination') for k, v in dest.items()]
    red = raw.get('redact') or {}
    if not isinstance(red, dict):
        raise ConfigError(f'{where}.redact: expected {{data_classes: [...]}}')
    _unknown(red, ('data_classes',), f'{where}.redact')
    rule = ResidencyRule(id=str(raw.get('id') or f'rule-{i + 1}'), effect=effect,
                         data_classes=_list(m.get('data_classes'), f'{where}.match.data_classes'), flow=flow,
                         destination=conds, differs_from_here=differs,
                         redact=_list(red.get('data_classes'), f'{where}.redact.data_classes'),
                         reason=str(raw.get('reason') or ''))
    if not (rule.data_classes or rule.flow or rule.destination or rule.differs_from_here):
        raise ConfigError(f'{where}.match: a residency rule names data_classes, a flow or a destination')
    return rule


@dataclass
class ResidencyDecision:
    effect: str = 'allow'
    rule: str = ''
    reason: str = ''
    redact: List[str] = field(default_factory=list)


@dataclass
class Residency:
    default_effect: str = 'allow'
    rules: List[ResidencyRule] = field(default_factory=list)
    tools: Dict[str, Dict[str, R.Marks]] = field(default_factory=dict)      # pattern -> {arguments|results: marks}

    def decide(self, classes: List[str], flow: str, dest: Dict[str, Any], here: Dict[str, Any]) -> ResidencyDecision:
        """Deny overrides; then require_approval; with ``default_effect: deny`` classified data needs an
        allow rule; the redactions of every matching rule are collected (as SAJHA's policy engine does)."""
        hits = [r for r in self.rules if r.matches(classes, flow, dest, here)]
        stop = next((r for r in hits if r.effect == 'deny'), None)
        if stop is not None:
            return ResidencyDecision('deny', stop.id, stop.reason or f'refused by residency rule {stop.id}')
        appr = next((r for r in hits if r.effect == 'require_approval'), None)
        if appr is not None:
            return ResidencyDecision('require_approval', appr.id,
                                     appr.reason or f'residency rule {appr.id} requires approval')
        allow = next((r for r in hits if r.effect == 'allow'), None)
        if classes and allow is None and self.default_effect == 'deny':
            return ResidencyDecision('deny', 'residency.default_effect',
                                     f'no residency rule allows {", ".join(classes)} to go there')
        red: List[str] = []
        for r in hits:
            red += [c for c in r.redact if c not in red]
        return ResidencyDecision('allow', allow.id if allow else '', '', red)

    def marks(self, names_: List[str]) -> Tuple[R.Marks, R.Marks]:
        """The overlay's (arguments, results) marks for a tool known by ``names_``."""
        a: R.Marks = {}
        r: R.Marks = {}
        for pat, spec in self.tools.items():
            if any(fnmatch.fnmatchcase(n, pat) for n in names_ if n):
                a = R.merge_marks(a, spec.get('arguments') or {})
                r = R.merge_marks(r, spec.get('results') or {})
        return a, r


def _marks_of(v: Any) -> R.Marks:
    if isinstance(v, dict):
        return {str(k): R.as_classes(x) for k, x in v.items() if R.as_classes(x)}
    if isinstance(v, (list, str)):
        return {R.WHOLE: R.as_classes(v)} if R.as_classes(v) else {}
    return {}


def _residency(raw: Any) -> Residency:
    if raw is None:
        return Residency()
    if not isinstance(raw, dict):
        raise ConfigError('residency: expected an object')
    _unknown(raw, ('default_effect', 'rules', 'tools'), 'residency')
    d = str(raw.get('default_effect') or 'allow').lower()
    if d not in ('allow', 'deny'):
        raise ConfigError('residency.default_effect: allow or deny')
    tools = {}
    for pat, spec in (raw.get('tools') or {}).items():
        if not isinstance(spec, dict):
            raise ConfigError(f'residency.tools.{pat}: expected {{arguments, results}}')
        tools[str(pat)] = {'arguments': _marks_of(spec.get('arguments')), 'results': _marks_of(spec.get('results'))}
    return Residency(d, [_residency_rule(r, i) for i, r in enumerate(raw.get('rules') or [])], tools)


# ── the whole file ─────────────────────────────────────────────────

@dataclass
class AgentPolicy:
    identity: List[str] = field(default_factory=lambda: ['api_key'])
    users: List[User] = field(default_factory=list)
    anonymous_calls: bool = False
    import_rules: List[Dict[str, Any]] = field(default_factory=lambda: [{'tools': ['*']}])
    blocks: List[Dict[str, Any]] = field(default_factory=list)
    residency: Residency = field(default_factory=Residency)
    reexport: bool = False
    reexport_rules: List[Dict[str, Any]] = field(default_factory=list)
    max_hops: int = 1
    max_call_chain: int = 8
    token_ttl_seconds: int = 300
    assertion_ttl_seconds: int = 30
    bare_aliases: str = 'on'
    digest: str = ''

    def user_by_key_hash(self, kh: str) -> Optional[Tuple[User, Key]]:
        for u in self.users:
            for k in u.keys:
                if k.key_hash == kh:
                    return u, k
        return None

    def user(self, login: str) -> Optional[User]:
        return next((u for u in self.users if u.user_name == login), None)


def _block(raw: Any, i: int, set_at: str) -> Dict[str, Any]:
    where = f'blocks[{i}]'
    if not isinstance(raw, dict):
        raise ConfigError(f'{where}: expected an object')
    _unknown(raw, ('id', 'level', 'target_instance', 'tool', 'direction', 'user', 'reason', 'expires_at',
                   'withhold_reason', 'set_at'), where)
    level = str(raw.get('level') or '')
    if level not in LEVELS:
        raise ConfigError(f'{where}.level: one of {", ".join(LEVELS)}')
    b = {k: raw[k] for k in raw if raw[k] not in (None, '')}
    b['level'] = level
    b['id'] = str(raw.get('id') or f'block-{i + 1}')[:64]
    b['set_at'] = str(raw.get('set_at') or set_at)        # default: when the file was last written
    if level == 'user':
        if '@' not in str(raw.get('user') or ''):
            raise ConfigError(f'{where}.user: a net user, <login>@<home instance>')
        b.setdefault('target_instance', str(raw['user']).rpartition('@')[2])
    elif not raw.get('target_instance'):
        raise ConfigError(f'{where}.target_instance: an instance name, or "*"')
    if level == 'tool':
        if not raw.get('tool'):
            raise ConfigError(f'{where}.tool: the tool (a host tool for inbound, a qualified name glob for outbound)')
        if str(raw.get('direction') or 'inbound') not in ('inbound', 'outbound'):
            raise ConfigError(f'{where}.direction: inbound or outbound')
        b['direction'] = str(raw.get('direction') or 'inbound')
    for k in ('expires_at', 'set_at'):
        try:
            crypto.parse_rfc3339(str(b[k])) if b.get(k) else None
        except Exception:
            raise ConfigError(f'{where}.{k}: an RFC 3339 timestamp')
    return b


def _rules(raw: Any, where: str, keys) -> List[Dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ConfigError(f'{where}: expected a list of rules')
    out = []
    for i, r in enumerate(raw):
        if not isinstance(r, dict):
            raise ConfigError(f'{where}[{i}]: expected an object')
        _unknown(r, keys, f'{where}[{i}]')
        if not _list(r.get('tools'), f'{where}[{i}].tools'):
            raise ConfigError(f'{where}[{i}].tools: the tools the rule is about (globs)')
        out.append({k: (_list(v, f'{where}[{i}].{k}') if k != 'require_approval' else v) for k, v in r.items()})
    return out


def parse(doc: Any, written: Optional[float] = None) -> AgentPolicy:
    if not isinstance(doc, dict):
        raise ConfigError('the configuration file holds one JSON object')
    _unknown(doc, TOP_KEYS, 'the configuration file')
    ids = _list(doc.get('identity'), 'identity') or ['api_key']
    bad = [i for i in ids if i not in IDENTITIES]
    if bad:
        raise ConfigError(f'identity: unknown resolver {", ".join(bad)} (one of {", ".join(IDENTITIES)})')
    users = [_user(u, i) for i, u in enumerate(doc.get('users') or [])]
    seen_users, seen_keys, seen_hashes = set(), set(), set()
    for u in users:
        if u.user_name in seen_users:
            raise ConfigError(f'users: {u.user_name} appears twice')
        seen_users.add(u.user_name)
        for k in u.keys:
            if k.id in seen_keys or k.key_hash in seen_hashes:
                raise ConfigError(f'users: key {k.id} (or its key) appears twice')
            seen_keys.add(k.id)
            seen_hashes.add(k.key_hash)
    rx = doc.get('reexport') or {}
    if not isinstance(rx, dict):
        raise ConfigError('reexport: expected {enabled, rules}')
    _unknown(rx, ('enabled', 'rules'), 'reexport')
    aliases = str(doc.get('bare_aliases') or 'on').lower()
    if aliases not in ('on', 'off'):
        raise ConfigError('bare_aliases: on or off')
    p = AgentPolicy(
        identity=list(dict.fromkeys(ids)), users=users, anonymous_calls=bool(doc.get('anonymous_calls', False)),
        import_rules=_rules(doc['import'], 'import', ('tools', 'instances', 'for_roles')) if 'import' in doc
        else [{'tools': ['*']}],
        blocks=[_block(b, i, crypto.rfc3339(written)) for i, b in enumerate(doc.get('blocks') or [])],
        residency=_residency(doc.get('residency')), reexport=bool(rx.get('enabled', False)),
        reexport_rules=_rules(rx.get('rules'), 'reexport.rules', ('tools', 'from_instances', 'to_instances',
                                                                   'for_roles')),
        max_hops=max(1, min(8, int(doc.get('max_hops') or (2 if rx.get('enabled') else 1)))),
        max_call_chain=max(1, min(32, int(doc.get('max_call_chain') or 8))),
        token_ttl_seconds=max(1, min(3600, int(doc.get('token_ttl_seconds') or 300))),
        assertion_ttl_seconds=max(1, min(60, int(doc.get('assertion_ttl_seconds') or 30))), bare_aliases=aliases)
    for b in p.blocks:
        t = str(b.get('target_instance') or '')
        if t != '*' and not names.is_instance_name(t):
            raise ConfigError(f'blocks: {t!r} is not an instance name (or "*")')
    return p


class PolicyFile:
    """The file, re-read when its modification time or size changes; a broken edit keeps the last good
    configuration (and says why in ``error``)."""

    def __init__(self, path: str = ''):
        self.path = path
        self._stamp: Any = None
        self.policy = AgentPolicy()
        self.error = ''
        if path:
            self.policy = self._read()
            self._stamp = self._stat()

    def _stat(self):
        try:
            st = os.stat(self.path)
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def _read(self) -> AgentPolicy:
        try:
            with open(self.path, 'rb') as f:
                raw = f.read()
        except OSError as e:
            raise ConfigError(f'{self.path}: {e}')
        try:
            doc = json.loads(raw.decode('utf-8'))
        except ValueError as e:
            raise ConfigError(f'{self.path}: not JSON ({e})')
        st = self._stat()
        p = parse(doc, written=st[0] / 1e9 if st else None)
        p.digest = hashlib.sha256(raw).hexdigest()
        return p

    def check(self) -> bool:
        """Re-read the file if it changed; True when the configuration changed."""
        if not self.path:
            return False
        stamp = self._stat()
        if stamp == self._stamp:
            return False
        self._stamp = stamp
        try:
            new = self._read()
        except ConfigError as e:
            self.error = str(e)
            return False
        self.error = ''
        changed = new.digest != self.policy.digest
        self.policy = new
        return changed
