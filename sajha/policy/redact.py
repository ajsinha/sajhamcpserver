"""
SAJHA MCP Server — output governance: PII redaction and prompt-injection screening.

Both walk a tool's result (dicts, lists, strings) and return a **new** value: the result
may be the tool cache's own object, which must stay untouched. Dict keys are never
changed, and the base64 ``data``/``blob`` of image, audio and resource blocks is skipped.

Redaction kinds: ``emails``, ``phones``, ``cards`` (13 to 19 digits that pass the Luhn
check), national IDs (``us_ssn``, ``uk_nino``, ``in_aadhaar`` with its Verhoeff check
digit, ``in_pan``, ``ca_sin`` with Luhn) and custom regexes. Screening reuses federation's
injection markers (sajha/federation/security.py). Design: docs/architecture/Policy and
Audit.md, section 4.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Callable, Dict, List, Optional, Tuple

_EMAIL = re.compile(r'(?<![\w.+-])([A-Za-z0-9._%+-]{1,64})@((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})(?![\w-])')
_CARD = re.compile(r'(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])')
_PHONE_INTL = re.compile(r'(?<![\w+])\+\d{1,3}(?:[ .-]?\(?\d{1,4}\)?){2,5}(?!\d)')
_PHONE_NANP = re.compile(r'(?<![\d(])(?:\(\d{3}\)\s?|\d{3}[-. ])\d{3}[-. ]\d{4}(?!\d)')
_US_SSN = re.compile(r'(?<![\d-])(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}(?![\d-])')
_UK_NINO = re.compile(r'\b(?!BG|GB|NK|KN|TN|NT|ZZ)[A-CEGHJ-PR-TW-Z][A-CEGHJ-NPR-TW-Z] ?\d{2} ?\d{2} ?\d{2} ?[A-D]\b')
_IN_AADHAAR = re.compile(r'(?<![\d-])[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}(?![\d-])')
_IN_PAN = re.compile(r'\b[A-Z]{3}[ABCFGHLJPTK][A-Z]\d{4}[A-Z]\b')
_CA_SIN = re.compile(r'(?<![\d-])\d{3}[ -]\d{3}[ -]\d{3}(?![\d-])')


def luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = ord(ch) - 48
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


_V_D = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
        [3, 4, 0, 1, 2, 8, 9, 5, 6, 7], [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
        [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3], [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
        [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
_V_P = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
        [8, 9, 1, 6, 0, 4, 3, 5, 2, 7], [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
        [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]


def verhoeff_ok(digits: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(digits)):
        c = _V_D[c][_V_P[i % 8][ord(ch) - 48]]
    return c == 0


def _digits(s: str) -> str:
    return re.sub(r'\D', '', s)


def _mask(kind: str, s: str) -> str:
    if kind == 'emails':
        local, _, domain = s.partition('@')
        return (local[:1] + '***@' + domain) if local else s
    keep = 4
    out, seen = [], 0
    alnum_total = sum(ch.isalnum() for ch in s)
    for ch in s:
        if ch.isalnum():
            seen += 1
            out.append(ch if seen > alnum_total - keep else '*')
        else:
            out.append(ch)
    return ''.join(out)


#: kind -> (regex, extra check on the match text)
_DETECTORS: Dict[str, Tuple['re.Pattern', Optional[Callable[[str], bool]]]] = {
    'emails': (_EMAIL, None),
    'cards': (_CARD, lambda m: 13 <= len(_digits(m)) <= 19 and luhn_ok(_digits(m))),
    'us_ssn': (_US_SSN, None),
    'uk_nino': (_UK_NINO, None),
    'in_aadhaar': (_IN_AADHAAR, lambda m: verhoeff_ok(_digits(m))),
    'in_pan': (_IN_PAN, None),
    'ca_sin': (_CA_SIN, lambda m: _digits(m)[0] not in '08' and luhn_ok(_digits(m))),
    'phones': (_PHONE_INTL, lambda m: 8 <= len(_digits(m)) <= 15),
}
# the order matters: a card number must not be half-eaten as a phone number first
_ORDER = ('emails', 'cards', 'us_ssn', 'uk_nino', 'in_aadhaar', 'in_pan', 'ca_sin', 'phones')


def redact_text(text: str, spec, counts: Counter) -> str:
    kinds = set(spec.kinds)
    for kind in _ORDER:
        if kind not in kinds:
            continue
        rx, check = _DETECTORS[kind]
        patterns = [rx, _PHONE_NANP] if kind == 'phones' else [rx]
        for p in patterns:
            def sub(m, kind=kind, check=check):
                s = m.group(0)
                if check is not None and p is rx and not check(s):
                    return s
                counts[kind] += 1
                return _mask(kind, s) if spec.mode == 'mask' else f'[REDACTED:{kind}]'
            text = p.sub(sub, text)
    for c in spec.custom:
        def sub_c(m, c=c):
            counts[c.name] += 1
            if c.replacement is not None:
                return m.expand(c.replacement)
            return _mask(c.name, m.group(0)) if spec.mode == 'mask' else f'[REDACTED:{c.name}]'
        text = c.regex.sub(sub_c, text)
    return text


def _is_binary_block(d: Dict[str, Any]) -> bool:
    return 'mimeType' in d or d.get('type') in ('image', 'audio', 'resource', 'blob')


def walk(value: Any, fn: Callable[[str], str], _depth: int = 0) -> Any:
    """A copy of ``value`` with ``fn`` applied to every string value (keys untouched)."""
    if _depth > 64:
        return value
    if isinstance(value, str):
        return fn(value)
    if isinstance(value, dict):
        binary = _is_binary_block(value)
        return {k: (v if binary and k in ('data', 'blob') else walk(v, fn, _depth + 1)) for k, v in value.items()}
    if isinstance(value, list):
        return [walk(v, fn, _depth + 1) for v in value]
    if isinstance(value, tuple):
        return tuple(walk(v, fn, _depth + 1) for v in value)
    return value


def redact(value: Any, spec) -> Tuple[Any, Dict[str, int]]:
    """(redacted copy, {kind: count})."""
    counts: Counter = Counter()
    out = walk(value, lambda s: redact_text(s, spec, counts))
    return out, dict(counts)


def screen(value: Any, mode: str) -> Tuple[Any, int]:
    """(value, number of injection markers found); ``strip`` replaces them with [removed]."""
    from sajha.federation.security import INJECTION_MARKERS
    found = [0]

    def fn(s: str) -> str:
        for rx in INJECTION_MARKERS:
            if mode == 'strip':
                s, n = rx.subn('[removed]', s)
            else:
                n = len(rx.findall(s))
            found[0] += n
        return s

    out = walk(value, fn)
    return (out if mode == 'strip' else value), found[0]


def kinds_found(text: str) -> List[str]:
    """The redaction kinds present in ``text`` (for the test bench)."""
    from sajha.policy.model import NATIONAL_IDS, RedactSpec
    counts: Counter = Counter()
    redact_text(text, RedactSpec(('emails', 'phones', 'cards') + NATIONAL_IDS), counts)
    return sorted(counts)
