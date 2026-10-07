"""
RFC 8941 Structured Field Values: the parser and serializer the protocol needs
(``Signature-Input``, ``Signature``, ``Content-Digest``, ``Sajha-Net-Certificate``,
``Sajha-Net-Visited`` and the integer headers).

Values: ``int``, ``float`` (decimal), ``str`` (string), :class:`Token`, ``bytes`` (byte
sequence), ``bool``. An item is ``(value, params)``; an inner list is ``([items], params)``;
``params`` is an ordered ``dict``.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import base64
import re
from typing import Any, Dict, List, Tuple


class Token(str):
    """An RFC 8941 token (serialized without quotes)."""


class SFVError(ValueError):
    pass


_KEY_RE = re.compile(r'[a-z*][a-z0-9_\-.*]*')
_TOKEN_RE = re.compile(r"[A-Za-z*][A-Za-z0-9!#$%&'*+\-.^_`|~:/]*")


class _P:
    def __init__(self, s: str):
        self.s = s
        self.i = 0

    def peek(self) -> str:
        return self.s[self.i] if self.i < len(self.s) else ''

    def ows(self):
        while self.peek() in (' ', '\t') and self.peek():
            self.i += 1

    def sp(self):
        while self.peek() == ' ':
            self.i += 1

    def done(self) -> bool:
        return self.i >= len(self.s)

    def key(self) -> str:
        m = _KEY_RE.match(self.s, self.i)
        if not m:
            raise SFVError(f'expected a key at {self.i}')
        self.i = m.end()
        return m.group()

    def bare(self) -> Any:
        c = self.peek()
        if c == '-' or c.isdigit():
            return self.number()
        if c == '"':
            return self.string()
        if c == ':':
            return self.bytes_()
        if c == '?':
            self.i += 1
            b = self.peek()
            if b not in ('0', '1'):
                raise SFVError('bad boolean')
            self.i += 1
            return b == '1'
        m = _TOKEN_RE.match(self.s, self.i)
        if m:
            self.i = m.end()
            return Token(m.group())
        raise SFVError(f'unexpected {c!r} at {self.i}')

    def number(self):
        m = re.compile(r'-?[0-9]{1,15}(\.[0-9]{1,3})?').match(self.s, self.i)
        if not m:
            raise SFVError('bad number')
        self.i = m.end()
        t = m.group()
        if '.' in t:
            if len(t.split('.')[0].lstrip('-')) > 12:
                raise SFVError('decimal too long')
            return float(t)
        return int(t)

    def string(self) -> str:
        self.i += 1
        out = []
        while True:
            if self.done():
                raise SFVError('unterminated string')
            c = self.s[self.i]
            self.i += 1
            if c == '\\':
                if self.done():
                    raise SFVError('bad escape')
                n = self.s[self.i]
                self.i += 1
                if n not in ('"', '\\'):
                    raise SFVError('bad escape')
                out.append(n)
            elif c == '"':
                return ''.join(out)
            elif ord(c) < 0x20 or ord(c) > 0x7e:
                raise SFVError('non-ASCII in string')
            else:
                out.append(c)

    def bytes_(self) -> bytes:
        self.i += 1
        j = self.s.find(':', self.i)
        if j < 0:
            raise SFVError('unterminated byte sequence')
        raw = self.s[self.i:j]
        self.i = j + 1
        if not re.fullmatch(r'[A-Za-z0-9+/=]*', raw):
            raise SFVError('bad byte sequence')
        try:
            return base64.b64decode(raw + '=' * (-len(raw) % 4), validate=True)
        except Exception:
            raise SFVError('bad base64')

    def params(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        while self.peek() == ';':
            self.i += 1
            self.sp()
            k = self.key()
            v: Any = True
            if self.peek() == '=':
                self.i += 1
                v = self.bare()
            out[k] = v
        return out

    def item(self):
        v = self.bare()
        return v, self.params()

    def item_or_inner(self):
        if self.peek() == '(':
            self.i += 1
            items = []
            while True:
                self.sp()
                if self.peek() == ')':
                    self.i += 1
                    return items, self.params()
                items.append(self.item())
                if self.peek() not in (' ', ')'):
                    raise SFVError('bad inner list')
        return self.item()


def parse_list(s: str) -> List[Tuple[Any, Dict[str, Any]]]:
    p = _P((s or '').strip(' '))
    out = []
    if p.done():
        return out
    while True:
        out.append(p.item_or_inner())
        p.ows()
        if p.done():
            return out
        if p.peek() != ',':
            raise SFVError('expected ","')
        p.i += 1
        p.ows()
        if p.done():
            raise SFVError('trailing comma')


def parse_dict(s: str) -> Dict[str, Tuple[Any, Dict[str, Any]]]:
    p = _P((s or '').strip(' '))
    out: Dict[str, Any] = {}
    if p.done():
        return out
    while True:
        k = p.key()
        if p.peek() == '=':
            p.i += 1
            out[k] = p.item_or_inner()
        else:
            out[k] = (True, p.params())
        p.ows()
        if p.done():
            return out
        if p.peek() != ',':
            raise SFVError('expected ","')
        p.i += 1
        p.ows()
        if p.done():
            raise SFVError('trailing comma')


def parse_item(s: str):
    p = _P((s or '').strip(' '))
    v = p.item()
    if not p.done():
        raise SFVError('trailing characters')
    return v


# ── serialization ─────────────────────────────────────────────────

def ser_bare(v: Any) -> str:
    if isinstance(v, bool):
        return '?1' if v else '?0'
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return ('%.3f' % v).rstrip('0').rstrip('.') if not v.is_integer() else '%d.0' % v
    if isinstance(v, Token):
        return str(v)
    if isinstance(v, (bytes, bytearray)):
        return ':' + base64.b64encode(bytes(v)).decode('ascii') + ':'
    if isinstance(v, str):
        if any(ord(c) < 0x20 or ord(c) > 0x7e for c in v):
            raise SFVError('strings must be printable ASCII')
        return '"' + v.replace('\\', '\\\\').replace('"', '\\"') + '"'
    raise SFVError(f'cannot serialize {type(v).__name__}')


def ser_params(params: Dict[str, Any]) -> str:
    out = []
    for k, v in (params or {}).items():
        out.append(';' + k if v is True else f';{k}={ser_bare(v)}')
    return ''.join(out)


def ser_item(v: Any, params=None) -> str:
    return ser_bare(v) + ser_params(params or {})


def ser_inner(items, params=None) -> str:
    return '(' + ' '.join(ser_item(v, p) for v, p in items) + ')' + ser_params(params or {})


def ser_member(member) -> str:
    v, params = member
    if isinstance(v, list):
        return ser_inner(v, params)
    return ser_item(v, params)


def ser_list(members) -> str:
    return ', '.join(ser_member(m) for m in members)


def ser_dict(d: Dict[str, Any]) -> str:
    out = []
    for k, m in d.items():
        v, params = m
        out.append(k + ser_params(params) if v is True else f'{k}={ser_member(m)}')
    return ', '.join(out)
