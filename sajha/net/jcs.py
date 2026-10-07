"""
RFC 8785 JSON Canonicalization Scheme (JCS), used for record signatures (protocol §8.10) and
streamed response signatures (§8.9).

Object members are sorted by their UTF-16 code units, strings are escaped as ECMAScript's
``JSON.stringify`` does, and numbers are written in ECMAScript's shortest round-trip form
(signed records hold only integers, §8.10, but tool results may hold fractions).

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import math
from typing import Any

_ESC = {'"': '\\"', '\\': '\\\\', '\b': '\\b', '\f': '\\f', '\n': '\\n', '\r': '\\r', '\t': '\\t'}


def _string(s: str) -> str:
    out = ['"']
    for ch in s:
        if ch in _ESC:
            out.append(_ESC[ch])
        elif ord(ch) < 0x20:
            out.append('\\u%04x' % ord(ch))
        else:
            out.append(ch)
    out.append('"')
    return ''.join(out)


def _number(v) -> str:
    if isinstance(v, bool):
        raise TypeError('bool is not a number')
    if isinstance(v, int):
        if abs(v) > 2 ** 53 - 1:
            raise ValueError('integer outside the I-JSON range')
        return str(v)
    f = float(v)
    if math.isnan(f) or math.isinf(f):
        raise ValueError('NaN and Infinity are not JSON')
    if f == 0:
        return '0'
    if f.is_integer() and abs(f) < 1e21:
        return str(int(f))
    r = repr(f)                                  # shortest round-trip digits
    mant, _, exp = r.partition('e')
    if not exp:
        return r
    e = int(exp)
    digits = mant.replace('.', '').replace('-', '').lstrip('0') or '0'
    neg = f < 0
    # ECMAScript Number::toString: plain notation for 1e-7 < |f| < 1e21
    point = e + (mant.lstrip('-').index('.') if '.' in mant else len(mant.lstrip('-')))
    k = len(digits)
    if -6 < point <= 21:
        if point <= 0:
            s = '0.' + '0' * (-point) + digits
        elif point >= k:
            s = digits + '0' * (point - k)
        else:
            s = digits[:point] + '.' + digits[point:]
    else:
        s = digits[0] + ('.' + digits[1:] if k > 1 else '') + 'e' + ('+' if point - 1 > 0 else '-') + str(abs(point - 1))
    return ('-' if neg else '') + s


def _ser(v: Any, out: list) -> None:
    if v is None:
        out.append('null')
    elif v is True:
        out.append('true')
    elif v is False:
        out.append('false')
    elif isinstance(v, str):
        out.append(_string(v))
    elif isinstance(v, (int, float)):
        out.append(_number(v))
    elif isinstance(v, (list, tuple)):
        out.append('[')
        for i, x in enumerate(v):
            if i:
                out.append(',')
            _ser(x, out)
        out.append(']')
    elif isinstance(v, dict):
        out.append('{')
        for i, k in enumerate(sorted(v, key=lambda s: s.encode('utf-16-be'))):
            if not isinstance(k, str):
                raise TypeError('object keys must be strings')
            if i:
                out.append(',')
            out.append(_string(k))
            out.append(':')
            _ser(v[k], out)
        out.append('}')
    else:
        raise TypeError(f'cannot canonicalize {type(v).__name__}')


def canonicalize(value: Any) -> bytes:
    out: list = []
    _ser(value, out)
    return ''.join(out).encode('utf-8')
